"""Exception hierarchy for Formulate.

Every stage raises a subclass of FormulateError so callers can catch one
type at the pipeline boundary and still discriminate by stage.
"""

from __future__ import annotations


class FormulateError(Exception):
    """Base class for all Formulate errors."""


class ExpressionSyntaxError(FormulateError):
    """The expression string does not conform to the grammar."""

    def __init__(self, message: str, position: int | None = None) -> None:
        self.position = position
        suffix = f" (at position {position})" if position is not None else ""
        super().__init__(f"{message}{suffix}")


class SpecValidationError(FormulateError):
    """A ModelSpec failed validation and cannot be compiled."""


class LinearizationError(FormulateError):
    """A nonlinearity was detected that no registered transform can handle."""


class CompilationError(FormulateError):
    """The spec could not be turned into a Pyomo model."""


class SolverError(FormulateError):
    """No usable solver was found, or the solver itself failed."""


class InterpreterError(FormulateError):
    """The LLM (or mock) could not produce a valid ModelSpec."""
