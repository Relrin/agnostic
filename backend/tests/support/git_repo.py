"""An upstream repository on disk for code source tests: a bare repo plus a work tree that commits and pushes."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path


def git_available() -> bool:
    return shutil.which("git") is not None


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env |= {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
    }
    return env


class Upstream:
    """``bare`` is what sources clone (``url``); ``work`` is where tests make commits as different people."""

    def __init__(self, root: Path, branch: str = "main") -> None:
        self.root = root
        self.branch = branch
        self.bare = root / "upstream.git"
        self.work = root / "work"
        root.mkdir(parents=True, exist_ok=True)
        self._git("init", "--bare", "--initial-branch", branch, str(self.bare), cwd=root)
        self._git("config", "uploadpack.allowFilter", "true", cwd=self.bare)
        self._git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=self.bare)
        self._git("clone", str(self.bare), str(self.work), cwd=root)
        self._git("checkout", "-B", branch, cwd=self.work)

    @property
    def url(self) -> str:
        return self.bare.as_uri()

    def _git(self, *args: str, cwd: Path, env: Mapping[str, str] | None = None) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=_env() | dict(env or {}),
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.decode(errors="replace"))
        return completed.stdout.decode(errors="replace").strip()

    def commit(
        self,
        files: Mapping[str, str | None],
        message: str,
        *,
        author: tuple[str, str] = ("Sam Rivera", "sam@northwind.test"),
    ) -> str:
        """Write (or with ``None`` delete) files, commit as ``author`` and push; the new head."""
        if self.head_or_none() is not None:
            self._git("fetch", "-q", "origin", cwd=self.work)
            self._git("checkout", "-q", "-B", self.branch, f"origin/{self.branch}", cwd=self.work)
        for path, content in files.items():
            target = self.work / path
            if content is None:
                target.unlink(missing_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.encode())
        self._git("add", "-A", cwd=self.work)
        people = {
            "GIT_AUTHOR_NAME": author[0],
            "GIT_AUTHOR_EMAIL": author[1],
            "GIT_COMMITTER_NAME": author[0],
            "GIT_COMMITTER_EMAIL": author[1],
        }
        self._git("commit", "-q", "-m", message, cwd=self.work, env=people)
        self._git("push", "-q", "origin", f"HEAD:refs/heads/{self.branch}", cwd=self.work)
        return self.head()

    def head_or_none(self, branch: str | None = None) -> str | None:
        try:
            return self._git("rev-parse", f"refs/heads/{branch or self.branch}", cwd=self.bare)
        except RuntimeError:
            return None

    def head(self, branch: str | None = None) -> str:
        found = self.head_or_none(branch)
        assert found is not None
        return found

    def read(self, path: str, branch: str | None = None) -> str:
        return self._git("show", f"refs/heads/{branch or self.branch}:{path}", cwd=self.bare)

    def branches(self) -> list[str]:
        refs = self._git("for-each-ref", "--format=%(refname:short)", "refs/heads", cwd=self.bare)
        return sorted(refs.split()) if refs else []

    def merge(self, branch: str) -> str:
        """Merge ``branch`` into the main branch on the bare repository (what a host does on "Merge")."""
        self._git("fetch", "-q", "origin", cwd=self.work)
        self._git("checkout", "-q", self.branch, cwd=self.work)
        self._git("reset", "-q", "--hard", f"origin/{self.branch}", cwd=self.work)
        people = {
            "GIT_AUTHOR_NAME": "Platform Reviewer",
            "GIT_AUTHOR_EMAIL": "platform@northwind.test",
            "GIT_COMMITTER_NAME": "Platform Reviewer",
            "GIT_COMMITTER_EMAIL": "platform@northwind.test",
        }
        self._git("merge", "-q", "--no-ff", "-m", f"Merge {branch}", f"origin/{branch}", cwd=self.work, env=people)
        self._git("push", "-q", "origin", f"HEAD:refs/heads/{self.branch}", cwd=self.work)
        return self.head()
