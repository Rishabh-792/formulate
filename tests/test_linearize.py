import pytest

from formulate.errors import LinearizationError
from formulate.linearize import linearize
from formulate.spec import ModelSpec
from formulate.validator import validate
from tests.test_compile_solve import needs_solver


def _spec(**overrides) -> ModelSpec:
    d = {
        "name": "lin",
        "sets": [],
        "params": [],
        "variables": [
            {"name": "x", "domain": "continuous", "lower": 0.0, "upper": 10.0},
            {"name": "b", "domain": "binary"},
        ],
        "constraints": [],
        "objective": {"sense": "maximize", "expr": "x"},
    }
    d.update(overrides)
    return ModelSpec.model_validate(d)


def test_linear_spec_passes_through(production_spec):
    out, notes = linearize(production_spec)
    assert notes == []
    assert out.model_dump() == production_spec.model_dump()


def test_binary_product_big_m():
    spec = _spec(
        objective={"sense": "maximize", "expr": "b * x"},
        constraints=[{"name": "cap", "expr": "x <= 7"}],
    )
    out, notes = linearize(spec)
    assert [n.transform for n in notes] == ["binary-product-big-m"]
    names = {v.name for v in out.variables}
    assert any(n.startswith("lin_prod") for n in names)
    # 3 big-M constraints were added
    assert len(out.constraints) == 1 + 3
    assert validate(out).ok


def test_abs_epigraph_in_min_objective():
    spec = _spec(objective={"sense": "minimize", "expr": "abs(x - 4)"})
    out, notes = linearize(spec)
    assert [n.transform for n in notes] == ["abs-epigraph"]
    assert len(out.constraints) == 2
    assert validate(out).ok


def test_abs_rejected_in_max_objective():
    spec = _spec(objective={"sense": "maximize", "expr": "abs(x - 4)"})
    with pytest.raises(LinearizationError):
        linearize(spec)


def test_continuous_product_rejected():
    spec = _spec(
        variables=[
            {"name": "x", "domain": "continuous", "upper": 10.0},
            {"name": "y", "domain": "continuous", "upper": 10.0},
        ],
        objective={"sense": "maximize", "expr": "x * y"},
    )
    with pytest.raises(LinearizationError):
        linearize(spec)


@needs_solver
def test_binary_product_solves_correctly():
    """max b*x with x<=7, plus a cost for switching b on that makes b=1 optimal."""
    from formulate.solve import solve_spec

    spec = _spec(
        objective={"sense": "maximize", "expr": "b * x - 3 * b"},
        constraints=[{"name": "cap", "expr": "x <= 7"}],
    )
    out, _ = linearize(spec)
    result = solve_spec(out)
    assert result.status == "optimal"
    # optimum: b=1, x=7 -> 7 - 3 = 4
    assert result.objective == pytest.approx(4.0)


@needs_solver
def test_abs_solves_correctly():
    """min abs(x - 4) with x integer-free continuous in [0,10] -> 0 at x=4."""
    from formulate.solve import solve_spec

    spec = _spec(objective={"sense": "minimize", "expr": "abs(x - 4)"})
    out, _ = linearize(spec)
    result = solve_spec(out)
    assert result.status == "optimal"
    assert result.objective == pytest.approx(0.0)
    assert result.variables["x"][""] == pytest.approx(4.0)
