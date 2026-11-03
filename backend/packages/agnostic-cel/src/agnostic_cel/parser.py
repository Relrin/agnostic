"""CEL's grammar, by precedence climbing.

``?:`` < ``||`` < ``&&`` < relations and ``in`` < ``+ -`` < ``* / %`` < unary ``! -`` < member access, indexing and
calls. Macros (``has``, ``all``, ``exists``, ``exists_one``, ``map``, ``filter``) become their own nodes.
"""

from __future__ import annotations

from agnostic_cel.errors import CelSyntaxError, Span
from agnostic_cel.lexer import Token, tokenize
from agnostic_cel.nodes import (
    Binary,
    Call,
    Comprehension,
    ComprehensionKind,
    Conditional,
    Has,
    Ident,
    Index,
    ListExpr,
    Lit,
    MapExpr,
    Node,
    Select,
    Unary,
)

RELATIONS = ("==", "!=", "<", "<=", ">", ">=", "in")
MAX_DEPTH = 100
_MACROS: dict[str, tuple[ComprehensionKind, tuple[int, ...]]] = {
    "all": ("all", (2,)),
    "exists": ("exists", (2,)),
    "exists_one": ("exists_one", (2,)),
    "map": ("map", (2, 3)),
    "filter": ("filter", (2,)),
}


