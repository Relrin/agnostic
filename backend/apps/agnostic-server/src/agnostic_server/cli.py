"""The ``agnostic`` command line (02 §10)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated

import orjson
import typer
import uvicorn
import watchfiles

from agnostic_kernel import metrics, migrations_runner
from agnostic_kernel.bootstrap import Bootstrapper, BootstrapResult, OwnerAccount
from agnostic_kernel.checks import run_all_checks
from agnostic_kernel.container import build_container
from agnostic_kernel.db import create_engine
from agnostic_kernel.errors import AppError
from agnostic_kernel.logging import configure_logging
from agnostic_kernel.modules import ModuleGraphError, discover_modules, load_modules, resolve_modules
from agnostic_kernel.settings import Settings
from agnostic_server import loops
from agnostic_server.audit_cli import audit_app
from agnostic_server.secrets_cli import secrets_app
from agnostic_server.tokens import tokens_app
from agnostic_server.worker import WorkerUnavailableError, run_worker

LOOP = "agnostic_server.loops:new_event_loop"

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Agnostic control plane.")
db_app = typer.Typer(no_args_is_help=True, help="Database migrations (Alembic, one branch per module).")
config_app = typer.Typer(no_args_is_help=True, help="Inspect configuration.")
modules_app = typer.Typer(no_args_is_help=True, help="Installed modules.")
app.add_typer(db_app, name="db")
app.add_typer(config_app, name="config")
app.add_typer(modules_app, name="modules")
app.add_typer(tokens_app, name="tokens")
app.add_typer(audit_app, name="audit")
app.add_typer(secrets_app, name="secrets")


def _source_dirs() -> list[Path]:
    """Workspace source folders watched by ``agnostic dev`` (empty when installed from wheels)."""
    backend = Path(__file__).resolve().parents[4]
    return [path for name in ("apps", "packages", "modules") if (path := backend / name).is_dir()]


@app.command()
def api(
    host: Annotated[str | None, typer.Option(help="Bind address (default: AGNOSTIC_HTTP__HOST)")] = None,
    port: Annotated[int | None, typer.Option(help="Port (default: AGNOSTIC_HTTP__PORT)")] = None,
    reload: Annotated[bool, typer.Option(help="Restart on code changes (development)")] = False,
) -> None:
    """Serve the HTTP API (and Prometheus metrics on AGNOSTIC_METRICS__PORT)."""
    settings = Settings()
    if not reload:
        metrics.serve_metrics(settings.metrics)
    uvicorn.run(
        "agnostic_server.app:create_app",
        factory=True,
        host=host or settings.http.host,
        port=port or settings.http.port,
        reload=reload,
        reload_dirs=[str(p) for p in _source_dirs()] if reload else None,
        loop=LOOP,
        log_config=None,
        proxy_headers=True,
    )


@app.command()
def worker(
    queue: Annotated[list[str] | None, typer.Option("--queue", "-q", help="Queue to listen to (repeatable)")] = None,
    concurrency: Annotated[int | None, typer.Option(help="Jobs run in parallel")] = None,
) -> None:
    """Run background jobs and periodic schedules."""
    try:
        loops.run(lambda: run_worker(Settings(), queues=queue, concurrency=concurrency))
    except WorkerUnavailableError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc


def _worker_process() -> None:
    loops.run(lambda: run_worker(Settings()))


@app.command()
def dev() -> None:
    """API and worker with auto-reload, for local development."""
    settings = Settings()
    api_process = subprocess.Popen([sys.executable, "-m", "agnostic_server", "api", "--reload"])
    try:
        if settings.job_mode() == "worker":
            _ = watchfiles.run_process(
                *_source_dirs(),
                target=_worker_process,
                watch_filter=watchfiles.PythonFilter(),
            )
        else:
            typer.echo(f"Jobs run inside the API process ({settings.database.backend}, embedded mode).")
            _ = api_process.wait()
    except KeyboardInterrupt:
        pass
    finally:
        api_process.terminate()
        _ = api_process.wait(timeout=15)


async def _migrate(operation: str, revision: str) -> None:
    settings = Settings()
    engine = create_engine(settings.database)
    modules = list(discover_modules())
    try:
        if operation == "upgrade":
            await migrations_runner.upgrade(engine, modules, revision)
        elif operation == "downgrade":
            await migrations_runner.downgrade(engine, modules, revision)
        state = await migrations_runner.state(engine, modules)
    finally:
        await engine.dispose()
    typer.echo(f"current: {', '.join(state.current) or '(empty)'}")
    typer.echo(f"heads:   {', '.join(state.heads)}")
    if state.pending:
        typer.echo(f"pending: {', '.join(state.pending)}")
    typer.echo("status:  " + ("up to date" if state.up_to_date else "pending migrations"))


async def _check_upgrade(revision: str) -> list[migrations_runner.AppliedRevision]:
    engine = create_engine(Settings().database)
    try:
        return await migrations_runner.check_upgrade(engine, list(discover_modules()), revision)
    finally:
        await engine.dispose()


@db_app.command("upgrade")
def db_upgrade(
    revision: Annotated[str, typer.Argument(help="Target revision")] = "heads",
    check: Annotated[
        bool, typer.Option("--check", help="Apply in one transaction, report timings, then roll back")
    ] = False,
) -> None:
    """Apply migrations of the kernel and every installed module."""
    configure_logging(Settings().log)
    if not check:
        loops.run(lambda: _migrate("upgrade", revision))
        return
    if Settings().database.backend != "postgresql":
        typer.secho(
            "--check needs PostgreSQL: SQLite commits schema changes right away.", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(2)
    try:
        applied = loops.run(lambda: _check_upgrade(revision))
    except Exception as exc:
        typer.secho(f"upgrade check failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    for step in applied:
        typer.echo(f"{step.revision:<40} {step.seconds * 1000:>9.1f} ms")
    typer.echo(f"{len(applied)} revision(s) would be applied; rolled back, nothing changed")


@app.command()
def migrate() -> None:
    """Apply every pending migration (the same as `agnostic db upgrade`; the image's one-shot command)."""
    configure_logging(Settings().log)
    loops.run(lambda: _migrate("upgrade", "heads"))


@db_app.command("downgrade")
def db_downgrade(revision: Annotated[str, typer.Argument(help="Target, e.g. 'gateway@base' or 'base'")]) -> None:
    """Revert migrations down to a revision."""
    configure_logging(Settings().log)
    loops.run(lambda: _migrate("downgrade", revision))


@db_app.command("current")
def db_current() -> None:
    """Show applied revisions and heads."""
    loops.run(lambda: _migrate("current", ""))


@config_app.command("check")
def config_check(
    connect: Annotated[bool, typer.Option("--connect", help="Probe every configured endpoint")] = False,
) -> None:
    """Print the effective configuration (secrets redacted); with --connect, probe each endpoint."""
    settings = Settings()
    typer.echo(orjson.dumps(settings.redacted(), option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS).decode())
    try:
        modules = load_modules(settings.modules.disabled)
    except ModuleGraphError as exc:
        typer.secho(f"modules: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"modules: {', '.join(modules.names()) or '(none)'}; jobs: {settings.job_mode()}")
    if not connect:
        return

    results = loops.run(lambda: run_all_checks(settings, modules))
    for result in results:
        mark = typer.style("ok  ", fg=typer.colors.GREEN) if result.ok else typer.style("FAIL", fg=typer.colors.RED)
        facts = ", ".join(f"{key}={value}" for key, value in result.facts.items())
        typer.echo(f"[{mark}] {result.name:<24} {result.detail}" + (f"  ({facts})" if facts else ""))
    if not all(result.ok for result in results):
        raise typer.Exit(1)


@modules_app.command("list")
def modules_list() -> None:
    """List installed modules, whether they're enabled, and what they contribute."""
    settings = Settings()
    try:
        loaded = resolve_modules(discover_modules(), settings.modules.disabled)
    except ModuleGraphError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    enabled = set(loaded.names())
    for name, module in sorted(loaded.installed.items()):
        state = "enabled " if name in enabled else "disabled"
        routes = sum(len(spec.router.routes) for spec in module.routers())
        jobs = ", ".join(spec.name for spec in module.jobs()) or "-"
        depends = ", ".join(module.depends_on) or "-"
        tools = len(tuple(module.assistant_tools()))
        typer.echo(
            f"{name:<16} {module.version:<8} {state}  depends: {depends}  routes: {routes}  jobs: {jobs}"
            f"  tools: {tools}"
        )


async def _bootstrap(org_name: str, owner: OwnerAccount | None) -> BootstrapResult:
    settings = Settings()
    configure_logging(settings.log)
    container = build_container(settings, load_modules(settings.modules.disabled))
    try:
        async with container() as request:
            bootstrapper = await request.get(Bootstrapper)
            return await bootstrapper.bootstrap(org_name, owner)
    finally:
        await container.close()


@app.command()
def bootstrap(
    org_name: Annotated[str, typer.Option("--org-name", help="The org's name, shown in the sidebar")],
    owner_email: Annotated[
        str | None, typer.Option("--owner-email", help="Create the first Owner now (asks for a password)")
    ] = None,
    owner_name: Annotated[str | None, typer.Option("--owner-name", help="The Owner's display name")] = None,
    password_stdin: Annotated[
        bool, typer.Option("--password-stdin", help="Read the Owner's password from stdin")
    ] = False,
) -> None:
    """Set up the org and its first Owner (02 §10).

    Without --owner-email, prints a one-time link (valid 24 h) where the first Owner signs up in the browser.
    """
    owner: OwnerAccount | None = None
    if owner_email:
        if password_stdin:
            password = sys.stdin.readline().rstrip("\r\n")
        else:
            password = typer.prompt("Password for the Owner", hide_input=True, confirmation_prompt=True)
        owner = OwnerAccount(email=owner_email, display_name=owner_name or "", password=password)
    try:
        result = loops.run(lambda: _bootstrap(org_name, owner))
    except AppError as exc:
        typer.secho(exc.detail or exc.title, fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"org:   {result.org_name}")
    if result.owner_email:
        typer.echo(f"owner: {result.owner_email} — sign in at {Settings().public_url()}/login")
    if result.setup_url:
        typer.echo("Open this link to create the first Owner (valid for 24 hours, works once):")
        typer.echo(result.setup_url)


@app.command()
def openapi(
    out: Annotated[Path | None, typer.Option(help="Write to a file instead of stdout")] = None,
) -> None:
    """Export the OpenAPI document (the frontend client is generated from it)."""
    from agnostic_server.app import create_app  # noqa: PLC0415  (keeps CLI start-up light)

    settings = Settings(log={"level": "WARNING", "format": "console"})  # pyright: ignore[reportArgumentType]
    document = create_app(settings).openapi()
    data = orjson.dumps(document, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS) + b"\n"
    if out is None:
        _ = sys.stdout.buffer.write(data)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        _ = out.write_bytes(data)
        typer.echo(f"wrote {out}")


def main() -> None:
    app()
