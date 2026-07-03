from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv

from .cost_estimator import estimate_vision_cost
from .frame_sampler import probe_video_duration_sec
from .validator import VisionConfig, validate_analysis_with_vision


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _minimal_analysis(video_path: Path) -> dict:
    duration = probe_video_duration_sec(video_path)
    if duration <= 0:
        raise RuntimeError(f"영상 길이를 확인할 수 없습니다: {video_path}")
    return {
        "session_id": "VISION_LOCAL_TEST",
        "status": "success",
        "meta": {"duration_sec": duration, "video_path": str(video_path)},
        "summary": {"total_time_sec": duration, "focus_score": 0},
        "timeline": [],
        "events": [],
    }


def _print_estimates(config: VisionConfig) -> None:
    print("비용 사전 추정(최대 출력 토큰 포함, 실제 사용량은 더 적을 수 있음)")
    for label, count in (("recommended", config.recommended_frames), ("dense", config.dense_frames)):
        estimate = estimate_vision_cost(
            model=config.model,
            detail=config.detail,
            frame_count=count,
            max_output_tokens=config.max_output_tokens,
        )
        print(
            f"- {label}: {count} frames, input={estimate['estimated_input_tokens']} tokens, "
            f"max output={estimate['estimated_output_tokens']} tokens, "
            f"estimated=${estimate['estimated_cost_usd']:.8f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="FocusAI OpenAI frame vision validation test")
    parser.add_argument("--video", required=True)
    parser.add_argument("--analysis-json", help="기존 분석 결과 JSON. 생략하면 균등 프레임 샘플링")
    parser.add_argument("--frame-mode", choices=["recommended", "dense"], default="recommended")
    parser.add_argument("--out", help="vision_validation이 추가된 결과 JSON 저장 경로")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    mode.add_argument("--live", dest="dry_run", action="store_false", help="실제 API 호출 허용")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    video_path = Path(args.video).expanduser().resolve()
    if not video_path.is_file():
        raise FileNotFoundError(f"video not found: {video_path}")

    if args.analysis_json:
        analysis = json.loads(Path(args.analysis_json).read_text(encoding="utf-8"))
    else:
        analysis = _minimal_analysis(video_path)

    config = replace(
        VisionConfig.from_env(),
        enabled=True,
        dry_run=bool(args.dry_run),
        frame_mode=args.frame_mode,
    )
    _print_estimates(config)
    result = validate_analysis_with_vision(video_path, analysis, config=config)
    validation = result["vision_validation"]
    print(json.dumps(validation, ensure_ascii=False, indent=2))

    if args.out:
        output = Path(args.out).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved: {output}")


if __name__ == "__main__":
    main()
