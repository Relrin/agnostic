"""Form edits applied to existing code, keeping everything a person wrote around them.

The code is read (:func:`read_source`), the edited config is compared with what the code says field by field, and
only the arguments that changed are rewritten: a value replaced in place, a keyword inserted where the generator
would put it or removed, list items added or dropped while the untouched items (and their comments) stay. A step
tree is compared node by node; a node whose type changed is written anew. Edits reach through module-level names,
so changing a hoisted Parallel's branches edits ``investigate = Parallel(...)``. The result is read again and must
say exactly the edited config, or the edit is reported as not equivalent.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

import libcst as cst
from libcst.codemod import CodemodContext
from libcst.codemod.visitors import AddImportsVisitor, RemoveImportsVisitor
from libcst.metadata import CodeRange, MetadataWrapper, PositionProvider

from agnostic_codegen.convention import RegistryConvention, snake
from agnostic_codegen.generate import INDENT, Imports, field_order, render_literal, string_literal
from agnostic_codegen.parse import (
    STEP_EXECUTORS,
    CodeDiagnostic,
    Reading,
    Resolver,
    owned_paths,
    read_source,
)
from agnostic_codegen.spans import Span
from agnostic_codegen.workflow import DERIVED, NodeWriter, node_order, omitted, segments
from agnostic_spec.v3_1 import Kind, ModelRef, WorkflowConfig, parse, shape_errors
from agnostic_spec.v3_1.refs import learning_name, schema_name
from agnostic_spec.v3_1.refs_index import MODEL_FIELDS

LANES = ("steps", "else_steps", "choices")
NAMED_REFS: Mapping[str, str] = {"knowledge": "knowledge", "memory_manager": "memory_manager", "learning": "learning"}
CONFIG_KEYWORDS: Mapping[str, str] = {key: keyword for keyword, (key, _) in STEP_EXECUTORS.items()}


@dataclass(slots=True)
class Transformed:
    code: str
    config: dict[str, Any] | None
    diagnostics: list[CodeDiagnostic] = field(default_factory=list[CodeDiagnostic])
    spans: dict[str, Span] = field(default_factory=dict[str, Span])
    code_owned: list[str] = field(default_factory=list[str])
    equivalent: bool = False
    """Whether the new code reads back as exactly the edited config."""
    changed: list[str] = field(default_factory=list[str])
    """Config paths whose code was rewritten."""


class _Refused(Exception):  # noqa: N818
    def __init__(self, message: str, path: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.path = path


def transform(
    code: str,
    after: dict[str, Any],
    *,
    kind: Kind,
    component_id: str | None = None,
    convention: RegistryConvention | None = None,
    resolver: Resolver | None = None,
) -> Transformed:
    convention = convention or RegistryConvention()
    reading = read_source(code, kind=kind, component_id=component_id, convention=convention, resolver=resolver)
    parsed = reading.parsed
    if parsed.config is None or reading.module is None or reading.component is None:
        return Transformed(code, None, parsed.diagnostics, parsed.spans, parsed.code_owned)
    problems = shape_errors(kind, after)
    if problems:
        diagnostics = [CodeDiagnostic("error", item.code, item.message, 1, 0, 1, 0, item.path) for item in problems]
        return Transformed(code, parsed.config, diagnostics, parsed.spans, parsed.code_owned)
    target = parse(kind, after).dump()
    if target == parsed.config:
        return Transformed(code, target, parsed.diagnostics, parsed.spans, parsed.code_owned, equivalent=True)

    planner = _Planner(reading, kind, convention)
    try:
        planner.plan(parsed.config, target)
    except _Refused as refusal:
        diagnostic = CodeDiagnostic("error", "transform_refused", refusal.message, 1, 0, 1, 0, refusal.path)
        return Transformed(code, parsed.config, [*parsed.diagnostics, diagnostic], parsed.spans, parsed.code_owned)
    module = planner.apply()
    new_code = module.code
    again = read_source(new_code, kind=kind, component_id=component_id, convention=convention, resolver=resolver)
    result = again.parsed
    equivalent = result.config == target
    diagnostics = list(result.diagnostics)
    if not equivalent:
        differing = sorted(
            key for key in set(target) | set(result.config or {}) if (result.config or {}).get(key) != target.get(key)
        )
        diagnostics.append(
            CodeDiagnostic(
                "error",
                "transform_not_equivalent",
                f"The edited code doesn't read back as the form's config ({', '.join(differing) or 'shape'}).",
                1,
                0,
                1,
                0,
            )
        )
    return Transformed(
        new_code, result.config, diagnostics, result.spans, result.code_owned, equivalent, sorted(planner.changed)
    )


@dataclass
class _Insert:
    keyword: str
    value: str
    after: str | None


@dataclass
class _Planner:
    reading: Reading
    kind: Kind
    convention: RegistryConvention
    replace_values: dict[cst.CSTNode, cst.BaseExpression] = field(default_factory=dict[cst.CSTNode, cst.BaseExpression])
    remove_args: dict[cst.Call, set[str]] = field(default_factory=dict[cst.Call, set[str]])
    insert_args: dict[cst.Call, list[_Insert]] = field(default_factory=dict[cst.Call, list[_Insert]])
    rebuild_lists: dict[cst.CSTNode, list[cst.BaseElement | cst.BaseExpression]] = field(
        default_factory=dict[cst.CSTNode, list[cst.BaseElement | cst.BaseExpression]]
    )
    rebuild_positional: dict[cst.Call, list[cst.Arg | cst.BaseExpression]] = field(
        default_factory=dict[cst.Call, list[cst.Arg | cst.BaseExpression]]
    )
    changed: set[str] = field(default_factory=set[str])
    needed: Imports = field(default_factory=Imports)

    def __post_init__(self) -> None:
        module = cast("cst.Module", self.reading.module)
        wrapper = MetadataWrapper(module, unsafe_skip_copy=True)
        self.ranges: Mapping[cst.CSTNode, CodeRange] = wrapper.resolve(PositionProvider)
        self.owned = owned_paths(self.reading.parsed)
        self.locals = self._locals(module)

    # ---------------------------------------------------------------- naming
    @staticmethod
    def _locals(module: cst.Module) -> dict[str, str]:
        """Qualified name → the name this file uses for it (``app.registry.tools`` → ``tools`` or ``t``)."""
        names: dict[str, str] = {}
        for statement in module.body:
            if not isinstance(statement, cst.SimpleStatementLine):
                continue
            for small in statement.body:
                if isinstance(small, cst.ImportFrom) and small.module is not None and not small.relative:
                    if isinstance(small.names, cst.ImportStar):
                        continue
                    base = _dotted(small.module)
                    for alias in small.names:
                        name = _dotted(alias.name)
                        local = (
                            alias.asname.name.value
                            if alias.asname and isinstance(alias.asname.name, cst.Name)
                            else name
                        )
                        names.setdefault(f"{base}.{name}", local)
                elif isinstance(small, cst.Import):
                    for alias in small.names:
                        dotted = _dotted(alias.name)
                        local = (
                            alias.asname.name.value
                            if alias.asname and isinstance(alias.asname.name, cst.Name)
                            else dotted
                        )
                        names.setdefault(dotted, local)
        return names

    def refer(self, module: str, name: str) -> str:
        """An expression for ``module.name`` using the file's own imports; imports it when the file doesn't."""
        qualified = f"{module}.{name}"
        if qualified in self.locals:
            return self.locals[qualified]
        for known, local in self.locals.items():
            if known.startswith(f"{module}.") and known.endswith(f".{name}"):
                return local
        if module in self.locals:
            return f"{self.locals[module]}.{name}"
        self.needed.add(module, name)
        self.locals[qualified] = name
        return name

    def registry(self, ref_type: str, entry: str) -> str:
        convention = self.convention
        namespace = convention.namespace(ref_type)  # pyright: ignore[reportArgumentType]
        return f"{self.refer(convention.registry_module, namespace)}.{convention.attribute(ref_type, entry)}"  # pyright: ignore[reportArgumentType]

    def writer(self) -> NodeWriter:
        return NodeWriter(self.convention, Imports(), hoisting=False, refer=self.refer)

    # ---------------------------------------------------------------- rendering
    def depth(self, node: cst.CSTNode) -> int:
        code_range = self.ranges.get(node)
        if code_range is None:
            return 1
        line = cast("cst.Module", self.reading.module).code.splitlines()[code_range.start.line - 1]
        return (len(line) - len(line.lstrip(" "))) // len(INDENT)

    def value(self, name: str, value: Any, depth: int) -> str:  # noqa: ANN401, C901, PLR0911
        if name in MODEL_FIELDS:
            model = ModelRef.parse(value)
            if model is not None:
                return self.registry("model", model.id)
        if name == "tools" and isinstance(value, list):
            return _list([self.tool(tool) for tool in _toolkits(cast("list[Any]", value))], depth)
        if name == "members" and isinstance(value, list):
            return _list([self.member(member) for member in cast("list[Any]", value)], depth)
        if name == "mode" and isinstance(value, str) and self.kind == "team":
            return f"{self.refer('agno.team.mode', 'TeamMode')}.{value}"
        if name in {"input_schema", "output_schema"} and schema_name(value) is not None:
            return self.registry("schema", str(value))
        if name in NAMED_REFS and isinstance(value, dict):
            entry = cast("dict[str, Any]", value)
            named: object = entry.get("name") if name == "knowledge" else entry.get("registry_id")
            if name == "learning":
                named = learning_name(entry)
            if isinstance(named, str):
                return self.registry(NAMED_REFS[name], named)
        if name == "steps" and self.kind == "workflow" and isinstance(value, list):
            writer = self.writer()
            nodes: list[Mapping[str, Any]] = value  # pyright: ignore[reportUnknownVariableType]
            return _list([writer.node(node, depth + 1).text for node in nodes], depth)
        return render_literal(cast("object", value), depth)

    def tool(self, tool: Mapping[str, Any]) -> str:
        return self.registry("tool", str(tool.get("toolkit") or tool.get("name")))

    def member(self, member: Mapping[str, Any]) -> str:
        member_type = "team" if member.get("type") == "team" else "agent"
        component = str(member.get("team_id") if member_type == "team" else member.get("agent_id"))
        return self.refer(self.convention.component_module(member_type), snake(component))

    # ---------------------------------------------------------------- planning
    def plan(self, before: dict[str, Any], after: dict[str, Any]) -> None:
        call = cast("cst.Call", self.reading.component)
        defaults: Mapping[str, Any] = WorkflowConfig.defaults if self.kind == "workflow" else {}
        order = field_order(self.kind, {**before, **after})
        for name in order:
            old, new = before.get(name), after.get(name)
            if old == new:
                continue
            if self.owned(name):
                raise _Refused(f"`{name}` is set in code in a way the form can't edit; change it in the code.", name)
            self.changed.add(name)
            arg = self.reading.args.get(name)
            dropped = name not in after or (name in defaults and defaults[name] == new)
            if dropped:
                if arg is not None:
                    self.remove_args.setdefault(call, set()).add(name)
                continue
            if arg is None:
                previous = _previous(order, name, self.reading.args)
                self.insert_args.setdefault(call, []).append(
                    _Insert(name, self.value(name, new, self.depth(call) + 1), previous)
                )
                continue
            if name == "steps" and self.kind == "workflow" and isinstance(old, list) and isinstance(new, list):
                self.lane("steps", cast("list[Any]", old), cast("list[Any]", new), arg.value)
            elif isinstance(old, list) and isinstance(new, list) and name in {"instructions", "tools", "members"}:
                self.items(name, cast("list[Any]", old), cast("list[Any]", new), arg)
            else:
                self.replace(arg.value, self.value(name, new, self.depth(arg)))

    def replace(self, node: cst.BaseExpression, code: str) -> None:
        target = self.reading_resolve(node) or node
        replacement = cst.parse_expression(code)
        if isinstance(target, cst.ConcatenatedString) and isinstance(replacement, cst.SimpleString):
            # Text a person split over several lines stays split, at the ternaries for a CEL expression.
            text = replacement.evaluated_value
            parts = segments(text) if isinstance(text, str) else []
            if len(parts) > 1:
                pad = INDENT * self.depth(target)
                body = "".join(f"{pad}{string_literal(part)}\n" for part in parts)
                replacement = cst.parse_expression(f"(\n{body})")
        self.replace_values[target] = replacement

    def reading_resolve(self, node: cst.BaseExpression) -> cst.BaseExpression | None:
        """A module-level name's value: edits go where the value is written."""
        if not isinstance(node, cst.Name):
            return None
        module = cast("cst.Module", self.reading.module)
        for statement in module.body:
            if not isinstance(statement, cst.SimpleStatementLine):
                continue
            for small in statement.body:
                if (
                    isinstance(small, cst.Assign)
                    and len(small.targets) == 1
                    and isinstance(small.targets[0].target, cst.Name)
                    and small.targets[0].target.value == node.value
                ):
                    return small.value
        return None

    def items(self, name: str, old: list[Any], new: list[Any], arg: cst.Arg) -> None:
        """Rebuild a list keeping the elements whose items are still there, in the new order."""
        container = self.reading_resolve(arg.value) or arg.value
        if not isinstance(container, cst.List | cst.Tuple):
            raise _Refused(f"`{name}` isn't a literal list in the code; change it in the code.", name)
        elements = list(container.elements)
        groups = self.reading.element_paths.get(name) or [[f"{name}[{index}]"] for index in range(len(elements))]
        owners: list[list[Any]] = [[old[_index(path)] for path in paths if _index(path) < len(old)] for paths in groups]
        used: set[int] = set()
        rebuilt: list[cst.BaseElement | cst.BaseExpression] = []
        position = 0
        while position < len(new):
            item = new[position]
            match = next(
                (
                    index
                    for index, owned in enumerate(owners)
                    if index not in used and owned and owned == new[position : position + len(owned)]
                ),
                None,
            )
            if match is not None:
                used.add(match)
                rebuilt.append(elements[match])
                position += len(owners[match])
                continue
            if name == "tools" and isinstance(item, dict) and cast("dict[str, Any]", item).get("toolkit"):
                kept = [index for index, owned in enumerate(owners) if any(tool == item for tool in owned)]
                if kept:
                    raise _Refused("A toolkit is listed whole in the code; add or remove it whole.", name)
            rebuilt.append(cst.parse_expression(self.element(name, item)))
            position += self._toolkit_span(new, position) if name == "tools" else 1
        self.rebuild_lists[container] = rebuilt

    def _toolkit_span(self, tools: list[Any], start: int) -> int:
        toolkit = tools[start].get("toolkit") if isinstance(tools[start], dict) else None
        if not toolkit:
            return 1
        end = start
        while end < len(tools) and isinstance(tools[end], dict) and tools[end].get("toolkit") == toolkit:
            end += 1
        return end - start

    def element(self, name: str, item: Any) -> str:  # noqa: ANN401
        if name == "tools" and isinstance(item, dict):
            return self.tool(cast("dict[str, Any]", item))
        if name == "members" and isinstance(item, dict):
            return self.member(cast("dict[str, Any]", item))
        return render_literal(item, 0)

    # ---------------------------------------------------------------- step trees
    def lane(self, path: str, old: list[Any], new: list[Any], holder: cst.BaseExpression | cst.Call) -> None:
        same_shape = len(old) == len(new) and all(_same_node(a, b) for a, b in zip(old, new, strict=True))
        if same_shape:
            for index, (a, b) in enumerate(zip(old, new, strict=True)):
                self.node(f"{path}[{index}]", a, b)
            return
        self.changed.add(path)
        parallel = isinstance(holder, cst.Call)
        if parallel:
            elements: Sequence[cst.Arg | cst.BaseElement] = [arg for arg in holder.args if arg.keyword is None]
        else:
            container = self.reading_resolve(holder) or holder
            if not isinstance(container, cst.List | cst.Tuple):
                raise _Refused("These steps aren't a literal list in the code; change them in the code.", path)
            holder = container
            elements = list(container.elements)
        used: set[int] = set()
        rebuilt: list[Any] = []
        writer = self.writer()
        for index, node in enumerate(new):
            match = next(
                (
                    position
                    for position, previous in enumerate(old)
                    if position not in used and _same_node(previous, node)
                ),
                None,
            )
            if match is not None and match < len(elements):
                used.add(match)
                self.node(f"{path}[{match}]", old[match], node)
                rebuilt.append(elements[match])
            else:
                depth = self.depth(elements[0]) if elements else self.depth(holder) + 1
                rebuilt.append(cst.parse_expression(writer.node(node, depth).text))
                self.changed.add(f"{path}[{index}]")
        if isinstance(holder, cst.Call):
            self.rebuild_positional[holder] = rebuilt
        else:
            self.rebuild_lists[holder] = rebuilt

    def node(self, path: str, old: Mapping[str, Any], new: Mapping[str, Any]) -> None:  # noqa: C901, PLR0912
        if old == new:
            return
        if self.owned(path):
            raise _Refused("This step is written in a way the form can't edit; change it in the code.", path)
        call = self.reading.calls.get(path)
        if call is None:
            raise _Refused("This step can't be found in the code.", path)
        node_type = str(new.get("type") or "Step")
        writer = self.writer()
        order = node_order(node_type, {**old, **new})
        for name in order:
            if name in DERIVED:
                continue
            before, after = old.get(name), new.get(name)
            if name in {"evaluator", "end_condition", "selector"}:
                type_key = f"{name}_type"
                if (before, old.get(type_key)) == (after, new.get(type_key)):
                    continue
            elif before == after:
                continue
            field_path = f"{path}.{name}"
            if self.owned(field_path):
                raise _Refused(f"`{name}` is set in code in a way the form can't edit.", field_path)
            keyword = CONFIG_KEYWORDS.get(name, name)
            arg = self.reading.args.get(f"{path}.{keyword}")
            if name in LANES and isinstance(before, list) and isinstance(after, list) and arg is not None:
                self.lane(field_path, cast("list[Any]", before), cast("list[Any]", after), arg.value)
                continue
            if node_type == "Parallel" and name == "steps":
                self.lane(field_path, cast("list[Any]", before or []), cast("list[Any]", after or []), call)
                continue
            self.changed.add(field_path)
            if omitted(node_type, name, cast("object", after)):
                if arg is not None:
                    self.remove_args.setdefault(call, set()).add(keyword)
                continue
            depth = self.depth(arg) if arg is not None else self.depth(call) + 1
            code_keyword, code = writer.keyword(node_type, name, after, new, depth)
            if arg is None:
                previous = _previous_keyword(order, name, path, self.reading.args)
                self.insert_args.setdefault(call, []).append(_Insert(code_keyword, code, previous))
            else:
                self.replace(arg.value, code)

    # ---------------------------------------------------------------- applying
    def apply(self) -> cst.Module:
        module = cast("cst.Module", self.reading.module)
        updated = module.visit(_Applier(self))
        context = CodemodContext()
        for imported, names in self.needed.modules.items():
            for name in sorted(names):
                AddImportsVisitor.add_needed_import(context, imported, name)
        updated = AddImportsVisitor(context).transform_module(updated)
        removals = CodemodContext()
        for qualified in self.locals:
            imported, _, name = qualified.rpartition(".")
            if imported and _removable(imported, self.convention):
                RemoveImportsVisitor.remove_unused_import(removals, imported, name)
        return RemoveImportsVisitor(removals).transform_module(updated)


