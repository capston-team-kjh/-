from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

from ai.training_scene_prep import (
    _frame_at,
    ReviewedScene,
    analysis_path_for_source,
    build_inventory_records,
    classify_candidate,
    clip_filename,
    extract_clip,
    discover_media_candidates,
    ensure_safe_output_root,
    group_timeline_candidates,
    load_analysis_timeline,
    probe_video,
    read_review_decisions,
    read_inventory_csv,
    run_extract,
    run_inventory,
    run_sheets,
    run_verify,
    sha256_file,
    shortage_rows,
    write_overview_sheets,
    write_scene_contact_sheet,
)


class TrainingScenePrepCoreTests(unittest.TestCase):
    def test_grouping_merges_two_second_gap_and_pads(self) -> None:
        timeline = [
            {"t": 10, "rule_state": "gaze_down", "flags": {"gaze_down": True}},
            {"t": 11, "rule_state": "gaze_down", "flags": {"gaze_down": True}},
            {"t": 14, "rule_state": "gaze_down", "flags": {"gaze_down": True}},
        ]

        rows = group_timeline_candidates("session54", timeline, duration_sec=100)

        self.assertEqual(
            [(row.start_sec, row.end_sec, row.suggested_label) for row in rows],
            [(8.0, 17.0, "gaze_down")],
        )

    def test_filename_is_traceable_ascii(self) -> None:
        scene = ReviewedScene(
            source_id="session54",
            start_sec=120,
            end_sec=134,
            label="focus",
            cue="writing_head_down",
            disposition="ready",
            notes="clear",
        )

        self.assertEqual(
            clip_filename(scene),
            "focus__writing-head-down__session54__000120-000134.mp4",
        )

    def test_shortage_uses_count_duration_and_source_minimums(self) -> None:
        scenes = [
            ReviewedScene(
                source_id="s1",
                start_sec=0,
                end_sec=10,
                label="gaze_down",
                cue="off_task",
                disposition="ready",
                notes="clear",
            )
        ]

        row = {item["label"]: item for item in shortage_rows(scenes)}["gaze_down"]

        self.assertTrue(row["is_shortage"])
        self.assertGreaterEqual(
            set(row["reasons"]),
            {"clips<20", "duration<180s", "sources<3"},
        )

    def test_long_candidates_are_split_to_thirty_seconds(self) -> None:
        timeline = [
            {"t": second, "rule_state": "focus", "flags": {"face_seen": True}}
            for second in range(70)
        ]

        rows = group_timeline_candidates("long", timeline, duration_sec=70)

        self.assertGreater(len(rows), 1)
        self.assertTrue(all(row.end_sec - row.start_sec <= 30 for row in rows))
        self.assertEqual(rows[0].start_sec, 0)
        self.assertEqual(rows[-1].end_sec, 70)

    def test_short_drowsy_candidate_expands_to_twelve_seconds(self) -> None:
        timeline = [
            {"t": second, "rule_state": "drowsy", "flags": {"eye_closed": True}}
            for second in range(20, 23)
        ]

        rows = group_timeline_candidates("sleep", timeline, duration_sec=60)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].end_sec - rows[0].start_sec, 12)

    def test_shortage_includes_ready_labels_with_no_scenes(self) -> None:
        labels = {row["label"] for row in shortage_rows([])}

        self.assertEqual(
            labels,
            {"focus", "drowsy", "gaze_down", "gaze_side", "unknown"},
        )


