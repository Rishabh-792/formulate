"""Formulate HTTP API.

Run:  uvicorn api.main:app --reload
Docs: http://localhost:8000/docs
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from formulate import __version__
from formulate.errors import FormulateError, SpecValidationError
from formulate.interpreter import get_interpreter
from formulate.llm import get_settings
from formulate.pipeline import PipelineResult, run_from_spec, run_from_text
from formulate.spec import ModelSpec
from formulate.validator import ValidationReport, validate

logger = logging.getLogger(__name__)
app = FastAPI(
    title="Formulate",
    version=__version__,
    description="Plain-English optimization problems, compiled and solved.",
)

_EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


class ProblemIn(BaseModel):
    problem: str


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "version": __version__, "mode": get_settings().mode}


@app.get("/examples")
def examples() -> dict[str, ModelSpec]:
    return {
        p.stem.removesuffix(".spec"): ModelSpec.from_file(p)
        for p in sorted(_EXAMPLES_DIR.glob("*.spec.json"))
    }


@app.post("/interpret")
def interpret(body: ProblemIn) -> ModelSpec:
    try:
        return get_interpreter().interpret(body.problem)
    except FormulateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/validate")
def validate_spec(spec: ModelSpec) -> ValidationReport:
    return validate(spec)


@app.post("/compile-and-solve")
def compile_and_solve(spec: ModelSpec) -> PipelineResult:
    try:
        return run_from_spec(spec)
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FormulateError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/solve")
def solve(body: ProblemIn) -> PipelineResult:
    """One-shot: NL problem in, explained solution out."""
    try:
        return run_from_text(body.problem)
    except SpecValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FormulateError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