class _Applier(cst.CSTTransformer):
    def __init__(self, planner: _Planner) -> None:
        super().__init__()
        self.planner = planner

    def on_leave(self, original_node: cst.CSTNode, updated_node: cst.CSTNode) -> cst.CSTNode:  # pyright: ignore[reportIncompatibleMethodOverride]
        planner = self.planner
        result: cst.CSTNode = updated_node
        if original_node in planner.replace_values:
            replacement = planner.replace_values[original_node]
            if isinstance(updated_node, cst.BaseExpression):
                replacement = replacement.with_changes(lpar=updated_node.lpar, rpar=updated_node.rpar)
            result = replacement
        if isinstance(original_node, cst.List | cst.Tuple) and original_node in planner.rebuild_lists:
            result = _rebuilt_list(
                original_node, cast("cst.List | cst.Tuple", updated_node), planner.rebuild_lists[original_node]
            )
        if isinstance(original_node, cst.Call) and isinstance(result, cst.Call):
            result = _edited_call(planner, original_node, result)
        return result


def _edited_call(planner: _Planner, original: cst.Call, updated: cst.Call) -> cst.Call:
    args = list(updated.args)
    trailing = args[-1].comma if args else cst.MaybeSentinel.DEFAULT
    if original in planner.rebuild_positional:
        by_original = dict(zip(original.args, updated.args, strict=True))
        positional = [
            by_original.get(item, item) if isinstance(item, cst.Arg) else cst.Arg(value=item)
            for item in planner.rebuild_positional[original]
        ]
        args = [*positional, *(arg for arg in args if arg.keyword is not None)]
    removed = planner.remove_args.get(original, set())
    args = [arg for arg in args if arg.keyword is None or arg.keyword.value not in removed]
    for insert in planner.insert_args.get(original, []):
        new_arg = cst.Arg(
            value=cst.parse_expression(insert.value),
            keyword=cst.Name(insert.keyword),
            equal=cst.AssignEqual(
                whitespace_before=cst.SimpleWhitespace(""), whitespace_after=cst.SimpleWhitespace("")
            ),
        )
        after = next(
            (
                index + 1
                for index, arg in enumerate(args)
                if arg.keyword is not None and arg.keyword.value == insert.after
            ),
            None,
        )
        first_keyword = next((index for index, arg in enumerate(args) if arg.keyword is not None), len(args))
        args.insert(after if after is not None else first_keyword, new_arg)
    return updated.with_changes(args=_relink(args, _separator(updated), trailing))


