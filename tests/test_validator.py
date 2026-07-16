from formulate.spec import ModelSpec
from formulate.validator import validate


def _codes(report):
    return {i.code for i in report.errors}


def _base() -> dict:
    return {
        "name": "t",
        "sets": [{"name": "P", "members": ["a", "b"]}],
        "params": [
            {"name": "profit", "indexed_by": ["P"], "values": {"a": 1, "b": 2}}
        ],
        "variables": [{"name": "make", "indexed_by": ["P"]}],
        "constraints": [
            {
                "name": "cap",
                "forall": [{"index": "p", "over": "P"}],
                "expr": "make[p] <= 10",
            }
        ],
        "objective": {"sense": "maximize", "expr": "sum(p in P, profit[p] * make[p])"},
    }


def test_valid_spec_passes(production_spec, transportation_spec):
    assert validate(production_spec).ok
    assert validate(transportation_spec).ok


def test_unknown_symbol():
    d = _base()
    d["objective"]["expr"] = "sum(p in P, price[p] * make[p])"
    assert "unknown-symbol" in _codes(validate(ModelSpec.model_validate(d)))


def test_unknown_set_in_forall():
    d = _base()
    d["constraints"][0]["forall"] = [{"index": "p", "over": "Q"}]
    assert "unknown-set" in _codes(validate(ModelSpec.model_validate(d)))


def test_index_arity():
    d = _base()
    d["constraints"][0]["expr"] = "make[p,p] <= 10"
    assert "index-arity" in _codes(validate(ModelSpec.model_validate(d)))


def test_param_missing_values():
    d = _base()
    d["params"][0]["values"] = {"a": 1}
    assert "missing-values" in _codes(validate(ModelSpec.model_validate(d)))


def test_param_extra_values():
    d = _base()
    d["params"][0]["values"] = {"a": 1, "b": 2, "zz": 3}
    assert "extra-values" in _codes(validate(ModelSpec.model_validate(d)))


def test_degenerate_bounds():
    d = _base()
    d["variables"][0]["lower"] = 5
    d["variables"][0]["upper"] = 1
    assert "degenerate-bounds" in _codes(validate(ModelSpec.model_validate(d)))


def test_duplicate_names():
    d = _base()
    d["params"].append({"name": "make", "indexed_by": [], "values": 1.0})
    assert "duplicate-name" in _codes(validate(ModelSpec.model_validate(d)))


def test_constant_objective():
    d = _base()
    d["objective"]["expr"] = "sum(p in P, profit[p])"
    assert "constant-objective" in _codes(validate(ModelSpec.model_validate(d)))


def test_index_set_mismatch():
    d = _base()
    d["sets"].append({"name": "M", "members": ["m1"]})
    d["constraints"][0]["forall"] = [{"index": "p", "over": "M"}]
    assert "index-set-mismatch" in _codes(validate(ModelSpec.model_validate(d)))


def test_unknown_literal_member():
    d = _base()
    d["constraints"][0]["forall"] = []
    d["constraints"][0]["expr"] = "make[nope] <= 10"
    assert "unknown-index" in _codes(validate(ModelSpec.model_validate(d)))


def test_syntax_error_reported_not_raised():
    d = _base()
    d["constraints"][0]["expr"] = "make[p] <= <="
    report = validate(ModelSpec.model_validate(d))
    assert "syntax" in _codes(report)
    assert not report.ok
