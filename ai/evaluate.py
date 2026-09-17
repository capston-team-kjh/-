from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ai.evaluation import EvaluationError, evaluate


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError as exc:
        raise EvaluationError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise EvaluationError(f"JSON root must be an object: {path}")
    return data


def _default_output(session_id: str) -> Path:
    return Path("evaluation_results") / f"{session_id}_metrics.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare a FocusAI result JSON with manual ground-truth labels."
    )
    parser.add_argument("--prediction", required=True, type=Path)
    parser.add_argument("--label", required=True, type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON path (default: evaluation_results/<session_id>_metrics.json)",
    )
    parser.add_argument(
        "--no-save", action="store_true", help="Print metrics without writing a JSON file"
    )
    parser.add_argument(
        "--sample-sec",
        type=float,
        default=1.0,
        help="Classification sampling interval in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--event-iou-threshold",
        type=float,
        default=0.5,
        help="Minimum temporal IoU for an event match (default: 0.5)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        prediction = _read_json(args.prediction)
        label = _read_json(args.label)
        result = evaluate(
            prediction,
            label,
            sample_sec=args.sample_sec,
            event_iou_threshold=args.event_iou_threshold,
        )
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        print(rendered)
        if not args.no_save:
            output = args.output or _default_output(result["session_id"])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + "\n", encoding="utf-8")
            print(f"saved: {output}", file=sys.stderr)
        return 0
    except (EvaluationError, OSError) as exc:
        print(f"evaluation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
