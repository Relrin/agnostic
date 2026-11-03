"""Tokens of a CEL expression: literals with CEL's escapes, identifiers, keywords and operators."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agnostic_cel.errors import CelSyntaxError, Span

TokenKind = Literal["int", "uint", "double", "string", "bytes", "ident", "op", "eof"]

OPERATORS = (
    *("||", "&&", "==", "!=", "<=", ">=", "<", ">", "+", "-", "*", "/", "%", "!", "?", ":", ".", ","),
    *("(", ")", "[", "]", "{", "}"),
)
RESERVED = frozenset(
    {
        "as",
        "break",
        "const",
        "continue",
        "else",
        "for",
        "function",
        "if",
        "import",
        "let",
        "loop",
        "package",
        "namespace",
        "return",
        "var",
        "void",
        "while",
    }
)
_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "\\": "\\",
    '"': '"',
    "'": "'",
    "`": "`",
    "?": "?",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
}
MAX_SOURCE = 4_000


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    text: str
    value: object
    span: Span


def tokenize(source: str) -> list[Token]:
    if len(source) > MAX_SOURCE:
        raise CelSyntaxError(f"The expression is longer than {MAX_SOURCE} characters.", Span(0, len(source)))
    return list(_Lexer(source).tokens())


class _Lexer:
    def __init__(self, source: str) -> None:
        self.source = source
        self.pos = 0

    def tokens(self) -> list[Token]:
        found: list[Token] = []
        while True:
            self._skip()
            if self.pos >= len(self.source):
                found.append(Token("eof", "", None, Span(self.pos, self.pos)))
                return found
            found.append(self._next())

    def _skip(self) -> None:
        while self.pos < len(self.source):
            char = self.source[self.pos]
            if char.isspace():
                self.pos += 1
            elif self.source.startswith("//", self.pos):
                end = self.source.find("\n", self.pos)
                self.pos = len(self.source) if end < 0 else end
            else:
                return

    def _next(self) -> Token:
        source, start = self.source, self.pos
        char = source[start]
        ahead = source[start : start + 3].lower()
        quotes = {'"', "'"}
        if (
            char in quotes
            or (ahead[:1] in {"r", "b"} and ahead[1:2] in quotes)
            or (ahead[:2] in {"rb", "br"} and ahead[2:3] in quotes)
        ):
            return self._string()
        if char.isdigit() or (char == "." and start + 1 < len(source) and source[start + 1].isdigit()):
            return self._number()
        if char.isalpha() or char == "_":
            end = start
            while end < len(source) and (source[end].isalnum() or source[end] == "_"):
                end += 1
            text = source[start:end]
            self.pos = end
            if text in RESERVED:
                raise CelSyntaxError(f"`{text}` is a reserved word in CEL.", Span(start, end))
            return Token("ident", text, text, Span(start, end))
        for operator in OPERATORS:
            if source.startswith(operator, start):
                self.pos = start + len(operator)
                return Token("op", operator, operator, Span(start, self.pos))
        raise CelSyntaxError(f"Unexpected character `{char}`.", Span(start, start + 1))

    def _number(self) -> Token:  # noqa: C901
        source, start = self.source, self.pos
        if source.startswith(("0x", "0X"), start):
            end = start + 2
            while end < len(source) and source[end] in "0123456789abcdefABCDEF":
                end += 1
            value = int(source[start + 2 : end], 16)
            return self._integer(start, end, value)
        end = start
        while end < len(source) and source[end].isdigit():
            end += 1
        is_double = False
        if end < len(source) and source[end] == "." and end + 1 < len(source) and source[end + 1].isdigit():
            is_double = True
            end += 1
            while end < len(source) and source[end].isdigit():
                end += 1
        if end < len(source) and source[end] in "eE":
            exponent = end + 1
            if exponent < len(source) and source[exponent] in "+-":
                exponent += 1
            if exponent < len(source) and source[exponent].isdigit():
                is_double = True
                end = exponent
                while end < len(source) and source[end].isdigit():
                    end += 1
        text = source[start:end]
        if is_double:
            self.pos = end
            return Token("double", text, float(text), Span(start, end))
        return self._integer(start, end, int(text))

    def _integer(self, start: int, end: int, value: int) -> Token:
        if end < len(self.source) and self.source[end] in "uU":
            self.pos = end + 1
            return Token("uint", self.source[start : self.pos], value, Span(start, self.pos))
        self.pos = end
        return Token("int", self.source[start:end], value, Span(start, end))

    def _string(self) -> Token:
        source, start = self.source, self.pos
        raw = is_bytes = False
        while source[self.pos] in "rRbB":
            raw = raw or source[self.pos] in "rR"
            is_bytes = is_bytes or source[self.pos] in "bB"
            self.pos += 1
        quote = source[self.pos]
        triple = source.startswith(quote * 3, self.pos)
        delimiter = quote * 3 if triple else quote
        self.pos += len(delimiter)
        parts: list[str] = []
        while True:
            if self.pos >= len(source):
                raise CelSyntaxError("This string is never closed.", Span(start, len(source)))
            if source.startswith(delimiter, self.pos):
                self.pos += len(delimiter)
                break
            char = source[self.pos]
            if char == "\n" and not triple:
                raise CelSyntaxError("A string can't span lines unless it's triple-quoted.", Span(start, self.pos))
            if char == "\\" and not raw:
                parts.append(self._escape())
                continue
            parts.append(char)
            self.pos += 1
        text = "".join(parts)
        span = Span(start, self.pos)
        if is_bytes:
            return Token("bytes", source[start : self.pos], text.encode("utf-8", "surrogateescape"), span)
        return Token("string", source[start : self.pos], text, span)

    def _escape(self) -> str:
        source, start = self.source, self.pos
        if start + 1 >= len(source):
            raise CelSyntaxError("A backslash ends the string.", Span(start, start + 1))
        code = source[start + 1]
        if code in _ESCAPES:
            self.pos += 2
            return _ESCAPES[code]
        widths = {"x": 2, "u": 4, "U": 8}
        if code in widths:
            digits = source[start + 2 : start + 2 + widths[code]]
            if len(digits) != widths[code] or any(char not in "0123456789abcdefABCDEF" for char in digits):
                raise CelSyntaxError(f"`\\{code}` needs {widths[code]} hex digits.", Span(start, start + 2))
            self.pos += 2 + widths[code]
            return chr(int(digits, 16))
        if code in "01234567":
            digits = source[start + 1 : start + 4]
            if len(digits) != 3 or any(char not in "01234567" for char in digits):  # noqa: PLR2004
                raise CelSyntaxError("An octal escape needs 3 digits.", Span(start, start + 2))
            self.pos += 4
            return chr(int(digits, 8))
        raise CelSyntaxError(f"`\\{code}` isn't an escape CEL knows.", Span(start, start + 2))
