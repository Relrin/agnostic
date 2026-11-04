"""Faults reproduce production failures in the dev stack: RUNTIME_FAULTS=web_search=timeout."""

import pytest

from app.settings import RuntimeSettings, get_settings
from app.tools import web_search


def test_faults_are_parsed_per_tool() -> None:
    settings = RuntimeSettings(faults="web_search=timeout, lookup_order=")
    assert settings.fault("web_search") == "timeout"
    assert settings.fault("lookup_order") is None
    assert RuntimeSettings().fault("web_search") is None


def test_web_search_times_out_when_asked_to(monkeypatch: pytest.MonkeyPatch) -> None:
    entrypoint = web_search.entrypoint
    assert entrypoint is not None
    assert "offline stub" in entrypoint(query="agents")
    monkeypatch.setenv("RUNTIME_FAULTS", "web_search=timeout")
    get_settings.cache_clear()
    try:
        with pytest.raises(TimeoutError, match="web_search exceeded the 30 s tool timeout"):
            entrypoint(query="agents")
    finally:
        monkeypatch.delenv("RUNTIME_FAULTS")
        get_settings.cache_clear()
