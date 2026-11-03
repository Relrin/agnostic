"""``agnostic audit``: verify the tamper-evidence chain, restore archived months."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated

import typer

from agnostic_audit.facade import AuditAdmin, ChainResult, RestoredMonth
from agnostic_kernel.container import build_container
from agnostic_kernel.db import aware
from agnostic_kernel.errors import AppError
from agnostic_kernel.logging import configure_logging
from agnostic_kernel.modules import load_modules
from agnostic_kernel.settings import Settings
from agnostic_server import loops

audit_app = typer.Typer(no_args_is_help=True, help="The audit log: hash-chain verification and archive restores.")


async def _with_admin[T](action: Callable[[AuditAdmin], Awaitable[T]]) -> T:
    settings = Settings()
    configure_logging(settings.log)
    container = build_container(settings, load_modules(settings.modules.disabled))
    try:
        async with container() as request:
            return await action(await request.get(AuditAdmin))
    finally:
        await container.close()


def _time(value: str | None, option: str) -> datetime | None:
    if value is None:
        return None
    try:
        return aware(datetime.fromisoformat(value))
    except ValueError as exc:
        raise typer.BadParameter(
            f"{value!r} isn't an ISO 8601 time (2026-01-31 or 2026-01-31T12:00:00Z)", param_hint=option
        ) from exc


@audit_app.command("verify")
def verify(
    since: Annotated[str | None, typer.Option(help="From this time (ISO 8601), inclusive")] = None,
    until: Annotated[str | None, typer.Option(help="Up to this time (ISO 8601), exclusive")] = None,
) -> None:
    """Check the hash chain; exits 1 when an event was changed, inserted or removed."""
    start, end = _time(since, "--since"), _time(until, "--until")

    async def run(admin: AuditAdmin) -> ChainResult:
        return await admin.verify(start, end)

    result = loops.run(lambda: _with_admin(run))
    if result.ok:
        typer.echo(f"ok: {result.checked} chained events verified")
        return
    typer.secho(
        f"broken: the chain breaks at {result.first_broken_event_id} (after {result.checked - 1} good events)",
        fg=typer.colors.RED,
        err=True,
    )
    raise typer.Exit(1)


@audit_app.command("restore")
def restore(month: Annotated[str, typer.Argument(help="The archived month, e.g. 2025-08")]) -> None:
    """Download an archived month, verify it against its manifest and make it searchable for 7 days."""

    async def run(admin: AuditAdmin) -> RestoredMonth:
        return await admin.restore(month)

    try:
        restored = loops.run(lambda: _with_admin(run))
    except AppError as exc:
        typer.secho(exc.detail or exc.title, fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    except (ValueError, OSError) as exc:
        typer.secho(f"restore failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    until = restored.restore_expires_at.isoformat() if restored.restore_expires_at else "-"
    typer.echo(f"restored {restored.month}: {restored.event_count} events, searchable until {until}")
