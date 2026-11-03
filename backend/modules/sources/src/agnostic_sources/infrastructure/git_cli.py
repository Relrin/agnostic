"""Bare mirrors through the ``git`` command line.

Every call runs git with a clean environment: no system or global config, no hooks, no credential helpers, no
prompts, and only the protocols sources use. Credentials reach git per call through ``GIT_CONFIG_*`` environment
variables (never the command line, where other processes could read them, and never a config file). Mirrors are
partial clones (``--filter=blob:none``): trees come with every fetch, file contents only when they are read.
Commits are made without a work tree, straight into the object store, and pushed from there.
"""

from __future__ import annotations

import asyncio
import os
import re
import secrets
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from agnostic_kernel.errors import ConflictError
from agnostic_kernel.logging import get_logger
from agnostic_sources.application.ports import FetchResult, GitError, PathChange, Remote
from agnostic_sources.domain.model import CommitInfo
from agnostic_sources.domain.remote import redact
from agnostic_sources.settings import SourcesSettings

log = get_logger(__name__)

MIN_VERSION = (2, 36)
_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]")
_STATUS = {"A": "added", "M": "modified", "D": "deleted", "T": "modified"}
_KEEP_ENV = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "COMSPEC", "PATHEXT")
_MISSING_OBJECT = ("does not exist", "bad revision", "not a valid object", "Not a valid object name", "invalid object")


