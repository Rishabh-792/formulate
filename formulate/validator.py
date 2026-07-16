"""Deterministic ModelSpec validation.

This is the firewall between the LLM and the compiler: anything the
interpreter emits passes through here before a single Pyomo object is built.
Checks: duplicate/colliding names, unknown set references, param coverage,
expression symbol resolution, index arity, variable bound sanity, and
objective shape. Returns a structured report instead of raising, so callers
can show all problems at once.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .errors import ExpressionSyntaxError
from .spec import (
    Abs,
    Bin,
    Expr,
    ModelSpec,
    Neg,
    Num,
    Ref,
    Rel,
    Sum,
    parse_constraint,
    parse_expression,
)


class Issue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    location: str  # e.g. "constraint:capacity", "param:profit", "objective"


class ValidationReport(BaseModel):
    issues: list[Issue] = []

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        if not self.issues:
            return "spec is valid: no issues"
        lines = [f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)"]
        lines += [f"  [{i.severity}] {i.location}: {i.message}" for i in self.issues]
        return "\n".join(lines)


def _expected_keys(spec: ModelSpec, indexed_by: list[str]) -> set[str] | None:
    """All comma-joined member combinations, or None if a set is unknown."""
    sets = spec.set_map()
    if any(s not in sets for s in indexed_by):
        return None
    keys = [""]
    for set_name in indexed_by:
        keys = [
            (f"{prefix},{m}" if prefix else m)
            for prefix in keys
            for m in sets[set_name].members
        ]
    return set(keys)


class _ExprChecker:
    """Walks an expression AST resolving every symbol against the spec."""

    def __init__(self, spec: ModelSpec, report: list[Issue], location: str) -> None:
        self.spec = spec
        self.report = report
        self.location = location
        self.params = spec.param_map()
        self.vars = spec.var_map()
        self.sets = spec.set_map()
        self.members = {m for s in spec.sets for m in s.members}
        self.uses_var = False

    def _err(self, code: str, message: str) -> None:
        self.report.append(
            Issue(severity="error", code=code, message=message, location=self.location)
        )

    def check(self, node: Expr | Rel, bound: dict[str, str]) -> None:
        """`bound` maps index name -> set name."""
        if isinstance(node, Rel):
            self.check(node.left, bound)
            self.check(node.right, bound)
        elif isinstance(node, Num):
            pass
        elif isinstance(node, (Neg, Abs)):
            self.check(node.operand, bound)
        elif isinstance(node, Bin):
            self.check(node.left, bound)
            self.check(node.right, bound)
        elif isinstance(node, Sum):
            if node.over not in self.sets:
                self._err("unknown-set", f"sum() iterates unknown set '{node.over}'")
                return
            if node.index in bound:
                self._err("index-shadow", f"sum() index '{node.index}' shadows an outer index")
            self.check(node.body, {**bound, node.index: node.over})
        elif isinstance(node, Ref):
            self._check_ref(node, bound)

    def _check_ref(self, node: Ref, bound: dict[str, str]) -> None:
        decl = self.params.get(node.name) or self.vars.get(node.name)
        if decl is None:
            if node.name in bound and not node.indices:
                return  # bare bound index used as a value is odd but caught below
            self._err("unknown-symbol", f"'{node.name}' is not a declared param or variable")
            return
        if node.name in self.vars:
            self.uses_var = True
        arity = len(decl.indexed_by)
        if len(node.indices) != arity:
            self._err(
                "index-arity",
                f"'{node.name}' expects {arity} index(es), got {len(node.indices)}",
            )
            return
        for pos, (idx, set_name) in enumerate(
            zip(node.indices, decl.indexed_by, strict=True)
        ):
            if idx in bound:
                if bound[idx] != set_name:
                    self._err(
                        "index-set-mismatch",
                        f"index '{idx}' ranges over '{bound[idx]}' but position "
                        f"{pos} of '{node.name}' is indexed by '{set_name}'",
                    )
            elif idx not in self.members:
                self._err(
                    "unknown-index",
                    f"index '{idx}' of '{node.name}' is neither a bound index "
                    f"nor a set member",
                )
            elif set_name in self.sets and idx not in self.sets[set_name].members:
                self._err(
                    "member-set-mismatch",
                    f"literal member '{idx}' is not in set '{set_name}'",
                )


def validate(spec: ModelSpec) -> ValidationReport:
    issues: list[Issue] = []

    def err(code: str, msg: str, loc: str) -> None:
        issues.append(Issue(severity="error", code=code, message=msg, location=loc))

    def warn(code: str, msg: str, loc: str) -> None:
        issues.append(Issue(severity="warning", code=code, message=msg, location=loc))

    # --- name collisions ---------------------------------------------------
    seen: dict[str, str] = {}
    for kind, items in (
        ("set", spec.sets),
        ("param", spec.params),
        ("variable", spec.variables),
    ):
        for item in items:
            if item.name in seen:
                err("duplicate-name", f"'{item.name}' already declared as a {seen[item.name]}", f"{kind}:{item.name}")
            seen[item.name] = kind
    cnames: set[str] = set()
    for c in spec.constraints:
        if c.name in cnames:
            err("duplicate-name", f"constraint '{c.name}' declared twice", f"constraint:{c.name}")
        cnames.add(c.name)

    # --- sets ----------------------------------------------------------------
    for s in spec.sets:
        if len(set(s.members)) != len(s.members):
            err("duplicate-member", f"set '{s.name}' has duplicate members", f"set:{s.name}")

    # --- params ---------------------------------------------------------------
    for p in spec.params:
        loc = f"param:{p.name}"
        expected = _expected_keys(spec, p.indexed_by)
        if expected is None:
            err("unknown-set", "indexed_by references an undeclared set", loc)
            continue
        if not p.indexed_by:
            if isinstance(p.values, dict):
                err("shape-mismatch", "scalar param must have a numeric value, not a table", loc)
            continue
        if not isinstance(p.values, dict):
            err("shape-mismatch", "indexed param must have a table of values", loc)
            continue
        missing = expected - p.values.keys()
        extra = p.values.keys() - expected
        if missing:
            err("missing-values", f"no value for key(s): {sorted(missing)}", loc)
        if extra:
            err("extra-values", f"key(s) not in index space: {sorted(extra)}", loc)

    # --- variables --------------------------------------------------------------
    for v in spec.variables:
        loc = f"variable:{v.name}"
        if _expected_keys(spec, v.indexed_by) is None:
            err("unknown-set", "indexed_by references an undeclared set", loc)
        if v.lower is not None and v.upper is not None and v.lower > v.upper:
            err("degenerate-bounds", f"lower bound {v.lower} > upper bound {v.upper}", loc)
        if v.domain == "binary" and (
            (v.lower is not None and v.lower not in (0, 1))
            or (v.upper is not None and v.upper not in (0, 1))
        ):
            warn("binary-bounds", "explicit bounds on a binary variable are ignored", loc)

    # --- constraints ------------------------------------------------------------
    sets = spec.set_map()
    for c in spec.constraints:
        loc = f"constraint:{c.name}"
        bound: dict[str, str] = {}
        bad_forall = False
        for b in c.forall:
            if b.over not in sets:
                err("unknown-set", f"forall index '{b.index}' ranges over unknown set '{b.over}'", loc)
                bad_forall = True
            if b.index in bound:
                err("duplicate-index", f"forall index '{b.index}' bound twice", loc)
            bound[b.index] = b.over
        try:
            rel = parse_constraint(c.expr)
        except ExpressionSyntaxError as exc:
            err("syntax", str(exc), loc)
            continue
        if not bad_forall:
            checker = _ExprChecker(spec, issues, loc)
            checker.check(rel, bound)
            if not checker.uses_var:
                warn("constant-constraint", "constraint references no decision variable", loc)

    # --- objective ---------------------------------------------------------------
    try:
        obj = parse_expression(spec.objective.expr)
    except ExpressionSyntaxError as exc:
        err("syntax", str(exc), "objective")
    else:
        checker = _ExprChecker(spec, issues, "objective")
        checker.check(obj, {})
        if not checker.uses_var:
            err("constant-objective", "objective references no decision variable", "objective")

    return ValidationReport(issues=issues)
