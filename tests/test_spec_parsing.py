import pytest

from formulate.errors import ExpressionSyntaxError
from formulate.spec import (
    Bin,
    Num,
    Ref,
    Sum,
    parse_constraint,
    parse_expression,
    unparse,
)


def test_precedence_and_shape():
    ast = parse_expression("a + b * c")
    assert isinstance(ast, Bin) and ast.op == "+"
    assert isinstance(ast.right, Bin) and ast.right.op == "*"


def test_indexed_ref_and_sum():
    ast = parse_expression("sum(p in P, profit[p] * make[p])")
    assert isinstance(ast, Sum)
    assert ast.index == "p" and ast.over == "P"
    assert isinstance(ast.body, Bin)
    assert ast.body.left == Ref("profit", ("p",))


def test_multi_index():
    assert parse_expression("cost[a,b]") == Ref("cost", ("a", "b"))


def test_unary_minus_and_parens():
    ast = parse_expression("-(a + 2) * 3")
    assert isinstance(ast, Bin) and ast.op == "*"
    assert isinstance(ast.right, Num)


def test_constraint_relops():
    for op in ("<=", ">=", "=="):
        rel = parse_constraint(f"x {op} 5")
        assert rel.op == op


@pytest.mark.parametrize(
    "bad",
    [
        "x +",  # dangling operator
        "sum(p, x)",  # missing 'in'
        "x[1]",  # numeric index
        "x <= y <= z",  # chained comparison
        "x $ y",  # unknown character
        "min(a, b)",  # unsupported function -> parses 'min' as ref, then '(' trails
        "",  # empty
    ],
)
def test_syntax_errors(bad):
    with pytest.raises(ExpressionSyntaxError):
        parse_constraint(bad)


@pytest.mark.parametrize(
    "text",
    [
        "a + b * c",
        "sum(p in P, profit[p] * make[p])",
        "(a + b) * (c - d)",
        "a - (b - c)",
        "a / b / c",
        "-(a + b)",
        "abs(x - y)",
        "sum(s in PLANTS, sum(w in WAREHOUSES, cost[s,w] * ship[s,w]))",
    ],
)
def test_unparse_roundtrip(text):
    ast = parse_expression(text)
    assert parse_expression(unparse(ast)) == ast


def test_constraint_unparse_roundtrip():
    rel = parse_constraint("sum(p in P, hours[p,m] * make[p]) <= capacity[m]")
    assert parse_constraint(unparse(rel)) == rel