def _rebuilt_list(
    original: cst.List | cst.Tuple, updated: cst.List | cst.Tuple, items: list[cst.BaseElement | cst.BaseExpression]
) -> cst.List | cst.Tuple:
    if (
        isinstance(updated, cst.List)
        and updated.elements
        and isinstance(updated.rbracket.whitespace_before, cst.ParenthesizedWhitespace)
    ):
        # A list keeps the line break (and the last item's comment) before its `]`; move it onto the last item's
        # comma, where a call keeps it, so it travels with that item.
        last = updated.elements[-1]
        comma = last.comma if isinstance(last.comma, cst.Comma) else cst.Comma()
        moved = last.with_changes(comma=comma.with_changes(whitespace_after=updated.rbracket.whitespace_before))
        updated = updated.with_changes(
            elements=[*updated.elements[:-1], moved],
            rbracket=updated.rbracket.with_changes(whitespace_before=cst.SimpleWhitespace("")),
        )
    by_original = dict(zip(original.elements, updated.elements, strict=True))
    separator = _list_separator(updated)
    trailing: cst.Comma | cst.MaybeSentinel = (
        updated.elements[-1].comma if updated.elements else cst.MaybeSentinel.DEFAULT
    )
    if not original.elements and isinstance(separator, cst.ParenthesizedWhitespace):
        trailing = cst.Comma(whitespace_after=_closing(separator))
    elements = [
        by_original.get(item, item) if isinstance(item, cst.BaseElement) else cst.Element(value=item) for item in items
    ]
    return updated.with_changes(elements=_relink(elements, separator, trailing))


