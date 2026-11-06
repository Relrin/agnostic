"""Studio → repository: outgoing changes, Commit & PR, pull request tracking, and holding a publish back.

A Studio version is written into its bound file by editing the file (comments and formatting stay) when the code
can say the config, and by generating it otherwise. Writes go to a new branch with a pull request (the default), to
the branch itself, or straight to disk for local folders. When the repository reads as the version again (the pull
request merged), the next fetch moves the binding to that commit and version.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_codegen import RegistryConvention, counts, render
from agnostic_kernel.auth import SYSTEM_PRINCIPAL, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import ConflictError, NotFoundError, ValidationFailedError
from agnostic_kernel.ids import new_id
from agnostic_kernel.logging import get_logger
from agnostic_sources.application.access import COMPONENTS_READ, COMPONENTS_WRITE, SourcesAccess
from agnostic_sources.application.files import SourceFiles
from agnostic_sources.application.ports import GitError, ProviderError, SourceLimits, SourceStore
from agnostic_sources.application.tasks import SourceJobs
from agnostic_sources.domain.model import Change, FileBinding, PullRequest, Source
from agnostic_sources.domain.outcomes import review_sentence
from agnostic_sources.domain.paths import match
from agnostic_sources.domain.templates import branch_name, commit_message, unique_branch
from agnostic_sources.domain.templates import render as render_template
from agnostic_spec.v3_1 import parse
from agnostic_studio.facade import HoldCheck, StudioFacade

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CommitPreview:
    branch: str
    base_branch: str
    mode: str
    message: str
    review_requirement: str | None
    sentence: str
    """``Branch studio/support-triage-v4 · PR into main · 1 review from Platform required``."""


def writable(source: Source, binding: FileBinding) -> bool:
    mapping = match(source.mappings, binding.path)
    return mapping is not None and mapping.effective_writable


async def read_only(store: SourceStore, source: Source) -> bool:
    """Whether the source's connection only pulls (Studio never writes back through it)."""
    if source.connection_id is None:
        return False
    connection = await store.connection(source.connection_id)
    return connection is not None and connection.access == "read_only"


class OutgoingPreparer:
    def __init__(
        self, store: SourceStore, files: SourceFiles, access: SourcesAccess, studio: StudioFacade, jobs: SourceJobs
    ) -> None:
        self._store = store
        self._files = files
        self._access = access
        self._studio = studio
        self._jobs = jobs

    async def prepare(  # noqa: C901
        self, source_id: str, *, component_id: str | None = None, version: int | None = None
    ) -> list[Change]:
        """Pending outgoing changes for every bound component Studio has moved past the repository."""
        source = await self._store.source(source_id)
        if source is None or source.status != "active" or source.head_sha is None:
            return []
        instance = await self._access.of(source)
        convention = RegistryConvention.from_dict(source.convention)
        snapshot = await self._files.snapshot(source)
        files = snapshot.files if snapshot else {}
        pending = {
            (change.path, change.component_id): change
            for change in await self._store.changes(source.id, "outgoing", ["pending"])
        }
        incoming = {
            (change.path, change.component_id)
            for change in await self._store.changes(source.id, "incoming", ["pending"])
        }
        prepared: list[Change] = []
        for binding in await self._store.bindings(source.id):
            if component_id is not None and binding.component_id != component_id:
                continue
            if not writable(source, binding):
                continue
            key = (binding.path, binding.component_id)
            state = await self._studio.component(SYSTEM_PRINCIPAL, instance, binding.component_id)
            if state is None:
                continue
            number = version or state.latest_version
            if number is None or (binding.last_synced_version is not None and number < binding.last_synced_version):
                if key in pending:
                    await self._store.save_change(replace(pending[key], status="superseded"))
                continue
            snap = await self._studio.snapshot(SYSTEM_PRINCIPAL, instance, binding.component_id, number)
            if binding.synced_config is not None and snap.config == binding.synced_config:
                continue
            existing = pending.get(key)
            if existing is not None and existing.draft_version == number and existing.config == snap.config:
                prepared.append(existing)
                continue
            repo_code = await self._files.read(source, source.head_sha, binding.path) if binding.path in files else None
            code, rewritten = await self._code(instance, binding, snap.code, snap.config, repo_code, convention)
            added, removed = counts(repo_code or "", code)
            summary = self._studio.summarize(binding.synced_config or {}, snap.config)
            blocked = key in incoming
            change = Change(
                id=new_id("sch"),
                source_id=source.id,
                direction="outgoing",
                path=binding.path,
                component_kind=binding.component_kind,
                component_id=binding.component_id,
                binding_id=binding.id,
                base_sha=source.head_sha,
                blob=files.get(binding.path),
                author_name=snap.author_name,
                committed_at=snap.updated_at,
                additions=added,
                deletions=removed,
                before_code=repo_code,
                after_code=code,
                config=snap.config,
                base_config=binding.synced_config,
                outcome={
                    "action": "blocked" if blocked else ("rewrite" if rewritten else "edit"),
                    "stage": snap.stage,
                },
                draft_version=number,
                summary=summary,
                included=not blocked,
            )
            if existing is not None:
                await self._store.save_change(replace(existing, status="superseded"))
            await self._store.save_change(change)
            prepared.append(change)
        await self._store.commit()
        await self._jobs.announce(source.instance_id, "sources.changed", {"source_id": source.id})
        return prepared

    async def _code(
        self,
        instance: Any,  # noqa: ANN401
        binding: FileBinding,
        own_code: str | None,
        config: dict[str, Any],
        repo_code: str | None,
        convention: RegistryConvention,
    ) -> tuple[str, bool]:
        """The file's new content, and whether it had to be generated from scratch."""
        if own_code is not None:
            return _newline(own_code, repo_code), False
        if repo_code is not None:
            edit = await self._studio.write_code(
                SYSTEM_PRINCIPAL, instance, binding.component_kind, repo_code, config, binding.component_id, convention
            )
            if edit.equivalent:
                return edit.code, False
        rendered = await render(parse(binding.component_kind, config), convention=convention)
        return _newline(rendered.code, repo_code), True


