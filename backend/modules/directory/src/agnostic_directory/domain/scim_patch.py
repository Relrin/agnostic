"""SCIM 2.0 PATCH (RFC 7644 §3.5.2) applied to a resource as a JSON dict.

Both forms are accepted: with a ``path`` (``active``, ``name.givenName``, ``emails[type eq "work"].value``,
``members[value eq "usr_…"]``, schema-qualified extension attributes) and without one, where ``value`` is an object
of attributes (keys may themselves be paths, as Entra ID sends them). Op names are case-insensitive (``"Replace"``).

Leniencies real IdPs rely on:

- ``remove`` on ``members`` with a ``value`` list removes those members (Entra ID);
- ``replace`` through a value filter that matches nothing adds an element built from the filter's equalities, so
  ``emails[type eq "work"].value`` works on a user without a work email (Entra ID);
- string booleans (``"False"``) are left for the caller to coerce with :func:`coerce_bool` on the fields it reads.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from agnostic_directory.domain.scim_filter import (
    And,
    AttrPath,
    Compare,
    Filter,
    PatchPath,
    ScimFilterError,
    as_mapping,
    get_key,
    matches,
    parse_attr_path,
    parse_patch_path,
)

PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
MAX_OPERATIONS = 1000

type Op = Literal["add", "replace", "remove"]
type Json = dict[str, object]


class ScimPatchError(ValueError):
    def __init__(self, message: str, scim_type: str = "invalidValue") -> None:
        super().__init__(message)
        self.scim_type = scim_type


@dataclass(frozen=True, slots=True)
class PatchOperation:
    op: Op
    path: str | None
    value: object


def parse_operations(body: Mapping[str, object]) -> list[PatchOperation]:
    raw = body.get("Operations") or body.get("operations")
    if not isinstance(raw, list) or not raw:
        raise ScimPatchError("A PATCH request needs a non-empty Operations list.", "invalidSyntax")
    items = cast("list[object]", raw)
    if len(items) > MAX_OPERATIONS:
        raise ScimPatchError(f"At most {MAX_OPERATIONS} operations per request.", "tooMany")
    operations: list[PatchOperation] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise ScimPatchError("Each operation must be an object.", "invalidSyntax")
        entry = cast("Mapping[str, object]", item)
        op = str(_ci(entry, "op") or "").strip().lower()
        if op not in {"add", "replace", "remove"}:
            raise ScimPatchError(f"Unknown PATCH op {_ci(entry, 'op')!r}.", "invalidSyntax")
        path = _ci(entry, "path")
        if path is not None and not isinstance(path, str):
            raise ScimPatchError("path must be a string.", "invalidPath")
        operations.append(PatchOperation(cast("Op", op), path or None, _ci(entry, "value")))
    return operations


def apply_patch(resource: Mapping[str, object], operations: list[PatchOperation]) -> Json:
    """A patched deep copy of ``resource``; the input stays untouched."""
    result: Json = copy.deepcopy(dict(resource))
    for operation in operations:
        _apply(result, operation)
    return result


def _apply(resource: Json, operation: PatchOperation) -> None:
    if operation.path is None:
        if operation.op == "remove":
            raise ScimPatchError("remove needs a path.", "noTarget")
        if not isinstance(operation.value, Mapping):
            raise ScimPatchError("Without a path, value must be an object of attributes.", "invalidValue")
        for key, value in cast("Mapping[str, object]", operation.value).items():
            if key.lower() == "schemas":
                continue
            fields = as_mapping(value)
            if key.lower().startswith("urn:") and fields is not None and _is_schema_urn(key):
                # {"urn:…:enterprise:2.0:User": {"department": "x"}}: an extension object.
                extension = _container(resource, key, create=True)
                assert extension is not None
                for sub_key, sub_value in fields.items():
                    _set_plain(extension, sub_key, sub_value, operation.op)
                continue
            _apply_path(resource, operation.op, _path(key), value)
        return
    _apply_path(resource, operation.op, _path(operation.path), operation.value)


def _is_schema_urn(key: str) -> bool:
    """``urn:…:2.0:User`` (a schema) rather than ``urn:…:2.0:User:department`` (an attribute)."""
    last = key.rpartition(":")[2]
    return last[:1].isupper()


def _path(text: str) -> PatchPath:
    try:
        return parse_patch_path(text)
    except ScimFilterError as exc:
        raise ScimPatchError(str(exc), "invalidPath") from exc


def _container(resource: Json, schema: str | None, *, create: bool) -> Json | None:
    if schema is None:
        return resource
    key = get_key(resource, schema)
    if key is None:
        if not create:
            return None
        resource[schema] = {}
        schemas = resource.get("schemas")
        if isinstance(schemas, list) and schema not in schemas:
            cast("list[object]", schemas).append(schema)
        key = schema
    value = resource[key]
    if not isinstance(value, dict):
        value = {}
        resource[key] = value
    return cast("Json", value)


def _apply_path(resource: Json, op: Op, path: PatchPath, value: object) -> None:  # noqa: C901
    container = _container(resource, path.attr.schema, create=op != "remove")
    if container is None:
        return
    if path.filter is not None:
        _apply_filtered(container, op, path, value)
        return
    attr = path.attr
    if attr.sub is not None:
        key = get_key(container, attr.name)
        parent = container.get(key) if key is not None else None
        if op == "remove":
            if isinstance(parent, dict):
                sub_key = get_key(cast("Json", parent), attr.sub)
                if sub_key is not None:
                    del cast("Json", parent)[sub_key]
            elif isinstance(parent, list):
                for element in cast("list[object]", parent):
                    if isinstance(element, dict):
                        sub_key = get_key(cast("Json", element), attr.sub)
                        if sub_key is not None:
                            del cast("Json", element)[sub_key]
            return
        if not isinstance(parent, dict):
            parent = {}
            container[key or attr.name] = parent
        _set_plain(cast("Json", parent), attr.sub, value, op)
        return
    if op == "remove":
        _remove(container, attr.name, value)
        return
    _set_plain(container, attr.name, value, op)


def _set_plain(container: Json, name: str, value: object, op: Op) -> None:  # noqa: C901
    """Set ``container[name]`` (case-insensitively): ``add`` appends to lists and merges objects."""
    if "." in name and not name.lower().startswith("urn:"):
        # A dotted key in a value object ({"name.givenName": "x"}).
        head, _, sub = name.partition(".")
        key = get_key(container, head)
        parent = container.get(key) if key is not None else None
        if not isinstance(parent, dict):
            parent = {}
            container[key or head] = parent
        _set_plain(cast("Json", parent), sub, value, op)
        return
    if name.lower().startswith("urn:"):
        attr = _attr(name)
        target = _container(container, attr.schema, create=True)
        assert target is not None
        _set_plain(target, f"{attr.name}.{attr.sub}" if attr.sub else attr.name, value, op)
        return
    key = get_key(container, name) or name
    current = container.get(key)
    if op == "add" and isinstance(current, list):
        items = cast("list[object]", current)
        for item in cast("list[object]", value) if isinstance(value, list) else [value]:
            if item not in items and not _same_value(items, item):
                items.append(item)
        return
    if op == "add" and isinstance(current, dict) and isinstance(value, Mapping):
        for sub_key, sub_value in cast("Mapping[str, object]", value).items():
            _set_plain(cast("Json", current), sub_key, sub_value, op)
        return
    if op == "replace" and isinstance(current, dict) and isinstance(value, Mapping):
        merged = cast("Json", current)
        for sub_key, sub_value in cast("Mapping[str, object]", value).items():
            merged[get_key(merged, sub_key) or sub_key] = copy.deepcopy(sub_value)
        return
    container[key] = copy.deepcopy(value)


def _same_value(items: list[object], item: object) -> bool:
    """Multi-valued complex attributes are sets keyed by ``value`` (members, emails)."""
    if not isinstance(item, Mapping):
        return False
    wanted = _ci(cast("Mapping[str, object]", item), "value")
    if wanted is None:
        return False
    return any(
        isinstance(existing, Mapping) and _ci(cast("Mapping[str, object]", existing), "value") == wanted
        for existing in items
    )


def _attr(name: str) -> AttrPath:
    try:
        return parse_attr_path(name)
    except ScimFilterError as exc:
        raise ScimPatchError(str(exc), "invalidPath") from exc


def _remove(container: Json, name: str, value: object) -> None:
    key = get_key(container, name)
    if key is None:
        return
    current = container[key]
    if isinstance(current, list) and value is not None:
        # Entra ID: {"op": "Remove", "path": "members", "value": [{"value": "usr_…"}]}.
        doomed = cast("list[object]", value) if isinstance(value, list) else [value]
        ids = {
            _ci(cast("Mapping[str, object]", item), "value") if isinstance(item, Mapping) else item for item in doomed
        }
        container[key] = [
            element
            for element in cast("list[object]", current)
            if (_ci(cast("Mapping[str, object]", element), "value") if isinstance(element, Mapping) else element)
            not in ids
        ]
        return
    del container[key]


def _apply_filtered(container: Json, op: Op, path: PatchPath, value: object) -> None:  # noqa: C901
    assert path.filter is not None
    key = get_key(container, path.attr.name)
    current = container.get(key) if key is not None else None
    elements = cast("list[object]", current) if isinstance(current, list) else []
    matched: list[object] = [
        element
        for element in elements
        if isinstance(element, dict) and matches(path.filter, cast("Mapping[str, object]", element))
    ]
    fields = as_mapping(value)
    if op == "remove":
        if path.sub is None:
            container[key or path.attr.name] = [element for element in elements if element not in matched]
        else:
            for element in matched:
                sub_key = get_key(cast("Json", element), path.sub)
                if sub_key is not None:
                    del cast("Json", element)[sub_key]
        return
    if not matched:
        seed = _seed(path.filter)
        if seed is None:
            raise ScimPatchError(f"Nothing matches {path.attr.name}[…].", "noTarget")
        elements.append(seed)
        container[key or path.attr.name] = elements
        matched = [seed]
    for element in matched:
        target = cast("Json", element)
        if path.sub is not None:
            target[get_key(target, path.sub) or path.sub] = copy.deepcopy(value)
        elif fields is not None:
            for sub_key, sub_value in fields.items():
                target[get_key(target, sub_key) or sub_key] = copy.deepcopy(sub_value)
        else:
            raise ScimPatchError(f"{path.attr.name}[…] needs an object value.", "invalidValue")


def _seed(node: Filter) -> Json | None:
    """``type eq "work"`` → ``{"type": "work"}``: the element a filtered ``add``/``replace`` creates."""
    if isinstance(node, Compare) and node.op == "eq" and node.path.sub is None and node.path.schema is None:
        return {node.path.name: node.value}
    if isinstance(node, And):
        left, right = _seed(node.left), _seed(node.right)
        if left is not None and right is not None:
            return {**left, **right}
    return None


def _ci(mapping: Mapping[str, object], name: str) -> object:
    key = get_key(mapping, name)
    return mapping[key] if key is not None else None
