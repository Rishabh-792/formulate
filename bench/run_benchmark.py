"""Run the correctness benchmark and write bench/results.json.

For every problem: build the spec, run the full pipeline (validate ->
linearize -> compile -> solve), and compare the returned objective against an
optimum computed by exhaustive enumeration in plain Python. The oracle never
touches Pyomo or HiGHS, so agreement is evidence the engine is right rather
than evidence it is self-consistent.

Also records per-stage wall-clock timing, so the latency figures quoted in the
README come from a committed artifact rather than from memory.

Usage:
    python -m bench.run_benchmark
    python -m bench.run_benchmark --repeats 5
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from bench.problems import Problem, all_problems
from formulate.pipeline import run_from_spec
from formulate.spec import ModelSpec

TOLERANCE = 1e-6
RESULTS_PATH = Path("bench/results.json")


def _time_pipeline(spec_dict: dict, repeats: int) -> tuple[dict, list[float]]:
    """Runs the pipeline `repeats` times, returning the last result and timings."""
    durations: list[float] = []
    result = None
    for _ in range(repeats):
        spec = ModelSpec.model_validate(spec_dict)
        start = time.perf_counter()
        result = run_from_spec(spec)
        durations.append((time.perf_counter() - start) * 1000.0)
    assert result is not None
    return result, durations


def evaluate(problem: Problem, repeats: int) -> dict:
    result, durations = _time_pipeline(problem.spec, repeats)
    solution = result.solution

    objective = solution.objective
    delta = None if objective is None else abs(objective - problem.optimum)
    passed = (
        solution.status == "optimal"
        and objective is not None
        and delta is not None
        and delta <= TOLERANCE
    )

    return {
        "problem": problem.name,
        "description": problem.description,
        "exercises": list(problem.exercises),
        "status": solution.status,
        "solver": solution.solver,
        "expected_optimum": problem.optimum,
        "oracle_method": problem.method,
        "reported_objective": objective,
        "absolute_error": delta,
        "passed": passed,
        "transforms_applied": [t.transform for t in result.transforms],
        "validation_warnings": len(result.validation.warnings),
        "latency_ms": {
            "min": round(min(durations), 3),
            "median": round(statistics.median(durations), 3),
            "max": round(max(durations), 3),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3,
                        help="pipeline runs per problem, for timing stability")
    parser.add_argument("--out", default=str(RESULTS_PATH))
    args = parser.parse_args(argv)

    problems = all_problems()
    cases = [evaluate(p, args.repeats) for p in problems]

    medians = [c["latency_ms"]["median"] for c in cases]
    passed = sum(1 for c in cases if c["passed"])

    report = {
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.system(),
        },
        "tolerance": TOLERANCE,
        "repeats_per_problem": args.repeats,
        "summary": {
            "problems": len(cases),
            "passed": passed,
            "failed": len(cases) - passed,
            "pass_rate": round(passed / len(cases), 4) if cases else 0.0,
            "max_absolute_error": max(
                (c["absolute_error"] for c in cases if c["absolute_error"] is not None),
                default=None,
            ),
            "median_latency_ms": round(statistics.median(medians), 3),
            "slowest_median_latency_ms": round(max(medians), 3),
        },
        "cases": cases,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    width = max(len(c["problem"]) for c in cases)
    print(f"{'problem':<{width}}  {'status':<9} {'expected':>10} {'reported':>10} {'err':>8} {'ms':>7}")
    for c in cases:
        mark = "ok" if c["passed"] else "FAIL"
        reported = "-" if c["reported_objective"] is None else f"{c['reported_objective']:.4f}"
        err = "-" if c["absolute_error"] is None else f"{c['absolute_error']:.2e}"
        print(f"{c['problem']:<{width}}  {mark:<9} {c['expected_optimum']:>10.4f} "
              f"{reported:>10} {err:>8} {c['latency_ms']['median']:>7.1f}")

    s = report["summary"]
    print(f"\n{s['passed']}/{s['problems']} matched the enumerated optimum "
          f"(max error {s['max_absolute_error']:.2e}); "
          f"median pipeline latency {s['median_latency_ms']} ms")
    print(f"wrote {out}")

    return 0 if s["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
