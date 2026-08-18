"""Benchmark problems, each paired with an independent optimum.

The point of this module is that the expected answer is **not** produced by
Pyomo or HiGHS. Every discrete problem here is small enough to enumerate
exhaustively in plain Python, so the benchmark compares the engine against a
solver-independent oracle rather than against itself.

Spec and oracle are built from the same literal data, so they cannot drift
apart; only the *method* of finding the optimum differs.

Each entry exposes:
    name        identifier
    spec()      a ModelSpec-shaped dict
    optimum()   the objective value, by exhaustive enumeration
    method      how the oracle found it (recorded in results.json)
    exercises   which engine features the problem covers
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Problem:
    name: str
    description: str
    spec: dict[str, Any]
    optimum: float
    method: str
    exercises: tuple[str, ...]


# ---------------------------------------------------------------------------
# 1. Binary knapsack - 2^8 = 256 combinations
# ---------------------------------------------------------------------------

_KNAPSACK_ITEMS = {
    "generator": (41, 12),
    "compressor": (50, 15),
    "welder": (28, 8),
    "lathe": (65, 22),
    "press": (33, 11),
    "scanner": (19, 5),
    "furnace": (72, 27),
    "conveyor": (44, 14),
}
_KNAPSACK_CAPACITY = 60


def _knapsack() -> Problem:
    names = list(_KNAPSACK_ITEMS)
    best = 0.0
    for picks in itertools.product([0, 1], repeat=len(names)):
        weight = sum(p * _KNAPSACK_ITEMS[n][1] for p, n in zip(picks, names, strict=True))
        if weight <= _KNAPSACK_CAPACITY:
            value = sum(p * _KNAPSACK_ITEMS[n][0] for p, n in zip(picks, names, strict=True))
            best = max(best, value)

    spec = {
        "name": "capital_equipment_knapsack",
        "description": "Choose equipment to buy within a capital budget, maximizing rated output.",
        "sets": [{"name": "I", "members": names, "description": "candidate machines"}],
        "params": [
            {"name": "value", "indexed_by": ["I"],
             "values": {n: float(v) for n, (v, _) in _KNAPSACK_ITEMS.items()}},
            {"name": "cost", "indexed_by": ["I"],
             "values": {n: float(w) for n, (_, w) in _KNAPSACK_ITEMS.items()}},
            {"name": "budget", "indexed_by": [], "values": float(_KNAPSACK_CAPACITY)},
        ],
        "variables": [
            {"name": "buy", "indexed_by": ["I"], "domain": "binary",
             "lower": 0.0, "upper": 1.0, "description": "purchase decision"}
        ],
        "constraints": [
            {"name": "budget_limit", "forall": [],
             "expr": "sum(i in I, cost[i] * buy[i]) <= budget",
             "description": "total spend cannot exceed the budget"}
        ],
        "objective": {"sense": "maximize", "expr": "sum(i in I, value[i] * buy[i])",
                      "description": "total rated output"},
    }
    return Problem(
        name="knapsack",
        description="0/1 knapsack over 8 machines",
        spec=spec,
        optimum=float(best),
        method="exhaustive enumeration of 2^8 = 256 subsets",
        exercises=("binary domain", "scalar param", "unindexed constraint"),
    )


# ---------------------------------------------------------------------------
# 2. Assignment - 4! = 24 permutations
# ---------------------------------------------------------------------------

_WORKERS = ["ana", "ben", "chi", "dee"]
_TASKS = ["calibrate", "inspect", "package", "ship"]
_COST = {
    ("ana", "calibrate"): 13, ("ana", "inspect"): 4, ("ana", "package"): 7, ("ana", "ship"): 6,
    ("ben", "calibrate"): 1, ("ben", "inspect"): 11, ("ben", "package"): 5, ("ben", "ship"): 4,
    ("chi", "calibrate"): 6, ("chi", "inspect"): 7, ("chi", "package"): 2, ("chi", "ship"): 8,
    ("dee", "calibrate"): 1, ("dee", "inspect"): 3, ("dee", "package"): 5, ("dee", "ship"): 9,
}


def _assignment() -> Problem:
    best = min(
        sum(_COST[(w, t)] for w, t in zip(_WORKERS, perm, strict=True))
        for perm in itertools.permutations(_TASKS)
    )

    spec = {
        "name": "shift_assignment",
        "description": "Assign each technician exactly one station, minimizing total time.",
        "sets": [
            {"name": "W", "members": _WORKERS, "description": "technicians"},
            {"name": "T", "members": _TASKS, "description": "stations"},
        ],
        "params": [
            {"name": "time", "indexed_by": ["W", "T"],
             "values": {f"{w},{t}": float(c) for (w, t), c in _COST.items()}}
        ],
        "variables": [
            {"name": "assign", "indexed_by": ["W", "T"], "domain": "binary",
             "lower": 0.0, "upper": 1.0, "description": "technician works station"}
        ],
        "constraints": [
            {"name": "one_station_each", "forall": [{"index": "w", "over": "W"}],
             "expr": "sum(t in T, assign[w,t]) == 1",
             "description": "every technician takes exactly one station"},
            {"name": "one_worker_each", "forall": [{"index": "t", "over": "T"}],
             "expr": "sum(w in W, assign[w,t]) == 1",
             "description": "every station gets exactly one technician"},
        ],
        "objective": {"sense": "minimize",
                      "expr": "sum(w in W, sum(t in T, time[w,t] * assign[w,t]))",
                      "description": "total technician-minutes"},
    }
    return Problem(
        name="assignment",
        description="4x4 assignment problem",
        spec=spec,
        optimum=float(best),
        method="exhaustive enumeration of 4! = 24 permutations",
        exercises=("binary domain", "2-D indexed param", "equality constraints", "nested sum"),
    )


# ---------------------------------------------------------------------------
# 3. Set cover - 2^6 = 64 combinations
# ---------------------------------------------------------------------------

_SITES = ["north", "south", "east", "west", "central", "harbor"]
_REGIONS = ["r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8"]
_SITE_COST = {"north": 9, "south": 7, "east": 12, "west": 6, "central": 15, "harbor": 8}
_COVERS = {
    "north": {"r1", "r2", "r3"},
    "south": {"r3", "r4", "r5"},
    "east": {"r5", "r6"},
    "west": {"r1", "r7"},
    "central": {"r2", "r4", "r6", "r8"},
    "harbor": {"r7", "r8"},
}


def _set_cover() -> Problem:
    best = None
    for k in range(len(_SITES) + 1):
        for combo in itertools.combinations(_SITES, k):
            covered: set[str] = set()
            for s in combo:
                covered |= _COVERS[s]
            if covered >= set(_REGIONS):
                cost = sum(_SITE_COST[s] for s in combo)
                best = cost if best is None else min(best, cost)
    assert best is not None, "instance must be coverable"

    spec = {
        "name": "depot_set_cover",
        "description": "Open the cheapest set of depots so that every region is served.",
        "sets": [
            {"name": "S", "members": _SITES, "description": "candidate depots"},
            {"name": "R", "members": _REGIONS, "description": "regions to serve"},
        ],
        "params": [
            {"name": "opencost", "indexed_by": ["S"],
             "values": {s: float(c) for s, c in _SITE_COST.items()}},
            {"name": "serves", "indexed_by": ["S", "R"],
             "values": {f"{s},{r}": (1.0 if r in _COVERS[s] else 0.0)
                        for s in _SITES for r in _REGIONS}},
        ],
        "variables": [
            {"name": "open", "indexed_by": ["S"], "domain": "binary",
             "lower": 0.0, "upper": 1.0, "description": "depot is opened"}
        ],
        "constraints": [
            {"name": "cover_every_region", "forall": [{"index": "r", "over": "R"}],
             "expr": "sum(s in S, serves[s,r] * open[s]) >= 1",
             "description": "each region is served by at least one open depot"}
        ],
        "objective": {"sense": "minimize", "expr": "sum(s in S, opencost[s] * open[s])",
                      "description": "total opening cost"},
    }
    return Problem(
        name="set_cover",
        description="6-depot set cover over 8 regions",
        spec=spec,
        optimum=float(best),
        method="exhaustive enumeration of 2^6 = 64 depot subsets",
        exercises=("binary domain", "0/1 incidence param", ">= constraint"),
    )


# ---------------------------------------------------------------------------
# 4. Bounded integer production - grid enumeration
# ---------------------------------------------------------------------------

_PRODUCTS = ["pump", "valve", "gauge"]
_MARGIN = {"pump": 90.0, "valve": 35.0, "gauge": 20.0}
_MACHINE_H = {"pump": 4.0, "valve": 2.0, "gauge": 1.0}
_LABOR_H = {"pump": 3.0, "valve": 3.0, "gauge": 1.0}
_MACHINE_CAP, _LABOR_CAP, _MAX_EACH = 40.0, 36.0, 12


def _integer_production() -> Problem:
    best = 0.0
    rng = range(_MAX_EACH + 1)
    for qty in itertools.product(rng, repeat=len(_PRODUCTS)):
        plan = dict(zip(_PRODUCTS, qty, strict=True))
        if sum(_MACHINE_H[p] * n for p, n in plan.items()) > _MACHINE_CAP:
            continue
        if sum(_LABOR_H[p] * n for p, n in plan.items()) > _LABOR_CAP:
            continue
        best = max(best, sum(_MARGIN[p] * n for p, n in plan.items()))

    spec = {
        "name": "integer_production",
        "description": "Whole units only: machine and labour hours both bind.",
        "sets": [{"name": "P", "members": _PRODUCTS, "description": "products"}],
        "params": [
            {"name": "margin", "indexed_by": ["P"], "values": dict(_MARGIN)},
            {"name": "mhours", "indexed_by": ["P"], "values": dict(_MACHINE_H)},
            {"name": "lhours", "indexed_by": ["P"], "values": dict(_LABOR_H)},
            {"name": "mcap", "indexed_by": [], "values": _MACHINE_CAP},
            {"name": "lcap", "indexed_by": [], "values": _LABOR_CAP},
        ],
        "variables": [
            {"name": "build", "indexed_by": ["P"], "domain": "integer",
             "lower": 0.0, "upper": float(_MAX_EACH), "description": "whole units built"}
        ],
        "constraints": [
            {"name": "machine_hours", "forall": [],
             "expr": "sum(p in P, mhours[p] * build[p]) <= mcap",
             "description": "machine capacity"},
            {"name": "labor_hours", "forall": [],
             "expr": "sum(p in P, lhours[p] * build[p]) <= lcap",
             "description": "labour capacity"},
        ],
        "objective": {"sense": "maximize", "expr": "sum(p in P, margin[p] * build[p])",
                      "description": "total contribution margin"},
    }
    return Problem(
        name="integer_production",
        description="3-product integer production plan",
        spec=spec,
        optimum=float(best),
        method=f"exhaustive enumeration of {(_MAX_EACH + 1) ** 3} integer grid points",
        exercises=("integer domain", "variable upper bounds", "multiple scalar params"),
    )


# ---------------------------------------------------------------------------
# 5. Absolute-deviation staffing - exercises the abs() epigraph transform
# ---------------------------------------------------------------------------

_SHIFTS = ["mon", "tue", "wed", "thu"]
_TARGET = {"mon": 7.0, "tue": 4.0, "wed": 9.0, "thu": 5.0}
_HEADCOUNT = 20
_MAX_PER_SHIFT = 10


def _abs_deviation() -> Problem:
    best = None
    rng = range(_MAX_PER_SHIFT + 1)
    for staff in itertools.product(rng, repeat=len(_SHIFTS)):
        if sum(staff) != _HEADCOUNT:
            continue
        dev = sum(abs(n - _TARGET[s]) for n, s in zip(staff, _SHIFTS, strict=True))
        best = dev if best is None else min(best, dev)
    assert best is not None, "instance must be feasible"

    spec = {
        "name": "shift_balancing",
        "description": "Spread a fixed headcount across shifts, minimizing total deviation from demand.",
        "sets": [{"name": "D", "members": _SHIFTS, "description": "shifts"}],
        "params": [
            {"name": "target", "indexed_by": ["D"], "values": dict(_TARGET)},
            {"name": "headcount", "indexed_by": [], "values": float(_HEADCOUNT)},
        ],
        "variables": [
            {"name": "staff", "indexed_by": ["D"], "domain": "integer",
             "lower": 0.0, "upper": float(_MAX_PER_SHIFT), "description": "people rostered"}
        ],
        "constraints": [
            {"name": "use_everyone", "forall": [],
             "expr": "sum(d in D, staff[d]) == headcount",
             "description": "the whole team is rostered"}
        ],
        "objective": {"sense": "minimize",
                      "expr": "sum(d in D, abs(staff[d] - target[d]))",
                      "description": "total absolute deviation from demand"},
    }
    return Problem(
        name="abs_deviation",
        description="shift balancing with absolute deviations",
        spec=spec,
        optimum=float(best),
        method=f"exhaustive enumeration of {(_MAX_PER_SHIFT + 1) ** 4} rosters",
        exercises=("abs() epigraph transform", "integer domain", "equality constraint"),
    )


BUILDERS: tuple[Callable[[], Problem], ...] = (
    _knapsack,
    _assignment,
    _set_cover,
    _integer_production,
    _abs_deviation,
)


def all_problems() -> list[Problem]:
    return [build() for build in BUILDERS]
