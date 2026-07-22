# FocusAI Blind Direct Labeling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the pseudo-labeled FocusAI classifier with the same runtime classifier trained and evaluated from independently created blind visual labels.

**Architecture:** Build a deterministic local-only blind review workspace from the existing 201 candidate clips without carrying over labels, cues, notes, or label-bearing paths. Freeze direct visual labels before comparing them with existing labels, then combine those labels with the existing 16 analyzer features, split by source group, train the unchanged `SimpleStateClassifier`, and replace the model and reports in draft PR #8.

**Tech Stack:** Python 3.12 target, `unittest`, OpenCV, NumPy, CSV/JSON, existing `ai.training_scene_prep` media helpers, existing `SimpleStateClassifier`, PowerShell and Git.

## Global Constraints

- Keep the runtime classes exactly `focus`, `drowsy`, `gaze_down`, `gaze_side`, and `unknown`.
- Keep the existing 16 feature names, classifier type, model path, confidence threshold, worker/API behavior, score rules, and frontend contract.
- Do not copy existing labels, suggested labels, cues, notes, folder labels, or `rule_state` values into the new direct-label manifest.
- Do not view old labels until every blind item is frozen as accepted or ambiguous.
- Process video and frames locally; do not call OpenAI Vision or any paid/external inference API.
- Never modify source videos. Keep contact sheets, source maps, logs, and absolute local paths outside Git.
- Keep all intervals from one source group entirely in train or test.
- Treat mixed or unresolvable intervals as `ambiguous` and exclude them instead of forcing `unknown`.

---

## File Structure

- Create `ai/blind_labeling.py`: blind interval construction, stable IDs, manifest schemas, contact-sheet generation, label validation, and audit helpers.
- Create `scripts/prepare_focusai_blind_labels.py`: CLI for `prepare`, `verify`, and `freeze` operations against a local workspace.
- Create `ai/tests/test_blind_labeling.py`: unit and synthetic-media coverage for blind preparation and leakage prevention.
- Create `ai/train_direct_state_classifier.py`: direct-label feature joining, source-group split, training, evaluation, model serialization, and reports.
- Create `ai/tests/test_train_direct_state_classifier.py`: sample joining, split isolation, model metadata, and report tests.
- Create `ai/direct_labeling/blind_labels.csv`: frozen sanitized direct labels with no absolute paths or previous labels.
- Create `ai/direct_labeling/labeling_summary.json`: counts, freeze checksum, label source, and exclusion totals.
- Create `docs/ai_direct_labeling.md`: reproducible local workflow, criteria, provenance, and limitations.
- Modify `ai/models/state_classifier.pkl`: replace pseudo-labeled model with direct-label model.
- Modify `ai/state_classifier_training/clip_report.csv`: replace pseudo-label provenance with direct-label interval provenance.
- Modify `ai/state_classifier_training/summary.json`: direct-label metrics and source-group split summary.
- Modify `ai/state_classifier_training/test_metrics_detailed.json`: direct-label held-out metrics.
- Modify `ai/state_classifier_training/test_predictions.csv`: held-out predictions using direct labels.
- Modify `ai/state_classifier_training/test_report.md`: report direct-label results and limitations.
- Modify `ai/state_classifier_training/test_samples.csv`: held-out analyzer features paired with direct labels.
- Modify `ai/state_classifier_training/train_samples.csv`: training analyzer features paired with direct labels.
- Modify `README.md`: link the direct-label workflow and state the model label source.
- Modify `.gitignore`: ignore any in-repository blind contact sheets or source maps defensively.

---

### Task 1: Blind Interval and Label Validation Core

**Files:**
- Create: `ai/blind_labeling.py`
- Create: `ai/tests/test_blind_labeling.py`

**Interfaces:**
- Consumes: rows from `clips_manifest.csv` containing `source_path`, `source_sha256`, `start_sec`, and `end_sec`.
- Produces: `BlindInterval`, `DirectLabel`, `build_blind_intervals(rows)`, `blind_id_for(...)`, `read_direct_labels(path)`, and `validate_direct_labels(intervals, labels)`.

- [ ] **Step 1: Write failing tests for stable IDs, overlap merging, ten-second splitting, and leakage rejection**

