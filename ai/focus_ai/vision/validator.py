from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .correction import apply_vision_corrections
from .cost_estimator import DEFAULT_VISION_MODEL, estimate_vision_cost, mode_frame_count
from .frame_sampler import analysis_duration_sec, extract_frames, frame_dimensions
from .openai_vision_client import VisionAPIError, validate_frames


LOGGER = logging.getLogger("ai.vision")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    LOGGER.warning("invalid boolean env %s=%r; using %s", name, raw, default)
    return default


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        LOGGER.warning("invalid integer env %s=%r; using %s", name, raw, default)
        return default


def _env_float(name: str, default: float, minimum: float = 0.1) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return max(minimum, float(raw))
    except ValueError:
        LOGGER.warning("invalid number env %s=%r; using %s", name, raw, default)
        return default


@dataclass(frozen=True)
class VisionConfig:
    enabled: bool = False
    dry_run: bool = True
    api_key: str = ""
    model: str = DEFAULT_VISION_MODEL
    detail: str = "low"
    frame_mode: str = "recommended"
    recommended_frames: int = 20
    dense_frames: int = 60
    apply_correction: bool = False
    max_output_tokens: int = 800
    timeout_sec: float = 60.0

    @classmethod
    def from_env(cls) -> "VisionConfig":
        detail = (os.getenv("OPENAI_VISION_DETAIL") or "low").strip().lower()
        if detail not in {"low", "high", "auto"}:
            LOGGER.warning("invalid OPENAI_VISION_DETAIL=%r; using low", detail)
            detail = "low"
        frame_mode = (os.getenv("OPENAI_VISION_FRAME_MODE") or "recommended").strip().lower()
        if frame_mode not in {"recommended", "dense"}:
            LOGGER.warning("invalid OPENAI_VISION_FRAME_MODE=%r; using recommended", frame_mode)
            frame_mode = "recommended"
        return cls(
            enabled=_env_bool("OPENAI_VISION_ENABLED", False),
            dry_run=_env_bool("OPENAI_VISION_DRY_RUN", True),
            api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            model=(os.getenv("OPENAI_VISION_MODEL") or DEFAULT_VISION_MODEL).strip(),
            detail=detail,
            frame_mode=frame_mode,
            recommended_frames=_env_int("OPENAI_VISION_RECOMMENDED_FRAMES", 20),
            dense_frames=_env_int("OPENAI_VISION_DENSE_FRAMES", 60),
            apply_correction=_env_bool("OPENAI_VISION_APPLY_CORRECTION", False),
            max_output_tokens=_env_int("OPENAI_VISION_MAX_OUTPUT_TOKENS", 800),
            timeout_sec=_env_float("OPENAI_VISION_TIMEOUT_SECONDS", 60.0),
        )

    @property
    def frame_count(self) -> int:
        return mode_frame_count(self.frame_mode, self.recommended_frames, self.dense_frames)


def _base_result(config: VisionConfig) -> dict[str, Any]:
    return {
        "vision_enabled": bool(config.enabled),
        "status": "disabled" if not config.enabled else "pending",
        "dry_run": bool(config.dry_run),
        "model": config.model,
        "detail": config.detail,
        "frame_mode": config.frame_mode,
        "configured_frame_count": config.frame_count,
        "sampled_frame_count": 0,
        "estimated_input_tokens": 0,
        "estimated_output_tokens": 0,
        "estimated_cost_usd": 0.0,
        "apply_correction_enabled": bool(config.apply_correction),
        "correction_application": {"applied_count": 0, "skipped_count": 0},
        "overall_verdict": "not_run",
        "confidence": 0.0,
        "corrections": [],
        "notes": "비전 검증은 보조 판단이며 기본 설정에서는 최종 점수에 반영하지 않음",
    }


def _with_estimate(target: dict[str, Any], estimate: dict[str, object]) -> None:
    for key in (
        "estimated_input_tokens",
        "estimated_output_tokens",
        "estimated_input_cost_usd",
        "estimated_output_cost_usd",
        "estimated_cost_usd",
        "pricing_model",
        "pricing_warning",
    ):
        if key in estimate:
            target[key] = estimate[key]


