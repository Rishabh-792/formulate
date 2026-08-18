"""End-to-end: both bundled examples compile and solve to their known optima.

The optima are derived by hand in examples/*.md — if these numbers move,
either the fixture data changed or the compiler broke.
"""

import pyomo.environ as pyo
import pytest

from formulate.compile import compile_spec, emit_pyomo_source
from formulate.solve import solve_model, solve_spec


def _solver_available() -> bool:
    for name in ("appsi_highs", "cbc", "glpk"):
        try:
            if pyo.SolverFactory(name).available(exception_flag=False):
                return True
        except Exception:
            continue
    return False


needs_solver = pytest.mark.skipif(not _solver_available(), reason="no LP solver installed")


def test_compile_production(production_spec):
    m = compile_spec(production_spec)
    assert isinstance(m, pyo.ConcreteModel)
    assert len(list(m.component_objects(pyo.Var))) == 1
    assert len(m.machine_capacity) == 2
    assert len(m.demand_limit) == 3


def test_emit_source_mentions_every_component(production_spec):
    src = emit_pyomo_source(production_spec)
    for name in ("m.P", "m.M", "m.profit", "m.make", "machine_capacity", "m.objective"):
        assert name in src


@needs_solver
def test_solve_production_known_optimum(production_spec):
    result = solve_spec(production_spec)
    assert result.status == "optimal"
    assert result.objective == pytest.approx(5450.0)
    make = result.variables["make"]
    assert make["chair"] == pytest.approx(40.0)
    assert make["table"] == pytest.approx(20.0)
    assert make["desk"] == pytest.approx(30.0)


@needs_solver
def test_solve_transportation_known_optimum(transportation_spec):
    result = solve_spec(transportation_spec)
    assert result.status == "optimal"
    assert result.objective == pytest.approx(450.0)
    ship = result.variables["ship"]
    assert ship["brightmoor,eastvale"] == pytest.approx(50.0)
    assert ship["avonford,carverton"] == pytest.approx(50.0)
    # total flow into dunmore covers demand regardless of which lane tops up
    assert ship["avonford,dunmore"] + ship["brightmoor,dunmore"] == pytest.approx(40.0)


@needs_solver
def test_emitted_source_is_executable(production_spec):
    ns: dict = {}
    exec(emit_pyomo_source(production_spec), ns)
    m = ns["m"]
    assert isinstance(m, pyo.ConcreteModel)
    result = solve_model(m)
    assert result.objective == pytest.approx(5450.0)
