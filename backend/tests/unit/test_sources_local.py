"""Local folders: what a fetch lists is what a write-back compares against, whatever the file's size, and a file the
listing left out is refused up front instead of failing as changed."""

from pathlib import Path
from typing import Any, cast

import pytest

from agnostic_kernel.errors import ValidationFailedError
from agnostic_sources.application.files import SourceFiles
from agnostic_sources.application.outgoing import Committer
from agnostic_sources.domain.model import Change, Source
from agnostic_sources.infrastructure import local_folders
from agnostic_sources.infrastructure.local_folders import LocalFolders
from agnostic_sources.settings import SourcesSettings

NONE = cast("Any", None)


def folders(root: Path, *, max_file_bytes: int = 16) -> LocalFolders:
    return LocalFolders(SourcesSettings(local_roots=[root], max_file_bytes=max_file_bytes))


def test_a_file_too_large_to_read_is_listed_with_the_hash_a_write_back_compares(tmp_path: Path) -> None:
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "small.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "agents" / "large.py").write_text("x = 1\n" * 100, encoding="utf-8")
    local = folders(tmp_path)

    listed = local.files(str(tmp_path))
    assert set(listed) == {"agents/small.py", "agents/large.py"}
    for path, blob in listed.items():
        assert local.digest(str(tmp_path), path) == blob
    assert local.read(str(tmp_path), "agents/large.py") is None, "it is still too large to read"
    assert local.digest(str(tmp_path), "agents/gone.py") is None


def source(root: Path) -> Source:
    return Source("src_1", "ins_1", "local", str(root), "local", local_path=str(root))


def committer(local: LocalFolders) -> Committer:
    files = SourceFiles(NONE, NONE, NONE, local, NONE)
    return Committer(NONE, files, NONE, NONE, NONE, NONE)


async def test_a_file_the_listing_left_out_is_refused_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local_folders, "MAX_FOLDER_FILES", 1)
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "a.py").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "agents" / "b.py").write_text("b = 1\n", encoding="utf-8")
    local = folders(tmp_path, max_file_bytes=1_000)
    listed = local.files(str(tmp_path))
    assert list(listed) == ["agents/a.py"]

    left_out = Change("sch_1", "src_1", "outgoing", "agents/b.py", blob=listed.get("agents/b.py"))
    with pytest.raises(ValidationFailedError, match="wasn't among the files Studio read"):
        await committer(local)._check_listed(source(tmp_path), [left_out])

    listed_change = Change("sch_2", "src_1", "outgoing", "agents/a.py", blob=listed["agents/a.py"])
    new_file = Change("sch_3", "src_1", "outgoing", "agents/c.py")
    await committer(local)._check_listed(source(tmp_path), [listed_change, new_file])
