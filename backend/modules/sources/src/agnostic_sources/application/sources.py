"""Connecting a repository (or a local folder) to an instance: setup, the initial scan, bindings, and settings."""

from __future__ import annotations

import secrets as random
from dataclasses import dataclass, replace
from typing import Any

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_codegen import RegistryConvention, components_in
from agnostic_instances.facade import EnvTag, Instance
from agnostic_kernel.auth import SYSTEM_PRINCIPAL, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import ConflictError, NotFoundError, ValidationFailedError
from agnostic_kernel.ids import new_id
from agnostic_kernel.logging import get_logger
from agnostic_sources.application.access import (
    COMPONENTS_READ,
    COMPONENTS_WRITE,
    SOURCES_DELETE,
    SOURCES_WRITE,
    SourcesAccess,
    rule,
)
from agnostic_sources.application.files import SourceFiles, mapped_files
from agnostic_sources.application.ports import GitError, ProviderError, SourceLimits, SourceStore, WebhookUrls
from agnostic_sources.application.sync import content_hash
from agnostic_sources.application.tasks import SourceJobs
from agnostic_sources.domain.model import (
    KIND_OF_TARGET,
    FileBinding,
    PathMapping,
    Provider,
    Source,
    SourceRuleError,
    SyncPolicy,
)
from agnostic_sources.domain.paths import DEFAULT_MAPPINGS, check_mappings, component_target, counts, match
from agnostic_sources.domain.remote import check_branch, check_clone_url, check_repo
from agnostic_sources.domain.templates import check_template
from agnostic_studio.facade import StudioFacade

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SourceDraft:
    provider: Provider
    repo: str | None = None
    branch: str = "main"
    connection_id: str | None = None
    clone_url: str | None = None
    local_path: str | None = None
    mappings: tuple[PathMapping, ...] | None = None
    policy: SyncPolicy | None = None
    convention: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SourcePatch:
    branch: str | None = None
    mappings: tuple[PathMapping, ...] | None = None
    policy: SyncPolicy | None = None
    convention: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class BindingDecision:
    path: str
    component_id: str
    bind: bool = True


