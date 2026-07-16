"""Solver adapter + elastic infeasibility diagnostic.

Prefers HiGHS (via Pyomo's appsi interface, wheels ship with `highspy`),
falls back to CBC or GLPK binaries if present. On infeasibility, re-solves
an elastic relaxation — every constraint gets a nonnegative slack, the
objective becomes "minimize total slack" — and reports the constraints whose
slack is nonzero: those are the ones that cannot all hold together.
"""

from __future__ import annotations

import logging
from typing import Literal

import pyomo.environ as pyo
from pydantic import BaseModel

from .compile import compile_spec
from .errors import SolverError
from .spec import ConstraintDef, ModelSpec, ObjectiveDef, VarDef, parse_constraint

logger = logging.getLogger(__name__)

_SOLVER_PREFERENCE = ("appsi_highs", "cbc", "glpk")


class SlackReport(BaseModel):
    constraint: str
    index: str  # "" for scalar constraints
    slack: float

    def describe(self) -> str:
        where = f"{self.constraint}[{self.index}]" if self.index else self.constraint
        return f"{where} must be relaxed by {self.slack:g}"


class SolveResult(BaseModel):
    status: Literal["optimal", "infeasible", "unbounded", "error"]
    solver: str = ""
    objective: float | None = None
    variables: dict[str, dict[str, float]] = {}  # var name -> {index-key: value}
    infeasibility: list[SlackReport] = []
    message: str = ""


def _find_solver(preferred: str | None = None):
    names = (preferred,) + _SOLVER_PREFERENCE if preferred else _SOLVER_PREFERENCE
    for name in names:
        try:
            solver = pyo.SolverFactory(name)
            if solver is not None and solver.available(exception_flag=False):
                return name, solver
        except Exception:  # noqa: BLE001 - probing availability, any failure means "not this one"
            continue
    raise SolverError(
        "no solver available — `pip install highspy` provides one with no system deps"
    )


def _extract_variables(model: pyo.ConcreteModel) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for var in model.component_objects(pyo.Var, active=True):
        values: dict[str, float] = {}
        for idx in var:
            v = var[idx]
            if v.value is None:
                continue
            key = "" if idx is None else (idx if isinstance(idx, str) else ",".join(idx))
            values[key] = round(v.value, 9)
        out[str(var.name)] = values
    return out


def solve_model(
    model: pyo.ConcreteModel, solver_name: str | None = None
) -> SolveResult:
    name, solver = _find_solver(solver_name)
    logger.info("solving %s with %s", model.name, name)
    try:
        results = solver.solve(model, load_solutions=False)
    except Exception as exc:  # pragma: no cover - solver crash path
        raise SolverError(f"{name} failed: {exc}") from exc

    tc = results.solver.termination_condition
    if tc == pyo.TerminationCondition.optimal:
        model.solutions.load_from(results)
        return SolveResult(
            status="optimal",
            solver=name,
            objective=round(pyo.value(model.objective), 9),
            variables=_extract_variables(model),
        )
    if tc in (
        pyo.TerminationCondition.infeasible,
        pyo.TerminationCondition.infeasibleOrUnbounded,
    ):
        return SolveResult(status="infeasible", solver=name, message=str(tc))
    if tc == pyo.TerminationCondition.unbounded:
        return SolveResult(
            status="unbounded",
            solver=name,
            message="objective can be improved without limit — check for a missing capacity or bound",
        )
    return SolveResult(status="error", solver=name, message=str(tc))


# --------------------------------------------------------------------------
# Elastic relaxation diagnostic (simplified IIS)
# --------------------------------------------------------------------------


def _elastic_spec(spec: ModelSpec) -> ModelSpec:
    """Copy of the spec where every constraint may be violated at a price."""
    relaxed = spec.model_copy(deep=True)
    slack_terms: list[str] = []
    new_constraints: list[ConstraintDef] = []
    new_vars: list[VarDef] = []

    for c in relaxed.constraints:
        rel = parse_constraint(c.expr)
        idx_sets = [b.over for b in c.forall]
        idx_suffix = f"[{','.join(b.index for b in c.forall)}]" if c.forall else ""

        def add_slack(tag: str, _c=c, _idx_sets=idx_sets, _suffix=idx_suffix) -> str:
            name = f"slack_{tag}_{_c.name}"
            new_vars.append(
                VarDef(name=name, indexed_by=_idx_sets, domain="continuous", lower=0.0)
            )
            if _idx_sets:
                inner = f"{name}{_suffix}"
                for b in _c.forall:
                    inner = f"sum({b.index} in {b.over}, {inner})"
                slack_terms.append(inner)
            else:
                slack_terms.append(name)
            return f"{name}{_suffix}"

        if rel.op == "<=":
            c.expr = f"{c.expr} + {add_slack('up')}"
        elif rel.op == ">=":
            lhs, rhs = c.expr.split(">=", 1)
            c.expr = f"{lhs.strip()} + {add_slack('up')} >= {rhs.strip()}"
        else:  # == : allow movement both ways
            lhs, rhs = c.expr.split("==", 1)
            up, dn = add_slack("up"), add_slack("dn")
            c.expr = f"{lhs.strip()} + {up} - {dn} == {rhs.strip()}"

        new_constraints.append(c)

    relaxed.constraints = new_constraints
    relaxed.variables = relaxed.variables + new_vars
    relaxed.objective = ObjectiveDef(
        sense="minimize",
        expr=" + ".join(slack_terms),
        description="total constraint violation",
    )
    relaxed.name = f"{spec.name}_elastic"
    return relaxed


def diagnose_infeasibility(
    spec: ModelSpec, solver_name: str | None = None
) -> list[SlackReport]:
    """Solve the elastic relaxation; nonzero slacks locate the conflict."""
    elastic = _elastic_spec(spec)
    result = solve_model(compile_spec(elastic), solver_name)
    if result.status != "optimal":
        logger.warning("elastic relaxation did not solve: %s", result.message)
        return []
    reports = []
    for var_name, values in result.variables.items():
        if not var_name.startswith("slack_"):
            continue
        constraint = var_name.split("_", 2)[2]
        for idx, val in values.items():
            if val > 1e-6:
                reports.append(
                    SlackReport(constraint=constraint, index=idx, slack=round(val, 6))
                )
    return sorted(reports, key=lambda r: -r.slack)


def solve_spec(spec: ModelSpec, solver_name: str | None = None) -> SolveResult:
    """Compile and solve; on infeasibility, attach the elastic diagnostic."""
    result = solve_model(compile_spec(spec), solver_name)
    if result.status == "infeasible":
        result.infeasibility = diagnose_infeasibility(spec, solver_name)
        hints = "; ".join(r.describe() for r in result.infeasibility[:5])
        result.message = (
            f"model is infeasible — smallest total relaxation: {hints}"
            if hints
            else "model is infeasible"
        )
    return result
