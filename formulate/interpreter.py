"""Stage 1: natural language -> ModelSpec.

The only creative step in the pipeline. Azure mode sends the problem
statement to the LLM with a schema-carrying system prompt and parses the
JSON reply straight into ModelSpec (pydantic rejects anything malformed).
Mock mode keyword-matches against the two bundled example problems so the
demo, tests, and UI run with no keys at all.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from .errors import InterpreterError
from .llm import AzureChatClient, get_settings, load_prompt
from .spec import ModelSpec

logger = logging.getLogger(__name__)

_EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


class Interpreter(Protocol):
    def interpret(self, problem: str) -> ModelSpec: ...


class LLMInterpreter:
    def __init__(self, client: AzureChatClient | None = None) -> None:
        self.client = client or AzureChatClient()
        self.system_prompt = load_prompt("interpreter")

    def interpret(self, problem: str) -> ModelSpec:
        raw = self.client.complete(self.system_prompt, problem, json_mode=True)
        try:
            return ModelSpec.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise InterpreterError(
                f"LLM reply is not a valid ModelSpec: {exc}"
            ) from exc


class MockInterpreter:
    """Keyword-matches the bundled examples. Keeps the keyless demo honest:
    the *spec* is hand-written, but everything after it is the same
    deterministic code Azure mode uses."""

    _ROUTES = [
        (("ship", "shipping", "transport", "warehouse", "plant"), "transportation"),
        (("produce", "product", "machine", "profit", "capacity"), "production_planning"),
    ]

    def interpret(self, problem: str) -> ModelSpec:
        text = problem.lower()
        scores = {
            name: sum(kw in text for kw in kws) for kws, name in self._ROUTES
        }
        best = max(scores, key=scores.get)  # type: ignore[arg-type]
        if scores[best] == 0:
            raise InterpreterError(
                "mock interpreter only understands the two bundled examples "
                "(production planning, transportation) — set Azure OpenAI keys "
                "for arbitrary problems"
            )
        logger.info("mock interpreter matched example '%s'", best)
        return ModelSpec.from_file(_EXAMPLES_DIR / f"{best}.spec.json")


def get_interpreter() -> Interpreter:
    if get_settings().mode == "azure":
        return LLMInterpreter()
    return MockInterpreter()
