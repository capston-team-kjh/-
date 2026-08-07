# FocusAI Legacy v2 Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, run, and audit an offline pipeline that reuses mapped FocusAI videos and labels to create a leakage-safe `focus-state-v2` dataset and a non-production ONNX candidate.

**Architecture:** Python inventories sources, normalizes label provenance, samples video frames, and runs MediaPipe Tasks. A persistent Vite/Node stream invokes the existing browser TypeScript feature modules for the exact 34-feature causal pipeline. A dedicated legacy trainer uses explicit original-recording splits, exports a protected candidate, and validates it with Python ONNX tools and the browser loader/runtime.

**Tech Stack:** Python 3.12, OpenCV, MediaPipe Tasks, scikit-learn, skl2onnx, ONNX, ONNX Runtime, TypeScript, Vite/Vitest, onnxruntime-web.

## Global Constraints

- Never modify or overwrite `frontend/public/focus_classifier.onnx` or active v1 metadata.
- Read the 34 ordered feature names and four ordered class names only from `frontend/src/ai/contracts/focus-state-v2.schema.json`.
- Use 1 FPS, causal median/IQR calibration (minimum 5, frozen after 30 valid samples), a 10,000 ms temporal window, and a 10-sample quality window from the contract.
- Do not start Worker, SQS, AWS, backend, or Python real-time inference services.
- Do not move, delete, or overwrite any existing source video, label, dataset, model, review material, cache, or candidate.
- Treat Human direct labels separately from Codex/visual direct and rule pseudo-labels.
- Never claim subject generalization without verified subject identity; this run must report source/session generalization only.
- Keep overhead data out of the front face-state tensor and do not train an overhead model without sufficient direct activity labels.

---

### Task 1: Legacy source inventory and label registry

**Files:**
- Create: `ai/browser_ml/legacy_sources.py`
- Create: `ai/tests/test_legacy_v2_pipeline.py`

**Interfaces:**
- Produces: `probe_video(path: Path) -> VideoRecord`, `discover_videos(roots: Sequence[Path]) -> tuple[VideoRecord, ...]`, `load_legacy_labels(...) -> LegacyLabelRegistry`.
- `LegacyLabel` carries `source_path`, `source_group_id`, `timestamp_ms` or `[start_ms,end_ms)`, `label`, category A-E, status, confidence, and split hint.

- [ ] **Step 1: Write failing inventory and provenance tests**

```python
def test_human_point_labels_are_category_a_and_keep_original_group():
    registry = load_human_point_labels(labels_csv, clip_manifest)
    assert registry.labels[0].category == "A_HUMAN_DIRECT"
    assert registry.labels[0].source_group_id == "2026-04-15 12-44-13"

def test_ambiguous_blind_rows_are_audited_but_not_eligible():
    registry = load_blind_visual_labels(review_csv, source_map_csv)
    assert registry.labels[0].eligible is False
    assert registry.labels[0].exclusion_reason == "ambiguous"
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `..\.venv-browser-ml-312\Scripts\python.exe -m unittest ai.tests.test_legacy_v2_pipeline.LegacySourceTests -v`

Expected: import failure for `ai.browser_ml.legacy_sources`.

- [ ] **Step 3: Implement minimal inventory and known-format loaders**

Implement immutable records, SHA-256/probe metadata, duplicate-path de-duplication, Human point CSV + 3-minute manifest mapping, blind review + private source map joins, frame segment + JSON manifest joins, and an audit-only generic label discovery record. Refuse uncertain path matches.

- [ ] **Step 4: Run tests and confirm GREEN**

Run the Task 1 test class and expect all tests to pass.

- [ ] **Step 5: Commit**

```powershell
git add ai/browser_ml/legacy_sources.py ai/tests/test_legacy_v2_pipeline.py
git commit -m "feat: inventory legacy focusai sources and labels"
```

### Task 2: Exact browser feature stream

**Files:**
- Modify: `frontend/src/ai/continuous-features.ts`
- Create: `frontend/scripts/focus-v2-feature-stream.ts`
- Create: `frontend/scripts/focus-v2-feature-stream.test.ts`

**Interfaces:**
- Produces: `createOfflineFeatureProcessor()` and JSONL commands `describe`, `sample`.
- `describe` returns schema/config and required landmark indices; `sample` accepts `timestamp_ms`, sparse face landmarks, and sparse pose landmarks and returns the existing `FrontV2FeaturePipeline` result.

- [ ] **Step 1: Write failing Vitest cases**

```typescript
it("uses the production v2 modules and emits contract-ordered features", () => {
  const processor = createOfflineFeatureProcessor();
  const row = processor.process(sampleAt(6000));
  expect(Object.keys(row.values)).toEqual(FRONT_V2_SCHEMA.feature_names);
});

