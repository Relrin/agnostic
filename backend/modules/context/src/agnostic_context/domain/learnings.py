"""Learning store types and how their record ids are made (the Learnings page's id explainer)."""

from __future__ import annotations

from collections.abc import Mapping

LEARNING_TYPES: tuple[str, ...] = (
    "user_profile",
    "user_memory",
    "session_context",
    "entity_memory",
    "decision_log",
)
"""Types stored in the learnings table. ``learned_knowledge`` lives in a knowledge base instead."""

ID_SCHEMES: Mapping[str, str] = {
    "user_profile": "Deterministic id: user_profile_{user_id}",
    "user_memory": "Deterministic id: memories_{user_id}",
    "session_context": "One record per session",
    "entity_memory": "Generated id · keyed by entity_type and entity_id",
    "decision_log": "Generated id · many per user",
}


def deletion_scope(learning_type: str | None) -> str:
    """The audit wording: "all learning types", or the one type."""
    return learning_type or "all learning types"


def confirmed(user_id: str, confirmation: str) -> bool:
    """Type-to-confirm: the exact user id, ignoring surrounding spaces."""
    return bool(user_id) and confirmation.strip() == user_id
