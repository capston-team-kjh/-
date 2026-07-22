import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Union

import yaml
from dotenv import load_dotenv

AI_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = AI_DIR.parent
DEFAULT_CONFIG_PATH = AI_DIR / "config" / "default.yaml"

load_dotenv(PROJECT_ROOT / ".env")


def _with_analysis_timing(
    result: dict[str, Any], started_at: datetime
) -> dict[str, Any]:
    ended_at = datetime.now(timezone.utc)
    meta = result.setdefault("meta", {})
    meta["analysis_started_at"] = started_at.isoformat().replace("+00:00", "Z")
    meta["analysis_ended_at"] = ended_at.isoformat().replace("+00:00", "Z")
    meta["total_processing_time_sec"] = round(
        max(0.0, (ended_at - started_at).total_seconds()), 3
    )
    return result


def _env_int(name: str, default_value: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default_value

    try:
        return int(raw_value)
    except ValueError:
        return default_value


def load_analyze_config(config_path: Union[str, os.PathLike[str]]) -> Any:
    from focus_ai.analyze import AnalyzeConfig

    cfg_dict = {}
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg_dict = yaml.safe_load(f) or {}

    return AnalyzeConfig(
        sampling_fps=_env_int("SAMPLING_FPS", int(cfg_dict.get("sampling_fps", 5))),
        absent_threshold_sec=int(cfg_dict.get("absent_threshold_sec", 5)),
        min_face_confidence=float(cfg_dict.get("min_face_confidence", 0.5)),
        parallel_merged_analysis=bool(cfg_dict.get("parallel_merged_analysis", True)),
        version=str(cfg_dict.get("version", "ai-0.2.0")),
    )


def run_analysis(
    session_id: str,
    video_path: Union[str, os.PathLike[str]],
    camera_type: str = "front",
    mode: str = "absent",
    config_path: Union[str, os.PathLike[str]] = DEFAULT_CONFIG_PATH,
    expected_duration_sec: float | None = None,
) -> dict[str, Any]:
    from focus_ai.analyze import analyze_absent, analyze_dummy, analyze_merged_video
    from focus_ai.video_preflight import VideoPreflightError, prepare_video_for_analysis
    from focus_ai.vision import validate_analysis_with_vision

    analysis_started_at = datetime.now(timezone.utc)
    config = load_analyze_config(config_path)
    source_video_path = str(Path(video_path).resolve())

    try:
        with prepare_video_for_analysis(
            video_path,
            expected_duration_sec=expected_duration_sec,
        ) as prepared:
            analysis_video_path = str(prepared.analysis_path)
            if mode == "dummy":
                result = analyze_dummy(
                    session_id=session_id,
                    video_path=analysis_video_path,
                    camera_type=camera_type,
                    config=config,
                )
            elif camera_type == "merged":
                result = analyze_merged_video(
                    session_id=session_id,
                    video_path=analysis_video_path,
                    config=config,
                    decoded_timing=prepared.decoded_timing,
                )
            else:
                result = analyze_absent(
                    session_id=session_id,
                    video_path=analysis_video_path,
                    camera_type=camera_type,
                    config=config,
                )

            meta = result.setdefault("meta", {})
            meta["video_path"] = source_video_path
            meta["video_validation"] = prepared.validation
            warnings = meta.setdefault("warnings", [])
            if not isinstance(warnings, list):
                warnings = [str(warnings)]
                meta["warnings"] = warnings
            for warning in prepared.warnings:
                if warning not in warnings:
                    warnings.append(warning)

            validated = validate_analysis_with_vision(prepared.analysis_path, result)
            return _with_analysis_timing(validated, analysis_started_at)
    except VideoPreflightError as exc:
        return _with_analysis_timing({
            "session_id": session_id,
            "status": "failed",
            "meta": {
                "video_path": source_video_path,
                "camera_type": camera_type,
                "version": config.version,
                "fail_reason": exc.reason,
                "video_validation": exc.details,
                "warnings": ["VIDEO_PREFLIGHT_FAILED"],
            },
            "summary": {},
            "timeline": [],
            "events": [],
        }, analysis_started_at)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--camera-type", choices=["front", "overhead", "merged"], default="front")
    parser.add_argument("--mode", choices=["dummy", "absent", "focus_analysis"], default="absent")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--out", default="output.json")
    args = parser.parse_args()

    result = run_analysis(
        session_id=args.session_id,
        video_path=args.video,
        camera_type=args.camera_type,
        mode=args.mode,
        config_path=args.config,
    )

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"saved: {args.out}")
    print(f"status: {result.get('status')}")


if __name__ == "__main__":
    main()
