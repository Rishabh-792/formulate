import pytest

from formulate.spec import ModelSpec
from tests.test_compile_solve import needs_solver


def _infeasible_spec() -> ModelSpec:
    """Demand (60) exceeds capacity (40): no plan can satisfy both."""
    return ModelSpec.model_validate(
        {
            "name": "overbooked",
            "sets": [{"name": "P", "members": ["a", "b"]}],
            "params": [
                {"name": "need", "indexed_by": ["P"], "values": {"a": 30, "b": 30}}
            ],
            "variables": [{"name": "make", "indexed_by": ["P"], "lower": 0.0}],
            "constraints": [
                {
                    "name": "meet_demand",
                    "forall": [{"index": "p", "over": "P"}],
                    "expr": "make[p] >= need[p]",
                },
                {
                    "name": "total_capacity",
                    "expr": "sum(p in P, make[p]) <= 40",
                },
            ],
            "objective": {"sense": "minimize", "expr": "sum(p in P, make[p])"},
        }
    )


@needs_solver
def test_infeasible_status_and_diagnostic():
    from formulate.solve import solve_spec

    result = solve_spec(_infeasible_spec())
    assert result.status == "infeasible"
    assert result.infeasibility, "elastic diagnostic should find nonzero slacks"
    # the minimum total relaxation is exactly 20 units, wherever it lands
    assert sum(r.slack for r in result.infeasibility) == pytest.approx(20.0)
    named = {r.constraint for r in result.infeasibility}
    assert named <= {"meet_demand", "total_capacity"}
    assert "relaxed" in result.message


@needs_solver
def test_feasible_spec_has_no_diagnostic(production_spec):
    from formulate.solve import solve_spec

    result = solve_spec(production_spec)
    assert result.status == "optimal"
    assert result.infeasibility == []
