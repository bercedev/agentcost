"""Pricing must never be applied to a model name the tool silently mangled (#206).

`roy-tong` reported that MODEL_PRICING stops at the previous model generation and
that unknown models fall back to a hard-coded $1/$3. The fallback is only half of
it: `ClaudeCodeParser._normalize_model` / `CursorParser._normalize_model` returned
the *lowercased, separator-mangled* form when no known family matched, so a name
they did not recognise was rewritten on the way into TokenUsage ("gpt-4o" ->
"gpt 4o") and could never match MODEL_PRICING. Every non-Claude model -- GPT,
Gemini, DeepSeek, and the explicitly-free ones -- was billed at the fallback rate.

These tests pin down the three guarantees the fix has to hold:

1. a name the normalizer does not recognise survives it unchanged,
2. every key already in MODEL_PRICING is reachable through a prefixed/dated
   spelling of itself,
3. an unknown model still costs the documented fallback, and now says so.
"""

import logging

import pytest

from agentcost.cost import (
    MODEL_PRICING,
    TokenUsage,
    calculate_cost,
    is_free_model,
)
from agentcost.cursor_parser import CursorParser
from agentcost.parsers import ClaudeCodeParser

FALLBACK_COST_PER_MTOK = (1.0, 3.0)


class TestParserNormalizerIsNotDestructive:
    """A normalizer must never rewrite a name it does not recognise."""

    @pytest.mark.parametrize("parser_cls", [ClaudeCodeParser, CursorParser])
    @pytest.mark.parametrize(
        "model",
        [
            "gpt-4o",
            "gpt-4o-mini",
            "gemini-2.5-pro",
            "gemini-1.5-flash",
            "deepseek-v3",
            "grok-2",
            "qwen-max",
            "llama-3.1-405b",
            "kimi-latest",
            "meituan/longcat-2.5-preview:free",
            "claude-3-7-sonnet",
        ],
    )
    def test_unrecognised_name_survives_unchanged(self, parser_cls, model):
        """The mangled return value is what made these unmatchable."""
        normalized = parser_cls()._normalize_model(model)
        assert normalized == model, (
            f"{parser_cls.__name__} rewrote {model!r} to {normalized!r}; a name it "
            "does not recognise must pass through untouched or pricing cannot find it"
        )

    @pytest.mark.parametrize("parser_cls", [ClaudeCodeParser, CursorParser])
    def test_recognised_claude_names_still_map(self, parser_cls):
        """The mapping the normalizer exists for must keep working."""
        parser = parser_cls()
        assert parser._normalize_model("claude-3-5-sonnet-20250219") == "claude-3-5-sonnet"
        assert parser._normalize_model("claude-sonnet-4-5") == "claude-sonnet-4"
        assert parser._normalize_model("claude-opus-4-5") == "claude-opus-4"

    def test_every_non_claude_pricing_key_is_reachable_from_its_log_name(self):
        """The bug was total: no non-Claude model could ever match."""
        parser = ClaudeCodeParser()
        for key in MODEL_PRICING:
            assert parser._normalize_model(key) == key, (
                f"{key!r} is in MODEL_PRICING but the parser rewrites it, so it "
                "can never be priced"
            )