```python
import unittest

from ai.blind_labeling import (
    BlindLabelError,
    blind_id_for,
    build_blind_intervals,
    validate_manifest_columns,
)


class BlindLabelingTests(unittest.TestCase):
    def test_blind_id_is_stable_and_contains_no_source_name(self) -> None:
        value = blind_id_for("abc123", 10.0, 20.0)
        self.assertEqual(value, blind_id_for("abc123", 10.0, 20.0))
        self.assertTrue(value.startswith("B"))
        self.assertNotIn("abc123", value)

    def test_overlaps_become_non_overlapping_ten_second_intervals(self) -> None:
        rows = [
            {"source_sha256": "abc", "source_path": "source.mp4", "start_sec": "0", "end_sec": "15"},
            {"source_sha256": "abc", "source_path": "source.mp4", "start_sec": "10", "end_sec": "25"},
        ]
        intervals = build_blind_intervals(rows)
        self.assertEqual(
            [(row.start_sec, row.end_sec) for row in intervals],
            [(0.0, 10.0), (10.0, 20.0), (20.0, 25.0)],
        )

    def test_existing_label_columns_are_rejected(self) -> None:
        with self.assertRaises(BlindLabelError):
            validate_manifest_columns(["blind_id", "suggested_label"])
```

- [ ] **Step 2: Run the focused tests and confirm the missing module failure**

Run: `.\.venv\Scripts\python.exe -B -m unittest ai.tests.test_blind_labeling -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'ai.blind_labeling'`.

- [ ] **Step 3: Implement the blind data types and pure functions**

```python
@dataclass(frozen=True)
class BlindInterval:
    blind_id: str
    source_group: str
    source_sha256: str
    source_path: Path
    start_sec: float
    end_sec: float


@dataclass(frozen=True)
class DirectLabel:
    blind_id: str
    direct_label: str
    confidence: str
    evidence: str
    review_status: str
    annotator: str
    annotated_at: str


FORBIDDEN_COLUMNS = {"label", "suggested_label", "cue", "notes", "rule_state"}
DIRECT_CLASSES = {"focus", "drowsy", "gaze_down", "gaze_side", "unknown"}
```

Implement merging by `source_sha256`, sort intervals by start time, merge overlap, split into at most 10 seconds, and fold a final remainder shorter than 5 seconds into the preceding interval. Generate `blind_id` as `B` plus the first 12 hexadecimal characters of SHA-256 over `source_sha256|start_sec|end_sec` and generate `source_group` from the source hash without exposing the path.

- [ ] **Step 4: Run focused tests and confirm all pass**

Run: `.\.venv\Scripts\python.exe -B -m unittest ai.tests.test_blind_labeling -v`

Expected: all Task 1 tests PASS.

- [ ] **Step 5: Commit Task 1**

```powershell
git add ai/blind_labeling.py ai/tests/test_blind_labeling.py
git commit -m "feat: add blind labeling core"
```

---

### Task 2: Local Blind Review Workspace CLI

**Files:**
- Modify: `ai/blind_labeling.py`
- Create: `scripts/prepare_focusai_blind_labels.py`
- Modify: `ai/tests/test_blind_labeling.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `build_blind_intervals()` from Task 1 and the existing `_frame_at()` / `_contact_tile()` media helpers.
- Produces: `write_blind_contact_sheet(interval, output_path)`, `write_review_workspace(...)`, and CLI commands `prepare`, `verify`, and `freeze`.

- [ ] **Step 1: Write failing synthetic-video and CLI leakage tests**

```python
class BlindWorkspaceTests(unittest.TestCase):
    def test_workspace_omits_previous_label_fields(self) -> None:
        write_review_workspace(clips_manifest, output_root)
        review_header = next(csv.reader((output_root / "blind_review.csv").open(encoding="utf-8-sig")))
        self.assertEqual(review_header, [
            "blind_id", "sheet_path", "direct_label", "confidence", "evidence",
            "review_status", "annotator", "annotated_at",
        ])
        text = (output_root / "blind_review.csv").read_text(encoding="utf-8-sig")
        self.assertNotIn("suggested_label", text)
        self.assertNotIn("rule_state", text)

    def test_contact_sheet_has_five_tiles(self) -> None:
        sheet = cv2.imread(str(write_blind_contact_sheet(interval, output_path)))
        self.assertIsNotNone(sheet)
        self.assertGreaterEqual(sheet.shape[1], 5 * 200)
