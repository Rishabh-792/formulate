"""Deterministic compiler: ModelSpec -> Pyomo ConcreteModel.

Two outputs from the same walk of the spec:
  * `compile_spec`   — the live ConcreteModel the solver consumes
  * `emit_pyomo_source` — equivalent standalone Python source, for humans

Multi-dimensional components are indexed by tuples of member strings.
"""

from __future__ import annotations

import pyomo.environ as pyo

from .errors import CompilationError
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

_DOMAINS = {
    "continuous": pyo.Reals,
    "integer": pyo.Integers,
    "binary": pyo.Binary,
}


def _key(parts: tuple[str, ...]):
    """Pyomo indexes 1-D components by scalars, N-D by tuples."""
    return parts[0] if len(parts) == 1 else parts


def _param_init(values: dict[str, float]) -> dict:
    return {_key(tuple(k.split(","))): v for k, v in values.items()}


def _eval(node: Expr | Rel, m: pyo.ConcreteModel, env: dict[str, str]):
    """Evaluate an AST into a Pyomo expression; `env` binds index names."""
    if isinstance(node, Num):
        return node.value
    if isinstance(node, Ref):
        comp = getattr(m, node.name, None)
        if comp is None:
            raise CompilationError(f"unknown symbol '{node.name}'")
        if not node.indices:
            return comp
        resolved = tuple(env.get(i, i) for i in node.indices)
        return comp[_key(resolved)]
    if isinstance(node, Neg):
        return -_eval(node.operand, m, env)
    if isinstance(node, Bin):
        left, right = _eval(node.left, m, env), _eval(node.right, m, env)
        if node.op == "+":
            return left + right
        if node.op == "-":
            return left - right
        if node.op == "*":
            return left * right
        return left / right
    if isinstance(node, Sum):
        members = getattr(m, node.over)
        return sum(_eval(node.body, m, {**env, node.index: v}) for v in members)
    if isinstance(node, Abs):
        raise CompilationError(
            "abs() is not directly compilable — run the linearizer first"
        )
    if isinstance(node, Rel):
        left, right = _eval(node.left, m, env), _eval(node.right, m, env)
        if node.op == "<=":
            return left <= right
        if node.op == ">=":
            return left >= right
        return left == right
    raise CompilationError(f"unknown AST node {node!r}")


def compile_spec(spec: ModelSpec) -> pyo.ConcreteModel:
    m = pyo.ConcreteModel(name=spec.name)

    for s in spec.sets:
        setattr(m, s.name, pyo.Set(initialize=s.members, ordered=True))

    for p in spec.params:
        idx_sets = [getattr(m, n) for n in p.indexed_by]
        init = _param_init(p.values) if idx_sets else p.values  # type: ignore[arg-type]
        setattr(m, p.name, pyo.Param(*idx_sets, initialize=init, within=pyo.Reals))

    for v in spec.variables:
        idx_sets = [getattr(m, n) for n in v.indexed_by]
        kwargs: dict = {"domain": _DOMAINS[v.domain]}
        if v.domain != "binary":
            kwargs["bounds"] = (v.lower, v.upper)
        setattr(m, v.name, pyo.Var(*idx_sets, **kwargs))

    for c in spec.constraints:
        rel = parse_constraint(c.expr)
        idx_sets = [getattr(m, b.over) for b in c.forall]
        idx_names = [b.index for b in c.forall]
        if idx_sets:

            def rule(_m, *members, _rel=rel, _names=tuple(idx_names)):
                return _eval(_rel, _m, dict(zip(_names, members, strict=True)))

            setattr(m, c.name, pyo.Constraint(*idx_sets, rule=rule))
        else:
            setattr(m, c.name, pyo.Constraint(expr=_eval(rel, m, {})))

    obj_expr = _eval(parse_expression(spec.objective.expr), m, {})
    m.objective = pyo.Objective(
        expr=obj_expr,
        sense=pyo.maximize if spec.objective.sense == "maximize" else pyo.minimize,
    )
    return m


