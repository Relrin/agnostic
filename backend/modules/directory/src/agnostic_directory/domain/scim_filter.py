"""SCIM 2.0 filters (RFC 7644 §3.4.2.2) and attribute paths, evaluated against resources as JSON dicts.

Supported: ``eq ne co sw ew gt ge lt le pr``, ``and``/``or``/``not``, parentheses, sub-attributes (``name.givenName``),
schema-qualified names (``urn:…:enterprise:2.0:User:employeeNumber``) and value filters on multi-valued attributes
(``emails[type eq "work"].value``, ``members[value eq "usr_…"]``). Attribute names and string comparisons are
case-insensitive, except ``id`` and ``externalId``, which compare exactly.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import cast

CORE_SCHEMAS = frozenset(
    {
        "urn:ietf:params:scim:schemas:core:2.0:user",
        "urn:ietf:params:scim:schemas:core:2.0:group",
    }
)
CASE_EXACT = frozenset({"id", "externalid"})
COMPARE_OPS = frozenset({"eq", "ne", "co", "sw", "ew", "gt", "ge", "lt", "le"})
MAX_FILTER = 4096

type Scalar = str | bool | int | float | None


class ScimFilterError(ValueError):
    """The filter (or attribute path) can't be parsed; answered with ``scimType: invalidFilter``."""


@dataclass(frozen=True, slots=True)
class AttrPath:
    """``[schema:]name[.sub]``; ``schema`` is ``None`` for the resource's core schema."""

    name: str
    sub: str | None = None
    schema: str | None = None

    def __str__(self) -> str:
        text = f"{self.name}.{self.sub}" if self.sub else self.name
        return f"{self.schema}:{text}" if self.schema else text


@dataclass(frozen=True, slots=True)
class Compare:
    path: AttrPath
    op: str
    value: Scalar


@dataclass(frozen=True, slots=True)
class Present:
    path: AttrPath


@dataclass(frozen=True, slots=True)
class And:
    left: Filter
    right: Filter


@dataclass(frozen=True, slots=True)
class Or:
    left: Filter
    right: Filter


@dataclass(frozen=True, slots=True)
class Not:
    inner: Filter


@dataclass(frozen=True, slots=True)
class ValuePath:
    """``emails[type eq "work"]``: some element of the multi-valued attribute matches ``filter``."""

    path: AttrPath
    filter: Filter


type Filter = Compare | Present | And | Or | Not | ValuePath


def parse_attr_path(text: str) -> AttrPath:
    """``name.givenName`` or ``urn:…:User:manager.value``; a core-schema prefix is dropped."""
    raw = text.strip()
    schema: str | None = None
    if raw.lower().startswith("urn:"):
        schema, _, raw = raw.rpartition(":")
        if not raw or not schema:
            raise ScimFilterError(f"{text!r} is not an attribute path.")
        if schema.lower() in CORE_SCHEMAS:
            schema = None
    name, _, sub = raw.partition(".")
    if not _NAME.fullmatch(name) or (sub and not _NAME.fullmatch(sub)):
        raise ScimFilterError(f"{text!r} is not an attribute path.")
    return AttrPath(name=name, sub=sub or None, schema=schema)