class Committer:
    def __init__(
        self,
        store: SourceStore,
        files: SourceFiles,
        access: SourcesAccess,
        audit: AuditLog,
        jobs: SourceJobs,
        settings: SourceLimits,
    ) -> None:
        self._store = store
        self._files = files
        self._access = access
        self._audit = audit
        self._jobs = jobs
        self._settings = settings

    async def preview(self, principal: Principal, ref: str, source_id: str, change_ids: Sequence[str]) -> CommitPreview:
        instance = await self._access.instance(principal, ref, COMPONENTS_READ)
        source = self._access.owned(await self._store.source(source_id), instance)
        changes = await self._outgoing(source, change_ids)
        return await self._preview(source, changes, instance.display_name, principal.display_name)

    async def _preview(self, source: Source, changes: Sequence[Change], instance: str, author: str) -> CommitPreview:
        first = changes[0]
        values = {
            "component": first.component_id or "studio",
            "version": first.draft_version or "",
            "kind": first.component_kind or "",
            "instance": instance,
            "author": author,
            "summary": first.summary or "update",
            "path": first.path,
            "count": len(changes),
        }
        if len(changes) > 1:
            values["summary"] = f"{len(changes)} components from Studio"
        message = commit_message(source.policy.commit_template, values).strip()
        mode = "local" if source.is_local else source.policy.publish_mode
        connection = await self._files.connection(source)
        if connection is not None and connection.access == "read_only" and mode != "no_write_back":
            raise ValidationFailedError(f"{connection.name} is read-only; Studio doesn't write back through it.")
        if connection is not None and connection.auth_kind == "deploy_key" and mode == "open_pr":
            raise ValidationFailedError(
                f"{connection.name} uses a deploy key, which can't open pull requests; change the source's sync "
                "policy to commit directly to the branch."
            )
        review: str | None = None
        if mode == "open_pr":
            branch = unique_branch(
                branch_name(render_template(source.policy.branch_template, values)), await self._taken(source)
            )
            client = await self._files.client(source)
            if client is not None:
                try:
                    found = await client.review_requirement(source.repo, source.branch)
                except ProviderError:
                    found = None
                review = review_sentence(*found) if found is not None else None
            sentence = f"Branch {branch} · PR into {source.branch}" + (f" · {review}" if review else "")
        elif mode == "commit_direct":
            branch = source.branch
            sentence = f"Commits straight to {source.branch}"
        elif mode == "local":
            branch = source.branch
            sentence = "Writes to the folder; the runtime reloads it"
        else:
            raise ValidationFailedError("This source doesn't write back (its policy is \"Don't write back\").")
        return CommitPreview(branch, source.branch, mode, message, review, sentence)

    async def _taken(self, source: Source) -> set[str]:
        """Branch names a new pull request can't use.

        Earlier pull requests' branches, and every branch on the remote: a push whose pull request failed to open
        leaves its branch behind, and pushing to it again would be rejected.
        """
        taken = {pull.branch for pull in await self._store.pull_requests(source.id)}
        try:
            taken.update(await self._files.git.branches(source.id, await self._files.remote(source)))
        except (GitError, ProviderError) as exc:
            log.warning("sources.remote_branches_failed", source_id=source.id, error=str(exc))
        return taken

    async def request(
        self, principal: Principal, ref: str, source_id: str, change_ids: Sequence[str], message: str | None
    ) -> int:
        instance = await self._access.instance(principal, ref, COMPONENTS_WRITE)
        source = self._access.owned(await self._store.source(source_id), instance)
        _ = await self._preview(source, await self._outgoing(source, change_ids), instance.display_name, "")
        for change_id in change_ids:
            change = await self._store.change(change_id)
            if change is not None:
                await self._store.save_change(replace(change, status="committing"))
        await self._store.commit()
        return await self._jobs.commit(
            source.id, list(change_ids), message, principal.id, principal.display_name, principal.email
        )

    async def _outgoing(self, source: Source, change_ids: Sequence[str]) -> list[Change]:
        changes: list[Change] = []
        for change_id in change_ids:
            change = await self._store.change(change_id)
            if change is None or change.source_id != source.id or change.direction != "outgoing":
                raise NotFoundError(f"There is no outgoing change {change_id} on this source.")
            if change.status not in {"pending", "committing"}:
                raise ConflictError(f"{change.path} was already {change.status}.")
            if change.outcome.get("action") == "blocked":
                raise ConflictError(f"{change.path} changed in the repository too; pull the incoming change first.")
            changes.append(change)
        if not changes:
            raise ValidationFailedError("Pick at least one outgoing change.")
        return changes

    async def run(  # noqa: C901, PLR0912
        self,
        source_id: str,
        change_ids: Sequence[str],
        message: str | None,
        actor_id: str | None,
        actor_name: str,
        actor_email: str | None,
    ) -> PullRequest | None:
        """The job: commit the outgoing changes, then push a branch and open a pull request (or write the folder)."""
        source = await self._store.source(source_id)
        if source is None:
            return None
        instance = await self._access.of(source)
        changes = await self._outgoing(source, change_ids)
        preview = await self._preview(source, changes, instance.display_name, actor_name)
        text = (message or preview.message).strip() or preview.message
        body = "\n".join(
            f"- {change.path}: {change.component_id} v{change.draft_version} · {change.summary}" for change in changes
        )
        actor = actor_of(_principal(actor_id, actor_name, actor_email))
        pull_request: PullRequest | None = None
        try:
            if source.is_local:
                for change in changes:
                    if await self._files.local_hash(source, change.path) != change.blob:
                        raise ConflictError(  # noqa: TRY301
                            f"{change.path} changed in the folder meanwhile; fetch and review again."
                        )
                for change in changes:
                    self._files.folders.write(source.local_path or "", change.path, (change.after_code or "").encode())
            else:
                snapshot = await self._files.fetch(source)
                for change in changes:
                    if snapshot.files.get(change.path) != change.blob:
                        raise ConflictError(  # noqa: TRY301
                            f"{change.path} changed in the repository meanwhile; fetch and review again."
                        )
                payload = {change.path: (change.after_code or "").encode() for change in changes}
                sha = await self._files.git.commit(
                    source.id,
                    snapshot.head,
                    payload,
                    f"{text}\n\n{body}\n",
                    (actor_name, actor_email or f"{actor_id or 'studio'}@users.agnostic.invalid"),
                    (self._settings.committer_name, self._settings.committer_email),
                )
                remote = await self._files.remote(source)
                await self._files.git.push(source.id, remote, sha, preview.branch)
                if preview.mode == "open_pr":
                    client = await self._files.client(source)
                    if client is None:
                        raise ProviderError("Opening a pull request needs a connection to the git host.")  # noqa: TRY301
                    opened = await client.open_pull_request(
                        source.repo, head=preview.branch, base=source.branch, title=text.splitlines()[0], body=body
                    )
                    pull_request = PullRequest(
                        id=new_id("spr"),
                        source_id=source.id,
                        number=opened.number,
                        url=opened.url,
                        branch=preview.branch,
                        base_branch=source.branch,
                        head_sha=sha,
                        components=tuple(
                            {"component_id": change.component_id, "version": change.draft_version, "path": change.path}
                            for change in changes
                        ),
                        review_requirement=preview.review_requirement,
                        title=text.splitlines()[0],
                        opened_by=actor_id,
                        opened_by_name=actor_name,
                        created_at=utcnow(),
                    )
                    await self._store.save_pull_request(pull_request)
        except (GitError, ProviderError, ConflictError) as exc:
            for change in changes:
                await self._store.save_change(replace(change, status="pending"))
            await self._store.commit()
            log.warning("sources.commit_failed", source_id=source.id, error=str(exc))
            raise
        for change in changes:
            await self._store.save_change(replace(change, status="committed"))
        _ = await self._audit.record(
            AuditEntry(
                action="sources.commit",
                actor=actor,
                resource_kind="source",
                resource_id=source.id,
                resource_display=source.label,
                instance_id=instance.id,
                fields={"message": text.splitlines()[0], "where": preview.sentence, "count": str(len(changes))},
                links={"pull_request": pull_request.url} if pull_request else None,
            )
        )
        if pull_request is not None:
            _ = await self._audit.record(
                AuditEntry(
                    action="sources.pr.open",
                    actor=actor,
                    resource_kind="source",
                    resource_id=source.id,
                    resource_display=source.label,
                    instance_id=instance.id,
                    fields={"number": str(pull_request.number), "branch": pull_request.branch, "url": pull_request.url},
                )
            )
        await self._store.commit()
        if pull_request is None:
            _ = await self._jobs.fetch(source.id, "commit")
        await self._jobs.announce(source.instance_id, "sources.changed", {"source_id": source.id})
        return pull_request


