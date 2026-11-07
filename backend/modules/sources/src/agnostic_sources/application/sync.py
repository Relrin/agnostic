"""Repository → Studio: fetch, work out what each changed file becomes, pull changes as drafts, resolve conflicts.

Nothing reaches Studio on its own: a fetch only records incoming changes; pulling turns them into new drafts (never
published). When Studio's open draft changed since the last sync too, the draft is merged field by field with the
file, using the last synced version as the base; fields changed on both sides wait as conflicts until someone picks.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_codegen import RegistryConvention, components_in, counts, line_marks
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import SYSTEM_PRINCIPAL, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import ConflictError, NotFoundError, ValidationFailedError
from agnostic_kernel.ids import new_id
from agnostic_kernel.logging import get_logger
from agnostic_sources.application.access import COMPONENTS_WRITE, SourcesAccess
from agnostic_sources.application.files import Snapshot, SourceFiles, mapped_files
from agnostic_sources.application.ports import GitError, ProviderError, SourceLimits, SourceStore
from agnostic_sources.application.tasks import SourceJobs
from agnostic_sources.domain.merge import MISSING, MergeResult, apply_resolutions, three_way
from agnostic_sources.domain.model import (
    KIND_OF_TARGET,
    Change,
    CommitInfo,
    ComponentKind,
    Conflict,
    FileBinding,
    Resolution,
    Side,
    Source,
    SourceStatus,
)
from agnostic_sources.domain.outcomes import Outcome
from agnostic_sources.domain.paths import MAX_FOLDER_FILES, component_target
from agnostic_sources.domain.paths import counts as mapping_counts
from agnostic_studio.facade import ComponentState, RepositoryDraft, StudioFacade

log = get_logger(__name__)

PULLABLE = frozenset({"new_draft", "new_component"})
SETTLED = frozenset({"active", "ready", "scanning", "setup"})
TOO_MANY = "files changed in this fetch"


def settled_status(source: Source) -> SourceStatus:
    """The status a source returns to once it fetches again (after a failure or being over quota).

    A source keeps its status while it is set up, scanned, ready or syncing. One that failed goes back to syncing if
    it was ever activated (bound or not), to its scan being ready to review if the scan finished, and otherwise
    back to scanning: it has nothing to review yet.
    """
    if source.activated_at is not None:
        return "active"
    if source.status in SETTLED:
        return source.status
    return "ready" if source.scanned else "scanning"


def studio_side(state: ComponentState) -> int | None:
    """The version an incoming file merges with: the open draft, or the newest version when no draft is open."""
    return state.draft_version or state.latest_version


def content_hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class PullResult:
    change_id: str
    path: str
    component_id: str | None
    version: int | None = None
    error: str | None = None


async def unbind(store: SourceStore, studio: StudioFacade, source: Source, binding: FileBinding) -> None:
    """Stop syncing ``binding``'s file; the component stays in Studio, bound to another file if it has one."""
    await store.delete_binding(binding.id)
    others = [
        (other_source, other)
        for other_source, other in await store.bindings_for_component(source.instance_id, binding.component_id)
        if other.id != binding.id
    ]
    if others:
        other_source, other = others[0]
        await studio.bind(
            source.instance_id,
            other.component_id,
            other.component_kind,
            binding_id=other.id,
            code_path=other.path,
            convention=other_source.convention,
        )
    else:
        await studio.bind(
            source.instance_id,
            binding.component_id,
            binding.component_kind,
            binding_id=None,
            code_path=None,
            convention=None,
        )


