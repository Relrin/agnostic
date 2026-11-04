"""CORS for direct mode."""

import pytest

from agnostic_bridge import direct_mode_cors


def test_direct_mode_cors_normalizes_origins() -> None:
    cors = direct_mode_cors(["https://agnostic.corp/", " http://localhost:5173 "])
    assert cors.origins == ["https://agnostic.corp", "http://localhost:5173"]
    assert cors.merge_base_app is True


@pytest.mark.parametrize("bad", ["agnostic.corp", "https://agnostic.corp/app", "ftp://agnostic.corp"])
def test_direct_mode_cors_rejects_non_origins(bad: str) -> None:
    with pytest.raises(ValueError, match="isn't an origin"):
        direct_mode_cors([bad])
