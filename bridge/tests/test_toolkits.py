"""The Agno toolkit list: generated from agno, identical in the bridge and the control plane, true to agno."""

from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

from agnostic_bridge.toolkits import importable, load_class, toolkit_list

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dump_toolkits.py"


def test_both_copies_match_the_installed_agno() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"run scripts/dump_toolkits.py: {result.stderr}"


def test_every_toolkit_is_an_agno_tool_and_none_is_a_framework_one() -> None:
    listed = toolkit_list()
    assert len(listed.toolkits) > 100
    keys = {toolkit.key for toolkit in listed.toolkits}
    assert len(keys) == len(listed.toolkits)
    assert all(toolkit.class_path.startswith("agno.tools.") for toolkit in listed.toolkits)
    assert not keys & {"mcp", "knowledge", "memory", "reasoning", "workflow", "user_feedback"}
    assert {"calculator", "duck_duck_go", "github", "slack", "shell"} <= keys


def test_parameters_exist_on_the_classes_that_import_here() -> None:
    checked = 0
    for spec in toolkit_list().toolkits:
        if not importable(spec.key):
            continue
        parameters = inspect.signature(load_class(spec)).parameters
        assert {param.name for param in spec.params} <= set(parameters), spec.key
        checked += 1
    assert checked > 5


def test_credentials_are_marked_secret() -> None:
    github = toolkit_list().get("github")
    assert github is not None
    token = github.param("access_token")
    assert token is not None
    assert token.secret is True
    shell = toolkit_list().get("shell")
    assert shell is not None
    assert shell.local is True
