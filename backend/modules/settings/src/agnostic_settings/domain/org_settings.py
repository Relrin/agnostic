"""Org-wide settings: a typed set of known keys with defaults. Pure Python."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from typing import Any


class InvalidSettingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OrgSettings:
    require_explicit_bindings: bool = False
    """Owners and Administrators need a binding (audited) to read runtime data, instead of implicit full access
    on every instance (06 §3.1, decision Q2)."""
    audit_log_all_reads: bool = False
    """Record every gateway read in the audit log, not a sample (regulated orgs)."""

    @classmethod
    def keys(cls) -> tuple[str, ...]:
        return tuple(f.name for f in fields(cls))

    @classmethod
    def from_values(cls, values: Mapping[str, Any]) -> OrgSettings:
        known = {key: value for key, value in values.items() if key in set(cls.keys())}
        return replace(cls(), **known)

    def updated(self, changes: Mapping[str, Any]) -> OrgSettings:
        defaults = OrgSettings()
        for key, value in changes.items():
            if key not in self.keys():
                raise InvalidSettingError(f"Unknown org setting {key!r}.")
            if type(value) is not type(getattr(defaults, key)):
                expected = type(getattr(defaults, key)).__name__
                raise InvalidSettingError(f"Org setting {key!r} must be a {expected}.")
        return replace(self, **dict(changes))

    def diff(self, other: OrgSettings) -> dict[str, dict[str, Any]]:
        return {
            key: {"before": getattr(self, key), "after": getattr(other, key)}
            for key in self.keys()
            if getattr(self, key) != getattr(other, key)
        }


ACCESS_RELEVANT = frozenset({"require_explicit_bindings"})