_NAME = re.compile(r"[A-Za-z$][\w$-]*")
_TOKEN = re.compile(
    r"""
    (?P<space>\s+)
    | (?P<string>"(?:[^"\\]|\\.)*")
    | (?P<punct>[()\[\]])
    | (?P<sub>\.[A-Za-z$][\w$-]*)
    | (?P<number>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?(?![\w:.]))
    | (?P<word>(?:urn:[\w.:-]+:)?[A-Za-z$][\w$-]*(?:\.[A-Za-z$][\w$-]*)?)
    """,
    re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str
    text: str
    value: Scalar = None


def _tokens(text: str) -> list[_Token]:
    if len(text) > MAX_FILTER:
        raise ScimFilterError(f"Filters are limited to {MAX_FILTER} characters.")
    tokens: list[_Token] = []
    position = 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None:
            raise ScimFilterError(f"Unexpected {text[position : position + 20]!r} in the filter.")
        position = match.end()
        kind = match.lastgroup or ""
        chunk = match.group()
        if kind == "space":
            continue
        if kind == "string":
            try:
                tokens.append(_Token("value", chunk, cast("str", json.loads(chunk))))
            except ValueError as exc:
                raise ScimFilterError(f"{chunk} is not a valid string.") from exc
        elif kind == "number":
            number: int | float = float(chunk) if any(c in chunk for c in ".eE") else int(chunk)
            tokens.append(_Token("value", chunk, number))
        elif kind == "word" and chunk.lower() in {"true", "false", "null"}:
            literal = {"true": True, "false": False, "null": None}[chunk.lower()]
            tokens.append(_Token("value", chunk, literal))
        else:
            tokens.append(_Token(kind, chunk))
    return tokens


class _Parser:
    def __init__(self, text: str) -> None:
        self.tokens = _tokens(text)
        self.at = 0

    def peek(self) -> _Token | None:
        return self.tokens[self.at] if self.at < len(self.tokens) else None

    def keyword(self, *words: str) -> str | None:
        token = self.peek()
        if token is not None and token.kind == "word" and token.text.lower() in words:
            self.at += 1
            return token.text.lower()
        return None

    def expect(self, kind: str, text: str | None = None) -> _Token:
        token = self.peek()
        if token is None or token.kind != kind or (text is not None and token.text != text):
            found = token.text if token else "the end"
            raise ScimFilterError(f"Expected {text or kind} but found {found!r}.")
        self.at += 1
        return token

    def parse(self) -> Filter:
        result = self.disjunction()
        if self.peek() is not None:
            raise ScimFilterError(f"Unexpected {self.tokens[self.at].text!r} in the filter.")
        return result

    def disjunction(self) -> Filter:
        result = self.conjunction()
        while self.keyword("or"):
            result = Or(result, self.conjunction())
        return result

    def conjunction(self) -> Filter:
        result = self.unary()
        while self.keyword("and"):
            result = And(result, self.unary())
        return result

    def unary(self) -> Filter:
        if self.keyword("not"):
            return Not(self.unary())
        token = self.peek()
        if token is not None and token.kind == "punct" and token.text == "(":
            self.at += 1
            inner = self.disjunction()
            _ = self.expect("punct", ")")
            return inner
        return self.attribute_expression()

    def attribute_expression(self) -> Filter:
        token = self.expect("word")
        path = parse_attr_path(token.text)
        following = self.peek()
        if following is not None and following.kind == "punct" and following.text == "[":
            self.at += 1
            inner = self.disjunction()
            _ = self.expect("punct", "]")
            then = self.peek()
            if then is not None and then.kind == "sub":
                # emails[type eq "work"].value eq "x": the element must also satisfy the trailing comparison.
                self.at += 1
                inner = And(inner, self.comparison(AttrPath(name=then.text[1:])))
            return ValuePath(path, inner)
        return self.comparison(path)

    def comparison(self, path: AttrPath) -> Filter:
        if self.keyword("pr"):
            return Present(path)
        op = self.keyword(*COMPARE_OPS)
        if op is None:
            found = self.peek()
            raise ScimFilterError(
                f"Expected an operator after {path} but found {found.text if found else 'the end'!r}."
            )
        value = self.expect("value")
        return Compare(path, op, value.value)


def parse_filter(text: str) -> Filter:
    if not text.strip():
        raise ScimFilterError("The filter is empty.")
    return _Parser(text).parse()


@dataclass(frozen=True, slots=True)
class PatchPath:
    """A PATCH target: ``attr``, ``attr.sub``, ``attr[filter]`` or ``attr[filter].sub``."""

    attr: AttrPath
    filter: Filter | None = None
    sub: str | None = None


def parse_patch_path(text: str) -> PatchPath:
    raw = text.strip()
    if "[" not in raw:
        return PatchPath(parse_attr_path(raw))
    head, _, rest = raw.partition("[")
    body, closing, tail = rest.rpartition("]")
    if not closing:
        raise ScimFilterError(f"{text!r} has an unclosed '['.")
    attr = parse_attr_path(head)
    if attr.sub is not None:
        raise ScimFilterError(f"{text!r}: a value filter applies to a multi-valued attribute.")
    sub: str | None = None
    if tail:
        if not tail.startswith(".") or not _NAME.fullmatch(tail[1:]):
            raise ScimFilterError(f"{text!r} is not a valid path.")
        sub = tail[1:]
    return PatchPath(attr=attr, filter=parse_filter(body), sub=sub)


def as_mapping(value: object) -> Mapping[str, object] | None:
    """``value`` as a JSON object, or ``None`` when it isn't one."""
    return cast("Mapping[str, object]", value) if isinstance(value, Mapping) else None


def get_key(container: Mapping[str, object], name: str) -> str | None:
    """The key of ``container`` that matches ``name`` case-insensitively."""
    if name in container:
        return name
    lowered = name.lower()
    return next((key for key in container if key.lower() == lowered), None)


def get_value(container: Mapping[str, object], name: str) -> object:
    key = get_key(container, name)
    return container[key] if key is not None else None


def schema_container(resource: Mapping[str, object], schema: str | None) -> Mapping[str, object] | None:
    if schema is None:
        return resource
    extension = get_value(resource, schema)
    return cast("Mapping[str, object]", extension) if isinstance(extension, Mapping) else None


def resolve(resource: Mapping[str, object], path: AttrPath) -> list[object]:
    """Every value at ``path``: one for single-valued attributes, the elements (or their ``sub``) otherwise.

    A multi-valued complex attribute without a sub-attribute compares on its elements' ``value``.
    """
    container = schema_container(resource, path.schema)
    if container is None:
        return []
    value = get_value(container, path.name)
    found: list[object] = []
    for item in _flatten(value):
        mapping = as_mapping(item)
        if path.sub is None:
            found.append(get_value(mapping, "value") if mapping is not None and isinstance(value, list) else item)
        elif mapping is not None:
            found.extend(_flatten(get_value(mapping, path.sub)))
    return [item for item in found if item is not None]


def _flatten(value: object) -> Iterator[object]:
    if isinstance(value, list):
        yield from cast("list[object]", value)
    elif value is not None:
        yield value


def matches(node: Filter, resource: Mapping[str, object]) -> bool:  # noqa: PLR0911
    match node:
        case And(left, right):
            return matches(left, resource) and matches(right, resource)
        case Or(left, right):
            return matches(left, resource) or matches(right, resource)
        case Not(inner):
            return not matches(inner, resource)
        case Present(path):
            return any(_present(value) for value in resolve(resource, path))
        case ValuePath(path, inner):
            container = schema_container(resource, path.schema)
            elements = get_value(container, path.name) if container is not None else None
            return any(
                isinstance(element, Mapping) and matches(inner, cast("Mapping[str, object]", element))
                for element in _flatten(elements)
            )
        case Compare(path, op, expected):
            values = resolve(resource, path)
            exact = path.sub is None and path.schema is None and path.name.lower() in CASE_EXACT
            if op == "ne":
                return not any(_compare(value, "eq", expected, exact=exact) for value in values)
            return any(_compare(value, op, expected, exact=exact) for value in values)


def _present(value: object) -> bool:
    return value not in ("", [], {}) and value is not None


def _compare(actual: object, op: str, expected: Scalar, *, exact: bool) -> bool:  # noqa: C901, PLR0911, PLR0912
    if expected is None:
        return op == "eq" and actual is None
    if isinstance(expected, bool) or isinstance(actual, bool):
        actual_bool = coerce_bool(actual)
        return op == "eq" and actual_bool is not None and actual_bool == coerce_bool(expected)
    if isinstance(expected, int | float):
        if not isinstance(actual, int | float):
            try:
                actual = float(str(actual))
            except ValueError:
                return False
        number = float(actual)
        return {
            "eq": number == expected,
            "gt": number > expected,
            "ge": number >= expected,
            "lt": number < expected,
            "le": number <= expected,
        }.get(op, False)
    if isinstance(actual, Mapping | list):
        return False
    left, right = str(actual), expected
    if not exact:
        left, right = left.lower(), right.lower()
    if op == "eq":
        return left == right
    if op == "co":
        return right in left
    if op == "sw":
        return left.startswith(right)
    if op == "ew":
        return left.endswith(right)
    if op == "gt":
        return left > right
    if op == "ge":
        return left >= right
    if op == "lt":
        return left < right
    if op == "le":
        return left <= right
    return False


def coerce_bool(value: object) -> bool | None:
    """``True``/``"True"``/``"true"`` → ``True``: Entra ID sends booleans as strings in PATCH requests."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    return None


def equality(node: Filter) -> tuple[str, str] | None:
    """``(attribute, value)`` for a plain ``attr eq "value"`` filter on a top-level attribute (an index lookup)."""
    if isinstance(node, Compare) and node.op == "eq" and isinstance(node.value, str) and node.path.schema is None:
        if node.path.sub is None:
            return node.path.name.lower(), node.value
        if node.path.name.lower() == "emails" and node.path.sub.lower() == "value":
            return "emails.value", node.value
    if isinstance(node, ValuePath) and node.path.name.lower() == "emails" and isinstance(node.filter, And):
        # emails[type eq "work"].value eq "x"
        right = node.filter.right
        if (
            isinstance(right, Compare)
            and right.op == "eq"
            and isinstance(right.value, str)
            and right.path.name.lower() == "value"
        ):
            return "emails.value", right.value
    return None
