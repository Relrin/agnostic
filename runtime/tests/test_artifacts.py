"""The report writer's files become stored artefacts that AgentOS's media route serves."""

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media.storage.local import LocalMediaStorage
from agno.os import AgentOS
from agnostic_bridge import install
from agnostic_bridge.artifacts import DirectorySource, collect_artifacts
from fastapi.testclient import TestClient

from app.agents.report_writer import write_report
from app.models.mock import MockModel
from app.settings import get_settings
from app.workspace import write_sample_report


@pytest.fixture
def untraced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spans of these runs go nowhere: importing app.main sets up tracing into the dev Postgres, which may be down."""
    from agno.tracing.exporter import DatabaseSpanExporter
    from opentelemetry.sdk.trace.export import SpanExportResult

    monkeypatch.setattr(DatabaseSpanExporter, "export", lambda self, spans: SpanExportResult.SUCCESS)


@pytest.fixture
def workspaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("RUNTIME_WORKSPACE_DIR", str(tmp_path / "workspaces"))
    get_settings.cache_clear()
    yield tmp_path / "workspaces"
    get_settings.cache_clear()


def test_sample_report_writes_every_kind(tmp_path: Path) -> None:
    written = write_sample_report(tmp_path, "support volume")
    suffixes = {Path(path).suffix for path in written}
    assert suffixes == {".md", ".html", ".csv", ".json", ".svg", ".png", ".pdf", ".ipynb"}
    assert (tmp_path / "outputs" / "report.pdf").read_bytes().startswith(b"%PDF-1.4")
    assert (tmp_path / "outputs" / "charts" / "volume.png").read_bytes().startswith(b"\x89PNG")


def test_sample_notebook_is_nbformat_4_with_saved_outputs(tmp_path: Path) -> None:
    write_sample_report(tmp_path, "support volume")
    notebook = json.loads((tmp_path / "outputs" / "analysis.ipynb").read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    assert notebook["metadata"]["language_info"]["name"] == "python"
    assert {cell["cell_type"] for cell in notebook["cells"]} == {"markdown", "code"}
    outputs = [output for cell in notebook["cells"] for output in cell.get("outputs", [])]
    assert {output["output_type"] for output in outputs} == {"execute_result", "stream", "display_data", "error"}
    assert all(isinstance(line, str) for cell in notebook["cells"] for line in cell["source"])


def test_a_run_stores_its_files_and_the_media_route_serves_them(
    tmp_path: Path, workspaces: Path, untraced: None
) -> None:
    storage = LocalMediaStorage(base_path=str(tmp_path / "media"))
    db = SqliteDb(db_file=str(tmp_path / "os.db"))

    def source(run_context: object) -> DirectorySource:
        from app.workspace import workspace_for

        return DirectorySource(workspace_for(getattr(run_context, "session_id", None)))

    agent = Agent(
        id="report-writer",
        model=MockModel(persona="report-writer"),
        tools=[write_report],
        post_hooks=[collect_artifacts(source, include=("outputs/**",))],
        media_storage=storage,
        db=db,
        telemetry=False,
    )
    output = asyncio.run(agent.arun("Write a report on support volume", session_id="sess_demo"))
    assert len(output.files or []) == 6 and len(output.images or []) == 2

    app = install(AgentOS(id="artifacts-test", agents=[agent], db=db, media_storage=storage, telemetry=False))
    client = TestClient(app)
    rows = client.get("/agnostic/v1/artifacts", params={"session_id": "sess_demo"}).json()["data"]
    assert {row["filename"] for row in rows} >= {
        "report.md",
        "summary.html",
        "report.pdf",
        "volume.png",
        "analysis.ipynb",
    }
    notebook = next(row for row in rows if row["filename"] == "analysis.ipynb")
    assert notebook["content_type"] == "application/x-ipynb+json"
    report = next(row for row in rows if row["filename"] == "report.md")
    body = client.get(f"/sessions/sess_demo/media/{report['storage_key']}")
    assert body.status_code == 200 and body.text.startswith("# Report: Write a report on support volume")

    # The next run writes the same files again: nothing new is attached.
    again = asyncio.run(agent.arun("Write a report on support volume", session_id="sess_demo"))
    assert not again.files and not again.images
