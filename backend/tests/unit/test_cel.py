"""agnostic_cel: the parser, the checker per workflow context (types, router exhaustiveness) and the evaluator."""

from __future__ import annotations

import pytest

from agnostic_cel import (
    CelEvalError,
    CelSyntaxError,
    Conditional,
    Uint,
    activation,
    check,
    describe,
    evaluate,
    parse,
    ternary_chain,
)

ROUTE_BY_CATEGORY = (
    'input.contains("refund") || input.contains("invoice") ? "Billing"'
    ' : previous_step_content.contains("BUG") ? "Investigate"'
    ' : "Draft & review"'
)
CHOICES = ["Billing", "Investigate", "Draft & review"]

# Expressions from agno's docs and examples, each with the context it belongs to.
AGNO_CORPUS = [
    ("condition", 'input.contains("urgent")'),
    ("condition", "session_state.retry_count < 3"),
    ("condition", "additional_data.priority > 5"),
    ("condition", 'previous_step_outputs.research.contains("error")'),
    ("condition", 'previous_step_content.contains("ESCALATE")'),
    ("condition", 'has(session_state.plan) && session_state.plan == "pro"'),
    ("condition", "size(previous_step_outputs) > 0"),
    ("router", 'input.contains("video") ? "video_step" : "image_step"'),
    ("router", "additional_data.route"),
    ("router", 'previous_step_outputs.classifier.contains("billing") ? "Billing" : "Support"'),
    ("router", ROUTE_BY_CATEGORY),
    ("loop", 'last_step_content.contains("APPROVED")'),
    ("loop", "current_iteration >= max_iterations || all_success"),
    ("loop", 'step_outputs.size() >= 2 && step_outputs.exists(name, step_outputs[name].contains("done"))'),
]


@pytest.mark.parametrize(("context", "expression"), AGNO_CORPUS)
def test_agno_corpus_parses_and_type_checks(context: str, expression: str) -> None:
    result = check(expression, context)  # pyright: ignore[reportArgumentType]
    assert result.ok, result.findings


def test_parser_spans_and_precedence() -> None:
    tree = parse('a || b && c ? "x" : "y"')
    assert isinstance(tree, Conditional)
    assert (tree.span.start, tree.span.end) == (0, 23)
    chain = ternary_chain(parse(ROUTE_BY_CATEGORY))
    assert len(chain) == 3
    assert ROUTE_BY_CATEGORY[chain[1].span.start : chain[1].span.end].startswith("previous_step_content")


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("", "empty"),
        ('input.contains("x"', r"Expected `\)`"),
        ("a ? b", "Expected `:`"),
        ('"never closed', "never closed"),
        ("for", "reserved"),
        ("a @ b", "Unexpected character"),
        ("has(a)", "has"),
        ("list.all(1, true)", "names a variable"),
    ],
)
def test_syntax_errors_are_located(source: str, message: str) -> None:
    with pytest.raises(CelSyntaxError, match=message) as caught:
        parse(source)
    assert caught.value.span is not None


def test_literals() -> None:
    assert evaluate(r'"tab\there" + r"\n" + "é"', {}) == "tab\there\\né"
    assert evaluate("0x1F + 1", {}) == 32
    assert evaluate("3u + 4u", {}) == Uint(7)
    assert evaluate("1.5e1", {}) == 15.0
    assert evaluate("-2 * 3", {}) == -6
    assert evaluate("'''multi\nline'''", {}) == "multi\nline"
    assert evaluate('b"ab"', {}) == b"ab"
    assert evaluate("[1, 2][1] == 2 && {'k': true}.k", {}) is True


def test_router_exhaustiveness() -> None:
    result = check(ROUTE_BY_CATEGORY, "router", choices=CHOICES)
    assert result.ok
    assert result.exhaustive is True
    assert result.results == ("Billing", "Investigate", "Draft & review")
    assert result.summary == "Returns string · every result matches a choice"

    missing = check('input.contains("refund") ? "Refund" : "Billing"', "router", choices=CHOICES)
    assert not missing.ok
    assert missing.exhaustive is False
    unknown = next(finding for finding in missing.findings if finding.code == "router_unknown_choice")
    assert "`Refund` isn't a choice" in unknown.message
    assert (unknown.span.start, unknown.span.end) == (27, 35)
    assert any(finding.code == "router_choice_unused" for finding in missing.findings)

    unproven = check("additional_data.route", "router", choices=CHOICES)
    assert unproven.ok
    assert unproven.exhaustive is None
    assert unproven.summary == "Returns dyn · can't prove every result matches a choice"