class Fetcher:
    def __init__(
        self,
        store: SourceStore,
        files: SourceFiles,
        incoming: IncomingComputer,
        settings: SourceLimits,
        jobs: SourceJobs,
    ) -> None:
        self._store = store
        self._files = files
        self._incoming = incoming
        self._settings = settings
        self._jobs = jobs

    async def fetch(self, source_id: str, reason: str) -> Source | None:
        source = await self._store.source(source_id)
        if source is None:
            return None
        try:
            snapshot = await self._files.fetch(source)
        except (GitError, ProviderError, NotFoundError) as exc:
            failed = replace(source, status="failed", status_detail=str(exc), last_fetched_at=utcnow())
            _ = await self._store.save_source(failed)
            await self._store.commit()
            log.warning("sources.fetch_failed", source_id=source_id, error=str(exc))
            return failed
        size = 0 if source.is_local else await self._files.git.size(source.id)
        quota = self._settings.mirror_quota_mb * 1024 * 1024
        if size > quota:
            over = replace(
                source,
                status="over_quota",
                status_detail=f"The mirror takes {size // (1024 * 1024)} MB, over the {self._settings.mirror_quota_mb} "
                "MB quota; narrow the path mappings or raise AGNOSTIC_SOURCES__MIRROR_QUOTA_MB.",
                head_sha=snapshot.head,
                last_fetched_at=utcnow(),
            )
            _ = await self._store.save_source(over)
            await self._store.commit()
            return over
        if not source.scanned and source.activated_at is None:
            return await self._scan_instead(source)
        fetched = replace(
            source,
            head_sha=snapshot.head,
            last_fetched_at=utcnow(),
            status=settled_status(source),
            status_detail=None,
            scan_report={**(source.scan_report or {}), "counts": mapping_counts(source.mappings, snapshot.files)},
        )
        fetched = await self._store.save_source(fetched)
        await self._store.commit()
        if fetched.status == "active":
            _ = await self._incoming.compute(fetched.id, reason, snapshot)
            return await self._store.source(fetched.id) or fetched
        return fetched

    async def _scan_instead(self, source: Source) -> Source:
        """The initial scan never finished: a fetch alone would leave nothing to review, so scan instead."""
        if source.status == "scanning":
            return source  # the scan is queued already
        scanning = await self._store.save_source(replace(source, status="scanning", status_detail=None))
        await self._store.commit()
        _ = await self._jobs.scan(source.id)
        return scanning


