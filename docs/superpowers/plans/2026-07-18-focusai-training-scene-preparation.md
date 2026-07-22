# FocusAI Training Scene Preparation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inventory every local video candidate, analyze all 26 unique FocusAI recordings, extract clearly labeled scene clips, and report scene shortages without modifying source videos.

**Architecture:** Add one isolated preparation module and one thin CLI under the existing AI project. Existing FocusAI analysis JSON supplies candidates, local contact sheets support visual verification, and only reviewed intervals are cut into traceable clips outside the repository.

**Tech Stack:** Python 3.12, standard library, OpenCV from the existing `.venv`, `unittest`, existing FocusAI JSON and `ai/run_local.py`.

## Global Constraints

- Process `C:` and record all 1,414 extension candidates.
- Exclude the 1,242 TypeScript `.mts` files and Windows/program/game media assets with explicit reasons.
- Process 26 unique FocusAI videos totaling about 8.08 hours; mark `C:\Projects\session_54_full.webm` as an exact duplicate.
- Never move, rename, delete, overwrite, or upload source videos or existing artifacts.
- Preserve merged-camera composition and write reviewed clips as MP4 under `C:\Projects\focusai_training_scenes_2026-07-18`.
- Put ambiguous scenes in `needs_review` and exclude them from ready totals.
- Do not change the analyzer, thresholds, model, or operational training script.

## File Structure

- Create `ai/training_scene_prep.py`: scene grouping, media I/O, naming, inventory, CSV, and shortage logic.
- Create `scripts/prepare_focusai_training_scenes.py`: CLI stages `inventory`, `sheets`, `extract`, and `verify`.
- Create `ai/tests/test_training_scene_prep.py`: focused unit and media round-trip tests.
- Generate all data only under `C:\Projects\focusai_training_scenes_2026-07-18`; generated media is not committed.

---

### Task 1: Scene interval and shortage core

**Files:**
- Create: `ai/training_scene_prep.py`
- Create: `ai/tests/test_training_scene_prep.py`

**Interfaces:**
- Produces: `SceneCandidate`, `ReviewedScene`, `group_timeline_candidates()`, `clip_filename()`, `shortage_rows()`.
- Consumes: `analysis_result.front_result.timeline` or `analysis_result.timeline` dictionaries.

- [ ] **Step 1: Write failing grouping, naming, and shortage tests**

```python
import unittest
from ai.training_scene_prep import ReviewedScene, clip_filename, group_timeline_candidates, shortage_rows

class TrainingScenePrepTests(unittest.TestCase):
    def test_grouping_merges_two_second_gap_and_pads(self):
        timeline = [
            {"t": 10, "rule_state": "gaze_down", "flags": {"gaze_down": True}},
            {"t": 11, "rule_state": "gaze_down", "flags": {"gaze_down": True}},
            {"t": 14, "rule_state": "gaze_down", "flags": {"gaze_down": True}},
        ]
        rows = group_timeline_candidates("session54", timeline, duration_sec=100)
        self.assertEqual([(r.start_sec, r.end_sec, r.suggested_label) for r in rows], [(8.0, 17.0, "gaze_down")])

    def test_filename_is_traceable_ascii(self):
        scene = ReviewedScene("session54", 120, 134, "focus", "writing_head_down", "ready", "clear")
        self.assertEqual(clip_filename(scene), "focus__writing-head-down__session54__000120-000134.mp4")

    def test_shortage_uses_all_minimums(self):
        scenes = [ReviewedScene("s1", 0, 10, "gaze_down", "off_task", "ready", "clear")]
        row = {item["label"]: item for item in shortage_rows(scenes)}["gaze_down"]
        self.assertTrue(row["is_shortage"])
        self.assertGreaterEqual(set(row["reasons"]), {"clips<20", "duration<180s", "sources<3"})
```

- [ ] **Step 2: Run the focused test and confirm failure**

Run: `.\.venv\Scripts\python.exe -m unittest ai.tests.test_training_scene_prep -v`

Expected: `ModuleNotFoundError: No module named 'ai.training_scene_prep'`.

- [ ] **Step 3: Implement the minimal core**

```python
ALLOWED_LABELS = ("focus", "drowsy", "gaze_down", "gaze_side", "unknown", "absent", "bad_posture")
READY_LABELS = ("focus", "drowsy", "gaze_down", "gaze_side", "unknown")

@dataclass(frozen=True)
class SceneCandidate:
    source_id: str
    start_sec: float
    end_sec: float
    suggested_label: str
    evidence_flags: tuple[str, ...]

@dataclass(frozen=True)
class ReviewedScene:
    source_id: str
    start_sec: float
    end_sec: float
    label: str
    cue: str
    disposition: str
    notes: str

def clip_filename(scene: ReviewedScene) -> str:
    return f"{_ascii_token(scene.label)}__{_ascii_token(scene.cue).replace('_', '-')}__{_ascii_token(scene.source_id)}__{int(scene.start_sec):06d}-{int(scene.end_sec):06d}.mp4"
```

