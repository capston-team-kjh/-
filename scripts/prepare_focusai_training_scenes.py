from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai.training_scene_prep import run_extract, run_inventory, run_sheets, run_verify


def _add_project_and_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output-root", type=Path, required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare locally reviewed FocusAI training scene clips."
    )
    subparsers = parser.add_subparsers(dest="stage", required=True)

    inventory = subparsers.add_parser("inventory", help="Inventory local video candidates.")
    inventory.add_argument("--computer-root", type=Path, required=True)
    _add_project_and_output(inventory)

    sheets = subparsers.add_parser("sheets", help="Generate overview and candidate sheets.")
    _add_project_and_output(sheets)
    sheets.add_argument("--every-sec", type=float, default=10.0)

    extract = subparsers.add_parser("extract", help="Extract reviewed scene decisions.")
    _add_project_and_output(extract)
    extract.add_argument("--decisions", type=Path, required=True)
    extract.add_argument("--dry-run", action="store_true")

    verify = subparsers.add_parser("verify", help="Verify clips and source invariants.")
    _add_project_and_output(verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.stage == "inventory":
        result = run_inventory(
            computer_root=args.computer_root,
            project_root=args.project_root,
            output_root=args.output_root,
        )
    elif args.stage == "sheets":
        result = run_sheets(
            project_root=args.project_root,
            output_root=args.output_root,
            every_sec=args.every_sec,
        )
    elif args.stage == "extract":
        result = run_extract(
            project_root=args.project_root,
            output_root=args.output_root,
            decisions_path=args.decisions,
            dry_run=args.dry_run,
        )
    else:
        result = run_verify(
            project_root=args.project_root,
            output_root=args.output_root,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
