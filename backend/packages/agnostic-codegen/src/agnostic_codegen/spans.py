"""Field path → source span, read from the final (formatted) code so positions are exact."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Span:
    line: int
    col_start: int
    col_end: int
    end_line: int

    def as_dict(self) -> dict[str, int]:
        return {"line": self.line, "col_start": self.col_start, "col_end": self.col_end, "end_line": self.end_line}


def span_map(code: str, variable: str, element_paths: Mapping[str, list[list[str]]]) -> dict[str, Span]:
    """Spans for every keyword argument of ``variable = Cls(...)`` and for each element of list arguments.

    Lines are 1-based and columns 0-based, like :mod:`ast`. A multi-line value spans to ``end_line``.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {}
    call = _constructor(tree, variable)
    if call is None:
        return {}
    spans: dict[str, Span] = {}
    lines = code.splitlines()
    for kw in call.keywords:
        if kw.arg is None:
            continue
        spans[kw.arg] = _span(kw, lines)
        if isinstance(kw.value, ast.List):
            paths = element_paths.get(kw.arg) or [[f"{kw.arg}[{index}]"] for index in range(len(kw.value.elts))]
            for element, element_paths_ in zip(kw.value.elts, paths, strict=False):
                for path in element_paths_:
                    spans[path] = _span(element, lines)
    return spans


def _constructor(tree: ast.Module, variable: str) -> ast.Call | None:
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == variable for target in node.targets)
            and isinstance(node.value, ast.Call)
        ):
            return node.value
    return None


def _span(node: ast.AST, lines: list[str]) -> Span:
    line = getattr(node, "lineno", 1)
    end_line = getattr(node, "end_lineno", None) or line
    col_start = getattr(node, "col_offset", 0)
    if end_line == line:
        col_end = getattr(node, "end_col_offset", None) or len(lines[line - 1])
    else:
        col_end = len(lines[line - 1]) if line - 1 < len(lines) else col_start
    return Span(line=line, col_start=col_start, col_end=col_end, end_line=end_line)
