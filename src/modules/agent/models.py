from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from src.core.constants import (
    LLM_PROVIDER_OPENAI,
    FEATURE_GENERATE_PARENT_QUERY_RESPONSE,
    FEATURE_REFRESH_CONVERSATION_SUMMARY,
)
from src.core.config import Settings, get_settings


@dataclass(frozen=True)
class AgentFeatureModel:
    """Resolved model handle for one agent feature, including the ready-to-use client."""

    feature_name: str
    provider: str
    model_name: str
    client: Any


@dataclass(frozen=True)
class FeatureModel:
    """Default provider/model choice for a feature before we build the actual client."""

    provider: str | None = None
    model_name: str | None = None


FEATURE_MODEL_MAP: dict[str, FeatureModel] = {
    FEATURE_GENERATE_PARENT_QUERY_RESPONSE: FeatureModel(model_name="gpt-5-mini"),
    FEATURE_REFRESH_CONVERSATION_SUMMARY: FeatureModel(model_name="gpt-5-nano"),
}


class AgentModelRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._clients_by_config: dict[tuple[str, str], Any] = {}

    def get_model(self, feature_name: str) -> AgentFeatureModel:
        """Return the configured chat model for a named agent feature.

        `models.py` owns the feature-to-model routing so we can keep .env focused on
        real environment configuration like API keys and timeouts. A feature can use
        an explicit provider/model route here, or fall back to the global defaults.
        """
        route = FEATURE_MODEL_MAP.get(feature_name, FeatureModel())
        provider = route.provider or self.settings.llm_provider
        model_name = route.model_name or self.settings.llm_model
        client = self._get_or_build_client(provider=provider, model_name=model_name)
        return AgentFeatureModel(
            feature_name=feature_name,
            provider=provider,
            model_name=model_name,
            client=client,
        )

    def _get_or_build_client(self, *, provider: str, model_name: str) -> Any:
        client_key = (provider, model_name)
        cached_client = self._clients_by_config.get(client_key)
        if cached_client is not None:
            return cached_client

        client = self._build_chat_model(
            provider=provider,
            model_name=model_name,
        )
        self._clients_by_config[client_key] = client
        return client

    def _build_chat_model(self, *, provider: str, model_name: str) -> Any:
        """Build one provider client for a concrete provider/model pair."""
        if provider != LLM_PROVIDER_OPENAI:
            raise ValueError(f"Unsupported LLM provider: {provider}")

        return ChatOpenAI(
            model=model_name,
            api_key=(
                SecretStr(self.settings.openai_api_key)
                if self.settings.openai_api_key
                else None
            ),
            base_url=self.settings.llm_base_url,
            timeout=self.settings.llm_timeout_seconds,
            reasoning_effort=self.settings.llm_reasoning_effort,
            use_responses_api=True,
            stream_usage=True,
        )


@lru_cache
def get_model_registry() -> AgentModelRegistry:
    return AgentModelRegistry(get_settings())