def validate_analysis_with_vision(
    video_path: str | Path,
    analysis_result: dict[str, Any],
    *,
    config: VisionConfig | None = None,
) -> dict[str, Any]:
    """Attach optional frame-based validation without making rule analysis fail."""
    config = config or VisionConfig.from_env()
    validation = _base_result(config)
    analysis_result["vision_validation"] = validation
    if not config.enabled:
        LOGGER.info("OpenAI vision validation disabled; API cost is $0")
        return analysis_result

    duration = analysis_duration_sec(analysis_result)
    LOGGER.info(
        "OpenAI vision sampling started: model=%s mode=%s frames=%s duration_sec=%.1f",
        config.model,
        config.frame_mode,
        config.frame_count,
        duration,
    )

    try:
        with tempfile.TemporaryDirectory(prefix="focusai_vision_") as temp_dir:
            frames = extract_frames(
                video_path,
                analysis_result,
                temp_dir,
                config.frame_count,
            )
            validation["sampled_frame_count"] = len(frames)
            validation["sampled_frames"] = [frame.prompt_metadata() for frame in frames]
            estimate = estimate_vision_cost(
                model=config.model,
                detail=config.detail,
                frame_count=len(frames),
                max_output_tokens=config.max_output_tokens,
                frame_dimensions=frame_dimensions(frames),
            )
            _with_estimate(validation, estimate)
            LOGGER.info(
                "OpenAI vision preflight estimate: frames=%s input_tokens=%s max_output_tokens=%s estimated_cost_usd=%.8f",
                len(frames),
                validation["estimated_input_tokens"],
                validation["estimated_output_tokens"],
                validation["estimated_cost_usd"],
            )

            effective_dry_run = config.dry_run or not bool(config.api_key)
            if effective_dry_run:
                validation["dry_run"] = True
                validation["status"] = "dry_run_missing_api_key" if not config.api_key else "dry_run"
                validation["notes"] = "dry-run: 프레임은 로컬에서 추출·정리했고 OpenAI API는 호출하지 않음"
                if not config.api_key:
                    validation["error"] = {
                        "type": "missing_api_key",
                        "message": "OPENAI_API_KEY가 없어 자동으로 dry-run 처리함",
                    }
                    LOGGER.warning("OPENAI_API_KEY missing; vision validation switched to dry-run")
                return analysis_result

            api_result = validate_frames(
                api_key=config.api_key,
                model=config.model,
                detail=config.detail,
                max_output_tokens=config.max_output_tokens,
                timeout_sec=config.timeout_sec,
                analysis_result=analysis_result,
                frames=frames,
            )
            validation.update(api_result)
            validation["status"] = "completed"
            validation["dry_run"] = False
            if config.apply_correction:
                validation["correction_application"] = apply_vision_corrections(
                    analysis_result,
                    validation,
                )
            LOGGER.info(
                "OpenAI vision validation complete: verdict=%s confidence=%s corrections=%s applied=%s",
                validation.get("overall_verdict"),
                validation.get("confidence"),
                len(validation.get("corrections") or []),
                validation["correction_application"].get("applied_count", 0),
            )
    except VisionAPIError as exc:
        validation["status"] = "error"
        validation["error"] = {"type": exc.error_type, "message": str(exc)}
        LOGGER.error("OpenAI vision validation %s: %s", exc.error_type, exc)
    except FileNotFoundError as exc:
        validation["status"] = "error"
        validation["error"] = {"type": "video_not_found", "message": str(exc)}
        LOGGER.error("OpenAI vision frame sampling failed: %s", exc)
    except Exception as exc:
        validation["status"] = "error"
        validation["error"] = {"type": "frame_or_validation_error", "message": str(exc)}
        LOGGER.exception("OpenAI vision validation failed; keeping rule-based result: %s", exc)
    return analysis_result