it("does not let a future observation alter an earlier row", () => {
  const first = runSequence(samples.slice(0, 8))[7];
  const withFuture = runSequence([...samples.slice(0, 8), extremeFuture])[7];
  expect(withFuture.values).toEqual(first.values);
});
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `npm test -- scripts/focus-v2-feature-stream.test.ts` from `frontend`.

Expected: module not found.

- [ ] **Step 3: Implement the stream and exported landmark-index constants**

Export the exact indices already used by `extractFrontMeasurements` without changing calculations. Reconstruct sparse arrays, call `extractFrontMeasurements`, then call `FrontV2FeaturePipeline(frontV2RuntimeConfig())`. Keep CLI JSONL handling outside test-only behavior.

- [ ] **Step 4: Run focused and existing frontend AI tests**

Run: `npm test -- scripts/focus-v2-feature-stream.test.ts src/ai/continuous-features.test.ts src/ai/personal-normalization.test.ts src/ai/temporal-window.test.ts`.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/ai/continuous-features.ts frontend/scripts/focus-v2-feature-stream.ts frontend/scripts/focus-v2-feature-stream.test.ts
git commit -m "feat: stream offline landmarks through browser v2 features"
```

### Task 3: MediaPipe extraction and keyed per-source cache

**Files:**
- Create: `ai/browser_ml/legacy_extraction.py`
- Modify: `ai/tests/test_legacy_v2_pipeline.py`

**Interfaces:**
- Consumes: `VideoRecord`, `LegacyLabelRegistry`, the TypeScript `describe/sample` JSONL protocol.
- Produces: `extract_source_features(request: ExtractionRequest) -> ExtractionResult` and immutable cache CSV/metadata JSON keyed by source/model/contract hashes.

- [ ] **Step 1: Write failing cache, camera, and causal sampling tests**

```python
def test_cache_key_changes_when_contract_or_source_hash_changes():
    assert cache_key(base) != cache_key(replace(base, contract_sha256="f" * 64))

def test_merged_video_sends_only_verified_front_crop():
    result = choose_front_half(left_face_score=8.0, right_face_score=0.2)
    assert result.role == "front" and result.half == "left"

def test_requested_timestamps_include_calibration_and_temporal_history():
    assert 0 in extraction_seconds(labels, duration_sec=180)
    assert 29 in extraction_seconds(labels, duration_sec=180)
```

- [ ] **Step 2: Run tests and confirm RED**

Run the `LegacyExtractionTests` class and expect missing symbols.

- [ ] **Step 3: Implement extraction with injectable detectors/process runner**

Use OpenCV timestamp seeking at 1 FPS, MediaPipe VIDEO mode with strictly increasing timestamps, local task files, left/right face-evidence verification, sparse landmark serialization, per-source subprocess lifetime, atomic new-cache writes, and per-source recoverable errors. Never decode/write full-resolution frame caches.

- [ ] **Step 4: Run tests and a one-source smoke extraction**

Run focused tests, then process one short labeled source into a temporary new run directory and assert finite rows appear after calibration.

- [ ] **Step 5: Commit**

```powershell
git add ai/browser_ml/legacy_extraction.py ai/tests/test_legacy_v2_pipeline.py
git commit -m "feat: extract cached browser v2 features from legacy video"
```

### Task 4: Label join, quality summary, and leakage-safe fixed groups

**Files:**
- Create: `ai/browser_ml/legacy_dataset.py`
- Modify: `ai/tests/test_legacy_v2_pipeline.py`

**Interfaces:**
- Consumes: feature-cache rows and normalized `LegacyLabel` records.
- Produces: `build_legacy_dataset(...) -> LegacyDatasetResult`, training CSV, quality-only CSV, exclusions CSV, dataset summary JSON, and explicit split assignments.

- [ ] **Step 1: Write failing point/interval/split tests**

```python
def test_point_label_selects_nearest_one_fps_row_without_becoming_interval():
    rows = join_labels(features, [point_label(timestamp_ms=10_000)])
    assert [row.timestamp_ms for row in rows] == [10_000]