```

- [ ] **Step 2: Run focused tests and confirm they fail on missing workspace functions**

Run: `.\.venv\Scripts\python.exe -B -m unittest ai.tests.test_blind_labeling -v`

Expected: FAIL because `write_review_workspace` and `write_blind_contact_sheet` do not exist.

- [ ] **Step 3: Implement contact sheets and the three CLI commands**

`prepare` writes the following under the output root:

```text
blind_review.csv
private/source_map.csv
contact_sheets/Bxxxxxxxxxxxx.jpg
summary.json
```

`blind_review.csv` exposes only the blind ID, sheet path, and blank review fields. `private/source_map.csv` includes source paths and interval times but no existing labels, cues, notes, folders, or rule states. `verify` rejects missing sheets, duplicate IDs, forbidden columns, invalid labels, and accepted rows without confidence/evidence. `freeze` requires every row to be `accepted` or `ambiguous`, writes a SHA-256 checksum, and refuses later edits unless the output root is recreated explicitly.

- [ ] **Step 4: Add defensive ignore rules**

```gitignore
# Local blind-label review media and private path maps
ai/direct_labeling/contact_sheets/
ai/direct_labeling/private/
focusai_blind_labeling_*/
```

- [ ] **Step 5: Run focused tests and CLI help checks**

Run: `.\.venv\Scripts\python.exe -B -m unittest ai.tests.test_blind_labeling -v`

Run: `.\.venv\Scripts\python.exe -B scripts\prepare_focusai_blind_labels.py --help`

Expected: tests PASS and help lists `prepare`, `verify`, and `freeze`.

- [ ] **Step 6: Commit Task 2**

```powershell
git add .gitignore ai/blind_labeling.py ai/tests/test_blind_labeling.py scripts/prepare_focusai_blind_labels.py
git commit -m "feat: prepare local blind review sets"
```

---

### Task 3: Generate, Independently Label, and Freeze the Blind Set

**Files:**
- Create: `ai/direct_labeling/blind_labels.csv`
- Create: `ai/direct_labeling/labeling_summary.json`
- Local only: `C:\Projects\focusai_blind_labeling_2026-07-22\`

**Interfaces:**
- Consumes: Task 2 CLI and `C:\Projects\focusai_training_scenes_2026-07-18\manifests\clips_manifest.csv`.
- Produces: frozen direct labels with provenance `codex_visual_direct` and no absolute source paths.

- [ ] **Step 1: Generate the blind review workspace**

Run:

```powershell
.\.venv\Scripts\python.exe -B scripts\prepare_focusai_blind_labels.py prepare `
  --clips-manifest C:\Projects\focusai_training_scenes_2026-07-18\manifests\clips_manifest.csv `
  --output-root C:\Projects\focusai_blind_labeling_2026-07-22
```

Expected: exit 0, 201 input clips reported, all 23 source paths readable, and a deterministic non-overlapping blind interval count in `summary.json`.

- [ ] **Step 2: Verify the blank workspace before any visual review**

Run:

```powershell
.\.venv\Scripts\python.exe -B scripts\prepare_focusai_blind_labels.py verify `
  --output-root C:\Projects\focusai_blind_labeling_2026-07-22 `
  --allow-pending
```

Expected: exit 0, zero forbidden columns, zero missing sheets, and every row pending.

- [ ] **Step 3: Label every blind item from visual evidence only**

For each pending `blind_id`, open only its contact sheet with `view_image`. Use the five direct classes and criteria from the design. When the sheet cannot establish temporal continuity, inspect extra frames or the short local clip using its blind ID without opening existing label files. Record exactly one of:

```csv
B0123456789ab,contact_sheets/B0123456789ab.jpg,focus,high,"continuous writing across all frames",accepted,codex_visual_direct,2026-07-22T00:00:00+09:00
Babcdef012345,contact_sheets/Babcdef012345.jpg,,,"mixed behavior across interval",ambiguous,codex_visual_direct,2026-07-22T00:00:00+09:00
```

Do not infer a label from paths, filenames, rule outputs, or old CSV files. Do not use scripts to auto-fill labels.

- [ ] **Step 4: Validate and freeze the completed review**

Run:

```powershell
.\.venv\Scripts\python.exe -B scripts\prepare_focusai_blind_labels.py verify `
  --output-root C:\Projects\focusai_blind_labeling_2026-07-22
```

Run:

```powershell
.\.venv\Scripts\python.exe -B scripts\prepare_focusai_blind_labels.py freeze `
  --output-root C:\Projects\focusai_blind_labeling_2026-07-22 `
  --labels-output ai\direct_labeling\blind_labels.csv `
  --summary-output ai\direct_labeling\labeling_summary.json
