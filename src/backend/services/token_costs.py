from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from backend.schemas import TokenUsagePayload

MICRO_DOLLAR = Decimal("0.000001")
TOKENS_PER_MILLION = Decimal("1000000")


@dataclass(frozen=True, slots=True)
class TokenPrice:
    input_cost_per_million: Decimal
    output_cost_per_million: Decimal
    cached_cost_per_million: Decimal = Decimal("0")


DEFAULT_TOKEN_PRICES: dict[tuple[str, str], TokenPrice] = {
    ("openai", "gpt-5.4"): TokenPrice(
        input_cost_per_million=Decimal("1.250000"),
        output_cost_per_million=Decimal("10.000000"),
        cached_cost_per_million=Decimal("0.125000"),
    ),
    ("openai", "gpt-5.4-mini"): TokenPrice(
        input_cost_per_million=Decimal("0.250000"),
        output_cost_per_million=Decimal("2.000000"),
        cached_cost_per_million=Decimal("0.025000"),
    ),
}


def zero_cost() -> Decimal:
    return Decimal("0")


@dataclass(slots=True)
class TokenCostService:
    price_book: Mapping[tuple[str, str], TokenPrice] = field(
        default_factory=lambda: DEFAULT_TOKEN_PRICES.copy()
    )

    def estimate_cost(self, usage: TokenUsagePayload) -> Decimal:
        pricing = self.resolve_price(provider=usage.provider, model=usage.model)
        if pricing is None:
            return zero_cost()

        total_cost = (
            _calculate_cost(usage.input_tokens, pricing.input_cost_per_million)
            + _calculate_cost(usage.output_tokens, pricing.output_cost_per_million)
            + _calculate_cost(usage.cached_tokens, pricing.cached_cost_per_million)
        )
        return total_cost.quantize(MICRO_DOLLAR, rounding=ROUND_HALF_UP)

    def resolve_price(self, *, provider: str, model: str) -> TokenPrice | None:
        exact_match = self.price_book.get((provider, model))
        if exact_match is not None:
            return exact_match

        return self.price_book.get((provider, "*"))

    def with_estimated_cost(self, usage: TokenUsagePayload) -> TokenUsagePayload:
        estimated_cost = self.estimate_cost(usage)
        return usage.model_copy(
            update={
                "cost_usd": estimated_cost,
                "estimated": self.resolve_price(provider=usage.provider, model=usage.model)
                is not None,
            }
        )

    def estimate_many(self, usages: Iterable[TokenUsagePayload]) -> list[TokenUsagePayload]:
        return [self.with_estimated_cost(usage) for usage in usages]

    def total_estimated_cost(self, usages: Iterable[TokenUsagePayload]) -> Decimal:
        total = sum((self.estimate_cost(usage) for usage in usages), start=zero_cost())
        return total.quantize(MICRO_DOLLAR, rounding=ROUND_HALF_UP)


def _calculate_cost(tokens: int, cost_per_million: Decimal) -> Decimal:
    if tokens == 0 or cost_per_million == 0:
        return zero_cost()
    return (Decimal(tokens) / TOKENS_PER_MILLION) * cost_per_million


__all__ = [
    "DEFAULT_TOKEN_PRICES",
    "TokenCostService",
    "TokenPrice",
    "zero_cost",
]