class IncomingComputer:
    def __init__(
        self,
        store: SourceStore,
        files: SourceFiles,
        access: SourcesAccess,
        studio: StudioFacade,
        jobs: SourceJobs,
        settings: SourceLimits,
    ) -> None:
        self._store = store
        self._files = files
        self._access = access
        self._studio = studio
        self._jobs = jobs
        self._settings = settings

    async def compute(  # noqa: C901, PLR0912, PLR0915
        self, source_id: str, reason: str, snapshot: Snapshot | None = None
    ) -> list[Change]:
        source = await self._store.source(source_id)
        if source is None or source.status != "active":
            return []
        snapshot = snapshot or await self._files.snapshot(source)
        if snapshot is None:
            return []
        instance = await self._access.of(source)
        convention = RegistryConvention.from_dict(source.convention)
        bindings = await self._store.bindings(source.id)
        by_path: dict[str, list[FileBinding]] = {}
        for binding in bindings:
            by_path.setdefault(binding.path, []).append(binding)
        pending = {
            (change.path, change.component_id): change
            for change in await self._store.changes(source.id, "incoming", ["pending"])
        }
        mapped = mapped_files(source, snapshot.files)
        every = [
            path
            for path, blob in sorted(mapped.items())
            if path not in by_path or any(binding.content_hash != blob for binding in by_path[path])
        ]
        limit = self._settings.max_changed_files
        changed = every[:limit]
        source = await self._report_limit(source, len(every), limit)
        kept: set[tuple[str, str | None]] = set()
        for path in changed:
            blob = mapped[path]
            code = await self._files.read(source, snapshot.head, path)
            commit = await self._files.last_commit(source, snapshot.head, path)
            mapping = component_target(source.mappings, path)
            kind: ComponentKind = KIND_OF_TARGET[mapping.target_kind] if mapping else "agent"
            targets: list[tuple[ComponentKind, str | None, FileBinding | None]]
            if path in by_path:
                targets = [(item.component_kind, item.component_id, item) for item in by_path[path]]
            else:
                found = [item for item in components_in(code or "") if item.kind == kind and item.component_id]
                targets = [(item.kind, item.component_id, None) for item in found] or [(kind, None, None)]
            for target_kind, component_id, binding in targets:
                if binding is not None and binding.content_hash == blob:
                    continue
                change = await self._one(
                    source,
                    instance,
                    snapshot,
                    convention,
                    path=path,
                    blob=blob,
                    code=code,
                    commit=commit,
                    kind=target_kind,
                    component_id=component_id,
                    binding=binding,
                    pending=pending.get((path, component_id)),
                )
                if change is not None:
                    kept.add((change.path, change.component_id))
        # A folder listing stops at MAX_FOLDER_FILES: a bound file it left out isn't gone, only unread.
        truncated = source.is_local and len(snapshot.files) >= MAX_FOLDER_FILES
        # Where each component is now: bound to a file that is there, or with a change waiting on another file.
        present: dict[str, set[str]] = {}
        for item in await self._store.bindings(source.id):
            if item.path in snapshot.files:
                present.setdefault(item.component_id, set()).add(item.path)
        waiting: dict[str | None, set[str]] = {}
        for changed_path, changed_component in kept:
            waiting.setdefault(changed_component, set()).add(changed_path)
        for path, items in by_path.items():
            if path in snapshot.files:
                continue
            if truncated and await self._files.local_hash(source, path) is not None:
                kept.update((path, binding.component_id) for binding in items)
                continue
            for binding in items:
                key = (path, binding.component_id)
                if present.get(binding.component_id, set()) - {path}:
                    # Moved: the component is synced with its new file already, so the old binding goes.
                    await unbind(self._store, self._studio, source, binding)
                    continue
                if waiting.get(binding.component_id, set()) - {path}:
                    # Moved and edited: the binding moves when the change at the new file is pulled.
                    continue
                if key in pending:
                    kept.add(key)
                    continue
                removed = Change(
                    id=new_id("sch"),
                    source_id=source.id,
                    direction="incoming",
                    path=path,
                    component_kind=binding.component_kind,
                    component_id=binding.component_id,
                    binding_id=binding.id,
                    base_sha=binding.last_synced_sha,
                    commit_sha=snapshot.head,
                    before_code=binding.synced_code,
                    outcome=Outcome("removed", binding.component_id, binding.component_kind).as_dict(),
                    included=False,
                )
                await self._store.save_change(removed)
                kept.add(key)
        for key, change in pending.items():
            if key not in kept:
                await self._supersede(change)
        await self._store.commit()
        await self._announce(source)
        fresh = await self._store.changes(source.id, "incoming", ["pending"])
        if reason == "push" and source.policy.pull_mode == "on_push_as_drafts":
            ready = [change.id for change in fresh if change.outcome.get("action") in PULLABLE]
            if ready:
                _ = await self._jobs.pull(source.id, ready)
        return fresh

    async def _one(
        self,
        source: Source,
        instance: Instance,
        snapshot: Snapshot,
        convention: RegistryConvention,
        *,
        path: str,
        blob: str,
        code: str | None,
        commit: CommitInfo | None,
        kind: ComponentKind,
        component_id: str | None,
        binding: FileBinding | None,
        pending: Change | None,
    ) -> Change | None:
        base_code = binding.synced_code if binding else None
        change = Change(
            id=new_id("sch"),
            source_id=source.id,
            direction="incoming",
            path=path,
            component_kind=kind,
            component_id=component_id,
            binding_id=binding.id if binding else None,
            base_sha=binding.last_synced_sha if binding else None,
            commit_sha=commit.sha if commit else snapshot.head,
            blob=blob,
            author_name=commit.author_name if commit else None,
            author_email=commit.author_email if commit else None,
            committed_at=commit.committed_at if commit else None,
            message=commit.message if commit else None,
            before_code=base_code,
            after_code=code,
        )
        if code is not None:
            added, removed = counts(base_code or "", code)
            change = replace(
                change,
                additions=added,
                deletions=removed,
                incoming_marks={str(line): "incoming" for line in line_marks(base_code or "", code)},
            )
        if (
            pending is not None
            and pending.blob == blob
            and pending.after_code == code
            and await self._still_holds(instance, pending)
        ):
            return pending
        if code is None or component_id is None:
            problem = (
                "The file isn't UTF-8 text or is too large."
                if code is None
                else ("No Agent, Team or Workflow with a literal id= is defined here.")
            )
            outcome = Outcome("unparseable", component_id, kind, problems=1)
            change = replace(
                change,
                outcome=outcome.as_dict(),
                diagnostics=[{"severity": "error", "code": "unreadable", "message": problem, "line": 1}],
                included=False,
            )
            return await self._replace(pending, change, [])
        parsed = await self._studio.read_code(SYSTEM_PRINCIPAL, instance, kind, code, component_id, convention)
        if not parsed.ok or parsed.config is None:
            errors = [item.as_dict() for item in parsed.diagnostics if item.severity == "error"]
            outcome = Outcome("unparseable", component_id, kind, problems=len(errors) or 1)
            change = replace(change, outcome=outcome.as_dict(), diagnostics=errors, included=False)
            return await self._replace(pending, change, [])
        incoming = parsed.config
        diagnostics = [item.as_dict() for item in parsed.diagnostics]
        state = await self._studio.component(SYSTEM_PRINCIPAL, instance, component_id)
        if state is None:
            outcome = Outcome("new_component", component_id, kind, version=1)
            change = replace(change, config=incoming, outcome=outcome.as_dict(), diagnostics=diagnostics)
            return await self._replace(pending, change, [])
        current = (
            (await self._studio.snapshot(SYSTEM_PRINCIPAL, instance, component_id, state.current_version)).config
            if state.current_version
            else None
        )
        latest = (
            (await self._studio.snapshot(SYSTEM_PRINCIPAL, instance, component_id, state.latest_version)).config
            if state.latest_version
            else None
        )
        synced = binding.synced_config if binding else None
        matches = next(
            (
                number
                for number, config in ((state.latest_version, latest), (state.current_version, current))
                if config is not None and config == incoming
            ),
            None,
        )
        if matches is not None or (synced is not None and synced == incoming):
            await self._mark_synced(
                source,
                binding,
                path,
                kind,
                component_id,
                snapshot.head,
                blob,
                code,
                incoming,
                matches if matches is not None else binding.last_synced_version if binding else None,
            )
            if pending is not None:
                await self._supersede(pending)
            return None
        # Studio's side: the open draft, or with none open the newest version. A version published since the last
        # sync that never reached the file (write-back off or failed) is merged too, not overwritten by the file.
        ours_version = studio_side(state)
        ours = (
            await self._studio.snapshot(SYSTEM_PRINCIPAL, instance, component_id, ours_version)
            if ours_version
            else None
        )
        base = synced if synced is not None else current
        result = MergeResult(merged=incoming)
        if ours is not None and base is not None and ours.config != base:
            result = three_way(base, ours.config, incoming)
        version = (state.latest_version or 0) + 1
        outcome = Outcome(
            "conflict" if result.conflicts else "new_draft",
            component_id,
            kind,
            version=version,
            beside_version=state.draft_version,
            beside_author_id=state.draft_author_id,
            beside_author_name=state.draft_author_name,
            auto_merged=result.auto_merged,
            conflict_paths=[item.path for item in result.conflicts],
        )
        change = replace(
            change,
            config=incoming,
            base_config=base,
            outcome=outcome.as_dict(),
            diagnostics=diagnostics,
            draft_version=state.draft_version,
        )
        conflicts = [
            Conflict(
                id=new_id("scf"),
                source_id=source.id,
                change_id=change.id,
                path=path,
                component_id=component_id,
                field_path=item.path,
                base_value=item.base,
                repo_side=Side(
                    item.theirs, change.author_name, (change.commit_sha or "")[:7] or None, item.theirs is not MISSING
                ),
                studio_side=Side(
                    item.ours,
                    state.draft_author_name if state.draft_version else None,
                    f"draft v{state.draft_version}" if state.draft_version else f"v{ours_version}",
                    item.ours is not MISSING,
                ),
                created_at=utcnow(),
            )
            for item in result.conflicts
        ]
        return await self._replace(pending, change, conflicts)

    async def _still_holds(self, instance: Instance, pending: Change) -> bool:
        """Whether Studio's side still merges into ``pending`` the way it did when it was worked out.

        The repository's file is the same, but the draft may have moved on: another draft opened, or the open one
        edited where the file changed too. Pulling then stops at a conflict the change doesn't know about, so it's
        worked out again (keeping it would ask for a fetch that never helps).
        """
        if pending.outcome.get("action") not in {"new_draft", "conflict"} or pending.config is None:
            return True
        component_id = pending.component_id or ""
        state = await self._studio.component(SYSTEM_PRINCIPAL, instance, component_id)
        if state is None or state.draft_version != pending.draft_version:
            return False
        ours_version = studio_side(state)
        if ours_version is None or pending.base_config is None:
            return True
        ours = await self._studio.snapshot(SYSTEM_PRINCIPAL, instance, component_id, ours_version)
        if ours.config == pending.base_config:
            return True
        known = {conflict.field_path for conflict in await self._store.conflicts_for_change(pending.id)}
        return all(item.path in known for item in three_way(pending.base_config, ours.config, pending.config).conflicts)

    async def _replace(self, pending: Change | None, change: Change, conflicts: Sequence[Conflict]) -> Change:
        if pending is not None:
            await self._supersede(pending)
        await self._store.save_change(change)
        for conflict in conflicts:
            await self._store.save_conflict(conflict)
        return change

    async def _supersede(self, change: Change) -> None:
        await self._store.save_change(replace(change, status="superseded"))
        for conflict in await self._store.conflicts_for_change(change.id):
            if conflict.status == "open":
                await self._store.save_conflict(replace(conflict, status="superseded"))

    async def _mark_synced(
        self,
        source: Source,
        binding: FileBinding | None,
        path: str,
        kind: ComponentKind,
        component_id: str,
        head: str,
        blob: str,
        code: str,
        config: dict[str, Any],
        version: int | None,
    ) -> None:
        binding = binding or FileBinding(new_id("sfb"), source.id, path, kind, component_id)
        await self._store.save_binding(
            replace(
                binding,
                last_synced_sha=head,
                last_synced_version=version,
                content_hash=blob,
                synced_code=code,
                synced_config=config,
            )
        )
        await self._studio.bind(
            source.instance_id, component_id, kind, binding_id=binding.id, code_path=path, convention=source.convention
        )

    async def _report_limit(self, source: Source, found: int, limit: int) -> Source:
        """Say on the source when a fetch brought more changed files than are read at once (and stop saying it)."""
        detail = source.status_detail
        if found > limit:
            detail = (
                f"{found} {TOO_MANY}; Studio read the first {limit}. Pull those, then fetch again for the rest "
                "(or raise AGNOSTIC_SOURCES__MAX_CHANGED_FILES)."
            )
            log.warning("sources.too_many_changes", source_id=source.id, found=found, limit=limit)
        elif detail and TOO_MANY in detail:
            detail = None
        if detail == source.status_detail:
            return source
        return await self._store.save_source(replace(source, status_detail=detail))

    async def _announce(self, source: Source) -> None:
        count = await self._store.open_conflict_count(source.instance_id)
        await self._jobs.announce(source.instance_id, "sources.changed", {"source_id": source.id})
        await self._jobs.announce(source.instance_id, "sources.conflicts", {"count": count})


