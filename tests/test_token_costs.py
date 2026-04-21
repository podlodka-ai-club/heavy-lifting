from decimal import Decimal

from backend.schemas import TokenUsagePayload
from backend.services.token_costs import TokenCostService, TokenPrice, zero_cost


def test_token_cost_service_estimates_cost_using_price_book() -> None:
    service = TokenCostService(
        price_book={
            ("openai", "gpt-5.4"): TokenPrice(
                input_cost_per_million=Decimal("1.25"),
                output_cost_per_million=Decimal("10.00"),
                cached_cost_per_million=Decimal("0.125"),
            )
        }
    )
    usage = TokenUsagePayload(
        model="gpt-5.4",
        provider="openai",
        input_tokens=2000,
        output_tokens=500,
        cached_tokens=1000,
    )

    estimated = service.with_estimated_cost(usage)

    assert estimated.estimated is True
    assert estimated.cost_usd == Decimal("0.007625")


def test_token_cost_service_returns_zero_for_unknown_price() -> None:
    service = TokenCostService(price_book={})
    usage = TokenUsagePayload(
        model="unknown-model",
        provider="unknown-provider",
        input_tokens=500,
        output_tokens=500,
    )

    estimated = service.with_estimated_cost(usage)

    assert estimated.estimated is False
    assert estimated.cost_usd == zero_cost()


def test_token_cost_service_totals_multiple_entries() -> None:
    service = TokenCostService(
        price_book={
            ("openai", "*"): TokenPrice(
                input_cost_per_million=Decimal("1.00"),
                output_cost_per_million=Decimal("2.00"),
            )
        }
    )
    usages = [
        TokenUsagePayload(model="gpt-a", provider="openai", input_tokens=1000, output_tokens=500),
        TokenUsagePayload(model="gpt-b", provider="openai", input_tokens=2000, output_tokens=500),
    ]

    total = service.total_estimated_cost(usages)

    assert total == Decimal("0.005000")


def test_token_cost_service_prefers_exact_price_over_provider_wildcard() -> None:
    service = TokenCostService(
        price_book={
            ("openai", "*"): TokenPrice(
                input_cost_per_million=Decimal("1.00"),
                output_cost_per_million=Decimal("2.00"),
            ),
            ("openai", "gpt-5.4"): TokenPrice(
                input_cost_per_million=Decimal("3.00"),
                output_cost_per_million=Decimal("4.00"),
            ),
        }
    )

    estimated = service.with_estimated_cost(
        TokenUsagePayload(
            model="gpt-5.4",
            provider="openai",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
    )

    assert estimated.estimated is True
    assert estimated.cost_usd == Decimal("7.000000")


def test_token_cost_service_estimate_many_preserves_order_and_flags_unknown_models() -> None:
    service = TokenCostService(
        price_book={
            ("openai", "*"): TokenPrice(
                input_cost_per_million=Decimal("1.00"),
                output_cost_per_million=Decimal("2.00"),
            )
        }
    )

    estimated = service.estimate_many(
        [
            TokenUsagePayload(model="gpt-known", provider="openai", input_tokens=1000),
            TokenUsagePayload(model="other", provider="anthropic", output_tokens=1000),
        ]
    )

    assert [item.model for item in estimated] == ["gpt-known", "other"]
    assert estimated[0].estimated is True
    assert estimated[1].estimated is False
    assert estimated[1].cost_usd == zero_cost()
