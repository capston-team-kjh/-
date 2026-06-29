from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Iterable, Sequence


DEFAULT_VISION_MODEL = "gpt-5.4-nano"


@dataclass(frozen=True)
class ModelPricing:
    input_usd_per_million: float
    output_usd_per_million: float
    tokenization: str
    low_tokens_per_image: int
    patch_multiplier: float = 1.0
    patch_budget: int = 1536
    tile_base_tokens: int = 0
    tile_tokens: int = 0


# Prices and image-token rules are a dated local snapshot. Always compare them
# with the official OpenAI pricing and vision documentation before budgeting.
MODEL_PRICING: dict[str, ModelPricing] = {
    "gpt-5.4-nano": ModelPricing(0.20, 1.25, "patch", 630, patch_multiplier=2.46),
    "gpt-5.4-mini": ModelPricing(0.75, 4.50, "patch", 415, patch_multiplier=1.62),
    "gpt-5-nano": ModelPricing(0.05, 0.40, "patch", 630, patch_multiplier=2.46),
    "gpt-5-mini": ModelPricing(0.25, 2.00, "patch", 415, patch_multiplier=1.62),
    "gpt-4.1-nano": ModelPricing(0.10, 0.40, "patch", 630, patch_multiplier=2.46),
    "gpt-4.1-mini": ModelPricing(0.40, 1.60, "patch", 415, patch_multiplier=1.62),
    "gpt-4o-mini": ModelPricing(
        0.15,
        0.60,
        "tile",
        2833,
        tile_base_tokens=2833,
        tile_tokens=5667,
    ),
}


def _model_key(model: str) -> str:
    normalized = str(model or DEFAULT_VISION_MODEL).strip().lower()
    for known in sorted(MODEL_PRICING, key=len, reverse=True):
        if normalized == known or normalized.startswith(f"{known}-"):
            return known
    return DEFAULT_VISION_MODEL


def pricing_for_model(model: str) -> tuple[ModelPricing, str, bool]:
    normalized = str(model or DEFAULT_VISION_MODEL).strip().lower()
    key = _model_key(model)
    matched = any(
        normalized == known or normalized.startswith(f"{known}-")
        for known in MODEL_PRICING
    )
    return MODEL_PRICING[key], key, not matched


def _patch_tokens(width: int, height: int, pricing: ModelPricing) -> int:
    width = max(1, int(width))
    height = max(1, int(height))
    patches = math.ceil(width / 32) * math.ceil(height / 32)
    if patches > pricing.patch_budget:
        shrink = math.sqrt((32 * 32 * pricing.patch_budget) / (width * height))
        scaled_w = max(32, int(width * shrink))
        scaled_h = max(32, int(height * shrink))
        patches = min(
            pricing.patch_budget,
            math.ceil(scaled_w / 32) * math.ceil(scaled_h / 32),
        )
    return int(math.ceil(patches * pricing.patch_multiplier))


def _tile_tokens(width: int, height: int, pricing: ModelPricing) -> int:
    width = max(1, int(width))
    height = max(1, int(height))
    scale = min(1.0, 2048.0 / max(width, height))
    width *= scale
    height *= scale
    shortest = min(width, height)
    if shortest > 0:
        scale_768 = 768.0 / shortest
        width *= scale_768
        height *= scale_768
    tiles = math.ceil(width / 512.0) * math.ceil(height / 512.0)
    return int(pricing.tile_base_tokens + tiles * pricing.tile_tokens)


def estimate_image_tokens(
    model: str,
    detail: str,
    frame_dimensions: Sequence[tuple[int, int]],
) -> int:
    pricing, _, _ = pricing_for_model(model)
    normalized_detail = str(detail or "low").strip().lower()
    if normalized_detail == "low":
        return len(frame_dimensions) * pricing.low_tokens_per_image

    total = 0
    for width, height in frame_dimensions:
        if pricing.tokenization == "patch":
            total += _patch_tokens(width, height, pricing)
        else:
            total += _tile_tokens(width, height, pricing)
    return int(total)


def estimate_vision_cost(
    *,
    model: str,
    detail: str,
    frame_count: int,
    max_output_tokens: int,
    frame_dimensions: Iterable[tuple[int, int]] | None = None,
) -> dict[str, object]:
    count = max(0, int(frame_count))
    dimensions = list(frame_dimensions or [])
    if len(dimensions) < count:
        dimensions.extend([(512, 512)] * (count - len(dimensions)))
    dimensions = dimensions[:count]

    pricing, pricing_model, used_fallback = pricing_for_model(model)
    image_tokens = estimate_image_tokens(model, detail, dimensions)
    output_tokens = max(0, int(max_output_tokens))
    input_cost = image_tokens * pricing.input_usd_per_million / 1_000_000
    output_cost = output_tokens * pricing.output_usd_per_million / 1_000_000

    estimate: dict[str, object] = {
        "estimated_input_tokens": int(image_tokens),
        "estimated_output_tokens": output_tokens,
        "estimated_input_cost_usd": round(input_cost, 8),
        "estimated_output_cost_usd": round(output_cost, 8),
        "estimated_cost_usd": round(input_cost + output_cost, 8),
        "pricing_model": pricing_model,
        "pricing": asdict(pricing),
    }
    if used_fallback:
        estimate["pricing_warning"] = (
            f"unknown model {model!r}; estimate uses {DEFAULT_VISION_MODEL} pricing"
        )
    return estimate


def mode_frame_count(mode: str, recommended_frames: int = 20, dense_frames: int = 60) -> int:
    return max(1, int(dense_frames if str(mode).strip().lower() == "dense" else recommended_frames))
