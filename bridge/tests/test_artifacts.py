"""Artefacts: sources refuse to leave their root, types come from the bytes, the collector attaches each version
once, the publish tool and post-hook attach media, and the routes list what a session's runs stored."""

from __future__ import annotations

import asyncio
import io
import os
import tarfile
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agno.db.sqlite import SqliteDb
from agno.media import File, Image
from agno.media.reference import MediaReference
from agno.run.agent import RunInput, RunOutput, RunStatus
from agno.session import AgentSession
from fastapi.testclient import TestClient

from agnostic_bridge import SCOPE_MAPPINGS, install
from agnostic_bridge._artifacts import session_artifacts
from agnostic_bridge.artifacts import (
    ArtifactCollector,
    ArtifactSourceError,
    ArtifactTools,
    CheckpointSource,
    DirectorySource,
    E2BSource,
    collect_artifacts,
    detect_content_type,
)
from agnostic_bridge.artifacts._collector import matches
from agnostic_bridge.artifacts._sources import clean_relative, relative_to_root
from tests.conftest import make_os

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "work"
    (root / "outputs" / "charts").mkdir(parents=True)
    (root / "outputs" / "report.md").write_text("# Report\n\nAll good.\n", encoding="utf-8")
    (root / "outputs" / "charts" / "q3.png").write_bytes(PNG)
    (root / "outputs" / "page.html").write_text("<!doctype html><p>hi</p>", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "x.js").write_text("x", encoding="utf-8")
    return root


# --- paths -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["../secret", "/etc/passwd", "a/../../b", "C:/x", "", "."])
def test_clean_relative_refuses_paths_out_of_the_root(bad: str) -> None:
    with pytest.raises(ArtifactSourceError):
        clean_relative(bad)


def test_relative_to_root_accepts_absolute_paths_inside_the_root() -> None:
    assert relative_to_root("/home/user/outputs/a/b.md", "/home/user/outputs") == "a/b.md"
    assert relative_to_root("./a.md", "/home/user/outputs") == "a.md"
    with pytest.raises(ArtifactSourceError):
        relative_to_root("/home/user/other.md", "/home/user/outputs")


def test_directory_source_lists_regular_files_and_reads_inside_the_root(tmp_path: Path) -> None:
    source = DirectorySource(_workspace(tmp_path))
    paths = sorted(entry.path for entry in run(source.list()))
    assert "outputs/report.md" in paths and "outputs/charts/q3.png" in paths
    assert run(source.read("outputs/charts/q3.png", limit=1024)) == PNG
    with pytest.raises(ArtifactSourceError):
        run(source.read("../outside.txt", limit=1024))
    with pytest.raises(ArtifactSourceError):
        run(source.read("outputs/charts/q3.png", limit=8))


@pytest.mark.skipif(os.name == "nt", reason="creating symlinks needs privileges on Windows")
def test_directory_source_refuses_a_symlink_that_leaves_the_root(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    (root / "outputs" / "leak.txt").symlink_to(tmp_path / "secret.txt")
    source = DirectorySource(root)
    assert "outputs/leak.txt" not in {entry.path for entry in run(source.list())}
    with pytest.raises(ArtifactSourceError):
        run(source.read("outputs/leak.txt", limit=1024))


# --- types -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [
        ("chart.png", PNG, "image/png"),
        ("chart.txt", PNG, "image/png"),  # the bytes win over the extension
        ("report.md", b"# Title", "text/markdown"),
        ("doc.pdf", b"%PDF-1.7\n", "application/pdf"),
        ("page", b"<!DOCTYPE html><html></html>", "text/html"),
        ("logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"),
        ("data.csv", b"a,b\n1,2\n", "text/csv"),
        ("blob.bin", b"\x00\x01\x02\xff", "application/octet-stream"),
        ("clip.mp4", b"\x00\x00\x00\x18ftypisom", "video/mp4"),
        ("sound.wav", b"RIFF\x00\x00\x00\x00WAVEfmt ", "audio/wav"),
    ],
)
def test_detect_content_type(name: str, data: bytes, expected: str) -> None:
    assert detect_content_type(name, data) == expected


def test_globs() -> None:
    assert matches("outputs/a/b.md", ["outputs/**"])
    assert matches("report.md", ["**/*.md"])
    assert matches("x/node_modules/y.js", ["**/node_modules/**"])
    assert not matches("outputs.md", ["outputs/**"])


# --- collector ---------------------------------------------------------------------------------------------------


