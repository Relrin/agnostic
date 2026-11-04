"""What the System page shows, gathered from the kernel and every enabled module."""

from __future__ import annotations

import asyncio
import platform
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

from dishka import AsyncContainer
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_instances.facade import Instance, InstancesFacade
from agnostic_kernel import metrics
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.cache import detect_server
from agnostic_kernel.checks import check_cache, check_database, check_key_provider, check_migrations, check_smtp
from agnostic_kernel.diagnostics import CheckResult, StatusItem
from agnostic_kernel.errors import NotFoundError
from agnostic_kernel.job_admin import FailedJob, JobAdmin, QueueStats
from agnostic_kernel.logging import get_logger
from agnostic_kernel.modules import LoadedModules
from agnostic_kernel.settings import Settings

log = get_logger(__name__)

READ = "org:system:read"
MANAGE = "org:system:manage"
PROBE_TIMEOUT = 5.0


@dataclass(frozen=True, slots=True)
class Versions:
    server: str
    python: str
    database: str
    cache: str
    modules: dict[str, str]


@dataclass(frozen=True, slots=True)
class CacheStats:
    backend: str
    hits: int
    misses: int

    @property
    def hit_ratio(self) -> float | None:
        total = self.hits + self.misses
        return self.hits / total if total else None


@dataclass(frozen=True, slots=True)
class Overview:
    environment: str
    versions: Versions
    queues: list[QueueStats]
    cache: CacheStats
    instances: list[Instance]
    items: list[StatusItem]


def _installed_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


def _cache_counts() -> tuple[int, int]:
    hits = metrics.REGISTRY.get_sample_value("agnostic_cache_lookups_total", {"result": "hit"}) or 0.0
    misses = metrics.REGISTRY.get_sample_value("agnostic_cache_lookups_total", {"result": "miss"}) or 0.0
    return int(hits), int(misses)


class SystemStatus:
    def __init__(
        self,
        settings: Settings,
        modules: LoadedModules,
        container: AsyncContainer,
        engine: AsyncEngine,
        redis: Redis,
        jobs: JobAdmin,
        instances: InstancesFacade,
        authorizer: Authorizer,
        audit: AuditLog,
    ) -> None:
        self._settings = settings
        self._modules = modules
        self._container = container
        self._engine = engine
        self._redis = redis
        self._jobs = jobs
        self._instances = instances
        self._authorizer = authorizer
        self._audit = audit

    async def _database_version(self) -> str:
        query = "SELECT sqlite_version()" if self._engine.dialect.name == "sqlite" else "SHOW server_version"
        try:
            async with asyncio.timeout(PROBE_TIMEOUT), self._engine.connect() as connection:
                version = (await connection.execute(text(query))).scalar_one()
        except Exception as exc:  # noqa: BLE001  (the page shows what it can)
            return f"unavailable ({exc})"
        return f"{self._engine.dialect.name} {version}"

    async def _cache_version(self) -> str:
        if self._settings.cache_backend() == "memory":
            return "in-process (development)"
        try:
            async with asyncio.timeout(PROBE_TIMEOUT):
                server = await detect_server(self._redis)
        except Exception as exc:  # noqa: BLE001
            return f"unavailable ({exc})"
        return f"{server.kind} {server.version}"

    async def overview(self, principal: Principal) -> Overview:
        _ = await self._authorizer.require(principal, READ)
        items: list[StatusItem] = []
        for module in self._modules.enabled:
            try:
                items.extend(await module.system_status(self._container))
            except Exception as exc:  # noqa: BLE001  (one module's failure is a line on the page, not a 500)
                items.append(StatusItem(module.name, "Status", "error", f"couldn't read: {exc}"))
        hits, misses = _cache_counts()
        return Overview(
            environment=self._settings.env,
            versions=Versions(
                server=_installed_version("agnostic-server"),
                python=platform.python_version(),
                database=await self._database_version(),
                cache=await self._cache_version(),
                modules={module.name: module.version for module in self._modules.enabled},
            ),
            queues=await self._jobs.queues(),
            cache=CacheStats(self._settings.cache_backend(), hits, misses),
            instances=await self._instances.list(),
            items=items,
        )

    async def checks(self, principal: Principal) -> list[CheckResult]:
        """Probe every endpoint now (database, cache, master key, SMTP, then each module's)."""
        _ = await self._authorizer.require(principal, READ)
        results = [
            await check_database(self._engine),
            await check_migrations(self._engine, list(self._modules.installed.values())),
        ]
        if self._settings.cache_backend() == "redis":
            results.append(await check_cache(self._redis))
        results.append(await check_key_provider(self._settings))
        smtp = await check_smtp(self._settings.smtp)
        if smtp is not None:
            results.append(smtp)
        for module in self._modules.enabled:
            try:
                results.extend(await module.endpoint_checks(self._container))
            except Exception as exc:  # noqa: BLE001
                results.append(CheckResult(module.name, ok=False, detail=f"probe failed: {exc}"))
        return results

    async def failed_jobs(self, principal: Principal, *, limit: int, before: int | None) -> list[FailedJob]:
        _ = await self._authorizer.require(principal, READ)
        return await self._jobs.failed(limit=limit, before=before)

    async def _find(self, job_id: int) -> FailedJob:
        for job in await self._jobs.failed(limit=1, before=job_id + 1):
            if job.id == job_id:
                return job
        raise NotFoundError(f"There is no failed job {job_id}.")

    async def retry(self, principal: Principal, job_id: int) -> None:
        _ = await self._authorizer.require(principal, MANAGE)
        job = await self._find(job_id)
        await self._jobs.retry(job_id)
        await self._record(principal, "system.job.retry", job)

    async def discard(self, principal: Principal, job_id: int) -> None:
        _ = await self._authorizer.require(principal, MANAGE)
        job = await self._find(job_id)
        if not await self._jobs.discard(job_id):
            raise NotFoundError(f"There is no failed job {job_id}.")
        await self._record(principal, "system.job.discard", job)

    async def _record(self, principal: Principal, action: str, job: FailedJob) -> None:
        _ = await self._audit.record_now(
            AuditEntry(
                action=action,
                actor=actor_of(principal),
                resource_kind="job",
                resource_id=str(job.id),
                resource_display=f"{job.task} #{job.id}",
                fields={"task": job.task, "queue": job.queue, "job": str(job.id)},
            )
        )
        log.info(action.replace(".", "_"), job=job.id, task=job.task, actor=principal.id)
