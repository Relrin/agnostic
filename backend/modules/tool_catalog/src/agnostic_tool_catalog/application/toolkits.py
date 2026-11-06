"""The Agno toolkits entries may name: the shared list, and a runtime's own list when its bridge reports one."""

from __future__ import annotations

from typing import Any

from agnostic_spec.toolkits import ToolkitList, ToolkitSpec, parse_toolkits, toolkit_list
from agnostic_tool_catalog.domain.entries import ToolkitInfo, ToolkitParamInfo


def info_of(spec: ToolkitSpec) -> ToolkitInfo:
    return ToolkitInfo(
        key=spec.key,
        label=spec.label,
        local=spec.local,
        params=tuple(
            ToolkitParamInfo(
                name=param.name, type=param.type, required=param.required, secret=param.secret, choices=param.choices
            )
            for param in spec.params
        ),
    )


class Toolkits:
    def __init__(self, toolkits: ToolkitList | None = None) -> None:
        self._list = toolkits or toolkit_list()

    def all(self) -> ToolkitList:
        return self._list

    def info(self, key: str) -> ToolkitInfo | None:
        spec = self._list.get(key)
        return info_of(spec) if spec is not None else None

    @staticmethod
    def from_runtime(body: dict[str, Any]) -> ToolkitList:
        return parse_toolkits(body)
