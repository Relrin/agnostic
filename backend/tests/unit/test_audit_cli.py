"""``agnostic audit`` against a migrated SQLite database (restores themselves: the API and integration tests)."""

import pytest
from typer.testing import CliRunner

from agnostic_kernel.testing import UNREACHABLE_REDIS
from agnostic_server.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch, sqlite_database: str) -> None:
    monkeypatch.setenv("AGNOSTIC_ENV", "test")
    monkeypatch.setenv("AGNOSTIC_DATABASE__URL", sqlite_database)
    monkeypatch.setenv("AGNOSTIC_REDIS__URL", UNREACHABLE_REDIS)
    monkeypatch.setenv("AGNOSTIC_REDIS__SOCKET_TIMEOUT", "1")
    monkeypatch.setenv("AGNOSTIC_LOG__LEVEL", "WARNING")
    monkeypatch.setenv("AGNOSTIC_LOG__FORMAT", "console")


def test_audit_commands() -> None:
    assert runner.invoke(app, ["db", "upgrade"]).exit_code == 0

    verified = runner.invoke(app, ["audit", "verify", "--since", "2026-01-01"])
    assert verified.exit_code == 0, verified.output
    assert "ok: 0 chained events verified" in verified.output

    bad_time = runner.invoke(app, ["audit", "verify", "--until", "yesterday"])
    assert bad_time.exit_code == 2

    missing = runner.invoke(app, ["audit", "restore", "2025-08"])
    assert missing.exit_code == 1
    assert "No archive for 2025-08" in missing.output

    malformed = runner.invoke(app, ["audit", "restore", "August"])
    assert malformed.exit_code == 1
    assert "expected a month like 2025-08" in malformed.output


def test_archive_commands() -> None:
    assert runner.invoke(app, ["db", "upgrade"]).exit_code == 0

    listed = runner.invoke(app, ["audit", "archives", "list"])
    assert listed.exit_code == 0, listed.output
    assert "events" not in listed.stdout  # nothing archived yet

    missing = runner.invoke(app, ["audit", "archives", "verify", "2025-08"])
    assert missing.exit_code == 1
    assert "No archive for 2025-08" in missing.output

    assert runner.invoke(app, ["audit", "archives", "verify"]).exit_code == 2
    nothing = runner.invoke(app, ["audit", "archives", "verify", "--all"])
    assert nothing.exit_code == 0, nothing.output
