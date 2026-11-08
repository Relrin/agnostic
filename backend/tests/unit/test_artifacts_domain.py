"""Artefact serving rules and share links: real types from the bytes, sandbox policies, names, tokens, expiry."""

from datetime import UTC, datetime, timedelta

import pytest

from agnostic_artifacts.domain.content import (
    INERT_POLICY,
    SCRIPTED_SANDBOX_POLICY,
    content_type_of,
    safe_filename,
    serve,
)
from agnostic_artifacts.domain.shares import Share, ShareError, expiry, looks_like_token, new_token, token_hash

NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("name", "data", "declared", "expected"),
    [
        ("chart.png", b"\x89PNG\r\n\x1a\n....", None, "image/png"),
        ("evil.png", b"<!doctype html><script>", "image/png", "text/html"),  # bytes beat the name and the claim
        ("report.md", b"# Title", "application/octet-stream", "text/markdown"),
        ("page", b"<html><body>", None, "text/html"),
        ("logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", None, "image/svg+xml"),
        ("doc.pdf", b"%PDF-1.7", None, "application/pdf"),
        ("data.bin", b"\x00\x01\xff", "application/x-thing", "application/x-thing"),
        ("data.bin", b"\x00\x01\xff", "text/html", "application/octet-stream"),
        (
            "sheet.xlsx",
            b"PK\x03\x04\x00\x00",
            None,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    ],
)
def test_content_type_comes_from_the_bytes(name: str, data: bytes, declared: str | None, expected: str) -> None:
    assert content_type_of(name, data, declared) == expected


def test_html_runs_only_inside_an_opaque_sandbox() -> None:
    served = serve("page.html", b"<!doctype html>", declared=None, disposition="inline")
    policy = served.headers["Content-Security-Policy"]
    assert policy == SCRIPTED_SANDBOX_POLICY
    assert "allow-same-origin" not in policy
    assert "connect-src 'none'" in policy
    assert served.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert served.content_type == "text/html; charset=utf-8"


def test_everything_else_and_downloads_are_inert() -> None:
    assert (
        serve("a.png", b"\x89PNG\r\n\x1a\n", declared=None, disposition="inline").headers["Content-Security-Policy"]
        == INERT_POLICY
    )
    download = serve("page.html", b"<html>", declared=None, disposition="attachment")
    assert download.headers["Content-Security-Policy"] == INERT_POLICY
    assert download.headers["Content-Disposition"] == "attachment; filename=\"page.html\"; filename*=UTF-8''page.html"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("../../etc/passwd", "passwd"), ('a"b.md', "a_b.md"), ("", "artifact"), ("folder\\report.md", "report.md")],
)
def test_safe_filename(raw: str, expected: str) -> None:
    assert safe_filename(raw) == expected


def test_non_ascii_names_keep_their_utf8_form() -> None:
    served = serve("отчёт.md", b"# x", declared=None, disposition="attachment")
    assert "filename*=UTF-8''%D0%BE%D1%82%D1%87%D1%91%D1%82.md" in served.headers["Content-Disposition"]


def test_tokens_are_random_and_stored_as_hashes() -> None:
    first, second = new_token(), new_token()
    assert first != second
    assert looks_like_token(first)
    assert not looks_like_token("shr_123")
    assert len(token_hash(first)) == 64
    assert token_hash(first) != first


def test_expiry_bounds() -> None:
    assert expiry(NOW, 3600, maximum=timedelta(days=30)) == NOW + timedelta(hours=1)
    with pytest.raises(ShareError):
        _ = expiry(NOW, 60, maximum=timedelta(days=30))
    with pytest.raises(ShareError):
        _ = expiry(NOW, 31 * 86400, maximum=timedelta(days=30))


def test_share_states() -> None:
    share = Share(
        id="shr_1",
        instance_id="ins_1",
        session_id="sess_1",
        storage_key="sess_1/a.md",
        filename="a.md",
        content_type="text/markdown",
        size=3,
        sha256="0" * 64,
        audience="org",
        created_by="usr_1",
        created_by_name="Daniel",
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    assert share.state(NOW) == "active"
    assert share.state(NOW + timedelta(hours=2)) == "expired"
    revoked = share.revoked(NOW)
    assert revoked.state(NOW) == "revoked"
    assert not revoked.active(NOW)
    assert share.opened(NOW).opened_count == 1