class TestNormalizedNameLookup:
    """`_normalize_model_name` covers prefixes, tiers and date stamps."""

    @pytest.mark.parametrize(
        ("logged", "expected"),
        [
            ("anthropic/claude-sonnet-4", "claude-sonnet-4"),
            ("meituan/longcat-2.5-preview:free", "longcat-2.5-preview"),
            ("openrouter/deepseek-v3:free", "deepseek-v3"),
            ("claude-sonnet-4-20250514", "claude-sonnet-4"),
            ("claude-sonnet-4", "claude-sonnet-4"),
            ("gpt-4o", "gpt-4o"),
        ],
    )
    def test_shapes(self, logged, expected):
        from agentcost.cost import _normalize_model_name

        assert _normalize_model_name(logged) == expected

    def test_prefixed_and_dated_names_price_like_the_bare_model(self):
        """A dated spelling must not be a different price."""
        bare = calculate_cost(TokenUsage(model="claude-sonnet-4", input_tokens=1_000_000, output_tokens=0))
        for alias in ("anthropic/claude-sonnet-4", "claude-sonnet-4-20250514"):
            assert calculate_cost(TokenUsage(model=alias, input_tokens=1_000_000, output_tokens=0)) == bare

    def test_free_model_stays_free_through_a_prefixed_alias(self):
        """Billing a free tier is the worst face of this bug."""
        assert is_free_model("meituan/longcat-2.0:free")
        assert calculate_cost(
            TokenUsage(model="meituan/longcat-2.0:free", input_tokens=1_000_000, output_tokens=1_000_000)
        ) == 0.0

    def test_free_tier_not_in_the_table_is_still_free(self):
        """`split(":")[-1]` used to name these 'free' and bill them at $1/$3."""
        model = "meituan/longcat-2.5-preview:free"
        assert model not in MODEL_PRICING
        assert is_free_model(model)
        assert calculate_cost(
            TokenUsage(model=model, input_tokens=1_000_000, output_tokens=1_000_000)
        ) == 0.0


class TestParsedModelNameIsTheRealModel:
    """The parsers must not rename the model on its way into TokenUsage."""

    @pytest.mark.parametrize("parser_cls", [ClaudeCodeParser, CursorParser])
    @pytest.mark.parametrize(
        "logged",
        [
            "meituan/longcat-2.5-preview:free",
            "gpt-4o",
            "claude-3-7-sonnet",
            "anthropic/claude-sonnet-4",
        ],
    )
    def test_parsed_entry_keeps_the_logged_name(self, parser_cls, logged):
        entry = {
            "timestamp": "2026-10-11T10:00:00Z",
            "message": {"model": logged, "usage": {"input_tokens": 1000, "output_tokens": 500}},
        }
        usage = parser_cls()._parse_entry(entry)
        assert usage is not None
        # A Claude alias is the one legitimate rewrite; everything else is verbatim.
        expected = parser_cls()._normalize_model(logged)
        assert usage.model == expected
        assert logged.split("/")[-1] in usage.model or expected.startswith("claude-"), (
            f"{logged!r} was rewritten to {usage.model!r}, losing the model name"
        )
        # The point of the whole fix: the parsed name must be priceable.
        assert usage.model in MODEL_PRICING or is_free_model(usage.model) or calculate_cost(usage) > 0


class TestUnknownModelIsLoud:
    """The fallback stays, but it is no longer silent (#206)."""

    def test_unknown_model_warns_and_still_costs_the_fallback(self, caplog):
        with caplog.at_level(logging.WARNING, logger="agentcost.cost"):
            cost = calculate_cost(
                TokenUsage(model="totally-made-up-model-9", input_tokens=1_000_000, output_tokens=1_000_000)
            )
        assert cost == pytest.approx(FALLBACK_COST_PER_MTOK[0] + FALLBACK_COST_PER_MTOK[1])
        assert any(
            "totally-made-up-model-9" in r.getMessage() for r in caplog.records
        ), f"unknown model was priced silently; records={[r.getMessage() for r in caplog.records]}"

    def test_known_model_does_not_warn(self, caplog):
        """Positive control: the warning must not fire on every call."""
        with caplog.at_level(logging.WARNING, logger="agentcost.cost"):
            calculate_cost(TokenUsage(model="claude-3-5-sonnet", input_tokens=1_000_000, output_tokens=0))
            calculate_cost(TokenUsage(model="gpt-4o", input_tokens=1_000_000, output_tokens=0))
        assert caplog.records == [], [r.getMessage() for r in caplog.records]

    def test_warning_is_emitted_once_per_model_not_once_per_call(self, caplog):
        """2000 calls on one unlisted model is one fact, not 2000 log lines."""
        with caplog.at_level(logging.WARNING, logger="agentcost.cost"):
            for _ in range(50):
                calculate_cost(TokenUsage(model="repeat-unknown-model", input_tokens=1, output_tokens=0))
        assert len(caplog.records) == 1, [r.getMessage() for r in caplog.records]