def test_same_original_recording_cannot_cross_splits():
    with self.assertRaisesRegex(LeakageError, "source_group"):
        validate_split_leakage(conflicting_rows)
```

- [ ] **Step 2: Run tests and confirm RED**

Run `LegacyDatasetTests`; expect missing module/symbols.

- [ ] **Step 3: Implement minimal joins and reports**

Use exact half-open intervals, at most 500 ms point alignment tolerance, four-class eligibility from the contract, explicit quality/exclusion reasons, human test group `2026-06-28 16-04-40`, human validation group `2026-05-27 12-55-27`, and train for all other non-colliding groups. Add `subject_id_known`, `environment_id_known`, `camera_setup_id_known`, `label_category`, `label_source`, `source_sha256`, `source_group_id`, and `split` columns.

- [ ] **Step 4: Run tests and inspect generated synthetic reports**

Confirm zero overlap for source group, session, hash, and label identity.

- [ ] **Step 5: Commit**

```powershell
git add ai/browser_ml/legacy_dataset.py ai/tests/test_legacy_v2_pipeline.py
git commit -m "feat: build leakage-safe legacy v2 dataset"
```

### Task 5: Legacy group trainer and candidate export

**Files:**
- Create: `ai/browser_ml/legacy_training.py`
- Modify: `ai/browser_ml/requirements-training.txt`
- Modify: `ai/tests/test_legacy_v2_pipeline.py`

**Interfaces:**
- Consumes: the explicit-split training CSV and shared feature contract.
- Produces: `train_legacy_candidates(...) -> LegacyTrainingResult` plus ONNX, pickle, metadata, metrics, confusion CSV, dataset summary, and SHA-256.

- [ ] **Step 1: Write failing candidate comparison/export tests**

```python
def test_all_candidates_use_the_same_explicit_split():
    result = train_legacy_candidates(dataset, random_seed=42)
    assert set(result.validation_metrics) == {
        "logistic_regression", "random_forest", "gradient_boosting", "gaussian_nb"
    }

def test_metadata_marks_subject_generalization_invalid():
    assert metadata["subject_generalization_valid"] is False
    assert metadata["evaluation_scope"] == "source_session_generalization"
```

- [ ] **Step 2: Run tests and confirm RED**

Run `LegacyTrainingTests`; expect the legacy trainer import to fail.

- [ ] **Step 3: Implement candidates, metrics, and protected export**

Fit each candidate on train only, select validation macro-F1 with balanced accuracy as tie-breaker, refit the selected model on train+validation, evaluate test once, convert with FloatTensorType `[None, 34]`, write class order from the estimator and contract, and refuse protected/existing output directories. Add ONNX Runtime to the offline requirements.

- [ ] **Step 4: Run synthetic training/export tests**

Assert ONNX checker and ONNX Runtime output shape `[N, 4]`, float input, finite probabilities, metadata SHA equality, and a contract-ordered confusion matrix.

- [ ] **Step 5: Commit**

```powershell
git add ai/browser_ml/legacy_training.py ai/browser_ml/requirements-training.txt ai/tests/test_legacy_v2_pipeline.py
git commit -m "feat: train and export legacy v2 candidate"
```

### Task 6: Browser candidate validation

**Files:**
- Create: `frontend/scripts/validate-focus-v2-candidate.ts`
- Create: `frontend/scripts/validate-focus-v2-candidate.test.ts`

**Interfaces:**
- Consumes: candidate metadata path and ONNX path.
- Produces: browser compatibility JSON bound to candidate SHA-256.

- [ ] **Step 1: Write failing loader/runtime validation test**

```typescript
it("rejects a candidate whose metadata hash is not its ONNX hash", async () => {
  await expect(validateCandidate(paths.withWrongHash)).rejects.toThrow(/SHA-256/);
});
```

- [ ] **Step 2: Run test and confirm RED**

Run: `npm test -- scripts/validate-focus-v2-candidate.test.ts`.

- [ ] **Step 3: Implement validation through the actual loader**

Use `loadBrowserModel` with local file adapters and a real
`onnxruntime-web.InferenceSession`. Verify input/output names, float32 shape,
four-class order, feature order, schema/model version, normalization,
confidence threshold, SHA, and finite four-value output.

- [ ] **Step 4: Run focused test**

Expect valid fixture pass and wrong hash/order/shape failures.

- [ ] **Step 5: Commit**

```powershell
git add frontend/scripts/validate-focus-v2-candidate.ts frontend/scripts/validate-focus-v2-candidate.test.ts
git commit -m "test: validate v2 candidate in browser runtime"
```

### Task 7: End-to-end CLI and A-P report artifacts

**Files:**
- Create: `ai/build_legacy_v2_candidate.py`
- Modify: `ai/browser_ml/README.md`
- Modify: `ai/tests/test_legacy_v2_pipeline.py`

**Interfaces:**
- Consumes: explicit data roots and label paths.
- Produces: one immutable run directory plus machine-readable `final-report.json` and human-readable `final-report.md` with sections A-P.

- [ ] **Step 1: Write failing CLI/protection/report tests**

```python
def test_cli_refuses_existing_run_directory():
    with self.assertRaises(FileExistsError):
        run_pipeline(config_with_existing_output)

