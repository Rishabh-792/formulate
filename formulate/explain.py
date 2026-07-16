"""Stage 6: solved model -> plain-English explanation.

Azure mode asks the LLM to narrate the solution (facts are passed in as
JSON; the prompt forbids inventing numbers). Mock mode renders a plain
template from the same facts — less prose, same information.
"""

from __future__ import annotations

import json
from typing import Protocol

from .llm import AzureChatClient, get_settings, load_prompt
from .solve import SolveResult
from .spec import ModelSpec


class Explainer(Protocol):
    def explain(self, spec: ModelSpec, result: SolveResult) -> str: ...


def _facts(spec: ModelSpec, result: SolveResult) -> dict:
    return {
        "problem": spec.description or spec.name,
        "objective_sense": spec.objective.sense,
        "objective_description": spec.objective.description,
        "status": result.status,
        "objective_value": result.objective,
        "variables": {
            name: values
            for name, values in result.variables.items()
            if any(abs(v) > 1e-9 for v in values.values())
        },
        "infeasibility": [r.model_dump() for r in result.infeasibility],
    }


class LLMExplainer:
    def __init__(self, client: AzureChatClient | None = None) -> None:
        self.client = client or AzureChatClient()
        self.system_prompt = load_prompt("explainer")

    def explain(self, spec: ModelSpec, result: SolveResult) -> str:
        return self.client.complete(
            self.system_prompt, json.dumps(_facts(spec, result), indent=2)
        )


class TemplateExplainer:
    def explain(self, spec: ModelSpec, result: SolveResult) -> str:
        facts = _facts(spec, result)
        if result.status == "infeasible":
            lines = [
                "No feasible plan exists: the constraints contradict each other.",
                "Smallest total relaxation that restores feasibility:",
            ]
            lines += [f"  - {r.describe()}" for r in result.infeasibility] or [
                "  (no diagnostic available)"
            ]
            return "\n".join(lines)
        if result.status != "optimal":
            return f"The solver stopped without an optimum: {result.status}. {result.message}"

        verb = "maximizes" if spec.objective.sense == "maximize" else "minimizes"
        what = spec.objective.description or "the objective"
        lines = [
            f"Optimal plan found. It {verb} {what} at a value of "
            f"{result.objective:,.2f}.",
            "",
            "Decisions:",
        ]
        for name, values in facts["variables"].items():
            desc = spec.var_map().get(name)
            label = desc.description if desc and desc.description else name
            for idx, val in values.items():
                where = f" for {idx.replace(',', ', ')}" if idx else ""
                lines.append(f"  - {label}{where}: {val:g}")
        zero_vars = [
            name for name, values in result.variables.items()
            if name not in facts["variables"] and values
        ]
        if zero_vars:
            lines.append(f"  - all other decisions ({', '.join(zero_vars)}) stay at zero")
        return "\n".join(lines)


def get_explainer() -> Explainer:
    if get_settings().mode == "azure":
        return LLMExplainer()
    return TemplateExplainer()
