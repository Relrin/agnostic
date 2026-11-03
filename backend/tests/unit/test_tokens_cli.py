"""``agnostic tokens`` argument handling against a migrated SQLite database (creation itself: the API tests)."""

import pytest
from typer.testing import CliRunner

from agnostic_kernel.testing import UNREACHABLE_REDIS
from agnostic_server.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch, sqlite_database: str) -> None:
    monkeypatch.setenv("AGNOSTIC_DATABASE__URL", sqlite_database)
    monkeypatch.setenv("AGNOSTIC_REDIS__URL", UNREACHABLE_REDIS)
    monkeypatch.setenv("AGNOSTIC_REDIS__SOCKET_TIMEOUT", "1")
    monkeypatch.setenv("AGNOSTIC_LOG__LEVEL", "WARNING")
    monkeypatch.setenv("AGNOSTIC_LOG__FORMAT", "console")
    monkeypatch.setenv("AGNOSTIC_ENV", "test")  # the gateway-token pepper derives from the master key


def test_tokens_commands() -> None:
    assert runner.invoke(app, ["db", "upgrade"]).exit_code == 0

    listed = runner.invoke(app, ["tokens", "list"])
    assert listed.exit_code == 0, listed.output
    assert "No service accounts yet." in listed.output

    no_scopes = runner.invoke(app, ["tokens", "create", "ci-evals", "--instance", "staging-agentos"])
    assert no_scopes.exit_code == 2
    both = runner.invoke(
        app, ["tokens", "create", "ci-evals", "--instance", "x", "--role", "viewer", "--scopes", "agents:read"]
    )
    assert both.exit_code == 2
    bad_kind = runner.invoke(
        app, ["tokens", "create", "ci-evals", "--instance", "x", "--scopes", "agents:read", "--kind", "jwt"]
    )
    assert bad_kind.exit_code == 2

    unknown = runner.invoke(
        app, ["tokens", "create", "ci-evals", "--instance", "staging-agentos", "--scopes", "agents:read"]
    )
    assert unknown.exit_code == 1
    assert "There is no instance 'staging-agentos'" in unknown.output

    missing = runner.invoke(app, ["tokens", "revoke", "ghost"])
    assert missing.exit_code == 1
    assert "There is no service account 'ghost'" in missing.output
