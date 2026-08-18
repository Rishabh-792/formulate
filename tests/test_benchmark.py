"""The correctness benchmark, run as tests.

Each case compares the engine's objective against an optimum found by
exhaustive enumeration in plain Python — a solver-independent oracle, so a
match is evidence the engine is correct rather than self-consistent.
"""

from __future__ import annotations

import pytest

from bench.problems import all_problems
from bench.run_benchmark import TOLERANCE
from formulate.linearize import linearize
from formulate.pipeline import run_from_spec
from formulate.spec import ModelSpec

PROBLEMS = all_problems()


@pytest.mark.parametrize("problem", PROBLEMS, ids=[p.name for p in PROBLEMS])
def test_engine_matches_enumerated_optimum(problem):
    result = run_from_spec(ModelSpec.model_validate(problem.spec))

    assert result.solution.status == "optimal", (
        f"{problem.name}: solver returned {result.solution.status}"
    )
    assert result.solution.objective == pytest.approx(problem.optimum, abs=TOLERANCE), (
        f"{problem.name}: engine says {result.solution.objective}, "
        f"{problem.method} says {problem.optimum}"
    )


def test_abs_inside_sum_is_indexed_per_member():
    """Regression: abs() under a sum() needs one epigraph variable per index.

    The transform previously emitted a single scalar `t` plus scalar
    constraints referencing the sum's bound index, which the validator
    rejected outright ("index 'd' is neither a bound index nor a set member").
    Any model minimizing a sum of absolute deviations was unsolvable.
    """
    spec = ModelSpec.model_validate(
        next(p for p in PROBLEMS if p.name == "abs_deviation").spec
    )
    linear, notes = linearize(spec)

    epigraph = [v for v in linear.variables if v.name.startswith("lin_abs_")]
    assert epigraph, "expected an epigraph variable"
    for var in epigraph:
        assert var.indexed_by == ["D"], (
            f"{var.name} must be indexed by the enclosing sum's set, got {var.indexed_by}"
        )

    generated = [c for c in linear.constraints if c.name.startswith("lin_abs_")]
    assert len(generated) == 2, "expected one pos and one neg bound"
    for constraint in generated:
        assert [b.over for b in constraint.forall] == ["D"], (
            f"{constraint.name} must be quantified over D, got {constraint.forall}"
        )

    assert any(n.transform == "abs-epigraph" for n in notes)


def test_abs_in_a_plain_constraint_stays_scalar():
    """The indexed path must not regress the scalar one."""
    spec = ModelSpec.model_validate(
        {
            "name": "scalar_abs",
            "sets": [],
            "params": [{"name": "target", "indexed_by": [], "values": 10.0}],
            "variables": [
                {"name": "x", "indexed_by": [], "domain": "continuous",
                 "lower": 0.0, "upper": 100.0}
            ],
            "constraints": [
                {"name": "near_target", "forall": [], "expr": "abs(x - target) <= 3"}
            ],
            "objective": {"sense": "maximize", "expr": "x"},
        }
    )
    linear, _ = linearize(spec)

    epigraph = [v for v in linear.variables if v.name.startswith("lin_abs_")]
    assert epigraph and all(v.indexed_by == [] for v in epigraph)
    assert all(c.forall == [] for c in linear.constraints if c.name.startswith("lin_abs_"))

    result = run_from_spec(spec)
    assert result.solution.status == "optimal"
    # |x - 10| <= 3 with x maximized puts the optimum at 13.
    assert result.solution.objective == pytest.approx(13.0, abs=TOLERANCE)


def _abs_spec(
    forall: list[dict],
    expr: str,
    extra_sets: list[dict],
    extra_params: list[dict] | None = None,
) -> ModelSpec:
    extra_params = extra_params or []
    return ModelSpec.model_validate(
        {
            "name": "abs_scope",
            "sets": [{"name": "D", "members": ["a", "b", "c"]}, *extra_sets],
            "params": [{"name": "cap", "indexed_by": [], "values": 50.0}, *extra_params],
            "variables": [
                {"name": "x", "indexed_by": ["D"], "domain": "continuous",
                 "lower": 0.0, "upper": 10.0}
            ],
            "constraints": [{"name": "c", "forall": forall, "expr": expr}],
            "objective": {"sense": "minimize", "expr": "sum(d in D, x[d])"},
        }
    )


def test_abs_inherits_the_constraints_own_forall():
    """A constraint's forall must reach the epigraph variable.

    Previously untested: instrumenting the whole suite showed the binding
    stack only ever held () or (('d','D'),), so the line that seeds the stack
    from `c.forall` could be deleted with every test still passing.
    """
    spec = _abs_spec([{"index": "d", "over": "D"}], "abs(x[d] - 2) <= cap", [])
    linear, _ = linearize(spec)

    epigraph = [v for v in linear.variables if v.name.startswith("lin_abs_")]
    assert [v.indexed_by for v in epigraph] == [["D"]]
    generated = [c for c in linear.constraints if c.name.startswith("lin_abs_")]
    assert all([b.over for b in c.forall] == ["D"] for c in generated)
    assert run_from_spec(spec).solution.status == "optimal"


def test_abs_composes_constraint_forall_with_an_enclosing_sum():
    """Both scopes, outermost first, matching the subscript order."""
    spec = _abs_spec(
        [{"index": "d", "over": "D"}],
        "sum(e in E, abs(x[d] - target[e])) <= cap",
        [{"name": "E", "members": ["e1", "e2"]}],
        [{"name": "target", "indexed_by": ["E"], "values": {"e1": 2.0, "e2": 5.0}}],
    )
    linear, _ = linearize(spec)

    epigraph = [v for v in linear.variables if v.name.startswith("lin_abs_")]
    assert [v.indexed_by for v in epigraph] == [["D", "E"]]
    generated = [c for c in linear.constraints if c.name.startswith("lin_abs_")]
    assert all([b.index for b in c.forall] == ["d", "e"] for c in generated)
    assert run_from_spec(spec).solution.status == "optimal"


def test_epigraph_is_not_indexed_by_bindings_the_operand_ignores():
    """Indexing by every enclosing binding is correct but multiplicative.

    `forall (i in I, j in J)` around `sum(k in K, abs(x[k] - 1))` created
    |I|*|J|*|K| epigraph variables where |K| suffice - 8000 against 20 at
    size 20, which turns an easy MILP into a large one.
    """
    spec = ModelSpec.model_validate(
        {
            "name": "over_indexing",
            "sets": [
                {"name": "I", "members": ["i1", "i2"]},
                {"name": "J", "members": ["j1", "j2"]},
                {"name": "K", "members": ["k1", "k2"]},
            ],
            "params": [{"name": "cap", "indexed_by": [], "values": 100.0}],
            "variables": [
                {"name": "x", "indexed_by": ["K"], "domain": "continuous",
                 "lower": 0.0, "upper": 10.0}
            ],
            "constraints": [
                {
                    "name": "c",
                    "forall": [{"index": "i", "over": "I"}, {"index": "j", "over": "J"}],
                    "expr": "sum(k in K, abs(x[k] - 1)) <= cap",
                }
            ],
            "objective": {"sense": "minimize", "expr": "sum(k in K, x[k])"},
        }
    )
    linear, _ = linearize(spec)

    epigraph = [v for v in linear.variables if v.name.startswith("lin_abs_")]
    # Only K: the operand references x[k] and nothing bound by I or J.
    assert [v.indexed_by for v in epigraph] == [["K"]]
    assert run_from_spec(spec).solution.status == "optimal"
