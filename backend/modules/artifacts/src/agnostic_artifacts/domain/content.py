"""How an artefact's bytes are served: the type they really are, and the headers that keep them inert.

Everything an agent produced is untrusted. HTML and SVG can run script, and a PDF or an image can be crafted, so
every response carries its own content security policy with ``sandbox``. Without ``allow-same-origin`` the browser
gives the document an opaque origin: it cannot read the control plane's cookies or storage, and ``connect-src 'none'``
stops it calling anything. HTML may run its own inline script (charts, small apps) inside that box; nothing else may
run script at all.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

type Disposition = Literal["inline", "attachment"]

ACTIVE_TYPES = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "image/svg+xml",
        "text/xml",
        "application/xml",
        "text/javascript",
        "application/javascript",
    }
)
"""Types a browser can execute; served only under the scripted sandbox below, or as downloads."""

SCRIPTED_SANDBOX_POLICY = "; ".join(  # noqa: FLY002  (one directive per line reads better)
    (
        "sandbox allow-scripts allow-popups",
        "default-src 'none'",
        "script-src 'unsafe-inline'",
        "style-src 'unsafe-inline'",
        "img-src data: blob:",
        "media-src data: blob:",
        "font-src data:",
        "connect-src 'none'",
        "form-action 'none'",
        "base-uri 'none'",
        "frame-ancestors 'self'",
    )
)
"""HTML previews: own inline script and styles, no network, opaque origin, framed only by the control plane."""

INERT_POLICY = "sandbox; default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'self'"
"""Everything else: nothing runs, nothing loads; the web app reads the bytes and renders them itself."""

_MIME = re.compile(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+")
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
    (b"ID3", "audio/mpeg"),
    (b"OggS", "audio/ogg"),
    (b"fLaC", "audio/flac"),
    (b"\x1aE\xdf\xa3", "video/webm"),
)
_BY_EXTENSION = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".log": "text/plain",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".html": "text/html",
    ".htm": "text/html",
    ".svg": "image/svg+xml",
    ".xml": "text/xml",
    ".css": "text/css",
    ".js": "text/javascript",
    ".ts": "text/x-typescript",
    ".tsx": "text/x-typescript",
    ".py": "text/x-python",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".sql": "text/x-sql",
    ".sh": "text/x-shellscript",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".zip": "application/zip",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
OCTET_STREAM = "application/octet-stream"


def _magic(data: bytes) -> str | None:
    for signature, kind in _SIGNATURES:
        if data.startswith(signature):
            return kind
    if data[:4] == b"RIFF" and len(data) >= 12:  # noqa: PLR2004
        return {b"WEBP": "image/webp", b"WAVE": "audio/wav"}.get(data[8:12])
    if data[4:8] == b"ftyp":
        return "video/mp4"
    return None


def _textual(data: bytes) -> bool:
    sample = data[:4096]
    if b"\x00" in sample:
        return False
    try:
        _ = sample.decode("utf-8")
    except UnicodeDecodeError as error:
        return error.start >= len(sample) - 3
    return True


def content_type_of(filename: str, data: bytes, declared: str | None = None) -> str:  # noqa: PLR0911
    """What the bytes are: magic bytes first, then the extension for text, then a declared type that looks valid."""
    if (found := _magic(data)) is not None:
        return found
    extension = posixpath.splitext(filename.lower())[1]
    known = _BY_EXTENSION.get(extension)
    if _textual(data):
        if known is not None and (known.startswith("text/") or known in ACTIVE_TYPES or "json" in known):
            return known
        head = data[:512].lstrip().lower()
        if head.startswith((b"<!doctype html", b"<html")):
            return "text/html"
        if head.startswith(b"<svg"):
            return "image/svg+xml"
        return "text/plain"
    if known is not None and not known.startswith("text/"):
        return known
    candidate = (declared or "").split(";", 1)[0].strip().lower()
    return candidate if _MIME.fullmatch(candidate) and candidate not in ACTIVE_TYPES else OCTET_STREAM


def safe_filename(name: str) -> str:
    """A file name for ``Content-Disposition``: no folders, no control or quote characters, at most 150 characters."""
    base = posixpath.basename(name.replace("\\", "/")).strip().strip(".")
    cleaned = re.sub(r'[\x00-\x1f\x7f"\\/:*?<>|]+', "_", base)[:150]
    return cleaned or "artifact"


@dataclass(frozen=True, slots=True)
class ServedContent:
    content_type: str
    headers: dict[str, str]


def serve(filename: str, data: bytes, *, declared: str | None, disposition: Disposition) -> ServedContent:
    """The content type and headers to send an artefact with."""
    content_type = content_type_of(filename, data, declared)
    name = safe_filename(filename)
    ascii_name = name.encode("ascii", "replace").decode().replace("?", "_")
    active = content_type in ACTIVE_TYPES
    headers = {
        "Content-Security-Policy": SCRIPTED_SANDBOX_POLICY if active and disposition == "inline" else INERT_POLICY,
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "private, max-age=300",
        "Content-Disposition": f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}",
    }
    if content_type.startswith("text/") or content_type in {"application/json", "application/x-ndjson"}:
        content_type = f"{content_type}; charset=utf-8"
    return ServedContent(content_type=content_type, headers=headers)
