"""The ``agnostic`` CLI against a SQLite database."""

import json
from pathlib import Path

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


def test_db_upgrade_downgrade_current() -> None:
    upgraded = runner.invoke(app, ["db", "upgrade"])
    assert upgraded.exit_code == 0, upgraded.output
    assert "up to date" in upgraded.output

    downgraded = runner.invoke(app, ["db", "downgrade", "hello@base"])
    assert downgraded.exit_code == 0, downgraded.output
    assert "pending: h0001_greetings" in downgraded.output

    current = runner.invoke(app, ["db", "current"])
    assert "current: k0001_kernel_base" in current.output


def test_config_check() -> None:
    plain = runner.invoke(app, ["config", "check"])
    assert plain.exit_code == 0
    assert '"backend"' not in plain.output  # backend is derived, not a setting
    assert "jobs: embedded" in plain.output

    connected = runner.invoke(app, ["config", "check", "--connect"])
    assert connected.exit_code == 1  # the cache is unreachable on purpose
    assert "database" in connected.output
    assert "FAIL" in connected.output


def test_config_check_rejects_bad_module_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGNOSTIC_MODULES__DISABLED", "ghost")
    result = runner.invoke(app, ["config", "check"])
    assert result.exit_code == 1


def test_modules_list(monkeypatch: pytest.MonkeyPatch) -> None:
    result = runner.invoke(app, ["modules", "list"])
    assert "hello" in result.output
    assert "enabled" in result.output
    monkeypatch.setenv("AGNOSTIC_MODULES__DISABLED", "hello")
    assert "disabled" in runner.invoke(app, ["modules", "list"]).output
    monkeypatch.setenv("AGNOSTIC_MODULES__DISABLED", "ghost")
    assert runner.invoke(app, ["modules", "list"]).exit_code == 1


def test_openapi_export(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    result = runner.invoke(app, ["openapi", "--out", str(out)])
    assert result.exit_code == 0, result.output
    document = json.loads(out.read_text(encoding="utf-8"))
    assert "/api/v1/hello/greetings" in document["paths"]


def test_worker_refuses_sqlite() -> None:
    result = runner.invoke(app, ["worker"])
    assert result.exit_code == 2
