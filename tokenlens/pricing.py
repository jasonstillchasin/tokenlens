"""Cost calculation from pricing.toml. See that file to edit rates."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from tokenlens.transcripts import Turn

DEFAULT_PRICING_PATH = Path(__file__).parent / "pricing.toml"
_DATE_SUFFIX = re.compile(r"-\d{8}$")


def load_pricing(path: Path | None = None) -> dict:
    with open(path or DEFAULT_PRICING_PATH, "rb") as f:
        return tomllib.load(f)


def rates_for_model(pricing: dict, model: str) -> dict:
    models = pricing.get("models", {})
    if model in models:
        return models[model]
    stripped = _DATE_SUFFIX.sub("", model)
    if stripped in models:
        return models[stripped]
    for key, rates in models.items():
        if model.startswith(key) or key.startswith(stripped):
            return rates
    return pricing["default"]


def turn_cost(turn: Turn, pricing: dict) -> float:
    rates = rates_for_model(pricing, turn.model)
    return (
        turn.input_tokens * rates["input"]
        + turn.output_tokens * rates["output"]
        + turn.cache_write_5m * rates["cache_write_5m"]
        + turn.cache_write_1h * rates["cache_write_1h"]
        + turn.cache_read * rates["cache_read"]
    ) / 1_000_000