```

Expected: exit 0, no pending rows, a recorded checksum, and no absolute paths or previous-label columns in committed outputs.

- [ ] **Step 5: Compare only after freeze and write an audit report outside training inputs**

Run the CLI audit command implemented as part of `freeze` to create `C:\Projects\focusai_blind_labeling_2026-07-22\audit\old_label_comparison.csv`. Confirm the file is outside Git and no new label is automatically changed.

- [ ] **Step 6: Commit Task 3**

```powershell
git add ai/direct_labeling/blind_labels.csv ai/direct_labeling/labeling_summary.json
git commit -m "data: add independently reviewed FocusAI labels"
```

---

### Task 4: Direct-Label Training and Source-Isolated Evaluation

**Files:**
- Create: `ai/train_direct_state_classifier.py`
- Create: `ai/tests/test_train_direct_state_classifier.py`
- Reuse: `ai/train_state_classifier.py`
- Reuse: `ai/focus_ai/simple_state_classifier.py`

**Interfaces:**
- Consumes: frozen labels, private source map, existing analysis JSON, `_row_from_timeline_item()`, and `SimpleStateClassifier.fit()`.
- Produces: `load_direct_samples(...)`, `split_source_groups(...)`, `train_direct_classifier(...)`, and CLI outputs compatible with `ai/models/state_classifier.pkl`.

- [ ] **Step 1: Write failing tests for direct-label joining and source isolation**

```python
class DirectTrainingTests(unittest.TestCase):
    def test_direct_label_replaces_rule_state(self) -> None:
        timeline = [{"t": 3, "rule_state": "focus", "flags": {"gaze_side": True}}]
        rows = samples_for_interval(timeline, direct_label="gaze_side", start_sec=0, end_sec=10)
        self.assertEqual(rows[0]["label"], "gaze_side")

    def test_source_groups_never_cross_train_and_test(self) -> None:
        rows = [
            {"source_group": "S1", "label": "focus", "features": [0.0] * 16},
            {"source_group": "S2", "label": "gaze_side", "features": [1.0] * 16},
            {"source_group": "S3", "label": "focus", "features": [0.5] * 16},
            {"source_group": "S4", "label": "gaze_side", "features": [0.75] * 16},
        ]
        train_rows, test_rows = split_source_groups(rows, test_fraction=0.2)
        self.assertTrue(
            {row["source_group"] for row in train_rows}.isdisjoint(
                {row["source_group"] for row in test_rows}
            )
        )

    def test_model_metadata_identifies_direct_labels(self) -> None:
        train_rows = [
            {"source_group": "S1", "label": "focus", "features": [0.0] * 16},
            {"source_group": "S2", "label": "gaze_side", "features": [1.0] * 16},
        ]
        bundle = train_direct_classifier(train_rows)
        self.assertEqual(bundle["training"]["label_source"], "codex_visual_direct_labels")
        self.assertNotIn("pseudo", json.dumps(bundle["training"]).lower())
```

- [ ] **Step 2: Run focused tests and confirm missing-module failures**

Run: `.\.venv\Scripts\python.exe -B -m unittest ai.tests.test_train_direct_state_classifier -v`

Expected: FAIL with missing `ai.train_direct_state_classifier`.

- [ ] **Step 3: Implement sample joining, deterministic group split, training, and reports**

Load only `accepted` labels. For every direct interval, read its source analysis JSON and collect front/overhead timeline rows whose `t` lies in `[start_sec, end_sec)`. Reuse `_row_from_timeline_item()` for feature order, but set `label` exclusively from `direct_label`. Split complete source groups with a fixed seed and greedily preserve train coverage for each available class. Serialize:

```python
bundle = {
    "model": model,
    "feature_names": FEATURE_NAMES,
    "classes": list(model.classes_),
    "training": {
        "label_source": "codex_visual_direct_labels",
        "label_freeze_sha256": freeze_sha256,
        "train_source_groups": sorted(train_groups),
        "test_source_groups": sorted(test_groups),
        "metrics": metrics,
    },
}
```

Fail before writing outputs if labels are missing, a source group crosses splits, fewer than two train classes exist, or a private path would enter a report.

- [ ] **Step 4: Run focused tests and the full AI unit suite**

Run: `.\.venv\Scripts\python.exe -B -m unittest ai.tests.test_train_direct_state_classifier -v`

Run: `.\.venv\Scripts\python.exe -B -m unittest discover -s ai\tests -q`

Expected: focused tests PASS and the complete suite reports zero failures.

- [ ] **Step 5: Commit Task 4**

```powershell
git add ai/train_direct_state_classifier.py ai/tests/test_train_direct_state_classifier.py
git commit -m "feat: train classifier from direct labels"
```

---

### Task 5: Train, Replace Artifacts, and Document Provenance

**Files:**
- Modify: `ai/models/state_classifier.pkl`
- Modify: `ai/state_classifier_training/clip_report.csv`
- Modify: `ai/state_classifier_training/summary.json`
- Modify: `ai/state_classifier_training/test_metrics_detailed.json`
- Modify: `ai/state_classifier_training/test_predictions.csv`
- Modify: `ai/state_classifier_training/test_report.md`
- Modify: `ai/state_classifier_training/test_samples.csv`
- Modify: `ai/state_classifier_training/train_samples.csv`
- Create: `docs/ai_direct_labeling.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 3 frozen labels/source map and Task 4 training CLI.
- Produces: drop-in model plus sanitized direct-label training/evaluation artifacts.