def _offset_corrections(corrections: Any, offset_sec: float) -> list[dict[str, Any]]:
    adjusted: list[dict[str, Any]] = []
    if not isinstance(corrections, list):
        return adjusted
    for correction in corrections:
        if not isinstance(correction, dict):
            continue
        item = dict(correction)
        try:
            item["time_sec"] = float(item.get("time_sec", 0)) + offset_sec
        except (TypeError, ValueError):
            pass
        adjusted.append(item)
    return adjusted


def merge_vision_validations(
    chunk_validations: Iterable[tuple[int, float, dict[str, Any]]],
) -> dict[str, Any]:
    chunks = list(chunk_validations)
    if not chunks:
        return {
            "vision_enabled": False,
            "status": "disabled",
            "sampled_frame_count": 0,
            "estimated_cost_usd": 0.0,
            "overall_verdict": "not_run",
            "corrections": [],
            "notes": "비전 검증 결과 없음",
        }

    if len(chunks) == 1:
        _, offset, validation = chunks[0]
        merged = dict(validation)
        merged["corrections"] = _offset_corrections(validation.get("corrections"), offset)
        return merged

    verdict_rank = {
        "not_run": 0,
        "rule_result_valid": 1,
        "rule_result_mostly_valid": 2,
        "insufficient_visual_evidence": 3,
        "rule_result_needs_correction": 4,
    }
    top_verdict = "not_run"
    corrections: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    confidences: list[float] = []
    model_names: list[str] = []
    detail_names: list[str] = []
    chunk_items: list[dict[str, Any]] = []
    total_frames = total_input = total_output = 0
    total_cost = 0.0
    enabled = False
    any_completed = False
    any_dry_run = False

    for chunk_index, offset, validation in chunks:
        enabled = enabled or bool(validation.get("vision_enabled"))
        any_completed = any_completed or validation.get("status") == "completed"
        any_dry_run = any_dry_run or str(validation.get("status", "")).startswith("dry_run")
        total_frames += int(validation.get("sampled_frame_count") or 0)
        total_input += int(validation.get("estimated_input_tokens") or 0)
        total_output += int(validation.get("estimated_output_tokens") or 0)
        total_cost += float(validation.get("estimated_cost_usd") or 0.0)
        verdict = str(validation.get("overall_verdict") or "not_run")
        if verdict_rank.get(verdict, 0) > verdict_rank.get(top_verdict, 0):
            top_verdict = verdict
        try:
            confidences.append(float(validation.get("confidence")))
        except (TypeError, ValueError):
            pass
        if validation.get("model"):
            model_names.append(str(validation["model"]))
        if validation.get("detail"):
            detail_names.append(str(validation["detail"]))
        corrections.extend(_offset_corrections(validation.get("corrections"), offset))
        if isinstance(validation.get("error"), dict):
            errors.append({"chunk_index": chunk_index, **validation["error"]})
        chunk_items.append(
            {
                "chunk_index": chunk_index,
                "offset_sec": offset,
                "status": validation.get("status"),
                "sampled_frame_count": validation.get("sampled_frame_count", 0),
                "estimated_cost_usd": validation.get("estimated_cost_usd", 0.0),
                "overall_verdict": verdict,
            }
        )

    status = "completed" if any_completed else ("dry_run" if any_dry_run else "disabled")
    result: dict[str, Any] = {
        "vision_enabled": enabled,
        "status": status,
        "dry_run": not any_completed,
        "model": model_names[0] if len(set(model_names)) == 1 else "mixed",
        "detail": detail_names[0] if len(set(detail_names)) == 1 else "mixed",
        "sampled_frame_count": total_frames,
        "estimated_input_tokens": total_input,
        "estimated_output_tokens": total_output,
        "estimated_cost_usd": round(total_cost, 8),
        "overall_verdict": top_verdict,
        "confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
        "corrections": corrections,
        "chunks": chunk_items,
        "notes": "chunk별 프레임 비전 검증을 병합한 보조 결과이며 기본 설정에서는 점수에 반영하지 않음",
    }
    if errors:
        result["errors"] = errors
    return result