def _principal(actor_id: str | None, name: str, email: str | None) -> Principal:
    if actor_id is None:
        return SYSTEM_PRINCIPAL
    return Principal(kind="user", id=actor_id, display_name=name, email=email)


def _newline(code: str, like: str | None) -> str:
    """Keep the repository file's line endings."""
    if like is not None and "\r\n" in like and "\r\n" not in code:
        return code.replace("\n", "\r\n")
    return code


class PullRequestTracker:
    def __init__(
        self, store: SourceStore, files: SourceFiles, access: SourcesAccess, audit: AuditLog, jobs: SourceJobs
    ) -> None:
        self._store = store
        self._files = files
        self._access = access
        self._audit = audit
        self._jobs = jobs

    async def refresh(self, source_id: str, number: int | None = None) -> list[PullRequest]:  # noqa: C901
        source = await self._store.source(source_id)
        if source is None:
            return []
        client = await self._files.client(source)
        if client is None:
            return []
        instance = await self._access.of(source)
        updated: list[PullRequest] = []
        merged_any = False
        for pull in await self._store.pull_requests(source.id, open_only=True):
            if number is not None and pull.number != number:
                continue
            try:
                state = await client.pull_request(source.repo, pull.number)
            except ProviderError as exc:
                log.warning("sources.pr_refresh_failed", source_id=source.id, number=pull.number, error=str(exc))
                continue
            fresh = replace(pull, last_checked_at=utcnow())
            if state.status != pull.status:
                fresh = replace(
                    fresh,
                    status=state.status,
                    merge_sha=state.merge_sha,
                    merged_at=utcnow() if state.status == "merged" else None,
                )
                merged_any = merged_any or state.status == "merged"
                _ = await self._audit.record(
                    AuditEntry(
                        action=f"sources.pr.{state.status}",
                        actor=actor_of(SYSTEM_PRINCIPAL),
                        resource_kind="source",
                        resource_id=source.id,
                        resource_display=source.label,
                        instance_id=instance.id,
                        via="system",
                        fields={"number": str(pull.number), "branch": pull.branch},
                    )
                )
                if state.status == "closed":
                    for change in await self._store.changes(source.id, "outgoing", ["committed"]):
                        if any(item.get("path") == change.path for item in pull.components):
                            await self._store.save_change(replace(change, status="pending"))
            await self._store.save_pull_request(fresh)
            updated.append(fresh)
        await self._store.commit()
        if merged_any:
            _ = await self._jobs.fetch(source.id, "merged")
        if updated:
            await self._jobs.announce(source.instance_id, "sources.changed", {"source_id": source.id})
        return updated


