import pytest

from formulate.errors import InterpreterError
from formulate.interpreter import MockInterpreter
from tests.test_compile_solve import needs_solver

NL_PRODUCTION = (
    "We make chairs, tables and desks on two machines and want to maximize "
    "profit given machine capacity."
)
NL_TRANSPORT = "Ship pallets from two plants to three warehouses at minimum cost."


def test_mock_interpreter_routes_by_keyword():
    mock = MockInterpreter()
    assert mock.interpret(NL_PRODUCTION).name == "meridian_production"
    assert mock.interpret(NL_TRANSPORT).name == "northlake_distribution"


def test_mock_interpreter_rejects_unknown():
    with pytest.raises(InterpreterError):
        MockInterpreter().interpret("write me a poem about ducks")


@needs_solver
def test_keyless_end_to_end():
    from formulate.pipeline import run_from_text

    res = run_from_text(NL_PRODUCTION)
    assert res.mode == "mock"
    assert res.validation.ok
    assert res.solution.status == "optimal"
    assert res.solution.objective == pytest.approx(5450.0)
    assert "5,450" in res.explanation


@needs_solver
def test_cli_demo(capsys, production_spec, tmp_path):
    from formulate.pipeline import main

    spec_file = tmp_path / "spec.json"
    spec_file.write_text(production_spec.to_json(), encoding="utf-8")
    assert main([str(spec_file)]) == 0
    out = capsys.readouterr().out
    assert "optimal" in out
    assert "5,450" in out


@needs_solver
def test_api_solve_roundtrip():
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    assert client.get("/healthz").json()["mode"] == "mock"
    examples = client.get("/examples").json()
    assert set(examples) == {"production_planning", "transportation"}

    r = client.post("/solve", json={"problem": NL_TRANSPORT})
    assert r.status_code == 200
    body = r.json()
    assert body["solution"]["status"] == "optimal"
    assert body["solution"]["objective"] == pytest.approx(450.0)

    bad = client.post("/validate", json={**examples["production_planning"], "params": []})
    assert bad.status_code == 200
    assert any(i["code"] == "unknown-symbol" for i in bad.json()["issues"])
