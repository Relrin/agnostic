"""Three-way merge of config documents: one-sided changes merge, same-field edits conflict at their field path."""

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from agnostic_sources.domain.merge import MISSING, apply_resolutions, changed_paths, get_at, set_at, three_way

BASE: dict[str, Any] = {
    "id": "billing-agent",
    "name": "Billing Agent",
    "description": "Answers billing questions.",
    "instructions": ["Be brief.", "Quote the invoice number.", "Refunds over $100 need a manager."],
    "tools": [{"name": "lookup_invoice"}],
}


def test_non_overlapping_edits_merge_without_conflicts() -> None:
    ours = {**BASE, "description": "Answers billing and refund questions."}
    theirs = {**BASE, "instructions": [*BASE["instructions"], "Never promise dates."]}
    result = three_way(BASE, ours, theirs)
    assert result.clean
    assert result.merged["description"] == "Answers billing and refund questions."
    assert result.merged["instructions"][-1] == "Never promise dates."
    assert result.auto_merged == ["description"]


def test_the_same_instruction_edited_on_both_sides_conflicts_at_its_index() -> None:
    ours = {**BASE, "instructions": [*BASE["instructions"][:2], "Refunds over $150 need a manager."]}
    theirs = {
        **BASE,
        "description": "Billing.",
        "instructions": [*BASE["instructions"][:2], "Refunds over $200 need a manager."],
    }
    result = three_way(BASE, ours, theirs)
    assert [conflict.path for conflict in result.conflicts] == ["instructions[2]"]
    conflict = result.conflicts[0]
    assert (conflict.ours, conflict.theirs) == (
        "Refunds over $150 need a manager.",
        "Refunds over $200 need a manager.",
    )
    assert result.merged["description"] == "Billing."
    resolved = apply_resolutions(result.merged, {"instructions[2]": conflict.theirs})
    assert resolved["instructions"][2] == "Refunds over $200 need a manager."


def test_one_side_appends_while_the_other_edits_the_first_instruction() -> None:
    ours = {**BASE, "instructions": ["Be very brief.", *BASE["instructions"][1:]]}
    theirs = {**BASE, "instructions": [*BASE["instructions"], "Sign with the team name."]}
    result = three_way(BASE, ours, theirs)
    assert result.clean
    assert result.merged["instructions"] == ["Be very brief.", *BASE["instructions"][1:], "Sign with the team name."]


def test_scalars_and_removed_fields() -> None:
    assert [item.path for item in three_way({"a": 1}, {"a": 2}, {"a": 3}).conflicts] == ["a"]
    assert three_way({"a": 1}, {"a": 2}, {"a": 2}).merged == {"a": 2}
    removed = three_way({"a": 1, "b": 1}, {"b": 1}, {"a": 1, "b": 2})
    assert removed.clean
    assert removed.merged == {"b": 2}
    delete_vs_edit = three_way({"a": 1}, {}, {"a": 5})
    assert [item.path for item in delete_vs_edit.conflicts] == ["a"]
    assert delete_vs_edit.conflicts[0].ours is MISSING


def test_workflow_steps_align_by_name() -> None:
    base = {"steps": [{"name": "classify", "agent_id": "a"}, {"name": "route", "selector": "input"}]}
    ours = {"steps": [{"name": "route", "selector": "input"}, {"name": "classify", "agent_id": "a"}]}
    theirs = {"steps": [{"name": "classify", "agent_id": "a"}, {"name": "route", "selector": "input.category"}]}
    result = three_way(base, ours, theirs)
    assert result.clean
    assert result.merged["steps"] == [
        {"name": "route", "selector": "input.category"},
        {"name": "classify", "agent_id": "a"},
    ]
    clash = three_way(base, {"steps": [base["steps"][0], {"name": "route", "selector": "x"}]}, theirs)
    assert [item.path for item in clash.conflicts] == ["steps[1].selector"]


def test_paths() -> None:
    document = {"steps": [{"name": "a", "choices": [{"name": "b"}]}]}
    assert get_at(document, "steps[0].choices[0].name") == "b"
    assert get_at(document, "steps[3]") is MISSING
    assert set_at(document, "steps[0].choices[0].name", "c")["steps"][0]["choices"][0]["name"] == "c"
    assert set_at({"a": 1}, "a", MISSING) == {}
    assert changed_paths(BASE, {**BASE, "name": "Billing"}) == ["name"]


values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=5),
    lambda children: st.lists(children, max_size=3) | st.dictionaries(st.text(max_size=3), children, max_size=3),
    max_leaves=10,
)
documents = st.dictionaries(st.sampled_from(["a", "b", "c", "instructions"]), values, max_size=4)


@given(documents, documents)
def test_merge_identities(base: dict[str, Any], side: dict[str, Any]) -> None:
    assert three_way(base, side, base).merged == side
    assert three_way(base, base, side).merged == side
    assert three_way(base, side, side).merged == side
