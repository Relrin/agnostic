"""Turn a produced file into Agno media: detect its type from its bytes, then build an Image, Audio, Video or File.

The type a tool or model claims is never used: the bytes decide, with the extension as the tie-breaker for text.
Every artefact carries ``metadata["artifact"]``, which the artefact index reads back.
"""

from __future__ import annotations

import hashlib
import mimetypes
import posixpath
from typing import Any

from agno.media import Audio, File, Image, Video

ARTIFACT_METADATA_KEY = "artifact"

_SIGNATURES: tuple[tuple[bytes, int, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", 0, "image/png"),
    (b"\xff\xd8\xff", 0, "image/jpeg"),
    (b"GIF87a", 0, "image/gif"),
    (b"GIF89a", 0, "image/gif"),
    (b"%PDF-", 0, "application/pdf"),
    (b"PK\x03\x04", 0, "application/zip"),
    (b"ID3", 0, "audio/mpeg"),
    (b"OggS", 0, "audio/ogg"),
    (b"fLaC", 0, "audio/flac"),
    (b"\x1aE\xdf\xa3", 0, "video/webm"),
)

_TEXT_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".log": "text/plain",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".ipynb": "application/x-ipynb+json",
    ".jsonl": "application/x-ndjson",
    ".html": "text/html",
    ".htm": "text/html",
    ".svg": "image/svg+xml",
    ".xml": "text/xml",
    ".css": "text/css",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".ts": "text/x-typescript",
    ".tsx": "text/x-typescript",
    ".py": "text/x-python",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".toml": "text/x-toml",
    ".sql": "text/x-sql",
    ".sh": "text/x-shellscript",
    ".rs": "text/x-rust",
    ".go": "text/x-go",
}

_OFFICE = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _riff(data: bytes) -> str | None:
    if data[:4] != b"RIFF" or len(data) < 12:
        return None
    return {b"WEBP": "image/webp", b"WAVE": "audio/wav", b"AVI ": "video/x-msvideo"}.get(data[8:12])


def _iso_media(data: bytes) -> str | None:
    if data[4:8] != b"ftyp":
        return None
    brand = data[8:12]
    if brand in {b"M4A ", b"M4B "}:
        return "audio/mp4"
    if brand == b"qt  ":
        return "video/quicktime"
    return "video/mp4"


def _looks_textual(data: bytes) -> bool:
    sample = data[:4096]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError as error:
        return error.start >= len(sample) - 3  # a multi-byte character cut by the sample
    return True


def detect_content_type(filename: str, data: bytes) -> str:
    """The content type of ``data``: magic bytes first, then the extension for text formats."""
    extension = posixpath.splitext(filename.lower())[1]
    for signature, offset, kind in _SIGNATURES:
        if data[offset : offset + len(signature)] == signature:
            if kind == "application/zip" and extension in _OFFICE:
                return _OFFICE[extension]
            return kind
    if (kind := _riff(data) or _iso_media(data)) is not None:
        return kind
    if _looks_textual(data):
        if extension in _TEXT_TYPES:
            return _TEXT_TYPES[extension]
        stripped = data[:512].lstrip().lower()
        if stripped.startswith((b"<!doctype html", b"<html")):
            return "text/html"
        if stripped.startswith(b"<svg") or (stripped.startswith(b"<?xml") and b"<svg" in data[:2048].lower()):
            return "image/svg+xml"
        guessed = mimetypes.guess_type(filename)[0]
        return guessed if guessed and guessed.startswith("text/") else "text/plain"
    return "application/octet-stream"


def artifact_kind(content_type: str) -> str:
    """One of image, audio, video, file: which Agno media list the artefact goes to."""
    major = content_type.split("/", 1)[0]
    return major if major in {"image", "audio", "video"} else "file"


def build_media(
    path: str,
    data: bytes,
    *,
    source: str,
    title: str | None = None,
    producer: str | None = None,
    revision: int = 1,
) -> Image | Audio | Video | File:
    """Agno media for one produced file, with ``metadata["artifact"]`` describing where it came from."""
    filename = posixpath.basename(path) or "artifact"
    content_type = detect_content_type(filename, data)
    digest = hashlib.sha256(data).hexdigest()
    extension = posixpath.splitext(filename)[1].lstrip(".").lower() or None
    metadata: dict[str, Any] = {
        ARTIFACT_METADATA_KEY: {
            "path": path,
            "filename": filename,
            "title": title or filename,
            "content_type": content_type,
            "size": len(data),
            "sha256": digest,
            "source": source,
            "producer": producer,
            "revision": revision,
        }
    }
    # A stable id per (path, bytes): Agno's offload cache reuses an upload it already made for the same id.
    media_id = f"art_{hashlib.sha256(f'{path}:{digest}'.encode()).hexdigest()[:24]}"
    kind = artifact_kind(content_type)
    if kind == "image":
        return Image(id=media_id, content=data, mime_type=content_type, format=extension, metadata=metadata)
    if kind == "audio":
        return Audio(id=media_id, content=data, mime_type=content_type, format=extension, metadata=metadata)
    if kind == "video":
        return Video(id=media_id, content=data, mime_type=content_type, format=extension, metadata=metadata)
    # File only accepts the document types Agno can hand to a model; the real type stays in the metadata.
    mime = content_type if content_type in File.valid_mime_types() else None
    return File(
        id=media_id,
        content=data,
        mime_type=mime,
        filename=filename,
        name=filename,
        size=len(data),
        format=extension,
        metadata=metadata,
    )


def attach(run_output: Any, media: list[Image | Audio | Video | File]) -> None:
    """Append media to a run's output lists (``images``, ``audio``, ``videos``, ``files``), skipping duplicates."""
    for item in media:
        attribute = {Image: "images", Audio: "audio", Video: "videos"}.get(type(item), "files")
        existing = list(getattr(run_output, attribute, None) or [])
        if any(getattr(other, "id", None) == item.id for other in existing):
            continue
        existing.append(item)
        setattr(run_output, attribute, existing)
