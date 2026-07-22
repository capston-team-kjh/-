from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai.blind_labeling import (
    BlindLabelError,
    DirectLabel,
    freeze_review_workspace,
    record_review_decisions,
    verify_review_workspace,
    write_review_workspace,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare and freeze a local-only FocusAI blind labeling workspace."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Generate blind contact sheets and manifests.")
    prepare.add_argument("--clips-manifest", type=Path, required=True)
    prepare.add_argument("--output-root", type=Path, required=True)

    record = subparsers.add_parser("record", help="Record one or more visual decisions.")
    record.add_argument("--output-root", type=Path, required=True)
    record.add_argument(
        "--decision",
        action="append",
        required=True,
        help="blind_id|label|confidence|status|evidence (repeatable)",
    )

    verify = subparsers.add_parser("verify", help="Validate sheets and review rows.")
    verify.add_argument("--output-root", type=Path, required=True)
    verify.add_argument("--allow-pending", action="store_true")

    freeze = subparsers.add_parser("freeze", help="Freeze completed labels into sanitized outputs.")
    freeze.add_argument("--output-root", type=Path, required=True)
    freeze.add_argument("--labels-output", type=Path, required=True)
    freeze.add_argument("--summary-output", type=Path, required=True)
    return parser


def _parse_decision(value: str, annotated_at: str) -> DirectLabel:
    parts = value.split("|", maxsplit=4)
    if len(parts) != 5:
        raise BlindLabelError(
            "decision must use blind_id|label|confidence|status|evidence format"
        )
    blind_id, direct_label, confidence, review_status, evidence = parts
    return DirectLabel(
        blind_id=blind_id.strip(),
        direct_label=direct_label.strip(),
        confidence=confidence.strip(),
        evidence=evidence.strip(),
        review_status=review_status.strip(),
        annotator="codex_visual_direct",
        annotated_at=annotated_at,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            result = write_review_workspace(args.clips_manifest, args.output_root)
        elif args.command == "record":
            annotated_at = datetime.now().astimezone().isoformat(timespec="seconds")
            decisions = [_parse_decision(value, annotated_at) for value in args.decision]
            result = record_review_decisions(args.output_root, decisions)
        elif args.command == "verify":
            result = verify_review_workspace(args.output_root, allow_pending=args.allow_pending)
        else:
            result = freeze_review_workspace(
                args.output_root,
                args.labels_output,
                args.summary_output,
            )
    except (BlindLabelError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