class GitCli:
    def __init__(self, settings: SourcesSettings) -> None:
        self._settings = settings
        self._root = settings.mirrors_dir.resolve()
        self._git = settings.git_binary

    # ---------------------------------------------------------------- plumbing

    def _mirror(self, source_id: str) -> Path:
        return self._root / f"{_SAFE_ID.sub('_', source_id)}.git"

    def _prepare(self) -> tuple[Path, Path]:
        home = self._root / ".home"
        hooks = self._root / ".no-hooks"
        home.mkdir(parents=True, exist_ok=True)
        hooks.mkdir(parents=True, exist_ok=True)
        empty = home / ".gitconfig"
        if not empty.exists():
            empty.write_text("", encoding="utf-8")
        return home, hooks

    def _env(self, remote: Remote | None, extra: Mapping[str, str] | None, key_file: Path | None) -> dict[str, str]:
        home, hooks = self._prepare()
        env = {name: os.environ[name] for name in _KEEP_ENV if name in os.environ}
        protocols = "https:http:ssh" + (":file" if self._settings.allow_file_remotes else "")
        env |= {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "",
            "SSH_ASKPASS": "",
            "GCM_INTERACTIVE": "never",
            "LC_ALL": "C",
            "GIT_ALLOW_PROTOCOL": protocols,
        }
        config: list[tuple[str, str]] = [
            ("core.hooksPath", str(hooks)),
            ("core.autocrlf", "false"),
            ("core.longpaths", "true"),
            ("credential.helper", ""),
            ("safe.directory", "*"),
            ("advice.detachedHead", "false"),
            ("uploadpack.allowFilter", "true"),
        ]
        if self._settings.allow_file_remotes:
            config.append(("protocol.file.allow", "always"))
        if remote is not None and remote.header:
            config.append(("http.extraHeader", f"Authorization: {remote.header}"))
        env["GIT_CONFIG_COUNT"] = str(len(config))
        for index, (key, value) in enumerate(config):
            env[f"GIT_CONFIG_KEY_{index}"] = key
            env[f"GIT_CONFIG_VALUE_{index}"] = value
        if key_file is not None:
            known = self._root / ".known_hosts"
            env["GIT_SSH_COMMAND"] = (
                f'ssh -i "{key_file}" -o IdentitiesOnly=yes -o BatchMode=yes '
                f'-o UserKnownHostsFile="{known}" -o StrictHostKeyChecking=accept-new'
            )
        return env | dict(extra or {})

    async def _run(
        self,
        args: Sequence[str],
        *,
        git_dir: Path | None = None,
        remote: Remote | None = None,
        stdin: bytes | None = None,
        env: Mapping[str, str] | None = None,
        seconds: float | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        key_file: Path | None = None
        if remote is not None and remote.ssh_key:
            handle, name = tempfile.mkstemp(prefix="key-", dir=self._root)
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                _ = stream.write(remote.ssh_key.strip() + "\n")
            key_file = Path(name)
            key_file.chmod(0o600)
        command = [self._git, *(["--git-dir", str(git_dir)] if git_dir else []), *args]
        try:
            # A worker thread rather than an asyncio subprocess: it works on every event loop (Windows selector
            # loops can't spawn subprocesses) and keeps the loop free while git runs.
            completed = await asyncio.to_thread(
                subprocess.run,
                command,
                input=stdin,
                capture_output=True,
                env=self._env(remote, env, key_file),
                timeout=seconds or self._settings.git_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            limit = seconds or self._settings.git_timeout_seconds
            raise GitError(f"git {args[0]} took longer than {limit:g} s and was stopped.") from exc
        except FileNotFoundError as exc:
            raise GitError(f"The git executable {self._git!r} isn't installed where the worker runs.") from exc
        finally:
            if key_file is not None:
                with suppress(OSError):
                    key_file.unlink()
        if check and completed.returncode != 0:
            raise GitError(f"git {args[0]}: {_stderr(completed)}")
        return completed

    # ---------------------------------------------------------------- reads

    async def version(self) -> str | None:
        try:
            completed = await self._run(["version"], check=False)
        except GitError:
            return None
        text = completed.stdout.decode(errors="replace").strip()
        found = re.search(r"(\d+)\.(\d+)", text)
        if found is None or (int(found.group(1)), int(found.group(2))) < MIN_VERSION:
            log.warning("sources.git_too_old", version=text)
        return text or None

    async def fetch(self, source_id: str, remote: Remote, branch: str) -> FetchResult:
        mirror = self._mirror(source_id)
        timeout = self._settings.fetch_timeout_seconds
        refspec = f"+refs/heads/{branch}:refs/heads/{branch}"
        if not (mirror / "HEAD").exists():
            self._root.mkdir(parents=True, exist_ok=True)
            with suppress(FileNotFoundError):
                shutil.rmtree(mirror)
            _ = await self._run(
                [
                    "clone",
                    "--bare",
                    "--filter=blob:none",
                    "--no-tags",
                    "--single-branch",
                    "--branch",
                    branch,
                    remote.url,
                    str(mirror),
                ],
                remote=remote,
                seconds=timeout,
            )
        else:
            _ = await self._run(["remote", "set-url", "origin", remote.url], git_dir=mirror)
            _ = await self._run(
                ["fetch", "--prune", "--no-tags", "--filter=blob:none", "origin", refspec],
                git_dir=mirror,
                remote=remote,
                seconds=timeout,
            )
        head = await self._rev(mirror, f"refs/heads/{branch}")
        if head is None:
            raise GitError(f"The repository has no branch {branch!r}.")
        return FetchResult(head=head, size_bytes=await self.size(source_id))

    async def _rev(self, mirror: Path, rev: str) -> str | None:
        completed = await self._run(
            ["rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"], git_dir=mirror, check=False
        )
        text = completed.stdout.decode().strip()
        return text or None

    async def files(self, source_id: str, rev: str) -> dict[str, str]:
        completed = await self._run(["ls-tree", "-r", "-z", "--full-tree", rev], git_dir=self._mirror(source_id))
        found: dict[str, str] = {}
        for entry in completed.stdout.split(b"\0"):
            if not entry:
                continue
            meta, _, path = entry.partition(b"\t")
            parts = meta.split()
            if len(parts) == 3 and parts[1] == b"blob":  # noqa: PLR2004
                found[path.decode(errors="replace")] = parts[2].decode()
        return found

    async def changed(self, source_id: str, old: str | None, new: str) -> list[PathChange]:
        mirror = self._mirror(source_id)
        if old is None or not await self._exists(mirror, old):
            return [PathChange("added", path) for path in await self.files(source_id, new)]
        completed = await self._run(
            ["diff-tree", "-r", "-z", "--no-renames", "--name-status", old, new], git_dir=mirror
        )
        tokens = [token.decode(errors="replace") for token in completed.stdout.split(b"\0") if token]
        found: list[PathChange] = []
        for status, path in zip(tokens[::2], tokens[1::2], strict=False):
            kind = _STATUS.get(status[:1])
            if kind is not None:
                found.append(PathChange(kind, path))  # pyright: ignore[reportArgumentType]
        return found

    async def _exists(self, mirror: Path, rev: str) -> bool:
        completed = await self._run(["cat-file", "-e", f"{rev}^{{commit}}"], git_dir=mirror, check=False)
        return completed.returncode == 0

    async def read(self, source_id: str, remote: Remote, rev: str, path: str) -> bytes | None:
        completed = await self._run(
            ["cat-file", "blob", f"{rev}:{path}"],
            git_dir=self._mirror(source_id),
            remote=remote,
            seconds=self._settings.fetch_timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            detail = _stderr(completed)
            if any(marker in detail for marker in _MISSING_OBJECT):
                return None
            raise GitError(f"git cat-file: {detail}")
        return completed.stdout

    async def last_commit(self, source_id: str, rev: str, path: str) -> CommitInfo | None:
        completed = await self._run(
            ["log", "-1", "--format=%H%x00%an%x00%ae%x00%at%x00%s", rev, "--", path],
            git_dir=self._mirror(source_id),
            check=False,
        )
        fields = completed.stdout.decode(errors="replace").strip().split("\0")
        if completed.returncode != 0 or len(fields) < 5:  # noqa: PLR2004
            return None
        sha, name, email, stamp, subject = fields[:5]
        return CommitInfo(sha, name, email, datetime.fromtimestamp(int(stamp), UTC), subject)

    async def contains(self, source_id: str, ancestor: str, rev: str) -> bool:
        completed = await self._run(
            ["merge-base", "--is-ancestor", ancestor, rev], git_dir=self._mirror(source_id), check=False
        )
        return completed.returncode == 0

    async def branches(self, source_id: str, remote: Remote) -> list[str]:  # noqa: ARG002
        completed = await self._run(["ls-remote", "--heads", remote.url], remote=remote)
        names: list[str] = []
        for line in completed.stdout.decode(errors="replace").splitlines():
            _, _, ref = line.partition("\t")
            if ref.startswith("refs/heads/"):
                names.append(ref.removeprefix("refs/heads/"))
        return sorted(names)

    # ---------------------------------------------------------------- writes

    async def commit(
        self,
        source_id: str,
        base: str,
        files: Mapping[str, bytes],
        message: str,
        author: tuple[str, str],
        committer: tuple[str, str],
    ) -> str:
        mirror = self._mirror(source_id)
        index = self._root / f"index-{secrets.token_hex(8)}"
        env = {"GIT_INDEX_FILE": str(index)}
        try:
            _ = await self._run(["read-tree", base], git_dir=mirror, env=env)
            for path, data in files.items():
                written = await self._run(["hash-object", "-w", "--stdin"], git_dir=mirror, stdin=data)
                oid = written.stdout.decode().strip()
                _ = await self._run(
                    ["update-index", "--add", "--cacheinfo", f"100644,{oid},{path}"], git_dir=mirror, env=env
                )
            tree = (await self._run(["write-tree", "--missing-ok"], git_dir=mirror, env=env)).stdout.decode().strip()
            people = {
                "GIT_AUTHOR_NAME": author[0],
                "GIT_AUTHOR_EMAIL": author[1],
                "GIT_COMMITTER_NAME": committer[0],
                "GIT_COMMITTER_EMAIL": committer[1],
            }
            created = await self._run(
                ["commit-tree", tree, "-p", base, "-F", "-"], git_dir=mirror, env=people, stdin=message.encode()
            )
        finally:
            await asyncio.to_thread(index.unlink, missing_ok=True)
        return created.stdout.decode().strip()

    async def push(self, source_id: str, remote: Remote, sha: str, branch: str) -> None:
        completed = await self._run(
            ["push", "--porcelain", "origin", f"{sha}:refs/heads/{branch}"],
            git_dir=self._mirror(source_id),
            remote=remote,
            seconds=self._settings.fetch_timeout_seconds,
            check=False,
        )
        if completed.returncode == 0:
            return
        detail = _stderr(completed) + completed.stdout.decode(errors="replace")
        if "non-fast-forward" in detail or "fetch first" in detail or "[rejected]" in detail:
            raise ConflictError(f"{branch} moved on the repository since the last fetch; fetch and try again.")
        raise GitError(f"git push: {redact(detail.strip())[:500]}")

    # ---------------------------------------------------------------- housekeeping

    async def size(self, source_id: str) -> int:
        mirror = self._mirror(source_id)
        if not mirror.exists():
            return 0
        completed = await self._run(["count-objects", "-v"], git_dir=mirror, check=False)
        kib = 0
        for line in completed.stdout.decode().splitlines():
            name, _, value = line.partition(":")
            if name in {"size", "size-pack"} and value.strip().isdigit():
                kib += int(value.strip())
        return kib * 1024

    async def gc(self, source_id: str) -> None:
        mirror = self._mirror(source_id)
        if mirror.exists():
            _ = await self._run(["gc", "--auto", "--quiet"], git_dir=mirror, seconds=600, check=False)

    async def remove(self, source_id: str) -> None:
        mirror = self._mirror(source_id)
        await asyncio.to_thread(shutil.rmtree, mirror, ignore_errors=True)

    async def mirrors(self) -> list[str]:
        if not self._root.exists():
            return []
        return sorted(path.name.removesuffix(".git") for path in self._root.glob("*.git") if path.is_dir())


def _stderr(completed: subprocess.CompletedProcess[bytes]) -> str:
    return redact(completed.stderr.decode(errors="replace").strip())[:800] or f"exit {completed.returncode}"