class Puller:
    def __init__(
        self,
        store: SourceStore,
        access: SourcesAccess,
        studio: StudioFacade,
        audit: AuditLog,
        jobs: SourceJobs,
        files: SourceFiles,
    ) -> None:
        self._store = store
        self._access = access
        self._studio = studio
        self._audit = audit
        self._jobs = jobs
        self._files = files

    async def pull(self, principal: Principal, ref: str, source_id: str, change_ids: Sequence[str]) -> list[PullResult]:
        instance = await self._access.instance(principal, ref, COMPONENTS_WRITE)
        source = self._access.owned(await self._store.source(source_id), instance)
        return await self.run(principal, source, instance, change_ids)

    async def run(
        self, principal: Principal, source: Source, instance: Instance, change_ids: Sequence[str]
    ) -> list[PullResult]:
        results: list[PullResult] = []
        convention = RegistryConvention.from_dict(source.convention)
        for change_id in change_ids:
            change = await self._store.change(change_id)
            if change is None or change.source_id != source.id or change.direction != "incoming":
                raise NotFoundError(f"There is no incoming change {change_id} on this source.")
            try:
                if change.outcome.get("action") == "removed":
                    await self._accept_removal(source, change)
                    await self._store.commit()
                    results.append(PullResult(change.id, change.path, change.component_id))
                    continue
                version = await self._one(principal, source, instance, change, convention)
            except (ConflictError, ValidationFailedError, NotFoundError) as exc:
                results.append(PullResult(change.id, change.path, change.component_id, error=str(exc)))
                continue
            # Each draft is its own transaction: the next one calls the instance (whose calls are audited apart).
            await self._store.commit()
            results.append(PullResult(change.id, change.path, change.component_id, version=version))
        pulled = [result for result in results if result.version is not None]
        if pulled:
            _ = await self._audit.record(
                AuditEntry(
                    action="sources.pull",
                    actor=actor_of(principal),
                    resource_kind="source",
                    resource_id=source.id,
                    resource_display=source.label,
                    instance_id=instance.id,
                    via="system" if principal.kind == "system" else "web",
                    fields={
                        "count": str(len(pulled)),
                        "source": source.label,
                        "components": ", ".join(f"{item.component_id} v{item.version}" for item in pulled),
                    },
                )
            )
        await self._store.commit()
        count = await self._store.open_conflict_count(instance.id)
        await self._jobs.announce(instance.id, "sources.changed", {"source_id": source.id})
        await self._jobs.announce(instance.id, "sources.conflicts", {"count": count})
        return results

    async def _one(
        self, principal: Principal, source: Source, instance: Instance, change: Change, convention: RegistryConvention
    ) -> int:
        if change.status != "pending":
            raise ConflictError(f"{change.path} was already {change.status}.")
        action = str(change.outcome.get("action") or "")
        if action not in {*PULLABLE, "conflict"} or change.config is None or change.after_code is None:
            raise ValidationFailedError(f"{change.path} can't become a draft.")
        component_id = change.component_id or ""
        kind: ComponentKind = change.component_kind or "agent"
        conflicts = await self._store.conflicts_for_change(change.id)
        still_open = [item for item in conflicts if item.status == "open"]
        if still_open:
            paths = ", ".join(item.field_path for item in still_open)
            raise ConflictError(f"Resolve the conflict on {paths} first.")
        state = await self._studio.component(principal, instance, component_id)
        merged = await self._merged(principal, instance, state, change, change.config, conflicts)
        code = change.after_code
        if merged != change.config:
            edit = await self._studio.write_code(principal, instance, kind, code, merged, component_id, convention)
            if not edit.equivalent:
                version = studio_side(state) if state else None
                raise ValidationFailedError(
                    f"Studio can't write v{version or ''} changes into {change.path}; merge in the editor instead."
                )
            code = edit.code
        short = (change.commit_sha or "")[:7]
        subject = (change.message or "").splitlines()[0] if change.message else ""
        notes = f"Pulled from {source.label}@{short}" + (f": {subject}" if subject else "")
        name = str(merged.get("name") or (state.name if state else component_id))
        binding = await self._binding(source, change, kind, component_id)
        # Claimed first, so a pull asked for in the app and one queued on push never both make a draft of it.
        if not await self._store.claim_change(change.id, "pending", "pulled"):
            raise ConflictError(f"{change.path} is being pulled already.")
        await self._store.commit()
        # Nothing else is written before the draft exists: the instance's calls are audited in their own transactions.
        try:
            created = await self._studio.create_draft(
                principal,
                instance,
                RepositoryDraft(
                    kind=kind,
                    component_id=component_id,
                    name=name,
                    config=merged,
                    code=code,
                    notes=notes,
                    author_name=change.author_name,
                    convention=source.convention,
                    binding_id=binding.id,
                    code_path=change.path,
                ),
            )
        except Exception:
            _ = await self._store.claim_change(change.id, "pulled", "pending")
            await self._store.commit()
            raise
        await self._store.save_binding(
            replace(
                binding,
                last_synced_sha=change.commit_sha if source.is_local else source.head_sha,
                last_synced_version=created.version,
                content_hash=change.blob,
                synced_code=change.after_code,
                synced_config=change.config,
            )
        )
        await self._store.save_change(replace(change, status="pulled", result_version=created.version))
        await self._drop_moved(source, binding)
        return created.version

    async def _merged(
        self,
        principal: Principal,
        instance: Instance,
        state: ComponentState | None,
        change: Change,
        incoming: dict[str, Any],
        conflicts: Sequence[Conflict],
    ) -> dict[str, Any]:
        """The file's config merged with Studio's side (as it is now), with the resolved conflicts applied."""
        ours_version = studio_side(state) if state is not None else None
        if not ours_version or change.base_config is None or not change.component_id:
            return incoming
        ours = await self._studio.snapshot(principal, instance, change.component_id, ours_version)
        if ours.config == change.base_config:
            return incoming
        result = three_way(change.base_config, ours.config, incoming)
        resolutions = {item.field_path: item.chosen() for item in conflicts if item.status == "resolved"}
        unresolved = [item.path for item in result.conflicts if item.path not in resolutions]
        if unresolved:
            which = f"Draft v{ours_version}" if state and state.draft_version else f"Version {ours_version}"
            raise ConflictError(f"{which} changed since this was fetched ({', '.join(unresolved)}); fetch again.")
        return apply_resolutions(result.merged, resolutions)

    async def _accept_removal(self, source: Source, change: Change) -> None:
        """The repository removed the file: stop syncing it. The component stays in Studio, unpublished changes too."""
        if change.status != "pending":
            raise ConflictError(f"{change.path} was already {change.status}.")
        if not await self._store.claim_change(change.id, "pending", "pulled"):
            raise ConflictError(f"{change.path} is being pulled already.")
        for binding in await self._store.bindings(source.id):
            if binding.id == change.binding_id:
                await unbind(self._store, self._studio, source, binding)

    async def _drop_moved(self, source: Source, kept: FileBinding) -> None:
        """A file pulled from its new path: the component's bindings to files no longer there go."""
        snapshot = await self._files.snapshot(source)
        if snapshot is None:
            return
        for binding in await self._store.bindings(source.id):
            if binding.component_id != kept.component_id or binding.id == kept.id or binding.path in snapshot.files:
                continue
            if source.is_local and await self._files.local_hash(source, binding.path) is not None:
                continue  # left out of a listing that stopped early, not gone
            await unbind(self._store, self._studio, source, binding)

    async def _binding(self, source: Source, change: Change, kind: ComponentKind, component_id: str) -> FileBinding:
        for binding in await self._store.bindings(source.id):
            if binding.path == change.path and binding.component_id == component_id:
                return binding
        return FileBinding(new_id("sfb"), source.id, change.path, kind, component_id)