- [ ] **Step 1: Run direct-label training into a temporary output root**

Run:

```powershell
.\.venv\Scripts\python.exe -B -m ai.train_direct_state_classifier `
  --labels ai\direct_labeling\blind_labels.csv `
  --label-summary ai\direct_labeling\labeling_summary.json `
  --source-map C:\Projects\focusai_blind_labeling_2026-07-22\private\source_map.csv `
  --output-root C:\Projects\focusai_blind_labeling_2026-07-22\trained
```

Expected: exit 0, source-group isolation confirmed, and model/report files written under `trained`.

- [ ] **Step 2: Inspect the actual held-out metrics without changing labels**

Check sample counts, class support, confusion matrix, macro F1, and per-class recall. If a class has no held-out support, report that limitation; do not move source groups merely to improve the score after seeing predictions.

- [ ] **Step 3: Copy verified outputs over repository artifacts**

Use explicit file paths and preserve the old Git history as recovery. Copy only the model and eight documented training artifacts. Do not copy source maps, contact sheets, logs, absolute paths, or audit comparison files.

- [ ] **Step 4: Write provenance documentation**

`docs/ai_direct_labeling.md` must state the five classes, blind process, interval policy, ambiguous exclusion, source-group split, label checksum, actual metrics, and the fact that the labels were visually assigned without paid Vision/API calls. Update `README.md` to link the document and stop describing pseudo-label agreement as model accuracy.

- [ ] **Step 5: Validate model metadata and path hygiene**

Run a pickle load smoke check that asserts five classes, sixteen features, `label_source == "codex_visual_direct_labels"`, and no `C:\Users\` text. Run `rg` over tracked artifacts for `pseudo-label`, `rule_state pseudo`, `C:\Users\`, and API key patterns; any historical explanation must clearly say it describes the replaced model.

- [ ] **Step 6: Commit Task 5**

```powershell
git add README.md ai/models/state_classifier.pkl ai/state_classifier_training docs/ai_direct_labeling.md
git commit -m "feat: replace classifier with direct-label model"
```

---

### Task 6: Full Verification and Draft PR Update

**Files:**
- Review: all files changed since commit `a769df0`
- Update remotely: branch `agent/publish-ai-model`, draft PR #8

**Interfaces:**
- Consumes: all earlier task outputs.
- Produces: verified clean branch and updated draft PR with accurate label provenance.

- [ ] **Step 1: Run the complete AI tests**

Run: `.\.venv\Scripts\python.exe -B -m unittest discover -s ai\tests -q`

Expected: all tests PASS with zero failures.

- [ ] **Step 2: Run no-write Python syntax validation**

Run `compileall` with `PYTHONPYCACHEPREFIX` pointing to a temporary directory and exclude virtual environments, `node_modules`, and generated training outputs.

Expected: exit 0.

- [ ] **Step 3: Run model smoke validation**

Load `ai/models/state_classifier.pkl` and assert five classes, sixteen features, direct-label metadata, a frozen label checksum, and no personal path.

Expected: exit 0 and a concise `model-ok` line.

- [ ] **Step 4: Run frontend build and repository checks**

Run: `npm.cmd run build` from `frontend`.

Run: `git diff --check`.

Run: `git status -sb`.

Expected: frontend build exits 0, no whitespace errors, and only intentional changes before the final commit.

- [ ] **Step 5: Review the full diff and commit any final documentation correction**

Review `git diff origin/agent/publish-ai-model...HEAD --stat` and `git diff origin/agent/publish-ai-model...HEAD --name-status`. Confirm no logs, videos, contact sheets, source maps, absolute paths, secrets, or old pseudo-labeled artifacts remain as current results.

- [ ] **Step 6: Push and update draft PR #8**

Push `agent/publish-ai-model`, then update PR #8 to state that the model now uses frozen independent visual labels. Include actual metrics, exclusions, source-group isolation, checks run, and any unsupported classes or environment limitations.

Expected: remote head equals local HEAD and PR remains draft until the user chooses to merge.
