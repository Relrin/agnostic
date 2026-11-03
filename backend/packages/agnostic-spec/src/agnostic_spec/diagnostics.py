"""Findings about a config, anchored to a field path such as ``instructions[2]`` or ``tools[0]``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Severity = Literal["error", "warning", "info"]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    path: str
    severity: Severity
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "severity": self.severity, "code": self.code, "message": self.message}
