"""``ruff format`` and ``ruff check`` on generated source, as a subprocess with a timeout and a size limit.

Only source text crosses the boundary: nothing is imported or executed.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass, field
from typing import Any

from ruff.__main__ import find_ruff_bin

MAX_SOURCE_BYTES = 256_000
TIMEOUT_SECONDS = 10.0
LINE_LENGTH = 120
LINT_RULES = "E,F,W,I,B,UP"


@dataclass(frozen=True, slots=True)
class LintMessage:
    code: str
    message: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class RuffResult:
    code: str
    available: bool
    """``False`` when ruff couldn't run (missing binary, timeout, input too large); ``code`` is then unchanged."""
    formatted: bool = False
    messages: list[LintMessage] = field(default_factory=list)
    error: str | None = None

    @property
    def status(self) -> str:
        if not self.available:
            return "ruff unavailable"
        count = len(self.messages)
        return f"ruff · {count} error{'s' if count != 1 else ''}"


async def format_and_lint(
    code: str, *, filename: str = "component.py", first_party: tuple[str, ...] = ("app",)
) -> RuffResult:
    """Format, then lint the formatted code. ``first_party`` names the repository's own top-level packages."""
    if len(code.encode()) > MAX_SOURCE_BYTES:
        return RuffResult(code=code, available=False, error="The source is too large to format.")
    try:
        formatted = await _run(
            ["format", "--isolated", f"--line-length={LINE_LENGTH}", f"--stdin-filename={filename}", "-"], code
        )
        report = await _run(
            [
                "check",
                "--isolated",
                f"--line-length={LINE_LENGTH}",
                f"--select={LINT_RULES}",
                "--ignore=E501",  # formatting already wraps what it can; long strings stay on one line
                "--output-format=json",
                f"--config=lint.isort.known-first-party = {json.dumps(list(first_party))}",
                "--exit-zero",
                f"--stdin-filename={filename}",
                "-",
            ],
            formatted,
        )
    except (OSError, TimeoutError, RuntimeError) as exc:
        return RuffResult(code=code, available=False, error=str(exc) or type(exc).__name__)
    return RuffResult(code=formatted, available=True, formatted=formatted != code, messages=_messages(report))


async def _run(arguments: list[str], source: str) -> str:
    # A worker thread rather than an asyncio subprocess: it works on every event loop (Windows selector loops
    # can't spawn subprocesses) and keeps the loop free while ruff runs.
    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            [find_ruff_bin(), *arguments],
            input=source.encode(),
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"ruff took longer than {TIMEOUT_SECONDS:g} s") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode(errors="replace").strip()[:500]
        raise RuntimeError(detail or f"ruff exited with {completed.returncode}")
    return completed.stdout.decode()


def _messages(report: str) -> list[LintMessage]:
    try:
        items: list[dict[str, Any]] = json.loads(report or "[]")
    except json.JSONDecodeError:
        return []
    messages: list[LintMessage] = []
    for item in items:
        location: dict[str, Any] = item.get("location") or {}
        messages.append(
            LintMessage(
                code=str(item.get("code") or ""),
                message=str(item.get("message") or ""),
                line=int(location.get("row") or 0),
                column=int(location.get("column") or 0),
            )
        )
    return messages
