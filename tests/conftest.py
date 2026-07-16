import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from formulate.spec import ModelSpec  # noqa: E402

EXAMPLES = ROOT / "examples"


@pytest.fixture
def production_spec() -> ModelSpec:
    return ModelSpec.from_file(EXAMPLES / "production_planning.spec.json")


@pytest.fixture
def transportation_spec() -> ModelSpec:
    return ModelSpec.from_file(EXAMPLES / "transportation.spec.json")
