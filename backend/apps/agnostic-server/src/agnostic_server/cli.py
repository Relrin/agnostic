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

from agnostic_kernel import migrations_runner
from agnostic_kernel.checks import run_endpoint_checks
from agnostic_kernel.db import create_engine
from agnostic_kernel.logging import configure_logging
from agnostic_kernel.modules import ModuleGraphError, discover_modules, load_modules, resolve_modules
from agnostic_kernel.settings import Settings
from agnostic_server import loops
from agnostic_server.worker import WorkerUnavailableError, run_worker

LOOP = "agnostic_server.loops:new_event_loop"

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Agnostic control plane.")
db_app = typer.Typer(no_args_is_help=True, help="Database migrations (Alembic, one branch per module).")
config_app = typer.Typer(no_args_is_help=True, help="Inspect configuration.")
modules_app = typer.Typer(no_args_is_help=True, help="Installed modules.")
app.add_typer(db_app, name="db")
app.add_typer(config_app, name="config")
app.add_typer(modules_app, name="modules")


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
    """Serve the HTTP API."""
    settings = Settings()
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


@db_app.command("upgrade")
def db_upgrade(revision: Annotated[str, typer.Argument(help="Target revision")] = "heads") -> None:
    """Apply migrations of the kernel and every installed module."""
    configure_logging(Settings().log)
    loops.run(lambda: _migrate("upgrade", revision))


@db_app.command("downgrade")
def db_downgrade(revision: Annotated[str, typer.Argument(help="Target, e.g. 'hello@base' or 'base'")]) -> None:
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

    results = loops.run(lambda: run_endpoint_checks(settings, list(modules.installed.values())))
    for result in results:
        mark = typer.style("ok  ", fg=typer.colors.GREEN) if result.ok else typer.style("FAIL", fg=typer.colors.RED)
        facts = ", ".join(f"{key}={value}" for key, value in result.facts.items())
        typer.echo(f"[{mark}] {result.name:<10} {result.detail}" + (f"  ({facts})" if facts else ""))
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
        typer.echo(f"{name:<16} {module.version:<8} {state}  depends: {depends}  routes: {routes}  jobs: {jobs}")


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
