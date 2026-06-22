"""
LLM cost estimation — per-model USD pricing.

Pricing tables are updated quarterly.  Unknown models return 0.0.
"""

from __future__ import annotations

from decimal import Decimal

# ── Pricing tables (USD per 1M tokens, input / output) ──────────
# Source: official provider pricing pages (2026-06 snapshot).

_OPENAI_PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "gpt-4": (Decimal("30.00"), Decimal("60.00")),
    "gpt-4-0314": (Decimal("30.00"), Decimal("60.00")),
    "gpt-4-0613": (Decimal("30.00"), Decimal("60.00")),
    "gpt-4-32k": (Decimal("60.00"), Decimal("120.00")),
    "gpt-4-turbo": (Decimal("10.00"), Decimal("30.00")),
    "gpt-4-turbo-2024-04-09": (Decimal("10.00"), Decimal("30.00")),
    "gpt-4o": (Decimal("2.50"), Decimal("10.00")),
    "gpt-4o-2024-05-13": (Decimal("5.00"), Decimal("15.00")),
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
    "o1": (Decimal("15.00"), Decimal("60.00")),
    "o1-mini": (Decimal("1.10"), Decimal("4.40")),
    "o3": (Decimal("10.00"), Decimal("40.00")),
    "o3-mini": (Decimal("1.10"), Decimal("4.40")),
    "o4-mini": (Decimal("1.10"), Decimal("4.40")),
    "gpt-3.5-turbo": (Decimal("0.50"), Decimal("1.50")),
    "gpt-3.5-turbo-0125": (Decimal("0.50"), Decimal("1.50")),
    "gpt-3.5-turbo-instruct": (Decimal("1.50"), Decimal("2.00")),
}

_ANTHROPIC_PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "claude-opus-4": (Decimal("15.00"), Decimal("75.00")),
    "claude-sonnet-4": (Decimal("3.00"), Decimal("15.00")),
    "claude-haiku-3.5": (Decimal("0.80"), Decimal("4.00")),
    "claude-opus-3": (Decimal("15.00"), Decimal("75.00")),
    "claude-sonnet-3.5": (Decimal("3.00"), Decimal("15.00")),
    "claude-haiku-3": (Decimal("0.25"), Decimal("1.25")),
    "claude-instant-1": (Decimal("0.80"), Decimal("2.40")),
}

_DEEPSEEK_PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "deepseek-chat": (Decimal("0.14"), Decimal("0.28")),
    "deepseek-reasoner": (Decimal("0.55"), Decimal("2.19")),
    "deepseek-v3": (Decimal("0.14"), Decimal("0.28")),
    "deepseek-v4-pro": (Decimal("0.27"), Decimal("1.09")),
    "deepseek-r1": (Decimal("0.55"), Decimal("2.19")),
}


def _lookup(
    table: dict[str, tuple[Decimal, Decimal]],
    model: str,
) -> tuple[Decimal, Decimal]:
    """Look up (input, output) price per 1M tokens, with prefix fallback."""
    if model in table:
        return table[model]
    best: tuple[Decimal, Decimal] = (Decimal("0"), Decimal("0"))
    best_len = 0
    for key, prices in table.items():
        if model.startswith(key) and len(key) > best_len:
            best = prices
            best_len = len(key)
    return best


def estimate_openai_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    """Estimate USD cost for an OpenAI chat completion."""
    input_price, output_price = _lookup(_OPENAI_PRICES, model)
    cost = input_price * prompt_tokens / 1_000_000 + output_price * completion_tokens / 1_000_000
    return cost.quantize(Decimal("0.000001"))


def estimate_anthropic_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    """Estimate USD cost for an Anthropic message."""
    input_price, output_price = _lookup(_ANTHROPIC_PRICES, model)
    cost = input_price * prompt_tokens / 1_000_000 + output_price * completion_tokens / 1_000_000
    return cost.quantize(Decimal("0.000001"))


def estimate_deepseek_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    """Estimate USD cost for a DeepSeek chat completion.

    Uses the non-cached (upper-bound) price.
    """
    input_price, output_price = _lookup(_DEEPSEEK_PRICES, model)
    cost = input_price * prompt_tokens / 1_000_000 + output_price * completion_tokens / 1_000_000
    return cost.quantize(Decimal("0.000001"))


_COST_DISPATCH = {
    "openai": estimate_openai_cost,
    "anthropic": estimate_anthropic_cost,
    "deepseek": estimate_deepseek_cost,
}


def estimate_cost(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> Decimal:
    """Cost estimator for any supported provider. Unknown → 0.0."""
    estimator = _COST_DISPATCH.get(provider.lower())
    if estimator is None:
        return Decimal("0")
    return estimator(model, prompt_tokens, completion_tokens)
