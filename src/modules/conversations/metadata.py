from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.core.config import Settings
from src.core.constants import LLM_PROVIDER_OPENAI


@dataclass(frozen=True)
class TokenPricing:
    input_per_million_tokens_usd: float
    cached_input_per_million_tokens_usd: float
    output_per_million_tokens_usd: float
    source: str


KNOWN_OPENAI_TOKEN_PRICING: tuple[tuple[str, TokenPricing], ...] = (
    (
        "gpt-5-mini",
        TokenPricing(
            input_per_million_tokens_usd=0.25,
            cached_input_per_million_tokens_usd=0.025,
            output_per_million_tokens_usd=2.0,
            source="openai_default_pricing",
        ),
    ),
    (
        "gpt-5-nano",
        TokenPricing(
            input_per_million_tokens_usd=0.05,
            cached_input_per_million_tokens_usd=0.005,
            output_per_million_tokens_usd=0.4,
            source="openai_default_pricing",
        ),
    ),
    (
        "gpt-5",
        TokenPricing(
            input_per_million_tokens_usd=1.25,
            cached_input_per_million_tokens_usd=0.125,
            output_per_million_tokens_usd=10.0,
            source="openai_default_pricing",
        ),
    ),
)


def build_message_metadata(
    *,
    settings: Settings,
    message_type: str,
    student_resolution_method: str | None = None,
    student_resolution_explanation: str | None = None,
    agent_runtime_duration_ms: float | int | None = None,
    model_provider: str | None = None,
    model_name: str | None = None,
    token_usage: dict[str, Any] | None = None,
    summary_updated: bool = False,
    summary_parent_turn_checkpoint: int | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"type": message_type}

    if student_resolution_method is not None:
        metadata["student_resolution"] = {
            "method": student_resolution_method,
            "explanation": student_resolution_explanation,
        }

    if agent_runtime_duration_ms is not None:
        metadata["timing"] = {
            "agent_runtime_duration_ms": round(float(agent_runtime_duration_ms), 2),
        }

    if model_provider is not None or model_name is not None:
        metadata["model"] = {
            "provider": model_provider,
            "name": model_name,
        }

    usage_metadata = build_usage_metadata(
        settings=settings,
        model_provider=model_provider,
        model_name=model_name,
        token_usage=token_usage,
    )
    if usage_metadata is not None:
        metadata["usage"] = usage_metadata

    if summary_updated or summary_parent_turn_checkpoint is not None:
        metadata["summary"] = {
            "updated": summary_updated,
            "parent_turn_checkpoint": summary_parent_turn_checkpoint,
        }

    return metadata


def build_usage_metadata(
    *,
    settings: Settings,
    model_provider: str | None,
    model_name: str | None,
    token_usage: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if token_usage is None:
        return None

    input_tokens = _int_value(token_usage.get("input_tokens"))
    output_tokens = _int_value(token_usage.get("output_tokens"))
    total_tokens = _int_value(token_usage.get("total_tokens"))
    cached_input_tokens = _int_value(
        (token_usage.get("input_token_details") or {}).get("cache_read")
    )
    reasoning_tokens = _int_value(
        (token_usage.get("output_token_details") or {}).get("reasoning")
    )
    billable_input_tokens = max(input_tokens - cached_input_tokens, 0)

    usage_metadata: dict[str, Any] = {
        "tokens": {
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "billable_input_tokens": billable_input_tokens,
            "output_tokens": output_tokens,
            "reasoning_tokens": reasoning_tokens,
            "total_tokens": total_tokens,
        }
    }

    token_pricing = resolve_token_pricing(
        settings=settings,
        model_provider=model_provider,
        model_name=model_name,
    )
    if token_pricing is None:
        return usage_metadata

    input_cost_usd = (billable_input_tokens / 1_000_000) * token_pricing.input_per_million_tokens_usd
    cached_input_cost_usd = (
        cached_input_tokens / 1_000_000
    ) * token_pricing.cached_input_per_million_tokens_usd
    output_cost_usd = (output_tokens / 1_000_000) * token_pricing.output_per_million_tokens_usd
    total_cost_usd = input_cost_usd + cached_input_cost_usd + output_cost_usd

    usage_metadata["cost"] = {
        "currency": "USD",
        "estimated_input_cost_usd": round(input_cost_usd, 6),
        "estimated_cached_input_cost_usd": round(cached_input_cost_usd, 6),
        "estimated_output_cost_usd": round(output_cost_usd, 6),
        "estimated_total_cost_usd": round(total_cost_usd, 6),
        "pricing_source": token_pricing.source,
        "input_per_million_tokens_usd": token_pricing.input_per_million_tokens_usd,
        "cached_input_per_million_tokens_usd": token_pricing.cached_input_per_million_tokens_usd,
        "output_per_million_tokens_usd": token_pricing.output_per_million_tokens_usd,
    }
    return usage_metadata


def resolve_token_pricing(
    *,
    settings: Settings,
    model_provider: str | None,
    model_name: str | None,
) -> TokenPricing | None:
    override_pricing = _build_override_pricing(settings)
    if override_pricing is not None:
        return override_pricing

    if model_provider != LLM_PROVIDER_OPENAI:
        return None

    candidate_names = [candidate for candidate in (model_name, settings.llm_model) if candidate]
    for candidate_name in candidate_names:
        normalized_model_name = candidate_name.lower()
        for prefix, pricing in KNOWN_OPENAI_TOKEN_PRICING:
            if normalized_model_name == prefix or normalized_model_name.startswith(f"{prefix}-"):
                return pricing

    return None


def _build_override_pricing(settings: Settings) -> TokenPricing | None:
    override_values = (
        settings.llm_input_cost_per_million_tokens_usd,
        settings.llm_cached_input_cost_per_million_tokens_usd,
        settings.llm_output_cost_per_million_tokens_usd,
    )
    if any(value is None for value in override_values):
        return None

    return TokenPricing(
        input_per_million_tokens_usd=settings.llm_input_cost_per_million_tokens_usd or 0.0,
        cached_input_per_million_tokens_usd=settings.llm_cached_input_cost_per_million_tokens_usd or 0.0,
        output_per_million_tokens_usd=settings.llm_output_cost_per_million_tokens_usd or 0.0,
        source="settings_override",
    )


def _int_value(value: Any) -> int:
    if value is None:
        return 0
    return int(value)
