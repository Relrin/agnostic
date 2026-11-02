"""Import dataset cases from CSV or JSONL.

Recognised fields: ``input`` (required), ``expected_output``, ``criteria``, ``expected_tool_calls`` (a JSON list or
names separated by ``;``/``,``), ``expected_tool_call_arguments`` (JSON object). Any other column is kept as case
metadata. Each case is checked against the dataset's eval type.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from agnostic_evals.domain.model import Case, EvalRuleError, EvalType, check_case

type ImportFormat = Literal["csv", "jsonl"]

MAX_CASES = 1000
KNOWN = {"input", "expected_output", "criteria", "expected_tool_calls", "expected_tool_call_arguments"}


@dataclass(frozen=True, slots=True)
class CaseDraft:
    input: str
    expected_output: str | None = None
    criteria: str | None = None
    expected_tool_calls: tuple[str, ...] | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


def tool_calls(value: object) -> tuple[str, ...] | None:
    if value is None or value == "":
        return None
    if isinstance(value, list):
        return tuple(str(item).strip() for item in cast("list[Any]", value) if str(item).strip()) or None
    text = str(value).strip()
    if text.startswith("["):
        try:
            return tool_calls(json.loads(text))
        except ValueError as exc:
            raise EvalRuleError(f"expected_tool_calls is not a JSON list: {text[:60]}") from exc
    names = [part.strip() for part in text.replace(";", ",").split(",")]
    return tuple(name for name in names if name) or None


def _draft(row: Mapping[str, Any], line: int) -> CaseDraft:
    text = row.get("input")
    if not isinstance(text, str) or not text.strip():
        raise EvalRuleError(f"Line {line}: input is missing.")
    metadata = {str(key): value for key, value in row.items() if key not in KNOWN and value not in (None, "")}
    arguments = row.get("expected_tool_call_arguments")
    if isinstance(arguments, str) and arguments.strip():
        try:
            arguments = json.loads(arguments)
        except ValueError as exc:
            raise EvalRuleError(f"Line {line}: expected_tool_call_arguments is not JSON.") from exc
    if isinstance(arguments, dict):
        metadata["expected_tool_call_arguments"] = arguments
    try:
        calls = tool_calls(row.get("expected_tool_calls"))
    except EvalRuleError as exc:
        raise EvalRuleError(f"Line {line}: {exc}") from exc
    return CaseDraft(
        input=text.strip(),
        expected_output=str(row["expected_output"]).strip() or None if row.get("expected_output") else None,
        criteria=str(row["criteria"]).strip() or None if row.get("criteria") else None,
        expected_tool_calls=calls,
        metadata=metadata,
    )


def _rows(content: str, fmt: ImportFormat) -> list[tuple[int, Mapping[str, Any]]]:
    """``(line number, fields)`` per case."""
    if fmt == "csv":
        reader = csv.DictReader(io.StringIO(content.lstrip("﻿")))
        if not reader.fieldnames or "input" not in reader.fieldnames:
            raise EvalRuleError("The CSV needs a header row with an input column.")
        return [(index + 2, row) for index, row in enumerate(reader)]
    rows: list[tuple[int, Mapping[str, Any]]] = []
    for index, raw in enumerate(content.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            value: object = json.loads(raw)
        except ValueError as exc:
            raise EvalRuleError(f"Line {index} is not JSON.") from exc
        if not isinstance(value, dict):
            raise EvalRuleError(f"Line {index} is not a JSON object.")
        rows.append((index, cast("dict[str, Any]", value)))
    return rows


def parse_cases(content: str, fmt: ImportFormat, eval_type: EvalType) -> list[CaseDraft]:
    rows = _rows(content, fmt)
    if not rows:
        raise EvalRuleError("The file has no cases.")
    if len(rows) > MAX_CASES:
        raise EvalRuleError(f"A dataset holds at most {MAX_CASES} cases.")
    drafts: list[CaseDraft] = []
    for line, row in rows:
        draft = _draft(row, line)
        try:
            check_case(
                eval_type,
                Case(
                    id="",
                    dataset_id="",
                    position=len(drafts) + 1,
                    input=draft.input,
                    expected_output=draft.expected_output,
                    criteria=draft.criteria,
                    expected_tool_calls=draft.expected_tool_calls,
                ),
            )
        except EvalRuleError as exc:
            raise EvalRuleError(f"Line {line}: {exc}") from exc
        drafts.append(draft)
    return drafts
