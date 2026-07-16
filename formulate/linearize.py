"""Linearization transforms: rewrite nonlinear patterns into MILP form.

Implemented (fully, with tests):
  * binary * continuous product  ->  big-M reformulation (McCormick for a
    binary factor): z replaces b*x with z <= M*b, z <= x, z >= x - M*(1-b).
  * abs(expr) in a convex position (minimized objective, or the <= side of
    a constraint)  ->  auxiliary t with t >= expr and t >= -expr.

Roadmap (detected, reported, not yet rewritten): continuous*continuous
products, piecewise-linear costs, indicator constraints. See
docs/architecture.md for the extform design sketch.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from .errors import LinearizationError
from .spec import (
    Abs,
    Bin,
    ConstraintDef,
    Expr,
    ModelSpec,
    Neg,
    Num,
    Ref,
    Rel,
    Sum,
    VarDef,
    parse_constraint,
    parse_expression,
    unparse,
)

logger = logging.getLogger(__name__)

_DEFAULT_BIG_M = 1e6


class TransformNote(BaseModel):
    transform: str
    location: str
    detail: str


class _Rewriter:
    def __init__(self, spec: ModelSpec) -> None:
        self.spec = spec
        self.vars = spec.var_map()
        self.new_vars: list[VarDef] = []
        self.new_constraints: list[ConstraintDef] = []
        self.notes: list[TransformNote] = []
        self._counter = 0

    def _fresh(self, stem: str) -> str:
        self._counter += 1
        return f"lin_{stem}_{self._counter}"

    # -- transform 1: binary * continuous --------------------------------

    def _try_product(self, node: Bin, location: str) -> Expr | None:
        if node.op != "*":
            return None
        sides = (node.left, node.right)
        if not all(isinstance(s, Ref) for s in sides):
            return None
        defs = [self.vars.get(s.name) for s in sides]  # type: ignore[union-attr]
        if any(d is None for d in defs):
            return None  # param * var is already linear
        binary = next((i for i, d in enumerate(defs) if d.domain == "binary"), None)
        if binary is None:
            raise LinearizationError(
                f"{location}: product of two non-binary variables "
                f"({unparse(node)}) — not yet supported (roadmap: McCormick envelopes)"
            )
        b_ref, x_ref = sides[binary], sides[1 - binary]
        x_def = defs[1 - binary]
        if x_def.indexed_by or defs[binary].indexed_by:
            raise LinearizationError(
                f"{location}: indexed variable products not yet supported"
            )
        big_m = x_def.upper if x_def.upper is not None else _DEFAULT_BIG_M
        z = self._fresh("prod")
        self.new_vars.append(
            VarDef(name=z, domain="continuous", lower=0.0, upper=x_def.upper)
        )
        b, x = unparse(b_ref), unparse(x_ref)
        self.new_constraints += [
            ConstraintDef(name=f"{z}_cap_bin", expr=f"{z} <= {big_m} * {b}"),
            ConstraintDef(name=f"{z}_cap_x", expr=f"{z} <= {x}"),
            ConstraintDef(name=f"{z}_floor", expr=f"{z} >= {x} - {big_m} * (1 - {b})"),
        ]
        self.notes.append(
            TransformNote(
                transform="binary-product-big-m",
                location=location,
                detail=f"replaced {b}*{x} with {z} (M={big_m:g})",
            )
        )
        return Ref(z)

    # -- transform 2: abs() in convex position ----------------------------

    def _rewrite_abs(self, node: Abs, location: str, convex: bool) -> Expr:
        if not convex:
            raise LinearizationError(
                f"{location}: abs() in a non-convex position (maximized objective "
                f"or >= side) cannot be linearized without binaries — roadmap item"
            )
        t = self._fresh("abs")
        self.new_vars.append(VarDef(name=t, domain="continuous", lower=0.0))
        inner = self._walk(node.operand, location, convex=False)
        e = unparse(inner)
        self.new_constraints += [
            ConstraintDef(name=f"{t}_pos", expr=f"{t} >= {e}"),
            ConstraintDef(name=f"{t}_neg", expr=f"{t} >= -({e})"),
        ]
        self.notes.append(
            TransformNote(
                transform="abs-epigraph",
                location=location,
                detail=f"replaced abs({e}) with epigraph variable {t}",
            )
        )
        return Ref(t)

    # -- generic walk -------------------------------------------------------

    def _walk(self, node: Expr, location: str, convex: bool) -> Expr:
        if isinstance(node, (Num, Ref)):
            return node
        if isinstance(node, Neg):
            return Neg(self._walk(node.operand, location, convex=False))
        if isinstance(node, Sum):
            return Sum(node.index, node.over, self._walk(node.body, location, convex))
        if isinstance(node, Abs):
            return self._rewrite_abs(node, location, convex)
        if isinstance(node, Bin):
            replaced = self._try_product(node, location)
            if replaced is not None:
                return replaced
            keep = convex and node.op == "+"
            return Bin(
                node.op,
                self._walk(node.left, location, keep),
                self._walk(node.right, location, keep),
            )
        raise LinearizationError(f"unexpected node {node!r}")


def linearize(spec: ModelSpec) -> tuple[ModelSpec, list[TransformNote]]:
    """Return a purely-linear equivalent spec plus notes on what changed.

    Specs that are already linear pass through untouched (and the notes
    list is empty), so the pipeline always calls this unconditionally.
    """
    rw = _Rewriter(spec)
    out = spec.model_copy(deep=True)

    obj_ast = parse_expression(spec.objective.expr)
    obj_convex = spec.objective.sense == "minimize"
    new_obj = rw._walk(obj_ast, "objective", convex=obj_convex)
    out.objective.expr = unparse(new_obj)

    for c in out.constraints:
        rel = parse_constraint(c.expr)
        # lhs of <= (and rhs of >=) are convex positions for abs()
        left_convex = rel.op == "<="
        right_convex = rel.op == ">="
        new_rel = Rel(
            rel.op,
            rw._walk(rel.left, f"constraint:{c.name}", left_convex),
            rw._walk(rel.right, f"constraint:{c.name}", right_convex),
        )
        c.expr = unparse(new_rel)

    out.variables = out.variables + rw.new_vars
    out.constraints = out.constraints + rw.new_constraints
    if rw.notes:
        logger.info("linearizer applied %d transform(s)", len(rw.notes))
    return out, rw.notes