class Sources:
    def __init__(
        self,
        store: SourceStore,
        access: SourcesAccess,
        files: SourceFiles,
        studio: StudioFacade,
        audit: AuditLog,
        jobs: SourceJobs,
        hooks: WebhookUrls,
        settings: SourceLimits,
    ) -> None:
        self._store = store
        self._access = access
        self._files = files
        self._studio = studio
        self._audit = audit
        self._jobs = jobs
        self._hooks = hooks
        self._settings = settings

    async def list(self, principal: Principal, ref: str) -> tuple[Instance, list[Source]]:
        instance = await self._access.instance(principal, ref, COMPONENTS_READ)
        return instance, await self._store.sources(instance.id)

    async def get(self, principal: Principal, ref: str, source_id: str) -> tuple[Instance, Source]:
        instance = await self._access.instance(principal, ref, COMPONENTS_READ)
        return instance, self._access.owned(await self._store.source(source_id), instance)

    async def create(self, principal: Principal, ref: str, draft: SourceDraft) -> Source:
        instance = await self._access.instance(principal, ref, SOURCES_WRITE)
        try:
            source = await self._new(instance, draft, principal)
        except SourceRuleError as exc:
            raise rule(exc) from exc
        for existing in await self._store.sources(instance.id):
            if (existing.provider, existing.repo, existing.branch, existing.local_path) == (
                source.provider,
                source.repo,
                source.branch,
                source.local_path,
            ):
                raise ConflictError(f"{instance.display_name} already syncs {source.label} · {source.branch}.")
        saved = await self._store.save_source(source)
        await self._audited(principal, instance, "sources.source.create", saved)
        await self._store.commit()
        _ = await self._jobs.scan(saved.id)
        return saved

    async def _new(self, instance: Instance, draft: SourceDraft, principal: Principal) -> Source:
        mappings = check_mappings(draft.mappings) if draft.mappings is not None else DEFAULT_MAPPINGS
        policy = _check_policy(draft.policy or SyncPolicy())
        base = Source(
            id=new_id("src"),
            instance_id=instance.id,
            provider=draft.provider,
            repo="",
            branch="",
            mappings=mappings,
            policy=policy,
            convention=RegistryConvention.from_dict(draft.convention).as_dict() if draft.convention else None,
            status="scanning",
            created_by=principal.id,
            created_at=utcnow(),
        )
        if draft.provider == "local":
            if instance.env_tag != EnvTag.DEVELOPMENT:
                raise SourceRuleError("Local folders sync only with development instances.")
            root = self._files.folders.check_root(draft.local_path or "")
            return replace(base, repo=root, branch="local", local_path=root)
        if draft.connection_id is None and not draft.clone_url:
            raise SourceRuleError("Pick a connection (or give a clone URL for a public repository).")
        if draft.connection_id is not None:
            connection = await self._store.connection(draft.connection_id)
            if connection is None:
                raise SourceRuleError("That connection doesn't exist any more.")
            if connection.provider != draft.provider and {connection.provider, draft.provider} != {"gitea", "forgejo"}:
                raise SourceRuleError(f"The connection is for {connection.provider}, not {draft.provider}.")
        clone_url = (
            check_clone_url(draft.clone_url, allow_file=self._settings.allow_file_remotes) if draft.clone_url else None
        )
        return replace(
            base,
            repo=check_repo(draft.repo or ""),
            branch=check_branch(draft.branch),
            connection_id=draft.connection_id,
            clone_url=clone_url,
        )

    async def update(
        self, principal: Principal, ref: str, source_id: str, patch: SourcePatch, expected_version: int | None
    ) -> Source:
        instance = await self._access.instance(principal, ref, SOURCES_WRITE)
        source = self._access.owned(await self._store.source(source_id), instance)
        try:
            updated = replace(
                source,
                branch=check_branch(patch.branch) if patch.branch and not source.is_local else source.branch,
                mappings=check_mappings(patch.mappings) if patch.mappings is not None else source.mappings,
                policy=_check_policy(patch.policy) if patch.policy is not None else source.policy,
                convention=RegistryConvention.from_dict(patch.convention).as_dict()
                if patch.convention is not None
                else source.convention,
            )
        except SourceRuleError as exc:
            raise rule(exc) from exc
        rescan = updated.branch != source.branch or updated.mappings != source.mappings
        if rescan:
            updated = replace(updated, status="scanning" if source.status != "active" else "active")
        saved = await self._store.save_source(updated, expected_version=expected_version)
        await self._audited(principal, instance, "sources.source.update", saved)
        await self._store.commit()
        if rescan:
            _ = await (self._jobs.scan(saved.id) if saved.status != "active" else self._jobs.fetch(saved.id, "manual"))
        return saved

    async def delete(self, principal: Principal, ref: str, source_id: str) -> None:
        instance = await self._access.instance(principal, ref, SOURCES_DELETE)
        source = self._access.owned(await self._store.source(source_id), instance)
        for binding in await self._store.bindings(source.id):
            await self._studio.bind(
                instance.id,
                binding.component_id,
                binding.component_kind,
                binding_id=None,
                code_path=None,
                convention=None,
            )
        if source.webhook_id:
            try:
                client = await self._files.client(source)
                if client is not None:
                    await client.delete_webhook(source.repo, source.webhook_id)
            except ProviderError as exc:
                log.warning("sources.webhook_delete_failed", source_id=source.id, error=str(exc))
        await self._store.delete_source(source.id)
        await self._audited(principal, instance, "sources.source.delete", source)
        await self._store.commit()
        if not source.is_local:
            await self._files.git.remove(source.id)

    async def fetch(self, principal: Principal, ref: str, source_id: str) -> int | None:
        instance = await self._access.instance(principal, ref, COMPONENTS_WRITE)
        source = self._access.owned(await self._store.source(source_id), instance)
        _ = await self._audit.record(
            AuditEntry(
                action="sources.fetch",
                actor=actor_of(principal),
                resource_kind="source",
                resource_id=source.id,
                resource_display=source.label,
                instance_id=instance.id,
                fields={"source": source.label, "branch": source.branch},
            )
        )
        await self._store.commit()
        if source.status in {"setup", "scanning", "ready", "failed"} and source.head_sha is None:
            return await self._jobs.scan(source.id)
        return await self._jobs.fetch(source.id, "manual")

    # ---------------------------------------------------------------- the initial scan

    async def scan(self, source_id: str) -> Source | None:  # noqa: C901, PLR0915
        """The job: fetch, read every mapped file, and report what each would bind to (nothing changes in Studio)."""
        source = await self._store.source(source_id)
        if source is None:
            return None
        try:
            snapshot = await self._files.fetch(source)
        except (GitError, ProviderError, NotFoundError) as exc:
            failed = replace(source, status="failed", status_detail=str(exc))
            _ = await self._store.save_source(failed)
            await self._store.commit()
            return failed
        instance = await self._access.of(source)
        convention = RegistryConvention.from_dict(source.convention)
        known = {state.id: state for state in await self._studio.components(SYSTEM_PRINCIPAL, instance)}
        report_files: list[dict[str, Any]] = []
        for path in sorted(snapshot.files):
            mapping = match(source.mappings, path)
            if mapping is None or mapping.target_kind == "ignored":
                continue
            entry: dict[str, Any] = {"path": path, "mapping": mapping.target_kind, "components": []}
            target = component_target(source.mappings, path)
            if target is None:
                report_files.append(entry)
                continue
            kind = KIND_OF_TARGET[target.target_kind]
            code = await self._files.read(source, snapshot.head, path)
            found = [item for item in components_in(code or "") if item.kind == kind]
            if not found:
                entry["problems"] = ["No Agent, Team or Workflow defined at module level."]
            for item in found:
                component: dict[str, Any] = {"variable": item.variable, "kind": item.kind, "id": item.component_id}
                if not item.component_id:
                    component |= {"parse": "problems", "match": "none", "proposed": "skip"}
                    component["diagnostics"] = ["Give the component a literal id= so Studio can bind it."]
                    entry["components"].append(component)
                    continue
                parsed = await self._studio.read_code(
                    SYSTEM_PRINCIPAL, instance, kind, code or "", item.component_id, convention
                )
                component["parse"] = "ok" if parsed.ok else "problems"
                component["diagnostics"] = [d.message for d in parsed.diagnostics if d.severity != "info"][:5]
                component["code_owned"] = parsed.code_owned
                state = known.get(item.component_id)
                if state is None:
                    component |= {"match": "new", "proposed": "create" if parsed.ok else "skip"}
                else:
                    latest = await self._studio.component(SYSTEM_PRINCIPAL, instance, item.component_id)
                    number = latest.latest_version if latest else None
                    same = False
                    if number is not None and parsed.config is not None:
                        snap = await self._studio.snapshot(SYSTEM_PRINCIPAL, instance, item.component_id, number)
                        same = snap.config == parsed.config
                    component |= {
                        "match": "same" if same else "differs",
                        "version": number,
                        "proposed": "bind" if parsed.ok else "skip",
                    }
                entry["components"].append(component)
            report_files.append(entry)
        totals = counts(source.mappings, snapshot.files)
        report = {
            "head": snapshot.head,
            "files": report_files,
            "counts": totals,
            "found": sum(len(item["components"]) for item in report_files),
            "scanned_at": utcnow().isoformat(),
        }
        status = "active" if source.status == "active" else "ready"
        saved = await self._store.save_source(
            replace(
                source,
                status=status,
                status_detail=None,
                head_sha=snapshot.head,
                last_fetched_at=utcnow(),
                scan_report=report,
            )
        )
        await self._store.commit()
        return saved

    async def activate(
        self, principal: Principal, ref: str, source_id: str, decisions: list[BindingDecision] | None
    ) -> Source:
        """Bind the scanned files as proposed (or as decided).

        Files that read as Studio's newest version start in sync; the others arrive as incoming changes.
        """
        instance = await self._access.instance(principal, ref, SOURCES_WRITE)
        source = self._access.owned(await self._store.source(source_id), instance)
        report = source.scan_report or {}
        if source.status not in {"ready", "active"} or not report.get("files"):
            raise ConflictError("The source hasn't finished its scan yet.")
        chosen = {(item.path, item.component_id): item.bind for item in decisions or []}
        existing = {(binding.path, binding.component_id) for binding in await self._store.bindings(source.id)}
        head = str(report.get("head") or source.head_sha or "")
        snapshot = await self._files.snapshot(source)
        snapshot_files = mapped_files(source, snapshot.files) if snapshot is not None else {}
        for entry in report.get("files", []):
            for component in entry.get("components", []):
                component_id = component.get("id")
                if not component_id or (entry["path"], component_id) in existing:
                    continue
                default = component.get("proposed") in {"bind", "create"}
                if not chosen.get((entry["path"], component_id), default):
                    continue
                binding = FileBinding(new_id("sfb"), source.id, entry["path"], component["kind"], component_id)
                if component.get("match") == "same":
                    code = await self._files.read(source, head, entry["path"]) or ""
                    snap = await self._studio.snapshot(SYSTEM_PRINCIPAL, instance, component_id, component["version"])
                    binding = replace(
                        binding,
                        last_synced_sha=head,
                        last_synced_version=component["version"],
                        content_hash=snapshot_files.get(entry["path"], content_hash(code)),
                        synced_code=code,
                        synced_config=snap.config,
                    )
                    await self._studio.bind(
                        instance.id,
                        component_id,
                        component["kind"],
                        binding_id=binding.id,
                        code_path=entry["path"],
                        convention=source.convention,
                    )
                await self._store.save_binding(binding)
        activated = replace(source, status="active")
        activated = await self._webhook(activated)
        saved = await self._store.save_source(activated)
        await self._audited(principal, instance, "sources.source.update", saved)
        await self._store.commit()
        _ = await self._jobs.compute(saved.id, "activate")
        return saved

    async def _webhook(self, source: Source) -> Source:
        if source.is_local or source.webhook_id:
            return source
        url = self._hooks.url(source.provider)
        client = await self._files.client(source)
        if url is None or client is None:
            return source
        secret = random.token_urlsafe(32)
        try:
            hook_id = await client.register_webhook(source.repo, url, secret)
        except ProviderError as exc:
            return replace(source, status_detail=f"Webhook not registered ({exc}); Studio fetches periodically.")
        if hook_id is None:
            return source
        await self._store.set_source_secret(source.id, secret)
        return replace(source, webhook_id=hook_id)

    async def _audited(self, principal: Principal, instance: Instance, action: str, source: Source) -> None:
        _ = await self._audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(principal),
                resource_kind="source",
                resource_id=source.id,
                resource_display=source.label,
                instance_id=instance.id,
                decision="allowed",
                scope_checked=SOURCES_DELETE if action.endswith("delete") else SOURCES_WRITE,
                fields={"source": source.label, "branch": source.branch, "instance": instance.display_name},
            )
        )


def _check_policy(policy: SyncPolicy) -> SyncPolicy:
    try:
        return replace(
            policy,
            branch_template=check_template(policy.branch_template, branch=True),
            commit_template=check_template(policy.commit_template, branch=False),
        )
    except SourceRuleError as exc:
        raise ValidationFailedError(str(exc)) from exc