def _relink[Item: cst.Arg | cst.BaseElement](
    items: list[Item], separator: cst.BaseParenthesizableWhitespace, trailing: cst.Comma | cst.MaybeSentinel
) -> list[Item]:
    """Commas for a sequence whose order changed.

    Every item but the last leads on to the next, the last ends the way the original sequence ended. A comment after
    an item stays with that item.
    """
    end = _without_comment(trailing)
    linked: list[Item] = []
    for index, item in enumerate(items):
        last = index == len(items) - 1
        target = end if last else cst.Comma(whitespace_after=separator)
        linked.append(item.with_changes(comma=_keep_comment(item.comma, target, separator)))
    return linked


def _keep_comment(
    own: cst.Comma | cst.MaybeSentinel,
    target: cst.Comma | cst.MaybeSentinel,
    separator: cst.BaseParenthesizableWhitespace,
) -> cst.Comma | cst.MaybeSentinel:
    if not isinstance(own, cst.Comma) or not isinstance(own.whitespace_after, cst.ParenthesizedWhitespace):
        return target
    if own.whitespace_after.first_line.comment is None:
        return target
    if isinstance(target, cst.Comma) and isinstance(target.whitespace_after, cst.ParenthesizedWhitespace):
        landing = target.whitespace_after
    else:
        closing = _closing(separator)
        landing = (
            cst.ParenthesizedWhitespace(last_line=closing.last_line)
            if isinstance(closing, cst.ParenthesizedWhitespace)
            else own.whitespace_after
        )
    return own.with_changes(
        whitespace_after=own.whitespace_after.with_changes(
            empty_lines=landing.empty_lines, indent=landing.indent, last_line=landing.last_line
        )
    )


