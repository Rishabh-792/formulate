"""Formulate: plain-English optimization problems -> validated spec -> Pyomo -> solution.

LLMs at the boundary, a typed contract in the middle, a deterministic
compiler at the core.
"""

from .errors import FormulateError
from .spec import ModelSpec

__version__ = "0.1.0"
__all__ = ["FormulateError", "ModelSpec", "__version__"]