Grouping uses a maximum two-second internal gap, two-second padding, source-bound clamping, 12-second minimum for `drowsy`, four-second minimum for other states, and 30-second maximum chunks. `shortage_rows()` ignores non-`ready` decisions and applies 20 clips, 180 seconds, and 3 sources.

- [ ] **Step 4: Run tests and confirm all Task 1 tests report `ok`**

- [ ] **Step 5: Commit only Task 1 files**

```powershell
git add -- ai/training_scene_prep.py ai/tests/test_training_scene_prep.py
git commit -m "feat: add FocusAI scene preparation core"
```

### Task 2: Safe media probe, sheets, and extraction

**Files:**
- Modify: `ai/training_scene_prep.py`
- Modify: `ai/tests/test_training_scene_prep.py`

**Interfaces:**
- Produces: `VideoMeta`, `probe_video()`, `write_overview_sheets()`, `write_scene_contact_sheet()`, `extract_clip()`, `sha256_file()`.
- Consumes: local source paths and reviewed intervals.

- [ ] **Step 1: Add failing synthetic-video tests**

```python
import cv2
import tempfile
import numpy
from pathlib import Path

def write_synthetic_video(path: Path, *, fps: int, seconds: int, width: int, height: int) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (width, height))
    for index in range(fps * seconds):
        frame = numpy.full((height, width, 3), index % 255, dtype=numpy.uint8)
        writer.write(frame)
    writer.release()

class TrainingScenePrepMediaTests(unittest.TestCase):
    def test_extract_clip_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.avi"
            write_synthetic_video(source, fps=10, seconds=5, width=64, height=48)
            output = root / "clip.mp4"
            extract_clip(source, output, start_sec=1.0, end_sec=4.0)
            meta = probe_video(output)
            self.assertTrue(meta.opened)
            self.assertLessEqual(abs(meta.duration_sec - 3.0), 0.2)
            self.assertEqual((meta.width, meta.height), (64, 48))

    def test_overview_sheet_is_readable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.avi"
            write_synthetic_video(source, fps=10, seconds=12, width=64, height=48)
            pages = write_overview_sheets(source, root / "sheets", every_sec=5, frames_per_page=3)
            self.assertEqual(len(pages), 1)
            self.assertIsNotNone(cv2.imread(str(pages[0])))
```

- [ ] **Step 2: Run focused tests and confirm missing-symbol failures**

- [ ] **Step 3: Implement media functions**

`probe_video()` returns opened state, duration, FPS, dimensions, and frame count. `extract_clip()` seeks to the start, preserves dimensions and FPS, writes a temporary sibling file, verifies it, and atomically renames it. It may delete only a failed temporary output. Sheets burn source ID and timestamp into every tile; overview pages sample every 10 seconds and candidate sheets sample start, quartiles, and end.

- [ ] **Step 4: Run focused tests and confirm all grouping/media tests pass**

- [ ] **Step 5: Commit only Task 2 files**

```powershell
git add -- ai/training_scene_prep.py ai/tests/test_training_scene_prep.py
git commit -m "feat: add safe FocusAI media extraction"
```

### Task 3: Inventory and CLI stages

**Files:**
- Modify: `ai/training_scene_prep.py`
- Create: `scripts/prepare_focusai_training_scenes.py`
- Modify: `ai/tests/test_training_scene_prep.py`

**Interfaces:**
- Produces CLI stages `inventory`, `sheets`, `extract`, `verify`.
- Consumes `--computer-root`, `--project-root`, `--output-root`, worker JSON, and `review_decisions.csv`.

- [ ] **Step 1: Add failing inventory and decision tests**

```python
class TrainingScenePrepInventoryTests(unittest.TestCase):
    def test_typescript_mts_is_not_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            code = root / "index.d.mts"
            code.write_text('import { FSLike } from "fdir";', encoding="utf-8")
            self.assertEqual(classify_candidate(code, project_root=root).reason, "typescript_mts")

    def test_unknown_review_label_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "review_decisions.csv"
            path.write_text("source_id,start_sec,end_sec,label,cue,disposition,notes\ns1,0,10,not_a_label,cue,ready,bad\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not_a_label"):
                read_review_decisions(path)
```

- [ ] **Step 2: Run focused tests and confirm new symbols are missing**

- [ ] **Step 3: Implement inventory and CLI orchestration**

Inventory columns are exactly:

```text
path,extension,size_bytes,sha256,opened,duration_sec,fps,width,height,disposition,reason,duplicate_of,source_id,analysis_json
```

The CLI creates files only below `--output-root`, rejects an output root equal to or above source/project roots, unwraps worker JSON from `analysis_result`, maps session/chunk filenames to `ai/tmp/session_*/chunk_*_result.json`, and loads S002 analysis from `output-root/analysis/S002_test.json`.

Use this record type so inventory serialization is explicit:

```python
@dataclass(frozen=True)
class InventoryRecord:
    path: str
    extension: str
    size_bytes: int
    sha256: str
    opened: bool
    duration_sec: float
    fps: float
    width: int
    height: int
    disposition: str
    reason: str
    duplicate_of: str
    source_id: str
    analysis_json: str
```

