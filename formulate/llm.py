"""Azure OpenAI client wrapper, settings, and the mock used in keyless mode.

MODE is auto-detected: if all Azure settings are present we call the real
API; otherwise every LLM-backed stage falls back to its mock and the whole
pipeline still runs. Nothing outside this module and the two LLM stages
(interpreter, explainer) ever talks to a model.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = "2024-10-21"
    formulate_log_level: str = "INFO"
    formulate_solver: str = ""  # empty = auto-pick

    @property
    def mode(self) -> str:
        keys = (
            self.azure_openai_endpoint,
            self.azure_openai_api_key,
            self.azure_openai_deployment,
        )
        return "azure" if all(keys) else "mock"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def load_prompt(name: str) -> str:
    """Read a system prompt from prompts/<name>.md."""
    return (_PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


class AzureChatClient:
    """Thin wrapper: one system prompt + one user message -> text.

    JSON output is enforced with `response_format={"type": "json_object"}`;
    the schema itself is embedded in the system prompt, and the *real*
    enforcement is downstream: pydantic parsing plus the validator. The LLM
    never gets to bypass the typed contract.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        from openai import AzureOpenAI  # imported lazily: mock mode needs no SDK

        self._client = AzureOpenAI(
            azure_endpoint=self.settings.azure_openai_endpoint,
            api_key=self.settings.azure_openai_api_key,
            api_version=self.settings.azure_openai_api_version,
        )

    def complete(self, system: str, user: str, json_mode: bool = False) -> str:
        kwargs: dict = {"temperature": 0.0}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = self._client.chat.completions.create(
            model=self.settings.azure_openai_deployment,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **kwargs,
        )
        content = response.choices[0].message.content or ""
        logger.debug("llm returned %d chars", len(content))
        return content


class MockLLM:
    """Deterministic stand-in: returns whatever canned reply it was given."""

    def __init__(self, reply: str = "") -> None:
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, json_mode: bool = False) -> str:
        self.calls.append((system, user))
        return self.reply
