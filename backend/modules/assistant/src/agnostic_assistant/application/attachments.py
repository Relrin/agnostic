"""Files attached to a question: text-like files become quoted text, images go to models that read images."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePath

from agnostic_assistant.domain.model import Attachment
from agnostic_assistant.domain.settings import VISION_PROVIDERS
from agnostic_kernel.errors import ValidationFailedError
from agnostic_kernel.ids import new_id

TEXT_TYPES = frozenset(
    {
        "application/json",
        "application/x-ndjson",
        "application/yaml",
        "application/x-yaml",
        "application/xml",
        "application/csv",
        "application/toml",
    }
)
TEXT_SUFFIXES = frozenset(
    {".log", ".txt", ".json", ".jsonl", ".ndjson", ".csv", ".md", ".yaml", ".yml", ".xml", ".toml", ".out", ".err"}
)
IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})


@dataclass(frozen=True, slots=True)
class AttachmentLimits:
    max_files: int
    max_bytes: int
    max_chars: int


@dataclass(frozen=True, slots=True)
class Upload:
    name: str
    media_type: str
    data: bytes


def _is_text(upload: Upload) -> bool:
    media_type = upload.media_type.split(";", 1)[0].strip().lower()
    return (
        media_type.startswith("text/")
        or media_type in TEXT_TYPES
        or PurePath(upload.name).suffix.lower() in TEXT_SUFFIXES
    )


def _text(data: bytes, limit: int) -> str:
    text = data.decode("utf-8", errors="replace").replace("\x00", "")
    if len(text) <= limit:
        return text
    # Logs end with the failure; keep the end.
    return f"(first {len(text) - limit:,} characters left out)\n{text[-limit:]}"


def extract(uploads: Sequence[Upload], *, provider: str | None, limits: AttachmentLimits) -> list[Attachment]:
    if len(uploads) > limits.max_files:
        raise ValidationFailedError(f"Attach at most {limits.max_files} files.")
    found: list[Attachment] = []
    for upload in uploads:
        name = PurePath(upload.name or "attachment").name[:200]
        if len(upload.data) > limits.max_bytes:
            limit = limits.max_bytes / 1_000_000
            raise ValidationFailedError(f"{name} is larger than {limit:g} MB.")
        media_type = upload.media_type.split(";", 1)[0].strip().lower() or "application/octet-stream"
        if media_type in IMAGE_TYPES:
            if provider not in VISION_PROVIDERS:
                raise ValidationFailedError(
                    f"{name} is an image, and the configured model provider doesn't take images. "
                    "Attach the log or error text instead."
                )
            found.append(Attachment(new_id("att"), name, media_type, len(upload.data), None, upload.data))
        elif _is_text(upload):
            text = _text(upload.data, limits.max_chars)
            found.append(Attachment(new_id("att"), name, "text/plain", len(upload.data), text))
        else:
            raise ValidationFailedError(
                f"{name}: attach text files (logs, JSON, YAML, CSV, Markdown) or screenshots (PNG, JPEG, WebP, GIF)."
            )
    return found
