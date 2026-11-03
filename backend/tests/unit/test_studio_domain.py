"""Studio's rules without I/O: field diffs, change summaries, registry entries, the used-by index and promotion."""

from typing import Any

from agnostic_studio.domain.diff import counts, diff, previous_values
from agnostic_studio.domain.promotion import Reference, check
from agnostic_studio.domain.registry import Source, normalize, tool_entry
from agnostic_studio.domain.summaries import change_summary, publish_outcome
from agnostic_studio.domain.usage import Use, index

V3: dict[str, Any] = {
    "model": {"id": "mock-creative", "provider": "Agnostic"},
    "instructions": ["Classify by product area and urgency.", "Search the help center before answering."],
    "tools": [{"name": "zendesk_search"}, {"name": "kb_lookup"}],
    "num_history_runs": 3,
}
V4: dict[str, Any] = {
    "model": {"id": "mock-precise", "provider": "Agnostic"},
    "instructions": [*V3["instructions"], "Never promise refunds; use refund_customer."],
    "tools": [{"name": "zendesk_search"}, {"name": "kb_lookup"}, {"name": "refund_customer"}],
    "num_history_runs": 3,
    "markdown": True,
}


def test_list_items_diff_by_identity() -> None:
    changes = diff(V3, V4)
    assert [(change.path, change.op) for change in changes] == [
        ("model", "changed"),
        ("instructions[2]", "added"),
        ("tools[2]", "added"),
        ("markdown", "added"),
    ]
    assert counts(changes).added == 3
    assert previous_values(changes)["model"] == {"id": "mock-creative", "provider": "Agnostic"}
    reordered = diff(V4, {**V4, "tools": list(reversed(V4["tools"]))})
    assert {change.op for change in reordered} <= {"added", "removed"}


def test_change_summaries_read_like_sentences() -> None:
    assert change_summary(diff(V3, V4)) == (
        "model mock-creative → mock-precise, one new instruction, tool refund_customer added, markdown on"
    )
    assert change_summary(diff({"temperature": 0.7}, {"temperature": 0.2})) == "temperature 0.7 → 0.2"
    assert change_summary([]) == "No changes"
    assert publish_outcome(4, "prod-agentos", 3) == (
        "v4 becomes current on prod-agentos, replacing v3; the API serves it from the next request."
    )


def test_registry_entries() -> None:
    toolkit = normalize(
        {
            "name": "websearch",
            "type": "tool",
            "metadata": {
                "class_path": "agno.tools.websearch.WebSearchTools",
                "is_toolkit": True,
                "functions": [
                    {"name": "web_search", "parameters": {"type": "object"}},
                    {"name": "search_news", "requires_confirmation": True},
                ],
            },
        }
    )
    assert toolkit.meta == "agno.tools.websearch.WebSearchTools · 2 functions · @approval"
    assert [entry["toolkit"] for entry in tool_entry(toolkit)] == ["websearch", "websearch"]
    assert tool_entry(toolkit, "search_news")[0]["requires_confirmation"] is True

    discovered = normalize({"name": "create_ticket", "type": "tool", "metadata": {}}, Source(declared=False))
    assert (discovered.status, discovered.studio_available) == ("discovered", False)
    assert discovered.blurb == "Found on a component that is defined in code."
    model = normalize({"name": "m", "type": "model", "metadata": {"provider": "anthropic", "model_id": "m"}})
    assert model.meta == "provider anthropic · model_id m"
    assert model.availability.title == "Registered."


def test_used_by_index_groups_versions() -> None:
    uses = [
        Use("tool", "kb_lookup", "support-triage", "agent", "support-triage", "v4 draft"),
        Use("tool", "kb_lookup", "support-triage", "agent", "support-triage", "v3"),
        Use("tool", "kb_lookup", "kb-researcher", "agent", "kb-researcher", "code"),
    ]
    used = index(uses)[("tool", "kb_lookup")]
    assert [(item.component_id, item.versions_text) for item in used] == [
        ("kb-researcher", ""),
        ("support-triage", "v3 · v4 draft"),
    ]


def test_promotion_report() -> None:
    references = [
        Reference("model", "model", "mock-precise"),
        Reference("tools[0]", "tool", "refund_customer"),
        Reference("members[0]", "agent", "kb-researcher"),
    ]
    blocked = check(
        references, {("model", "mock-precise")}, [("kb-researcher", "agent", 8)], set(), include_children=False
    )
    assert not blocked.ok
    assert blocked.summary == (
        "Blocked: tool `refund_customer` isn't registered on the target; member `kb-researcher` doesn't exist on the "
        "target."
    )
    together = check(
        references,
        {("model", "mock-precise"), ("tool", "refund_customer")},
        [("kb-researcher", "agent", 8)],
        set(),
        include_children=True,
    )
    assert together.ok
    assert together.summary == "All 2 registry references exist on the target; 1 pinned member moves with it."