class SourcePublishHold:
    """Holds a publish back until the repository has the version, for sources that ask for it."""

    def __init__(self, store: SourceStore, access: SourcesAccess, studio: StudioFacade) -> None:
        self._store = store
        self._access = access
        self._studio = studio

    async def _in_repository(self, source: Source, binding: FileBinding, version: int) -> bool:
        """Whether the bound file already says ``version`` (drafts change under the same number, so compare)."""
        if binding.last_synced_version is None or binding.synced_config is None:
            return False
        if binding.last_synced_version > version:
            return True
        if binding.last_synced_version < version:
            return False
        instance = await self._access.of(source)
        snapshot = await self._studio.snapshot(SYSTEM_PRINCIPAL, instance, binding.component_id, version)
        return snapshot.config == binding.synced_config

    async def check(self, instance_id: str, component_id: str, version: int) -> HoldCheck:  # noqa: PLR0911
        for source, binding in await self._store.bindings_for_component(instance_id, component_id):
            if not writable(source, binding) or source.status != "active" or await read_only(self._store, source):
                continue
            policy = source.policy
            if source.is_local:
                return HoldCheck(write_back=f"Writes {binding.path} in the folder; the runtime reloads it")
            if policy.publish_mode == "no_write_back":
                continue
            if policy.publish_mode == "commit_direct":
                return HoldCheck(write_back=f"Commits {binding.path} straight to {source.branch}")
            branch = render_template(policy.branch_template, {"component": component_id, "version": version})
            write_back = f"Opens a pull request {branch_name(branch)} into {source.branch}"
            if not policy.block_publish_until_merged:
                return HoldCheck(write_back=write_back)
            if await self._in_repository(source, binding, version):
                return HoldCheck()
            pulls = await self._store.pull_requests(source.id)
            mine = [
                pull
                for pull in pulls
                if any(
                    item.get("component_id") == component_id and item.get("version") == version
                    for item in pull.components
                )
            ]
            if any(pull.status == "merged" for pull in mine):
                return HoldCheck()
            waiting = next((pull for pull in mine if pull.status == "open"), None)
            if waiting is not None:
                review = f" · {waiting.review_requirement}" if waiting.review_requirement else ""
                return HoldCheck(
                    held=True, reason=f"Waiting for PR #{waiting.number} to merge{review}", link=waiting.url or None
                )
            return HoldCheck(
                held=True,
                reason=f"Open a pull request for v{version} first (Commit & PR…); publishing waits until it merges.",
            )
        return HoldCheck()