def _without_comment(comma: cst.Comma | cst.MaybeSentinel) -> cst.Comma | cst.MaybeSentinel:
    if isinstance(comma, cst.Comma) and isinstance(comma.whitespace_after, cst.ParenthesizedWhitespace):
        return comma.with_changes(
            whitespace_after=comma.whitespace_after.with_changes(first_line=cst.TrailingWhitespace())
        )
    return comma


def _separator(call: cst.Call) -> cst.BaseParenthesizableWhitespace:
    """The whitespace between two arguments: a newline and the argument indentation in an exploded call."""
    if isinstance(call.whitespace_before_args, cst.ParenthesizedWhitespace):
        return call.whitespace_before_args
    return cst.SimpleWhitespace(" ")


def _list_separator(node: cst.List | cst.Tuple) -> cst.BaseParenthesizableWhitespace:
    bracket = node.lbracket if isinstance(node, cst.List) else None
    if bracket is not None and isinstance(bracket.whitespace_after, cst.ParenthesizedWhitespace):
        return bracket.whitespace_after
    return cst.SimpleWhitespace(" ")


def _closing(separator: cst.BaseParenthesizableWhitespace) -> cst.BaseParenthesizableWhitespace:
    if isinstance(separator, cst.ParenthesizedWhitespace):
        indent = separator.last_line.value
        return separator.with_changes(last_line=cst.SimpleWhitespace(indent[: max(len(indent) - len(INDENT), 0)]))
    return cst.SimpleWhitespace("")