def parse(source: str) -> Node:
    """Raises :class:`CelSyntaxError` with the span at fault."""
    if not source.strip():
        raise CelSyntaxError("The expression is empty.", Span(0, len(source)))
    return _Parser(tokenize(source)).expression_only()


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0
        self.depth = 0

    # ---------------------------------------------------------------- helpers
    @property
    def current(self) -> Token:
        return self.tokens[self.pos]

    def _at(self, *texts: str) -> bool:
        token = self.current
        if token.kind == "op":
            return token.text in texts
        return token.kind == "ident" and token.text in texts and token.text == "in"

    def _advance(self) -> Token:
        token = self.current
        if token.kind != "eof":
            self.pos += 1
        return token

    def _expect(self, text: str) -> Token:
        if not self._at(text):
            found = self.current.text or "the end"
            raise CelSyntaxError(f"Expected `{text}` but found `{found}`.", self.current.span)
        return self._advance()

    def _nest(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise CelSyntaxError("The expression nests too deeply.", self.current.span)

    # ---------------------------------------------------------------- grammar
    def expression_only(self) -> Node:
        node = self.expression()
        if self.current.kind != "eof":
            raise CelSyntaxError(f"Unexpected `{self.current.text}`.", self.current.span)
        return node

    def expression(self) -> Node:
        self._nest()
        condition = self._or()
        if self._at("?"):
            self._advance()
            then = self._or()
            self._expect(":")
            otherwise = self.expression()
            condition = Conditional(Span(condition.span.start, otherwise.span.end), condition, then, otherwise)
        self.depth -= 1
        return condition

    def _or(self) -> Node:
        node = self._and()
        while self._at("||"):
            self._advance()
            right = self._and()
            node = Binary(Span(node.span.start, right.span.end), "||", node, right)
        return node

    def _and(self) -> Node:
        node = self._relation()
        while self._at("&&"):
            self._advance()
            right = self._relation()
            node = Binary(Span(node.span.start, right.span.end), "&&", node, right)
        return node

    def _relation(self) -> Node:
        node = self._addition()
        while self._at(*RELATIONS):
            op = self._advance().text
            right = self._addition()
            node = Binary(Span(node.span.start, right.span.end), op, node, right)
        return node

    def _addition(self) -> Node:
        node = self._multiplication()
        while self._at("+", "-"):
            op = self._advance().text
            right = self._multiplication()
            node = Binary(Span(node.span.start, right.span.end), op, node, right)
        return node

    def _multiplication(self) -> Node:
        node = self._unary()
        while self._at("*", "/", "%"):
            op = self._advance().text
            right = self._unary()
            node = Binary(Span(node.span.start, right.span.end), op, node, right)
        return node

    def _unary(self) -> Node:
        if self._at("!", "-"):
            token = self._advance()
            self._nest()
            operand = self._unary()
            self.depth -= 1
            if token.text == "-" and isinstance(operand, Lit) and operand.kind in {"int", "double"}:
                value = operand.value
                assert isinstance(value, int | float)
                return Lit(Span(token.span.start, operand.span.end), operand.kind, -value)
            op = "!" if token.text == "!" else "-"
            return Unary(Span(token.span.start, operand.span.end), op, operand)
        return self._member()

    def _member(self) -> Node:
        node = self._primary()
        while True:
            if self._at("."):
                self._advance()
                name = self._name()
                if self._at("("):
                    args, end = self._arguments()
                    node = self._method(node, name, args, Span(node.span.start, end))
                else:
                    node = Select(Span(node.span.start, name.span.end), node, name.text)
            elif self._at("["):
                self._advance()
                index = self.expression()
                end = self._expect("]").span.end
                node = Index(Span(node.span.start, end), node, index)
            else:
                return node

    def _method(self, target: Node, name: Token, args: list[Node], span: Span) -> Node:
        macro = _MACROS.get(name.text)
        if macro is None:
            return Call(span, name.text, tuple(args), target)
        kind, arities = macro
        if len(args) not in arities:
            expected = " or ".join(str(arity) for arity in arities)
            raise CelSyntaxError(f"`{name.text}` takes {expected} arguments.", span)
        variable = args[0]
        if not isinstance(variable, Ident):
            raise CelSyntaxError(f"The first argument of `{name.text}` names a variable.", variable.span)
        if kind == "map":
            predicate = args[1] if len(args) == 3 else None  # noqa: PLR2004
            return Comprehension(span, kind, target, variable.name, predicate, args[-1])
        return Comprehension(span, kind, target, variable.name, args[1])

    def _primary(self) -> Node:
        token = self.current
        if token.kind in {"int", "uint", "double", "string", "bytes"}:
            self._advance()
            return Lit(token.span, token.kind, token.value)  # pyright: ignore[reportArgumentType]
        if token.kind == "ident":
            return self._identifier()
        if self._at("("):
            self._advance()
            node = self.expression()
            self._expect(")")
            return node
        if self._at("["):
            start = self._advance().span.start
            items = self._list("]")
            end = self._expect("]").span.end
            return ListExpr(Span(start, end), tuple(items))
        if self._at("{"):
            return self._map()
        if self._at("."):
            self._advance()
            return self._identifier()
        found = token.text or "the end of the expression"
        raise CelSyntaxError(f"Expected a value but found `{found}`.", token.span)

    def _identifier(self) -> Node:
        token = self._name()
        constants: dict[str, Lit] = {
            "true": Lit(token.span, "bool", value=True),
            "false": Lit(token.span, "bool", value=False),
            "null": Lit(token.span, "null", None),
        }
        if token.text in constants:
            return constants[token.text]
        if not self._at("("):
            return Ident(token.span, token.text)
        args, end = self._arguments()
        span = Span(token.span.start, end)
        if token.text == "has":
            if len(args) != 1 or not isinstance(args[0], Select):
                raise CelSyntaxError("`has` takes one field selection, such as `has(session_state.plan)`.", span)
            return Has(span, args[0].operand, args[0].field)
        return Call(span, token.text, tuple(args))

    def _name(self) -> Token:
        token = self.current
        if token.kind != "ident" or token.text == "in":
            raise CelSyntaxError(f"Expected a name but found `{token.text or 'the end'}`.", token.span)
        return self._advance()

    def _arguments(self) -> tuple[list[Node], int]:
        self._expect("(")
        args = self._list(")")
        return args, self._expect(")").span.end

    def _list(self, closing: str) -> list[Node]:
        items: list[Node] = []
        while not self._at(closing):
            items.append(self.expression())
            if not self._at(","):
                break
            self._advance()
        return items

    def _map(self) -> Node:
        start = self._expect("{").span.start
        entries: list[tuple[Node, Node]] = []
        while not self._at("}"):
            key = self.expression()
            self._expect(":")
            entries.append((key, self.expression()))
            if not self._at(","):
                break
            self._advance()
        end = self._expect("}").span.end
        return MapExpr(Span(start, end), tuple(entries))
