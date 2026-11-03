"""The git command-line mirrors: partial fetch, reads, diffs, commits without a work tree, push, and isolation."""

import asyncio
from pathlib import Path

import pytest

from agnostic_kernel.errors import ConflictError
from agnostic_sources.application.ports import Remote
from agnostic_sources.infrastructure.git_cli import GitCli
from agnostic_sources.settings import SourcesSettings
from tests.support.git_repo import Upstream, git_available

pytestmark = pytest.mark.skipif(not git_available(), reason="git isn't installed")


def cli(tmp_path: Path) -> GitCli:
    return GitCli(SourcesSettings(mirrors_dir=tmp_path / "mirrors", allow_file_remotes=True))


def test_fetch_read_diff_commit_and_push(tmp_path: Path) -> None:
    upstream = Upstream(tmp_path)
    first = upstream.commit(
        {"agents/triage.py": "x = 1\n", "README.md": "hi\n"}, "First", author=("Lena Ito", "lena@northwind.test")
    )
    git = cli(tmp_path)
    remote = Remote(upstream.url)

    async def scenario() -> None:
        fetched = await git.fetch("src_1", remote, "main")
        assert fetched.head == first
        assert set(await git.files("src_1", first)) == {"agents/triage.py", "README.md"}
        assert await git.read("src_1", remote, first, "agents/triage.py") == b"x = 1\n"
        assert await git.read("src_1", remote, first, "agents/missing.py") is None

        second = upstream.commit({"agents/triage.py": "x = 2\n", "teams/crew.py": "y = 1\n"}, "Second")
        assert (await git.fetch("src_1", remote, "main")).head == second
        changes = {(item.status, item.path) for item in await git.changed("src_1", first, second)}
        assert changes == {("modified", "agents/triage.py"), ("added", "teams/crew.py")}
        info = await git.last_commit("src_1", second, "agents/triage.py")
        assert info is not None
        assert (info.author_name, info.message) == ("Sam Rivera", "Second")
        assert await git.contains("src_1", first, second)

        made = await git.commit(
            "src_1",
            second,
            {"agents/triage.py": b"x = 3\n"},
            "triage: three\n",
            ("Priya Nair", "priya@northwind.test"),
            ("Agnostic Studio", "studio@agnostic.invalid"),
        )
        await git.push("src_1", remote, made, "studio/triage-v3")
        assert upstream.read("agents/triage.py", "studio/triage-v3") == "x = 3"
        assert upstream.read("teams/crew.py", "studio/triage-v3") == "y = 1"
        assert "studio/triage-v3" in await git.branches("src_1", remote)

        _ = upstream.commit({"agents/triage.py": "x = 4\n"}, "Third")
        stale = await git.commit(
            "src_1", second, {"agents/triage.py": b"x = 5\n"}, "stale\n", ("A", "a@x.test"), ("A", "a@x.test")
        )
        with pytest.raises(ConflictError):
            await git.push("src_1", remote, stale, "main")
        assert await git.size("src_1") > 0

    asyncio.run(scenario())


def test_credentials_never_reach_a_config_file(tmp_path: Path) -> None:
    upstream = Upstream(tmp_path)
    _ = upstream.commit({"agents/a.py": "a = 1\n"}, "First")
    git = cli(tmp_path)
    remote = Remote(upstream.url, header="Basic c2VjcmV0LXRva2Vu")
    _ = asyncio.run(git.fetch("src_2", remote, "main"))
    mirror_config = (tmp_path / "mirrors" / "src_2.git" / "config").read_text(encoding="utf-8")
    assert "c2VjcmV0LXRva2Vu" not in mirror_config
    assert "extraHeader" not in mirror_config
    home = (tmp_path / "mirrors" / ".home" / ".gitconfig").read_text(encoding="utf-8")
    assert home == ""


def test_file_remotes_are_refused_unless_allowed(tmp_path: Path) -> None:
    upstream = Upstream(tmp_path)
    _ = upstream.commit({"a.py": "a = 1\n"}, "First")
    git = GitCli(SourcesSettings(mirrors_dir=tmp_path / "mirrors"))
    with pytest.raises(Exception, match="git clone"):
        _ = asyncio.run(git.fetch("src_3", Remote(upstream.url), "main"))