def _removable(module: str, convention: RegistryConvention) -> bool:
    if module == "agno" or module.startswith("agno."):
        return True
    roots = (
        convention.registry_module,
        convention.agents_module,
        convention.teams_module,
        convention.workflows_module,
        convention.functions_module,
    )
    return any(module == root or module.startswith(f"{root}.") for root in roots)


def _previous(order: list[str], name: str, present: Mapping[str, cst.Arg]) -> str | None:
    index = order.index(name)
    return next((candidate for candidate in reversed(order[:index]) if candidate in present), None)


def _previous_keyword(order: list[str], name: str, path: str, present: Mapping[str, cst.Arg]) -> str | None:
    index = order.index(name)
    for candidate in reversed(order[:index]):
        keyword = CONFIG_KEYWORDS.get(candidate, candidate)
        if f"{path}.{keyword}" in present:
            return keyword
    return None


def _same_node(a: object, b: object) -> bool:
    if not isinstance(a, Mapping) or not isinstance(b, Mapping):
        return False
    first = cast("Mapping[str, Any]", a)
    second = cast("Mapping[str, Any]", b)
    return first.get("type") == second.get("type") and first.get("name") == second.get("name")


def _toolkits(tools: list[Any]) -> list[Mapping[str, Any]]:
    """One entry per code element: a toolkit's functions collapse into the toolkit."""
    seen: set[str] = set()
    kept: list[Mapping[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, Mapping):
            continue
        entry = cast("Mapping[str, Any]", tool)
        toolkit = entry.get("toolkit")
        if isinstance(toolkit, str):
            if toolkit in seen:
                continue
            seen.add(toolkit)
        kept.append(entry)
    return kept


def _list(items: list[str], depth: int) -> str:
    if not items:
        return "[]"
    pad = INDENT * (depth + 1)
    return "[\n" + "".join(f"{pad}{item},\n" for item in items) + f"{INDENT * depth}]"


def _index(path: str) -> int:
    return int(path.rsplit("[", 1)[1].rstrip("]"))


def _dotted(node: cst.CSTNode) -> str:
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        return f"{_dotted(node.value)}.{node.attr.value}"
    return ""


__all__ = ["Transformed", "transform"]