# --------------------------------------------------------------------------
# Source emitter — the same walk, rendered as standalone Python
# --------------------------------------------------------------------------


def _safe(index: str) -> str:
    """Bound indices become Python identifiers; 'm' would shadow the model."""
    return f"{index}_idx" if index == "m" else index


def _py(node: Expr | Rel, names: dict[str, str]) -> str:
    """Render an AST as Pyomo-flavoured Python source.

    `names` maps bound index -> the Python identifier it is emitted as;
    unbound indices are literal set members and rendered as strings.
    """
    if isinstance(node, Num):
        return str(int(node.value)) if node.value == int(node.value) else str(node.value)
    if isinstance(node, Ref):
        if not node.indices:
            return f"m.{node.name}"
        parts = [names.get(i, f"'{i}'") for i in node.indices]
        return f"m.{node.name}[{', '.join(parts)}]"
    if isinstance(node, Neg):
        return f"-({_py(node.operand, names)})"
    if isinstance(node, Bin):
        return f"({_py(node.left, names)} {node.op} {_py(node.right, names)})"
    if isinstance(node, Sum):
        bound = _safe(node.index)
        inner = _py(node.body, {**names, node.index: bound})
        return f"sum({inner} for {bound} in m.{node.over})"
    if isinstance(node, Abs):
        return f"abs({_py(node.operand, names)})  # requires linearization"
    if isinstance(node, Rel):
        return f"{_py(node.left, names)} {node.op} {_py(node.right, names)}"
    raise CompilationError(f"unknown AST node {node!r}")


def emit_pyomo_source(spec: ModelSpec) -> str:
    lines = [
        '"""Generated by Formulate — deterministic output of compile.emit_pyomo_source."""',
        "import pyomo.environ as pyo",
        "",
        f"m = pyo.ConcreteModel(name={spec.name!r})",
        "",
    ]
    for s in spec.sets:
        lines.append(f"m.{s.name} = pyo.Set(initialize={s.members!r}, ordered=True)")
    for p in spec.params:
        idx = ", ".join(f"m.{n}" for n in p.indexed_by)
        init = _param_init(p.values) if p.indexed_by else p.values  # type: ignore[arg-type]
        prefix = f"{idx}, " if idx else ""
        lines.append(f"m.{p.name} = pyo.Param({prefix}initialize={init!r})")
    for v in spec.variables:
        idx = ", ".join(f"m.{n}" for n in v.indexed_by)
        prefix = f"{idx}, " if idx else ""
        if v.domain == "binary":
            lines.append(f"m.{v.name} = pyo.Var({prefix}domain=pyo.Binary)")
        else:
            dom = "pyo.Integers" if v.domain == "integer" else "pyo.Reals"
            lines.append(
                f"m.{v.name} = pyo.Var({prefix}domain={dom}, bounds=({v.lower}, {v.upper}))"
            )
    lines.append("")
    for c in spec.constraints:
        rel = parse_constraint(c.expr)
        if c.forall:
            args = ", ".join(_safe(b.index) for b in c.forall)
            sets = ", ".join(f"m.{b.over}" for b in c.forall)
            names = {b.index: _safe(b.index) for b in c.forall}
            lines.append(f"def {c.name}_rule(m, {args}):")
            lines.append(f"    return {_py(rel, names)}")
            lines.append(f"m.{c.name} = pyo.Constraint({sets}, rule={c.name}_rule)")
        else:
            lines.append(f"m.{c.name} = pyo.Constraint(expr={_py(rel, {})})")
        lines.append("")
    sense = "pyo.maximize" if spec.objective.sense == "maximize" else "pyo.minimize"
    obj = _py(parse_expression(spec.objective.expr), {})
    lines.append(f"m.objective = pyo.Objective(expr={obj}, sense={sense})")
    return "\n".join(lines) + "\n"
