"""The typed contract: ModelSpec and its expression grammar.

Everything upstream (the LLM interpreter) produces a ModelSpec; everything
downstream (validator, linearizer, compiler) consumes one. The grammar is
deliberately tiny — small enough that an LLM emits it reliably and a short
recursive-descent parser covers it completely.

Grammar (EBNF):

    constraint  := expr relop expr
    relop       := "<=" | ">=" | "=="
    expr        := term (("+" | "-") term)*
    term        := factor (("*" | "/") factor)*
    factor      := "-" factor | atom
    atom        := NUMBER
                 | "sum" "(" IDENT "in" IDENT "," expr ")"
                 | "abs" "(" expr ")"
                 | IDENT ("[" IDENT ("," IDENT)* "]")?
                 | "(" expr ")"
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .errors import ExpressionSyntaxError

# --------------------------------------------------------------------------
# AST nodes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Num:
    value: float


@dataclass(frozen=True)
class Ref:
    """Reference to a param, variable, or bound index: `x`, `cost[p,w]`."""

    name: str
    indices: tuple[str, ...] = ()


@dataclass(frozen=True)
class Bin:
    op: Literal["+", "-", "*", "/"]
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Neg:
    operand: Expr


@dataclass(frozen=True)
class Sum:
    """`sum(i in I, body)` — body may reference index `i`."""

    index: str
    over: str
    body: Expr


@dataclass(frozen=True)
class Abs:
    operand: Expr


@dataclass(frozen=True)
class Rel:
    op: Literal["<=", ">=", "=="]
    left: Expr
    right: Expr


Expr = Num | Ref | Bin | Neg | Sum | Abs

# --------------------------------------------------------------------------
# Tokenizer + recursive-descent parser
# --------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<ident>[A-Za-z_]\w*)"
    r"|(?P<op><=|>=|==|[+\-*/(),\[\]]))"
)

_KEYWORDS = {"sum", "abs", "in"}


def _tokenize(text: str) -> list[tuple[str, str, int]]:
    tokens: list[tuple[str, str, int]] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if m is None:
            if text[pos:].strip() == "":
                break
            raise ExpressionSyntaxError(f"unexpected character {text[pos]!r}", pos)
        for kind in ("num", "ident", "op"):
            if m.group(kind) is not None:
                tokens.append((kind, m.group(kind), m.start(kind)))
                break
        pos = m.end()
    return tokens


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tokens = _tokenize(text)
        self.i = 0

    def peek(self) -> tuple[str, str, int] | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def advance(self) -> tuple[str, str, int]:
        tok = self.peek()
        if tok is None:
            raise ExpressionSyntaxError("unexpected end of expression", len(self.text))
        self.i += 1
        return tok

    def expect(self, value: str) -> None:
        tok = self.advance()
        if tok[1] != value:
            raise ExpressionSyntaxError(f"expected {value!r}, got {tok[1]!r}", tok[2])

    def parse_expr(self) -> Expr:
        node = self.parse_term()
        while (tok := self.peek()) and tok[1] in ("+", "-"):
            self.advance()
            node = Bin(tok[1], node, self.parse_term())  # type: ignore[arg-type]
        return node

    def parse_term(self) -> Expr:
        node = self.parse_factor()
        while (tok := self.peek()) and tok[1] in ("*", "/"):
            self.advance()
            node = Bin(tok[1], node, self.parse_factor())  # type: ignore[arg-type]
        return node

    def parse_factor(self) -> Expr:
        tok = self.peek()
        if tok and tok[1] == "-":
            self.advance()
            return Neg(self.parse_factor())
        return self.parse_atom()

    def parse_atom(self) -> Expr:
        kind, value, pos = self.advance()
        if kind == "num":
            return Num(float(value))
        if kind == "op" and value == "(":
            inner = self.parse_expr()
            self.expect(")")
            return inner
        if kind == "ident":
            if value == "sum":
                return self._parse_sum()
            if value == "abs":
                self.expect("(")
                inner = self.parse_expr()
                self.expect(")")
                return Abs(inner)
            if value in _KEYWORDS:
                raise ExpressionSyntaxError(f"misplaced keyword {value!r}", pos)
            return self._parse_ref(value)
        raise ExpressionSyntaxError(f"unexpected token {value!r}", pos)

    def _parse_sum(self) -> Sum:
        self.expect("(")
        idx = self.advance()
        if idx[0] != "ident" or idx[1] in _KEYWORDS:
            raise ExpressionSyntaxError("expected index name in sum()", idx[2])
        kw = self.advance()
        if kw[1] != "in":
            raise ExpressionSyntaxError("expected 'in' in sum()", kw[2])
        over = self.advance()
        if over[0] != "ident" or over[1] in _KEYWORDS:
            raise ExpressionSyntaxError("expected set name in sum()", over[2])
        self.expect(",")
        body = self.parse_expr()
        self.expect(")")
        return Sum(idx[1], over[1], body)

    def _parse_ref(self, name: str) -> Ref:
        nxt = self.peek()
        if not (nxt and nxt[1] == "["):
            return Ref(name)
        self.advance()
        indices: list[str] = []
        while True:
            it = self.advance()
            if it[0] != "ident" or it[1] in _KEYWORDS:
                raise ExpressionSyntaxError("index must be an identifier", it[2])
            indices.append(it[1])
            sep = self.advance()
            if sep[1] == "]":
                break
            if sep[1] != ",":
                raise ExpressionSyntaxError("expected ',' or ']'", sep[2])
        return Ref(name, tuple(indices))


def parse_expression(text: str) -> Expr:
    """Parse an objective or sub-expression string into an AST."""
    p = _Parser(text)
    node = p.parse_expr()
    if (tok := p.peek()) is not None:
        raise ExpressionSyntaxError(f"trailing input {tok[1]!r}", tok[2])
    return node


def parse_constraint(text: str) -> Rel:
    """Parse a constraint string: `expr <= expr` (or >=, ==)."""
    p = _Parser(text)
    left = p.parse_expr()
    tok = p.peek()
    if tok is None or tok[1] not in ("<=", ">=", "=="):
        raise ExpressionSyntaxError(
            "constraint needs a relational operator (<=, >=, ==)",
            tok[2] if tok else len(text),
        )
    p.advance()
    right = p.parse_expr()
    if (extra := p.peek()) is not None:
        raise ExpressionSyntaxError(f"trailing input {extra[1]!r}", extra[2])
    return Rel(tok[1], left, right)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Unparser (precedence-aware; round-trips through the parser)
# --------------------------------------------------------------------------

_PREC = {"+": 1, "-": 1, "*": 2, "/": 2}


def unparse(node: Expr | Rel) -> str:
    if isinstance(node, Rel):
        return f"{unparse(node.left)} {node.op} {unparse(node.right)}"
    if isinstance(node, Num):
        return str(int(node.value)) if node.value == int(node.value) else str(node.value)
    if isinstance(node, Ref):
        return f"{node.name}[{','.join(node.indices)}]" if node.indices else node.name
    if isinstance(node, Neg):
        inner = unparse(node.operand)
        return f"-({inner})" if isinstance(node.operand, Bin) else f"-{inner}"
    if isinstance(node, Sum):
        return f"sum({node.index} in {node.over}, {unparse(node.body)})"
    if isinstance(node, Abs):
        return f"abs({unparse(node.operand)})"
    if isinstance(node, Bin):
        left = unparse(node.left)
        right = unparse(node.right)
        if isinstance(node.left, (Bin, Neg)) and (
            isinstance(node.left, Neg) or _PREC[node.left.op] < _PREC[node.op]
        ):
            left = f"({left})"
        if isinstance(node.right, (Bin, Neg)):
            rp = 0 if isinstance(node.right, Neg) else _PREC[node.right.op]
            if rp < _PREC[node.op] or (rp == _PREC[node.op] and node.op in ("-", "/")):
                right = f"({right})"
        return f"{left} {node.op} {right}"
    raise TypeError(f"unknown node {node!r}")


# --------------------------------------------------------------------------
# ModelSpec (pydantic v2)
# --------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[A-Za-z_]\w*$")


def _check_name(name: str) -> str:
    if not _NAME_RE.match(name) or name in _KEYWORDS:
        raise ValueError(f"{name!r} is not a valid identifier")
    return name


class SetDef(BaseModel):
    name: str
    members: list[str] = Field(min_length=1)
    description: str = ""

    _name_ok = field_validator("name")(_check_name)


class ParamDef(BaseModel):
    """Scalar (`indexed_by=[]`, values is a number) or indexed data.

    Indexed values are keyed by member name, comma-joined for
    multi-dimensional params: `{"chair,cutting": 1.0}`.
    """

    name: str
    indexed_by: list[str] = []
    values: float | dict[str, float]
    description: str = ""

    _name_ok = field_validator("name")(_check_name)


class VarDef(BaseModel):
    name: str
    indexed_by: list[str] = []
    domain: Literal["continuous", "integer", "binary"] = "continuous"
    lower: float | None = 0.0
    upper: float | None = None
    description: str = ""

    _name_ok = field_validator("name")(_check_name)


class IndexBinding(BaseModel):
    index: str
    over: str  # set name

    _index_ok = field_validator("index")(_check_name)


class ConstraintDef(BaseModel):
    name: str
    forall: list[IndexBinding] = []
    expr: str
    description: str = ""

    _name_ok = field_validator("name")(_check_name)


class ObjectiveDef(BaseModel):
    sense: Literal["maximize", "minimize"]
    expr: str
    description: str = ""


class ModelSpec(BaseModel):
    """The contract between the LLM boundary and the deterministic core."""

    name: str = "model"
    description: str = ""
    sets: list[SetDef] = []
    params: list[ParamDef] = []
    variables: list[VarDef] = []
    constraints: list[ConstraintDef] = []
    objective: ObjectiveDef

    def set_map(self) -> dict[str, SetDef]:
        return {s.name: s for s in self.sets}

    def param_map(self) -> dict[str, ParamDef]:
        return {p.name: p for p in self.params}

    def var_map(self) -> dict[str, VarDef]:
        return {v.name: v for v in self.variables}

    @classmethod
    def from_file(cls, path: str | Path) -> ModelSpec:
        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))

    def to_json(self, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)