class ConflictResolver:
    def __init__(self, store: SourceStore, access: SourcesAccess, audit: AuditLog, jobs: SourceJobs) -> None:
        self._store = store
        self._access = access
        self._audit = audit
        self._jobs = jobs

    async def resolve(
        self,
        principal: Principal,
        ref: str,
        source_id: str,
        conflict_id: str,
        resolution: Resolution,
        value: Any = None,  # noqa: ANN401
    ) -> Conflict:
        instance = await self._access.instance(principal, ref, COMPONENTS_WRITE)
        source = self._access.owned(await self._store.source(source_id), instance)
        conflict = await self._store.conflict(conflict_id)
        if conflict is None or conflict.source_id != source.id:
            raise NotFoundError("There is no such conflict on this source.")
        if conflict.status != "open":
            raise ConflictError(f"The conflict on {conflict.field_path} is already {conflict.status}.")
        if resolution == "merged" and value is None:
            raise ValidationFailedError("Give the merged value.")
        resolved = replace(
            conflict,
            status="resolved",
            resolution=resolution,
            resolved_value=value if resolution == "merged" else None,
            resolved_by=principal.id,
            resolved_by_name=principal.display_name,
            resolved_at=utcnow(),
        )
        await self._store.save_conflict(resolved)
        change = await self._store.change(conflict.change_id)
        if change is not None:
            remaining = [
                item.field_path
                for item in await self._store.conflicts_for_change(change.id)
                if item.status == "open" and item.id != conflict.id
            ]
            outcome = Outcome.of(change.outcome)
            outcome = replace(outcome, action="conflict" if remaining else "new_draft", conflict_paths=remaining)
            await self._store.save_change(replace(change, outcome=outcome.as_dict()))
        chosen = {"keep_studio": "kept Studio's value", "keep_repo": "kept the repository's value"}.get(
            resolution, "merged both values"
        )
        _ = await self._audit.record(
            AuditEntry(
                action="sources.conflict.resolve",
                actor=actor_of(principal),
                resource_kind="source",
                resource_id=source.id,
                resource_display=source.label,
                instance_id=instance.id,
                fields={"field": conflict.field_path, "path": conflict.path, "resolution": chosen},
            )
        )
        await self._store.commit()
        count = await self._store.open_conflict_count(instance.id)
        await self._jobs.announce(instance.id, "sources.conflicts", {"count": count})
        await self._jobs.announce(instance.id, "sources.changed", {"source_id": source.id})
        return resolved
