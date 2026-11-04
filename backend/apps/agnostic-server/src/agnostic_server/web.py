"""The built web app and the bundled user guides, served by the API on the same origin.

Every ``GET`` outside the API's own path segments (``api``, ``.well-known``, ``healthz``, …) is the web app: an
existing file of the build is served as is (hashed ``/assets/*`` files are cached for a year), anything else gets
``index.html`` so client-side routes survive a reload.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from starlette.responses import FileResponse
from starlette.types import ASGIApp, Receive, Scope, Send

IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"
_TITLE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def inside(root: Path, relative: str) -> Path | None:
    """``root / relative`` when it stays inside ``root`` and is a file, else ``None`` (no ``..`` escapes)."""
    try:
        candidate = (root / relative.lstrip("/")).resolve()
        if candidate.is_relative_to(root.resolve()) and candidate.is_file():
            return candidate
    except OSError, ValueError:
        return None
    return None


class WebApp:
    """ASGI middleware serving the single-page app for paths the API doesn't own."""

    def __init__(self, app: ASGIApp, *, web_dir: Path, reserved: set[str]) -> None:
        self.app = app
        self._root = web_dir
        self._index = web_dir / "index.html"
        self._reserved = reserved

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path", "/"))
        first = path.lstrip("/").split("/", 1)[0]
        if scope["type"] != "http" or scope["method"] not in {"GET", "HEAD"} or first in self._reserved:
            await self.app(scope, receive, send)
            return
        file = inside(self._root, path) if path != "/" else None
        if file is not None:
            cache = IMMUTABLE if first == "assets" else REVALIDATE
            response = FileResponse(file, headers={"Cache-Control": cache})
        elif first == "assets" or not self._index.is_file():
            response = PlainTextResponse("Not found", status_code=404)
        else:
            response = FileResponse(self._index, headers={"Cache-Control": REVALIDATE})
        await response(scope, receive, send)


def reserved_segments(paths: list[str]) -> set[str]:
    """First path segments of the API's own routes (``/api/v1/…`` → ``api``)."""
    return {segment for path in paths if (segment := path.lstrip("/").split("/", 1)[0]) and "{" not in segment}


class GuideEntry(BaseModel):
    path: str
    """Relative to the guides root, e.g. ``admin/install.md``."""
    title: str


class GuideIndex(BaseModel):
    available: bool
    guides: list[GuideEntry]


@dataclass(frozen=True, slots=True)
class Guides:
    root: Path | None

    def index(self) -> GuideIndex:
        if self.root is None or not self.root.is_dir():
            return GuideIndex(available=False, guides=[])
        entries: list[GuideEntry] = []
        for file in sorted(self.root.rglob("*.md")):
            relative = file.relative_to(self.root).as_posix()
            found = _TITLE.search(file.read_text(encoding="utf-8", errors="replace")[:4000])
            entries.append(GuideEntry(path=relative, title=found.group(1).strip() if found else relative))
        return GuideIndex(available=True, guides=entries)

    def read(self, relative: str) -> str | None:
        if self.root is None or not relative.endswith(".md"):
            return None
        file = inside(self.root, relative)
        return file.read_text(encoding="utf-8", errors="replace") if file is not None else None


def guides_router(guides: Guides) -> APIRouter:
    router = APIRouter(tags=["system"])

    @router.get("/system/docs", summary="The user guides bundled with this installation")
    async def list_guides() -> GuideIndex:
        return guides.index()

    @router.get(
        "/system/docs/{path:path}",
        summary="One bundled guide (Markdown)",
        response_class=PlainTextResponse,
        responses={200: {"content": {"text/markdown": {}}}},
    )
    async def read_guide(path: str) -> PlainTextResponse:
        text = guides.read(path)
        if text is None:
            raise HTTPException(status_code=404, detail=f"There is no guide {path!r}.")
        return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")

    return router