def test_final_report_has_all_required_sections():
    assert list(report) == list("ABCDEFGHIJKLMNOP")
```

- [ ] **Step 2: Run tests and confirm RED**

Run `LegacyPipelineCliTests`; expect missing CLI functions.

- [ ] **Step 3: Implement orchestration and documentation**

Wire inventory, registry, extraction, dataset, training, and browser validation. Record recoverable exclusions, overhead-label insufficiency, v1 comparison availability, production status, model/task/source hashes, commands, and environment versions. Documentation must show the Python 3.12 offline venv command and explicit arguments.

- [ ] **Step 4: Run all new tests and CLI help**

Run new Python tests, frontend script tests, and `python ai/build_legacy_v2_candidate.py --help`.

- [ ] **Step 5: Commit**

```powershell
git add ai/build_legacy_v2_candidate.py ai/browser_ml/README.md ai/tests/test_legacy_v2_pipeline.py
git commit -m "feat: orchestrate legacy v2 candidate run"
```

### Task 8: Real data run and final verification

**Files:**
- Generate only: `ai/browser_ml/artifacts/legacy-v2/<run-id>/**`

**Interfaces:**
- Produces the real dataset, candidate, reports, caches, and compatibility evidence.

- [ ] **Step 1: Record protected v1 hashes and create Python 3.12 offline environment**

Run `Get-FileHash frontend/public/focus_classifier.onnx -Algorithm SHA256` and metadata hashes. Create `C:\Projects\졸작우승기원\.venv-browser-ml-312` from the installed Python 3.12 and install only `ai/requirements.txt` plus `ai/browser_ml/requirements-training.txt` as needed for extraction/training.

- [ ] **Step 2: Execute the full immutable run**

Pass the confirmed project, Downloads, training-scenes, frame-label, human-label, blind-label, and manifest roots. Continue after per-source decode/match/extraction failures and preserve the exclusion audit.

- [ ] **Step 3: Validate artifacts and Browser compatibility**

Run ONNX checker/runtime and the TypeScript browser validator against the exact candidate SHA. Confirm input `[None,34]`, float32, output `[None,4]`, and contract class/feature order.

- [ ] **Step 4: Run regression verification**

```powershell
..\.venv-browser-ml-312\Scripts\python.exe -m unittest ai.tests.test_browser_ml_v2 ai.tests.test_legacy_v2_pipeline -v
cd frontend
npm test
npm run build
```

- [ ] **Step 5: Review status, diff, artifacts, and protected hashes**

Run `git status --short`, `git diff --check`, inspect every changed source file, compare before/after v1 hashes, and assert the candidate path is outside `frontend/public`.

- [ ] **Step 6: Commit source changes only**

Generated real-data artifacts remain uncommitted/ignored unless the repository's existing policy explicitly tracks them. Commit only intentional source/tests/docs and report the artifact paths to the user.
