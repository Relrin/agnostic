"""``agnostic tokens``: service accounts and their tokens from the command line.

Runs against the local database and instances as the control plane itself (like ``bootstrap``). Tokens are printed
once; afterwards only their prefixes are visible.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Annotated, cast

import typer
from dishka import AsyncContainer

from agnostic_kernel.auth import Principal
from agnostic_kernel.container import build_container
from agnostic_kernel.errors import AppError
from agnostic_kernel.logging import configure_logging
from agnostic_kernel.modules import load_modules
from agnostic_kernel.settings import Settings
from agnostic_server import loops

if TYPE_CHECKING:
    from agnostic_service_accounts.facade import Created, ServiceAccountsFacade, TokenKind

CLI_PRINCIPAL = Principal(kind="system", id="system", display_name="agnostic CLI", via="cli")

tokens_app = typer.Typer(no_args_is_help=True, help="Service accounts and their tokens (native and gateway).")


def _split(values: list[str] | None) -> list[str]:
    return [item.strip() for value in values or [] for item in value.split(",") if item.strip()]


async def _facade(container: AsyncContainer) -> ServiceAccountsFacade:
    from agnostic_service_accounts.facade import ServiceAccountsFacade  # noqa: PLC0415  (an optional module)

    return await container.get(ServiceAccountsFacade)


async def create_lines(
    container: AsyncContainer,
    name: str,
    *,
    instances: list[str],
    role: str | None,
    scopes: list[str],
    expires_in: str,
    kinds: list[TokenKind],
    forwards_user_id: bool,
    created_by: str | None,
    yes_privileged: bool,
    description: str = "",
) -> list[str]:
    from agnostic_service_accounts.facade import NewServiceAccount  # noqa: PLC0415

    async with container() as request:
        facade = await _facade(request)
        created = await facade.create(
            CLI_PRINCIPAL,
            NewServiceAccount(
                name=name,
                instances=tuple(instances),
                description=description,
                role_id=role,
                scopes=tuple(scopes),
                expires_in=expires_in,
                kinds=tuple(kinds),
                forwards_user_id=forwards_user_id,
                confirm_privileged=yes_privileged,
                created_by_email=created_by,
            ),
        )
    return _created_lines(created)


def _created_lines(created: Created) -> list[str]:
    view = created.view
    account = view.account
    lines = [
        f"created {account.principal} ({account.id})",
        f"scopes:  {', '.join(view.all_scopes)} ({view.source_label})",
        f"on:      {', '.join(instance.slug for instance in view.instances)}",
        "expires: " + (account.expires_at.date().isoformat() if account.expires_at else "never"),
        "",
        "Copy the tokens now: they are shown once. Afterwards only the prefix is visible.",
    ]
    for token in created.tokens:
        where = f" for {token.instance.slug}" if token.instance else " (gateway, every instance above)"
        lines.extend(("", f"{token.kind} token{where}:", token.token, "", token.curl))
    return lines


async def list_lines(container: AsyncContainer) -> list[str]:
    async with container() as request:
        views = await (await _facade(request)).list(CLI_PRINCIPAL)
    if not views:
        return ["No service accounts yet."]
    lines: list[str] = []
    for view in views:
        account = view.account
        expires = account.expires_at.date().isoformat() if account.expires_at else "never"
        if account.expired(view.now):
            expires = f"expired {expires}"
        tokens = [f"{t.token_prefix}… {t.status}" for t in view.native_tokens]
        tokens.extend(f"{t.prefix}… {t.current_status(view.now)}" for t in view.gateway_tokens)
        lines.append(
            f"{account.principal:<32} {len(view.all_scopes):>3} scopes  "
            f"{','.join(i.slug for i in view.instances):<28} expires {expires:<12} {'; '.join(tokens) or '-'}"
        )
    return lines


async def revoke_lines(container: AsyncContainer, name: str, token: str | None) -> list[str]:
    async with container() as request:
        await (await _facade(request)).revoke(CLI_PRINCIPAL, name, token=token)
    if token:
        return [f"revoked {token}… of sa:{name.removeprefix('sa:')}"]
    return [f"deleted sa:{name.removeprefix('sa:')}: every token revoked, its grants removed"]


def _run(work: Callable[[AsyncContainer], Awaitable[list[str]]]) -> None:
    settings = Settings()
    configure_logging(settings.log)

    async def go() -> list[str]:
        container = build_container(settings, load_modules(settings.modules.disabled))
        try:
            return await work(container)
        finally:
            await container.close()

    try:
        lines = loops.run(go)
    except AppError as exc:
        typer.secho(exc.detail or exc.title, fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    for line in lines:
        typer.echo(line)


@tokens_app.command("create")
def create(
    name: Annotated[str, typer.Argument(help="Lowercase slug; runs show up as sa:<name>")],
    instance: Annotated[list[str], typer.Option("--instance", help="Instance slug or id (repeatable)")],
    role: Annotated[str | None, typer.Option("--role", help="Access role slug or id")] = None,
    scopes: Annotated[list[str] | None, typer.Option("--scopes", help="Comma-separated custom scopes")] = None,
    extra_scopes: Annotated[
        list[str] | None, typer.Option("--extra-scopes", help="Comma-separated scopes on top of --role")
    ] = None,
    expires_in: Annotated[str, typer.Option("--expires-in", help="30d, 90d, 365d or never")] = "90d",
    kind: Annotated[list[str] | None, typer.Option("--kind", help="native or gateway (repeatable)")] = None,
    forwards_user_id: Annotated[
        bool, typer.Option("--forwards-user-id", help="Gateway: pass the caller's user_id through")
    ] = False,
    created_by: Annotated[str | None, typer.Option("--created-by", help="Email recorded as the creator")] = None,
    yes_privileged: Annotated[
        bool, typer.Option("--yes-privileged", help="Confirm privileged scopes (write, delete, admin)")
    ] = False,
    description: Annotated[str, typer.Option("--description", help="What the account is for")] = "",
) -> None:
    """Create a service account and print its tokens (once)."""
    if role is None and not scopes:
        typer.secho("Give --role or --scopes.", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    if role is not None and scopes:
        typer.secho("--scopes is for custom accounts; use --extra-scopes with --role.", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    kinds = _split(kind) or ["native"]
    unknown = [item for item in kinds if item not in {"native", "gateway"}]
    if unknown:
        typer.secho(f"--kind is native or gateway, not {', '.join(unknown)}.", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    _run(
        lambda container: create_lines(
            container,
            name,
            instances=_split(instance),
            role=role,
            scopes=_split(scopes) + _split(extra_scopes),
            expires_in=expires_in,
            kinds=cast("list[TokenKind]", [item for item in ("native", "gateway") if item in kinds]),
            forwards_user_id=forwards_user_id,
            created_by=created_by,
            yes_privileged=yes_privileged,
            description=description,
        )
    )


@tokens_app.command("list")
def list_accounts() -> None:
    """List service accounts with their scopes, instances, expiry and token prefixes."""
    _run(list_lines)


@tokens_app.command("revoke")
def revoke(
    name: Annotated[str, typer.Argument(help="The service account (name or sa:<name>)")],
    token: Annotated[
        str | None, typer.Option("--token", help="Revoke only this token (prefix or id); otherwise delete the account")
    ] = None,
) -> None:
    """Revoke one token now, or delete the account (every token revoked on every instance)."""
    _run(lambda container: revoke_lines(container, name, token))
