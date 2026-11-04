"""``agnostic secrets`` and the migration commands added for upgrades, against a SQLite database."""

import pytest
from sqlalchemy import create_engine, text
from typer.testing import CliRunner

from agnostic_kernel.crypto import SecretBox, decode_local_key, encode_local_key, key_id
from agnostic_kernel.testing import UNREACHABLE_REDIS
from agnostic_server.cli import app

runner = CliRunner()
OLD = bytes(range(32))
NEW = bytes(range(32, 64))


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch, sqlite_database: str) -> None:
    monkeypatch.setenv("AGNOSTIC_DATABASE__URL", sqlite_database)
    monkeypatch.setenv("AGNOSTIC_REDIS__URL", UNREACHABLE_REDIS)
    monkeypatch.setenv("AGNOSTIC_LOG__LEVEL", "WARNING")
    monkeypatch.setenv("AGNOSTIC_LOG__FORMAT", "console")
    monkeypatch.setenv("AGNOSTIC_ENV", "test")


def _sync_url(url: str) -> str:
    return url.replace("+aiosqlite", "")


def test_migrate_and_upgrade_check() -> None:
    refused = runner.invoke(app, ["db", "upgrade", "--check"])
    assert refused.exit_code == 2
    assert "needs PostgreSQL" in refused.output

    migrated = runner.invoke(app, ["migrate"])
    assert migrated.exit_code == 0, migrated.output
    assert "up to date" in migrated.output


def test_generate_key_local() -> None:
    result = runner.invoke(app, ["secrets", "generate-key"])
    assert result.exit_code == 0, result.output
    key = decode_local_key(result.stdout.strip().splitlines()[-1])
    assert len(key) == 32


def test_status_and_rotate(monkeypatch: pytest.MonkeyPatch, sqlite_database: str) -> None:
    assert runner.invoke(app, ["migrate"]).exit_code == 0
    engine = create_engine(_sync_url(sqlite_database))
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ntf_channels (id, kind, name, config_enc, events, instance_ids, enabled, created_at, "
                "updated_at) VALUES ('chn_1', 'slack', 'ops', :sealed, '[]', '[]', 1, CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP)"
            ),
            {"sealed": SecretBox(OLD).seal(b'{"webhook": "https://hooks.example"}')},
        )
    monkeypatch.setenv("AGNOSTIC_SECRETS__MASTER_KEY", encode_local_key(NEW))

    unknown = runner.invoke(app, ["secrets", "status"])
    assert unknown.exit_code == 1
    assert key_id(OLD) in unknown.output

    monkeypatch.setenv("AGNOSTIC_SECRETS__PREVIOUS_KEYS", encode_local_key(OLD))
    status = runner.invoke(app, ["secrets", "status"])
    assert status.exit_code == 0, status.output
    assert "ntf_channels.config_enc" in status.output
    assert "1 value(s) still sealed with a previous key" in status.output

    rotated = runner.invoke(app, ["secrets", "rotate"])
    assert rotated.exit_code == 0, rotated.output
    assert "re-sealed 1 row(s)" in rotated.output
    after = runner.invoke(app, ["secrets", "status"])
    assert "every value uses the current key" in after.output

    with engine.connect() as connection:
        sealed = connection.execute(text("SELECT config_enc FROM ntf_channels")).scalar_one()
    engine.dispose()
    assert SecretBox(NEW).open(sealed) == b'{"webhook": "https://hooks.example"}'


def test_wrap_key_requires_a_configured_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGNOSTIC_SECRETS__MASTER_KEY", raising=False)
    result = runner.invoke(app, ["secrets", "wrap-key", "--to", "local"])
    assert result.exit_code == 1
    monkeypatch.setenv("AGNOSTIC_SECRETS__MASTER_KEY", encode_local_key(NEW))
    monkeypatch.setenv("AGNOSTIC_SECRETS__PREVIOUS_KEYS", encode_local_key(OLD))
    wrapped = runner.invoke(app, ["secrets", "wrap-key", "--to", "local"])
    assert wrapped.exit_code == 0, wrapped.output
    lines = [line for line in wrapped.stdout.splitlines() if line and not line.startswith("#")]
    assert lines == [encode_local_key(NEW), encode_local_key(OLD)]
