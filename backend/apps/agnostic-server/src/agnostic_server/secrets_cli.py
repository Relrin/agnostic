"""``agnostic secrets``: master keys, KMS wrapping and re-sealing stored secrets with a new master key."""

from __future__ import annotations

from typing import Annotated, Literal

import typer

from agnostic_kernel.crypto import SecretBox, SecretsConfigError, generate_master_key, key_id
from agnostic_kernel.db import create_engine
from agnostic_kernel.keys import (
    KeyProvider,
    configured_keys,
    create_key_provider,
    load_secret_box,
    unwrap_all,
)
from agnostic_kernel.logging import configure_logging
from agnostic_kernel.modules import SealedColumn, discover_modules
from agnostic_kernel.rewrap import ColumnReport, scan
from agnostic_kernel.settings import Settings
from agnostic_server import loops

secrets_app = typer.Typer(no_args_is_help=True, help="Master keys and the secrets sealed with them.")

# A plain alias (not a ``type`` statement): Typer reads the Literal to offer the choices.
Provider = Literal["local", "vault", "aws-kms", "azure-key-vault", "gcp-kms"]
ProviderOption = Annotated[
    Provider | None,
    typer.Option("--provider", help="local, vault, aws-kms, azure-key-vault or gcp-kms (default: the configured one)"),
]


def _fail(message: str) -> typer.Exit:
    typer.secho(message, fg=typer.colors.RED, err=True)
    return typer.Exit(1)


def _sealed_columns() -> list[SealedColumn]:
    return [column for module in discover_modules() for column in module.sealed_columns()]


async def _wrap(provider: KeyProvider, keys: list[bytes]) -> list[str]:
    try:
        return [await provider.wrap(key) for key in keys]
    finally:
        await provider.aclose()


@secrets_app.command("generate-key")
def generate_key(provider: ProviderOption = None) -> None:
    """Print a new random master key, wrapped by the KMS provider when one is configured.

    Put the value into AGNOSTIC_SECRETS__MASTER_KEY (or the file named by __MASTER_KEY_FILE) and keep a backup:
    without the master key, every stored secret is lost.
    """
    settings = Settings()
    key = generate_master_key()
    try:
        target = create_key_provider(settings.secrets, settings.tls, name=provider)
        (wrapped,) = loops.run(lambda: _wrap(target, [key]))
    except SecretsConfigError as exc:
        raise _fail(str(exc)) from exc
    typer.echo(f"# master key {key_id(key)} ({target.name})", err=True)
    typer.echo(wrapped)


@secrets_app.command("wrap-key")
def wrap_key(
    to: Annotated[Provider, typer.Option("--to", help="Provider to wrap the configured keys with")],
) -> None:
    """Re-wrap the configured master keys (current and previous) for another provider or a newer KMS key version.

    Prints the new AGNOSTIC_SECRETS__MASTER_KEY, then one line per AGNOSTIC_SECRETS__PREVIOUS_KEYS entry. The keys
    themselves don't change, so nothing has to be re-sealed.
    """
    settings = Settings()
    configure_logging(settings.log)
    current, previous = configured_keys(settings.secrets)
    if current is None:
        raise _fail("no master key is configured (AGNOSTIC_SECRETS__MASTER_KEY or __MASTER_KEY_FILE)")

    async def run() -> list[str]:
        source = create_key_provider(settings.secrets, settings.tls)
        try:
            key, retired = await unwrap_all(source, current, previous)
        finally:
            await source.aclose()
        return await _wrap(create_key_provider(settings.secrets, settings.tls, name=to), [key, *retired])

    try:
        wrapped = loops.run(run)
    except SecretsConfigError as exc:
        raise _fail(str(exc)) from exc
    typer.echo(f"# AGNOSTIC_SECRETS__PROVIDER={to}", err=True)
    typer.echo("# AGNOSTIC_SECRETS__MASTER_KEY", err=True)
    typer.echo(wrapped[0])
    if len(wrapped) > 1:
        typer.echo("# AGNOSTIC_SECRETS__PREVIOUS_KEYS (one per line in __PREVIOUS_KEYS_FILE)", err=True)
        for value in wrapped[1:]:
            typer.echo(value)


async def _scan(*, reseal: bool) -> tuple[SecretBox, list[ColumnReport]]:
    settings = Settings()
    configure_logging(settings.log)
    box = await load_secret_box(settings.secrets, settings.tls, environment=settings.env)
    engine = create_engine(settings.database)
    try:
        return box, await scan(engine, box, _sealed_columns(), reseal=reseal)
    finally:
        await engine.dispose()


def _print(box: SecretBox, reports: list[ColumnReport]) -> dict[str, int]:
    totals: dict[str, int] = dict.fromkeys(box.key_ids, 0)
    for report in reports:
        if report.missing_table:
            typer.echo(f"{report.label:<52} (table not created yet)")
            continue
        counts = ", ".join(f"{kid}={count}" for kid, count in sorted(report.by_key.items())) or "empty"
        resealed = f"  re-sealed {report.resealed} rows" if report.resealed else ""
        typer.echo(f"{report.label:<52} {counts}{resealed}")
        for kid, count in report.by_key.items():
            totals[kid] = totals.get(kid, 0) + count
    return totals


@secrets_app.command("status")
def status() -> None:
    """Show which master key every stored secret is sealed with; exits 1 when a value needs an unknown key."""
    try:
        box, reports = loops.run(lambda: _scan(reseal=False))
    except SecretsConfigError as exc:
        raise _fail(str(exc)) from exc
    typer.echo(f"current master key: {box.key_id}; previous: {', '.join(box.key_ids[1:]) or 'none'}")
    totals = _print(box, reports)
    unknown = [kid for kid in totals if kid not in box.key_ids]
    stale = sum(count for kid, count in totals.items() if kid != box.key_id)
    if unknown:
        raise _fail(f"values sealed with unconfigured master keys: {', '.join(unknown)}")
    typer.echo(f"{stale} value(s) still sealed with a previous key" if stale else "every value uses the current key")


@secrets_app.command("rotate")
def rotate() -> None:
    """Re-seal every stored secret with the current master key.

    Configure the new key as AGNOSTIC_SECRETS__MASTER_KEY and the old one in __PREVIOUS_KEYS first; run this once,
    then remove the old key after the API and workers restarted with the new configuration. Safe to run again.
    """
    try:
        box, reports = loops.run(lambda: _scan(reseal=True))
    except SecretsConfigError as exc:
        raise _fail(str(exc)) from exc
    _ = _print(box, reports)
    resealed = sum(report.resealed for report in reports)
    typer.echo(f"re-sealed {resealed} row(s) with master key {box.key_id}")
    settings = Settings()
    if "service_accounts" not in settings.modules.disabled:
        typer.echo(
            "Gateway tokens of service accounts are re-hashed on their next use; keep the previous key configured "
            "until they have all been used, or set AGNOSTIC_SERVICE_ACCOUNTS__TOKEN_PEPPER to keep them independent "
            "of the master key."
        )
