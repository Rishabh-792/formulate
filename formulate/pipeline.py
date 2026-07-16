"""Pipeline orchestrator: NL text (or a ready spec) -> explained solution.

    interpret -> validate -> linearize -> compile -> solve -> explain

CLI (keyless demo):
    python -m formulate.pipeline examples/production_planning.spec.json
    python -m formulate.pipeline --text "We make chairs, tables and desks..."
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from pydantic import BaseModel

from .compile import emit_pyomo_source
from .errors import FormulateError, SpecValidationError
from .explain import get_explainer
from .interpreter import get_interpreter
from .linearize import TransformNote, linearize
from .llm import get_settings
from .solve import SolveResult, solve_spec
from .spec import ModelSpec
from .validator import ValidationReport, validate

logger = logging.getLogger(__name__)


class PipelineResult(BaseModel):
    """Everything each stage produced — the full artifact bundle."""

    mode: str
    spec: ModelSpec
    validation: ValidationReport
    transforms: list[TransformNote]
    pyomo_source: str
    solution: SolveResult
    explanation: str


def run_from_spec(spec: ModelSpec) -> PipelineResult:
    """Deterministic tail of the pipeline (no LLM involved past this point)."""
    report = validate(spec)
    if not report.ok:
        raise SpecValidationError(report.summary())

    linear_spec, notes = linearize(spec)
    if notes:
        # re-validate: transforms emit new vars/constraints and must obey
        # the same contract the LLM does
        re_report = validate(linear_spec)
        if not re_report.ok:  # pragma: no cover - would be a linearizer bug
            raise SpecValidationError(re_report.summary())

    source = emit_pyomo_source(linear_spec)
    result = solve_spec(linear_spec, get_settings().formulate_solver or None)
    explanation = get_explainer().explain(spec, result)
    return PipelineResult(
        mode=get_settings().mode,
        spec=spec,
        validation=report,
        transforms=notes,
        pyomo_source=source,
        solution=result,
        explanation=explanation,
    )


def run_from_text(problem: str) -> PipelineResult:
    spec = get_interpreter().interpret(problem)
    return run_from_spec(spec)


def _print_result(res: PipelineResult) -> None:
    print(f"mode: {res.mode}")
    print(f"validation: {res.validation.summary()}")
    for note in res.transforms:
        print(f"linearizer: [{note.transform}] {note.location}: {note.detail}")
    print(f"solver: {res.solution.solver}  status: {res.solution.status}")
    if res.solution.objective is not None:
        print(f"objective: {res.solution.objective:,.4f}")
    for name, values in res.solution.variables.items():
        for idx, val in values.items():
            if abs(val) > 1e-9:
                print(f"  {name}[{idx}] = {val:g}" if idx else f"  {name} = {val:g}")
    print()
    print(res.explanation)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m formulate.pipeline",
        description="Run the Formulate pipeline on a spec file or NL problem.",
    )
    parser.add_argument("spec", nargs="?", help="path to a ModelSpec .json file")
    parser.add_argument("--text", help="natural-language problem statement")
    parser.add_argument("--json", action="store_true", help="dump the full artifact bundle as JSON")
    args = parser.parse_args(argv)

    logging.basicConfig(level=get_settings().formulate_log_level)
    try:
        if args.text:
            res = run_from_text(args.text)
        elif args.spec:
            res = run_from_spec(ModelSpec.from_file(Path(args.spec)))
        else:
            parser.error("give a spec file or --text")
    except FormulateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(res.model_dump(), indent=2))
    else:
        _print_result(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