@pytest.mark.parametrize(
    ("context", "expression", "code"),
    [
        ("condition", 'input + "x"', "result_type"),
        ("condition", "unknown_name", "unknown_variable"),
        ("condition", "step_choices", "unknown_variable"),
        ("router", "input.size() > 1", "result_type"),
        ("condition", "input.contains(1)", "no_overload"),
        ("condition", "input.nope()", "unknown_function"),
        ("condition", "input.field == 1", "select_operand"),
        ("condition", "1 + 1.0 > 0", "no_overload"),
        ("condition", "!input", "no_overload"),
        ("condition", "input ? true : false", "condition_type"),
        ("loop", "current_iteration > 1 && last_step_content", "no_overload"),
    ],
)
def test_type_errors(context: str, expression: str, code: str) -> None:
    result = check(expression, context)  # pyright: ignore[reportArgumentType]
    assert code in {finding.code for finding in result.findings}, result.findings
    assert not result.ok


def test_dynamic_values_check_with_a_note() -> None:
    result = check("session_state.flag", "condition")
    assert result.ok
    assert [finding.code for finding in result.findings] == ["result_unknown"]
    assert check("1 + 2 == 3", "condition").summary == "Returns bool"


def test_evaluates_the_prototype_selector() -> None:
    variables = activation("router", {"input": "I was charged twice, need a refund"}, choices=CHOICES)
    assert evaluate(ROUTE_BY_CATEGORY, variables) == "Billing"
    variables = activation("router", {"input": "hi", "previous_step_content": "BUG: 502"}, choices=CHOICES)
    assert evaluate(ROUTE_BY_CATEGORY, variables) == "Investigate"
    assert evaluate(ROUTE_BY_CATEGORY, activation("router", {}, choices=CHOICES)) == "Draft & review"
    assert evaluate("step_choices.size()", variables) == 3


def test_activation_mirrors_agno() -> None:
    values = activation("condition", {"previous_step_content": {"a": 1}, "previous_step_outputs": {"x": 2}})
    assert values == {
        "input": "",
        "previous_step_content": '{"a": 1}',
        "previous_step_outputs": {"x": "2"},
        "additional_data": {},
        "session_state": {},
    }
    loop = activation("loop", {"last_step_content": "APPROVED"})
    assert loop["max_iterations"] == 3
    assert loop["step_outputs"] == {}
    assert evaluate('last_step_content.contains("APPROVED")', loop) is True


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("[1, 2, 3].all(x, x > 0)", True),
        ("[1, 2, 3].exists(x, x > 2)", True),
        ("[1, 2, 3].exists_one(x, x > 1)", False),
        ("[1, 2, 3].map(x, x * 2)", [2, 4, 6]),
        ("[1, 2, 3].map(x, x > 1, x * 10)", [20, 30]),
        ("[1, 2, 3].filter(x, x != 2)", [1, 3]),
        ("{'a': 1, 'b': 2}.all(k, k in ['a', 'b'])", True),
        ('"abc".matches("^a.c$") && matches("xyz", "y")', True),
        ('"héllo".size() == 5 && size([1]) == 1', True),
        ("int('7') + 1 == 8 && double(1) == 1.0 && string(true) == 'true'", True),
        ("7 / 2 == 3 && -7 / 2 == -3 && -7 % 3 == -1", True),
        ("1 == 1.0", True),
        ("true == 1", False),
        ("2 in [1, 2] && 'k' in {'k': 0}", True),
        ("false && (1 / 0 == 1)", False),
        ("(1 / 0 == 1) || true", True),
        ('"a" < "b" && 1u < 2u && 1 < 2.5', True),
        ("[1] + [2] == [1, 2]", True),
    ],
)
def test_evaluation(expression: str, expected: object) -> None:
    assert evaluate(expression, {}) == expected


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        ("missing", "undeclared reference"),
        ("{'a': 1}.b", "no such key"),
        ("1 / 0", "division by zero"),
        ("1 + 1.0", "no matching overload"),
        ("9223372036854775807 + 1", "overflow"),
        ("[1][5]", "out of range"),
        ('"x" ? 1 : 2', "no matching overload"),
        ("[0].map(x, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(y, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(z, z)))", ""),
    ],
)
def test_evaluation_errors(expression: str, message: str) -> None:
    if not message:
        assert evaluate(expression, {}) is not None
        return
    with pytest.raises(CelEvalError, match=message):
        evaluate(expression, {})


def test_the_step_budget_stops_runaway_work() -> None:
    big = "[" + ", ".join(["1"] * 200) + "]"
    with pytest.raises(CelEvalError, match="too much work"):
        evaluate(f"{big}.map(a, {big}.map(b, a + b))", {})


def test_describe_lists_what_the_editor_completes() -> None:
    described = describe()
    router = described["contexts"]["router"]
    assert router["result"] == "string"
    assert [variable["name"] for variable in router["variables"]][-1] == "step_choices"
    assert {function["name"] for function in described["functions"]} >= {"contains", "size", "matches"}
    assert {macro["name"] for macro in described["macros"]} == {"has", "all", "exists", "exists_one", "map", "filter"}