- [ ] **Step 4: Run focused and existing AI tests**

```powershell
.\.venv\Scripts\python.exe -m unittest ai.tests.test_training_scene_prep -v
.\.venv\Scripts\python.exe -m unittest discover -s ai\tests
```

Expected: focused tests and the existing AI suite pass; record pre-existing failures separately.

- [ ] **Step 5: Commit only Task 3 files**

```powershell
git add -- ai/training_scene_prep.py scripts/prepare_focusai_training_scenes.py ai/tests/test_training_scene_prep.py
git commit -m "feat: add FocusAI scene preparation CLI"
```

### Task 4: Run inventory, analysis, and visual review

**Files:**
- Generate: `C:\Projects\focusai_training_scenes_2026-07-18\manifests\source_inventory.csv`
- Generate: `C:\Projects\focusai_training_scenes_2026-07-18\analysis\S002_test.json`
- Generate: `C:\Projects\focusai_training_scenes_2026-07-18\contact_sheets\**\*.jpg`
- Create: `C:\Projects\focusai_training_scenes_2026-07-18\review_decisions.csv`

- [ ] **Step 1: Run inventory**

```powershell
.\.venv\Scripts\python.exe scripts\prepare_focusai_training_scenes.py inventory --computer-root C:\ --project-root . --output-root C:\Projects\focusai_training_scenes_2026-07-18
```

Expected: 1,414 candidates; 1,242 TypeScript exclusions; 27 FocusAI paths; one duplicate; 26 unique sources; about 29,105 unique seconds.

- [ ] **Step 2: Analyze S002 because it has no reusable result**

```powershell
$env:SAMPLING_FPS="1"
.\.venv\Scripts\python.exe ai\run_local.py --session-id PREP_S002 --video "C:\Projects\졸작우승기원\-\ai\downloads\S002_test.mp4" --camera-type merged --mode focus_analysis --out "C:\Projects\focusai_training_scenes_2026-07-18\analysis\S002_test.json"
```

Expected: analysis status `success`; source hash, size, and modified time remain unchanged.

- [ ] **Step 3: Generate all overview and dense candidate sheets**

```powershell
.\.venv\Scripts\python.exe scripts\prepare_focusai_training_scenes.py sheets --project-root . --output-root C:\Projects\focusai_training_scenes_2026-07-18 --every-sec 10
```

Expected: every unique source has overview pages and every non-focus candidate has dense evidence.

- [ ] **Step 4: Review every overview and candidate page**

Write exact observed intervals to `review_decisions.csv` using:

```text
source_id,start_sec,end_sec,label,cue,disposition,notes
```

Use `ready` only for clear model labels, `rule_validation` for `absent`/`bad_posture`, and `needs_review` for uncertain boundaries. Include hard-negative `focus` clips showing active reading/writing with the head down.

- [ ] **Step 5: Validate decisions in dry-run mode**

```powershell
.\.venv\Scripts\python.exe scripts\prepare_focusai_training_scenes.py extract --project-root . --output-root C:\Projects\focusai_training_scenes_2026-07-18 --decisions C:\Projects\focusai_training_scenes_2026-07-18\review_decisions.csv --dry-run
```

Expected: zero unknown sources/labels, invalid ranges, or overlapping ready intervals.

### Task 5: Extract, verify, and report

**Files:**
- Generate: final folders and MP4 clips
- Generate: `manifests/clips_manifest.csv`, `manifests/scene_balance.csv`, `README.md`, `shortage_report.md`

- [ ] **Step 1: Extract reviewed clips**

```powershell
.\.venv\Scripts\python.exe scripts\prepare_focusai_training_scenes.py extract --project-root . --output-root C:\Projects\focusai_training_scenes_2026-07-18 --decisions C:\Projects\focusai_training_scenes_2026-07-18\review_decisions.csv
```

Expected: each decision produces a correctly named MP4 and one manifest row.

- [ ] **Step 2: Verify every output and source invariant**

```powershell
.\.venv\Scripts\python.exe scripts\prepare_focusai_training_scenes.py verify --project-root . --output-root C:\Projects\focusai_training_scenes_2026-07-18
```

Expected: zero unreadable clips, invalid ranges, label mismatches, unexpected duplicates, or changed source files.

- [ ] **Step 3: Inspect balance and shortage reports**

Every state must report ready clip count, duration, unique sources, cues, threshold failures, and a concrete next-recording recommendation. `needs_review` must not count as ready.

- [ ] **Step 4: Run final scoped verification**

```powershell
.\.venv\Scripts\python.exe -m unittest ai.tests.test_training_scene_prep -v
git status --short
git diff --check
git diff -- ai/training_scene_prep.py scripts/prepare_focusai_training_scenes.py ai/tests/test_training_scene_prep.py
```

Expected: focused tests pass; only intentional scoped changes appear; unrelated user changes remain untouched.

- [ ] **Step 5: Deliver the output folder and shortage findings**

Report processed/failed sources, clips/duration/sources per class, `needs_review` count, exclusions, verification results, and the exact scene variants that must be recorded next.