def test_collector_attaches_each_version_once(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    collector = ArtifactCollector(DirectorySource(root), include=("outputs/**",))
    state: dict[str, Any] = {}

    first = run(collector.collect(state))
    assert sorted(type(item).__name__ for item in first) == ["File", "File", "Image"]
    report = next(item for item in first if getattr(item, "filename", None) == "report.md")
    info = report.metadata["artifact"]
    assert info["path"] == "outputs/report.md" and info["content_type"] == "text/markdown" and info["revision"] == 1
    assert report.mime_type == "text/markdown"
    html = next(item for item in first if getattr(item, "filename", None) == "page.html")
    assert html.metadata["artifact"]["content_type"] == "text/html"

    assert run(collector.collect(state)) == []  # nothing changed

    (root / "outputs" / "report.md").write_text("# Report\n\nRevised.\n", encoding="utf-8")
    os.utime(root / "outputs" / "report.md", (1, 1))
    second = run(collector.collect(state))
    assert [item.metadata["artifact"]["revision"] for item in second] == [2]


def test_collector_skips_files_over_the_limit(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    (root / "outputs" / "big.bin").write_bytes(b"\x00" * 2048)
    found = run(ArtifactCollector(DirectorySource(root), include=("outputs/**",), max_file_bytes=1024).collect({}))
    assert "big.bin" not in {getattr(item, "filename", None) for item in found}


def test_post_hook_attaches_media_to_the_run_output(tmp_path: Path) -> None:
    hook = collect_artifacts(DirectorySource(_workspace(tmp_path)), include=("outputs/**",))
    output = SimpleNamespace(images=None, files=None, audio=None, videos=None)
    context = SimpleNamespace(session_state={})
    run(hook(run_output=output, run_context=context))
    assert len(output.images) == 1 and len(output.files) == 2
    assert "agnostic_artifacts" in context.session_state


def test_publish_tool_returns_the_file_as_tool_media(tmp_path: Path) -> None:
    tools = ArtifactTools(DirectorySource(_workspace(tmp_path)))
    result = run(tools.publish_artifact(str(tmp_path / "work" / "outputs" / "report.md"), title="Q3 report"))
    assert result.content == "Published outputs/report.md."
    assert result.files[0].metadata["artifact"]["title"] == "Q3 report"
    refused = run(tools.publish_artifact("../../etc/passwd"))
    assert refused.content.startswith("Not published")


# --- E2B and checkpoints -----------------------------------------------------------------------------------------


class _FakeFiles:
    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files

    def list(self, path: str, depth: int = 1) -> list[Any]:
        return [
            SimpleNamespace(type=SimpleNamespace(value="file"), path=name, name=name.rsplit("/", 1)[-1], size=len(data))
            for name, data in self._files.items()
            if name.startswith(path)
        ]

    def read(self, path: str, format: str = "text") -> bytearray:
        return bytearray(self._files[path])


def test_e2b_source_reads_through_the_sdk() -> None:
    sandbox = SimpleNamespace(files=_FakeFiles({"/home/user/outputs/a.md": b"# A", "/home/user/other.txt": b"no"}))
    source = E2BSource(tools=SimpleNamespace(sandbox=sandbox))
    assert [entry.path for entry in run(source.list())] == ["a.md"]
    assert run(source.read("a.md", limit=100)) == b"# A"


def test_checkpoint_source_reads_the_workspace_from_the_archive(tmp_path: Path) -> None:
    archive = tmp_path / "checkpoint.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, data in {"workspace/outputs/r.md": b"# R", "workspace/src/x.py": b"x", "native/a": b"n"}.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    @asynccontextmanager
    async def open_archive() -> Any:
        yield archive

    source = CheckpointSource(open_archive, root="outputs")
    assert [entry.path for entry in run(source.list())] == ["r.md"]
    assert run(source.read("r.md", limit=100)) == b"# R"


# --- routes ------------------------------------------------------------------------------------------------------


def _stored_session(db: SqliteDb) -> None:
    reference = MediaReference(
        media_id="art_1",
        storage_key="sess_1/art_1.md",
        session_id="sess_1",
        storage_backend="local",
        mime_type="text/markdown",
        filename="report.md",
        size=9,
        metadata={"artifact": {"path": "outputs/report.md", "content_type": "text/markdown", "source": "directory"}},
    )
    produced = File(id="art_1", media_reference=reference, filename="report.md", mime_type="text/markdown")
    uploaded = Image(
        id="upl_1",
        media_reference=MediaReference(media_id="upl_1", storage_key="sess_1/upl_1.png", storage_backend="local"),
    )
    output = RunOutput(
        run_id="run_1",
        agent_id="writer",
        session_id="sess_1",
        status=RunStatus.completed,
        content="done",
        input=RunInput(input_content="write it", images=[uploaded]),
        files=[produced],
        created_at=1_790_000_000,
    )
    session = AgentSession(session_id="sess_1", agent_id="writer", runs=[output], created_at=1_790_000_000)
    db.upsert_session(session)
    with suppress(NotImplementedError):
        db.upsert_run(run=output, session_id="sess_1", run_index=0)


def test_session_artifacts_lists_outputs_and_optionally_inputs(tmp_path: Path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    _stored_session(db)
    app = install(make_os(db=db))
    client = TestClient(app)

    body = client.get("/agnostic/v1/artifacts", params={"session_id": "sess_1"}).json()
    assert [row["storage_key"] for row in body["data"]] == ["sess_1/art_1.md"]
    row = body["data"][0]
    assert row["kind"] == "file" and row["path"] == "outputs/report.md" and row["role"] == "output"

    with_inputs = client.get("/agnostic/v1/artifacts", params={"session_id": "sess_1", "include_inputs": True})
    assert {item["role"] for item in with_inputs.json()["data"]} == {"output", "input"}

    recent = client.get("/agnostic/v1/artifacts/recent").json()
    assert [item["storage_key"] for item in recent["data"]] == ["sess_1/art_1.md"]

    assert client.get("/agnostic/v1/artifacts", params={"session_id": "nope"}).status_code == 404
    synced = client.post("/agnostic/v1/artifacts/sync", json={"session_id": "sess_1"}).json()
    assert synced == {"session_id": "sess_1", "runs_synced": 0, "artifacts": 0}


def test_routes_need_session_scopes() -> None:
    assert SCOPE_MAPPINGS["GET /agnostic/v1/artifacts"] == ["sessions:read"]
    assert SCOPE_MAPPINGS["POST /agnostic/v1/artifacts/sync"] == ["sessions:write"]


def test_session_artifacts_without_runs() -> None:
    assert session_artifacts(SimpleNamespace(session_id="s", runs=None)) == []