def _write_synthetic_video(
    path: Path,
    *,
    fps: int,
    seconds: int,
    width: int,
    height: int,
) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError("could not create synthetic video")
    for index in range(fps * seconds):
        frame = np.full((height, width, 3), index % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()


class TrainingScenePrepMediaTests(unittest.TestCase):
    def test_frame_seek_retries_one_second_earlier(self) -> None:
        class FlakyCapture:
            def __init__(self) -> None:
                self.targets: list[float] = []
                self.read_count = 0

            def set(self, _: int, value: float) -> bool:
                self.targets.append(value)
                return True

            def read(self) -> tuple[bool, np.ndarray | None]:
                self.read_count += 1
                if self.read_count == 1:
                    return False, None
                return True, np.zeros((8, 8, 3), dtype=np.uint8)

        capture = FlakyCapture()

        frame = _frame_at(capture, 590)

        self.assertEqual(frame.shape, (8, 8, 3))
        self.assertEqual(capture.targets, [590000.0, 589000.0])

    def test_frame_seek_falls_back_to_sequential_decode(self) -> None:
        class SequentialOnlyCapture:
            def __init__(self) -> None:
                self.sequential = False
                self.position_resets = 0

            def set(self, property_id: int, _: float) -> bool:
                if property_id == cv2.CAP_PROP_POS_FRAMES:
                    self.sequential = True
                    self.position_resets += 1
                return True

            def get(self, property_id: int) -> float:
                if property_id == cv2.CAP_PROP_FPS:
                    return 2.0
                return 0.0

            def read(self) -> tuple[bool, np.ndarray | None]:
                if not self.sequential:
                    return False, None
                return True, np.zeros((8, 8, 3), dtype=np.uint8)

        capture = SequentialOnlyCapture()

        frame = _frame_at(capture, 3)

        self.assertEqual(frame.shape, (8, 8, 3))
        self.assertEqual(capture.position_resets, 1)

    def test_extract_clip_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.avi"
            output = root / "clip.mp4"
            _write_synthetic_video(source, fps=10, seconds=5, width=64, height=48)

            extract_clip(source, output, start_sec=1.0, end_sec=4.0)
            meta = probe_video(output)

            self.assertTrue(meta.opened)
            self.assertLessEqual(abs(meta.duration_sec - 3.0), 0.2)
            self.assertEqual((meta.width, meta.height), (64, 48))

    def test_overview_sheet_is_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.avi"
            _write_synthetic_video(source, fps=10, seconds=12, width=64, height=48)

            pages = write_overview_sheets(
                source,
                root / "sheets",
                source_id="synthetic",
                every_sec=5,
                frames_per_page=3,
            )

            self.assertEqual(len(pages), 1)
            self.assertIsNotNone(cv2.imread(str(pages[0])))

    def test_overview_sheet_honors_decoded_duration_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.avi"
            _write_synthetic_video(source, fps=10, seconds=12, width=64, height=48)
            sheet_dir = root / "sheets"
            sheet_dir.mkdir()
            stale = sheet_dir / "limited__overview_999.jpg"
            stale.write_bytes(b"stale")

            pages = write_overview_sheets(
                source,
                sheet_dir,
                source_id="limited",
                every_sec=1,
                frames_per_page=3,
                duration_limit_sec=2,
            )

            self.assertEqual(len(pages), 1)
            self.assertFalse(stale.exists())

    def test_scene_contact_sheet_is_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.avi"
            output = root / "candidate.jpg"
            _write_synthetic_video(source, fps=10, seconds=12, width=64, height=48)

            written = write_scene_contact_sheet(
                source,
                output,
                source_id="synthetic",
                start_sec=2,
                end_sec=10,
                sample_count=5,
            )

            self.assertEqual(written, output)
            self.assertIsNotNone(cv2.imread(str(output)))

    def test_sha256_file_matches_known_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "value.bin"
            path.write_bytes(b"abc")

            self.assertEqual(
                sha256_file(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )


class TrainingScenePrepInventoryTests(unittest.TestCase):
    def test_typescript_mts_is_not_video(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            code = root / "index.d.mts"
            code.write_text('import { FSLike } from "fdir";', encoding="utf-8")

            classification = classify_candidate(code, project_root=root)

            self.assertEqual(classification.disposition, "excluded")
            self.assertEqual(classification.reason, "typescript_mts")

    def test_comment_leading_node_modules_mts_is_typescript(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            code = root / "node_modules" / "date-fns" / "addDays.d.mts"
            code.parent.mkdir(parents=True)
            code.write_text("/** @name addDays */\nexport declare function addDays(): void;", encoding="utf-8")

            classification = classify_candidate(code, project_root=root)

            self.assertEqual(classification.reason, "typescript_mts")

    def test_unknown_review_label_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "review_decisions.csv"
            path.write_text(
                "source_id,start_sec,end_sec,label,cue,disposition,notes\n"
                "s1,0,10,not_a_label,cue,ready,bad\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "not_a_label"):
                read_review_decisions(path)

    def test_valid_review_decision_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "review_decisions.csv"
            path.write_text(
                "source_id,start_sec,end_sec,label,cue,disposition,notes\n"
                "s1,2,14,drowsy,eyes_closed,ready,clear\n",
                encoding="utf-8",
            )

            rows = read_review_decisions(path)

            self.assertEqual(
                rows,
                [ReviewedScene("s1", 2.0, 14.0, "drowsy", "eyes_closed", "ready", "clear")],
            )

    def test_discovery_includes_media_extensions_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "clip.mp4").write_bytes(b"video")
            (root / "types.mts").write_text("export type X = string;", encoding="utf-8")
            (root / "notes.txt").write_text("ignore", encoding="utf-8")

            paths = discover_media_candidates(root)

            self.assertEqual(
                {path.name for path in paths},
                {"clip.mp4", "types.mts"},
            )

    def test_discovery_uses_fast_rg_listing_when_runner_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            expected = root / "clip.mp4"
            calls: list[list[str]] = []

            def fake_runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                calls.append(command)
                return subprocess.CompletedProcess(command, 0, stdout=f"{expected}\n", stderr="")

            paths = discover_media_candidates(root, runner=fake_runner)

            self.assertEqual(paths, [expected])
            self.assertEqual(calls[0][:4], ["rg", "--files", "--hidden", "--no-ignore"])

    def test_inventory_marks_exact_focusai_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            video_dir = project / "ai" / "tmp" / "videos"
            video_dir.mkdir(parents=True)
            first = video_dir / "first.avi"
            second = video_dir / "second.avi"
            _write_synthetic_video(first, fps=5, seconds=1, width=32, height=24)
            shutil.copyfile(first, second)

            records = build_inventory_records(
                [first, second],
                project_root=project,
                output_root=Path(temp_dir) / "output",
            )

            self.assertEqual(records[0].disposition, "focusai")
            self.assertEqual(records[1].disposition, "duplicate")
            self.assertEqual(records[1].duplicate_of, records[0].path)

    def test_project_source_wins_over_external_session54_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "graduation" / "-"
            video_dir = project / "ai" / "tmp" / "videos"
            video_dir.mkdir(parents=True)
            project_source = video_dir / "54_8_chunk_1_value.avi"
            external = root / "session_54_full.webm"
            _write_synthetic_video(project_source, fps=5, seconds=1, width=32, height=24)
            shutil.copyfile(project_source, external)

            records = build_inventory_records(
                [external, project_source],
                project_root=project,
                output_root=root / "output",
            )
            by_path = {record.path: record for record in records}

            self.assertEqual(by_path[str(project_source.resolve())].disposition, "focusai")
            self.assertEqual(by_path[str(external.resolve())].disposition, "duplicate")
            self.assertEqual(
                by_path[str(external.resolve())].duplicate_of,
                str(project_source.resolve()),
            )

    def test_analysis_path_maps_session_chunk_and_s002(self) -> None:
        project = Path(r"C:\project")
        output = Path(r"C:\output")

        self.assertEqual(
            analysis_path_for_source(
                project / "ai" / "tmp" / "videos" / "54_8_chunk_2_hash.webm",
                project_root=project,
                output_root=output,
            ),
            project / "ai" / "tmp" / "session_54" / "chunk_2_result.json",
        )
        self.assertEqual(
            analysis_path_for_source(
                project / "ai" / "downloads" / "S002_test.mp4",
                project_root=project,
                output_root=output,
            ),
            output / "analysis" / "S002_test.json",
        )

    def test_inventory_stage_writes_readable_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            computer = Path(temp_dir) / "computer"
            project = computer / "project"
            video_dir = project / "ai" / "tmp" / "videos"
            video_dir.mkdir(parents=True)
            source = video_dir / "54_8_chunk_1_value.avi"
            _write_synthetic_video(source, fps=5, seconds=2, width=32, height=24)
            output = computer / "output"

            summary = run_inventory(
                computer_root=computer,
                project_root=project,
                output_root=output,
            )
            records = read_inventory_csv(output / "manifests" / "source_inventory.csv")

            self.assertEqual(summary["candidate_count"], 1)
            self.assertEqual(summary["unique_focusai_count"], 1)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].disposition, "focusai")

    def test_output_root_cannot_be_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()

            with self.assertRaisesRegex(ValueError, "output root"):
                ensure_safe_output_root(project, project_root=project)

    def test_nested_worker_analysis_timeline_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "result.json"
            expected = [{"t": 1, "rule_state": "focus", "flags": {"face_seen": True}}]
            path.write_text(
                json.dumps(
                    {
                        "analysis_result": {
                            "meta": {"duration_sec": 5},
                            "front_result": {"timeline": expected},
                        }
                    }
                ),
                encoding="utf-8",
            )

            duration, timeline = load_analysis_timeline(path)

            self.assertEqual(duration, 5)
            self.assertEqual(timeline, expected)

    def test_sheets_stage_writes_overview_and_candidate_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            computer = Path(temp_dir) / "computer"
            project = computer / "project"
            video_dir = project / "ai" / "tmp" / "videos"
            video_dir.mkdir(parents=True)
            source = video_dir / "54_8_chunk_1_value.avi"
            _write_synthetic_video(source, fps=5, seconds=5, width=64, height=48)
            analysis = project / "ai" / "tmp" / "session_54" / "chunk_1_result.json"
            analysis.parent.mkdir(parents=True)
            analysis.write_text(
                json.dumps(
                    {
                        "analysis_result": {
                            "meta": {"duration_sec": 5},
                            "front_result": {
                                "timeline": [
                                    {"t": 1, "rule_state": "gaze_side", "flags": {"gaze_side": True}},
                                    {"t": 2, "rule_state": "gaze_side", "flags": {"gaze_side": True}},
                                ]
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            output = computer / "output"
            run_inventory(computer_root=computer, project_root=project, output_root=output)

            summary = run_sheets(
                project_root=project,
                output_root=output,
                every_sec=2,
            )
            manifest = output / "manifests" / "candidate_scenes.csv"
            with manifest.open("r", newline="", encoding="utf-8-sig") as file:
                rows = list(csv.DictReader(file))

            self.assertEqual(summary["source_count"], 1)
            self.assertGreaterEqual(summary["overview_page_count"], 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["suggested_label"], "gaze_side")
            candidate_sheet = Path(rows[0]["sheet_path"])
            self.assertTrue(candidate_sheet.is_file())

            old_timestamp = 946684800
            os.utime(candidate_sheet, (old_timestamp, old_timestamp))
            run_sheets(project_root=project, output_root=output, every_sec=2)

            self.assertEqual(int(candidate_sheet.stat().st_mtime), old_timestamp)

    def test_extract_and_verify_write_traceable_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            computer = Path(temp_dir) / "computer"
            project = computer / "project"
            video_dir = project / "ai" / "tmp" / "videos"
            video_dir.mkdir(parents=True)
            source = video_dir / "54_8_chunk_1_value.avi"
            _write_synthetic_video(source, fps=5, seconds=5, width=64, height=48)
            output = computer / "output"
            run_inventory(computer_root=computer, project_root=project, output_root=output)
            decisions = output / "review_decisions.csv"
            decisions.write_text(
                "source_id,start_sec,end_sec,label,cue,disposition,notes\n"
                "session54_chunk1,0,4,focus,writing_head_down,ready,clear\n",
                encoding="utf-8",
            )

            summary = run_extract(
                project_root=project,
                output_root=output,
                decisions_path=decisions,
            )
            verification = run_verify(project_root=project, output_root=output)

            clips = list((output / "train_ready" / "focus").glob("*.mp4"))
            self.assertEqual(summary["clip_count"], 1)
            self.assertEqual(len(clips), 1)
            self.assertTrue((output / "manifests" / "clips_manifest.csv").is_file())
            self.assertTrue((output / "manifests" / "scene_balance.csv").is_file())
            self.assertTrue((output / "shortage_report.md").is_file())
            self.assertIn(
                "FocusAI 부족 장면 보고서",
                (output / "shortage_report.md").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "FocusAI 학습 장면 준비 결과",
                (output / "README.md").read_text(encoding="utf-8"),
            )
            self.assertEqual(verification["errors"], [])

    def test_verify_detects_changed_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            computer = Path(temp_dir) / "computer"
            project = computer / "project"
            video_dir = project / "ai" / "tmp" / "videos"
            video_dir.mkdir(parents=True)
            source = video_dir / "54_8_chunk_1_value.avi"
            _write_synthetic_video(source, fps=5, seconds=5, width=64, height=48)
            output = computer / "output"
            run_inventory(computer_root=computer, project_root=project, output_root=output)
            decisions = output / "review_decisions.csv"
            decisions.write_text(
                "source_id,start_sec,end_sec,label,cue,disposition,notes\n"
                "session54_chunk1,0,4,focus,screen_focus,ready,clear\n",
                encoding="utf-8",
            )
            run_extract(project_root=project, output_root=output, decisions_path=decisions)
            source.write_bytes(source.read_bytes() + b"changed")

            verification = run_verify(project_root=project, output_root=output)

            self.assertTrue(any("source hash changed" in error for error in verification["errors"]))


class TrainingScenePrepCliTests(unittest.TestCase):
    def test_cli_help_lists_all_stages(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        script = project_root / "scripts" / "prepare_focusai_training_scenes.py"

        completed = subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("inventory", completed.stdout)
        self.assertIn("sheets", completed.stdout)
        self.assertIn("extract", completed.stdout)
        self.assertIn("verify", completed.stdout)


if __name__ == "__main__":
    unittest.main()
