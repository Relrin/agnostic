"""Ports of the studio module."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from agnostic_kernel.errors import AppError
from agnostic_studio.domain.model import CanvasLayout, CodeDocument, ComponentMeta, HoldCheck, VersionMeta
from agnostic_studio.domain.promotion import Promotion
from agnostic_studio.domain.usage import IndexEntry


class StudioStore(Protocol):
    async def component_meta(self, instance_id: str, component_id: str) -> ComponentMeta | None: ...
    async def component_metas(self, instance_id: str) -> dict[str, ComponentMeta]: ...
    async def save_component_meta(self, meta: ComponentMeta) -> None: ...

    async def version_metas(self, instance_id: str, component_id: str) -> dict[int, VersionMeta]: ...
    async def version_meta(self, instance_id: str, component_id: str, version: int) -> VersionMeta | None: ...
    async def save_version_meta(self, meta: VersionMeta) -> None: ...

    async def replace_index(self, instance_id: str, snapshot_hash: str, entries: list[IndexEntry]) -> None:
        """Swap the instance's whole used-by index for ``entries``."""
        ...

    async def index(self, instance_id: str) -> list[IndexEntry]: ...

    async def add_promotion(self, promotion: Promotion) -> None: ...
    async def save_promotion(self, promotion: Promotion) -> None: ...
    async def promotion(self, promotion_id: str) -> Promotion | None: ...
    async def promotions(self, instance_id: str, component_id: str, limit: int = 20) -> list[Promotion]: ...

    async def canvas_layout(self, instance_id: str, component_id: str, version: int) -> CanvasLayout | None: ...
    async def save_canvas_layout(self, layout: CanvasLayout) -> None: ...

    async def code_document(self, instance_id: str, component_id: str, version: int) -> CodeDocument | None: ...
    async def save_code_document(self, document: CodeDocument) -> None: ...
    async def drop_code_document(self, instance_id: str, component_id: str, version: int) -> None: ...

    async def commit(self) -> None: ...


class SourceTimeoutError(AppError):
    status = 422
    code = "source_timeout"
    title = "The code took too long to process"

    def __init__(self, seconds: float) -> None:
        super().__init__(f"Reading or editing this code took longer than {seconds:g} s and was stopped.")


class SourceRunner(Protocol):
    """Runs CPU-bound source work (parsing, edits, CEL) away from the event loop, with a timeout per job."""

    async def run[**P, T](self, job: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T: ...


class PublishHold(Protocol):
    """Lets another module hold a publish back; Studio itself never does."""

    async def check(self, instance_id: str, component_id: str, version: int) -> HoldCheck: ...


class NoPublishHold:
    async def check(self, instance_id: str, component_id: str, version: int) -> HoldCheck:  # noqa: ARG002
        return HoldCheck()
