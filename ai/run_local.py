import argparse
import json
import os

import yaml

from focus_ai.analyze import AnalyzeConfig, analyze_absent, analyze_dummy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--camera-type", choices=["front", "overhead"], default="front")
    parser.add_argument("--mode", choices=["dummy", "absent"], default="absent")
    parser.add_argument("--config", default=os.path.join("config", "default.yaml"))
    parser.add_argument("--out", default="output.json")
    args = parser.parse_args()

    cfg_dict = {}
    if os.path.exists(args.config):
        with open(args.config, "r", encoding="utf-8") as f:
            cfg_dict = yaml.safe_load(f) or {}

    config = AnalyzeConfig(
        sampling_fps=int(cfg_dict.get("sampling_fps", 5)),
        absent_threshold_sec=int(cfg_dict.get("absent_threshold_sec", 5)),
        min_face_confidence=float(cfg_dict.get("min_face_confidence", 0.5)),
        version=str(cfg_dict.get("version", "ai-0.2.0")),
    )

    if args.mode == "dummy":
        result = analyze_dummy(
            session_id=args.session_id,
            video_path=args.video,
            camera_type=args.camera_type,
            config=config,
        )
    else:
        result = analyze_absent(
            session_id=args.session_id,
            video_path=args.video,
            camera_type=args.camera_type,
            config=config,
        )

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"saved: {args.out}")
    print(f"status: {result.get('status')}")


if __name__ == "__main__":
    main()