"""Report writer: writes a report to its session workspace; the files become artefacts of the run.

The workspace is a folder per session on the runtime host, the same shape as the ``cwd`` of a Claude Code or Codex
harness, or the folder Pi or OpenCode works in. ``collect_artifacts`` reconciles it at the end of every run, so files
written by any means (a tool, a script, a shell command) are stored, once per version. ``publish_artifact`` lets a
real model publish a file explicitly.
"""

from agno.agent import Agent
from agno.tools import tool
from agnostic_bridge.artifacts import ArtifactTools, DirectorySource, collect_artifacts

from app.media import media_storage
from app.models.mock import MockModel
from app.workspace import workspace_for, write_sample_report


def session_workspace(run_context: object) -> DirectorySource:
    return DirectorySource(workspace_for(getattr(run_context, "session_id", None)))


@tool
def write_report(query: str, run_context: object = None) -> str:
    """Write a report on a topic: Markdown, HTML, CSV, JSON, SVG and PNG charts and a PDF, under outputs/."""
    written = write_sample_report(workspace_for(getattr(run_context, "session_id", None)), query)
    return f"Wrote {len(written)} files: {', '.join(written)}."


report_writer = Agent(
    id="report-writer",
    name="report-writer",
    description="Writes reports with charts and data files; the files appear as artefacts of the run.",
    model=MockModel(persona="report-writer"),
    tools=[write_report, ArtifactTools(session_workspace)],
    instructions="Write the report with write_report, then summarise what you wrote in one sentence.",
    post_hooks=[collect_artifacts(session_workspace, include=("outputs/**",))],
    media_storage=media_storage(),
    markdown=True,
    store_events=True,
)