class OnPublished:
    """After a publish, write the version back to every source that asks for it (unless a merged PR already did)."""

    def __init__(self, store: SourceStore, preparer: OutgoingPreparer, committer: Committer) -> None:
        self._store = store
        self._preparer = preparer
        self._committer = committer

    async def __call__(self, payload: dict[str, Any]) -> None:
        instance_id = str(payload.get("instance_id") or "")
        component_id = str(payload.get("component_id") or "")
        version = int(payload.get("version") or 0)
        for source, binding in await self._store.bindings_for_component(instance_id, component_id):
            if not writable(source, binding) or source.status != "active":
                continue
            if source.policy.publish_mode == "no_write_back" and not source.is_local:
                continue
            if await read_only(self._store, source):
                log.info("sources.write_back_skipped", source_id=source.id, reason="read_only")
                continue
            if source.policy.block_publish_until_merged:
                continue
            prepared = [
                change
                for change in await self._preparer.prepare(source.id, component_id=component_id, version=version)
                if change.outcome.get("action") != "blocked"
            ]
            if not prepared:
                continue
            try:
                _ = await self._committer.run(
                    source.id,
                    [change.id for change in prepared],
                    None,
                    payload.get("published_by"),
                    str(payload.get("published_by_name") or "Studio"),
                    payload.get("published_by_email"),
                )
            except (GitError, ProviderError, ConflictError) as exc:
                log.warning("sources.write_back_failed", source_id=source.id, component_id=component_id, error=str(exc))
