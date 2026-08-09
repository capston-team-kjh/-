# FocusAI Incremental v2 Candidate Design

## 1. Status and objective

This design was approved on 2026-08-09. It defines an isolated offline
`incremental-v2` path that adds the ten recordings under
`C:\Users\wkdgu\OneDrive\바탕 화면\Desktop\ai_labelcsv` to the existing
FocusAI development data, then compares a control and an incremental model on
the existing frozen 65-row test.

The experiment conditions are:

- **A control:** existing development data only.
- **B incremental:** the same existing development data plus the ten new
  recordings.
- A and B use the same model structure, parameters, seed, feature order, class
  order, sample-weight policy, existing split, validation rows, and frozen
  test rows.
- The only intended training-data difference is whether the accepted new
  recording rows are present.

This path never promotes a model or changes the active application.

## 2. Confirmed project boundary

The active browser model remains the production v1 artifact loaded from
`frontend/public/focus_classifier.onnx` through
`frontend/public/models/focus-state-v1.metadata.json`. Production v1 uses the
legacy 16-feature schema.

Incremental v2 uses the existing candidate contract at
`frontend/src/ai/contracts/focus-state-v2.schema.json`:

- schema version: `focus-state-v2`;
- camera role: `front`;
- 34 ordered continuous features;
- class order: `drowsy`, `focus`, `gaze_down`, `gaze_side`;
- causal personal median/IQR normalization;
- 10-second causal temporal window;
- one sample per second in the offline extraction path.

The ten new files are 1280x720, 30 FPS merged-camera recordings. The left half
is the front camera and the right half is the overhead camera. The existing
merged-camera front-half selection and the existing browser-v2 stream are the
only permitted feature path.

The authoritative existing development and test definition is the completed
v3 run at:

```text
ai/experiments/focus_v3_aug/runs/20260808T124939Z/
```

It supplies:

- `selected_split_rows.csv` for existing train/validation 34-feature rows;
- `selected_split.json` for existing group assignments;
- `frozen_test_manifest.json` for the exact 65-row frozen test;
- `experiment-lock.json` for the existing split and contract proof.

The frozen test contains exactly source group `2026-06-28 16-04-40` and 65
rows. It must remain byte- and identity-equivalent to the existing manifest.

## 3. Non-goals and immutable inputs

The incremental run must not:

- change production code or configuration;
- change the browser-v2 extractor or 34-feature schema;
- change MediaPipe model files or feature-stream scripts;
- modify any original video or CSV;
- modify the production v1 artifact or metadata;
- modify the legacy v2 candidate run;
- modify the completed v3 experiment run;
- overwrite an existing incremental run;
- promote B automatically;
- tune any setting from frozen-test results;
- claim person generalization from one subject.

The run records pre-run and post-run SHA-256 values for all protected files and
fails if any protected hash changes.

## 4. Component architecture

New reusable code lives only under `ai/incremental_v2/`, with one thin CLI.

### `ai/incremental_v2/config.py`

Defines immutable configuration, approved roots, run ID, seed, model contract,
protected paths, baseline paths, and canonical serialization.

### `ai/incremental_v2/ingestion.py`

Discovers and pairs new videos and CSVs, parses the two observed interval
schemas, validates video metadata and intervals, and emits input decisions.

### `ai/incremental_v2/lineage.py`

Builds stable row identities and complete accepted/excluded/quarantined
lineage, including subject supplementation and feature-row relationships.

### `ai/incremental_v2/splitting.py`

Assigns whole new video/source groups to new train or new validation and
verifies that no source, video, hash, label identity, or sample identity crosses
a split.

### `ai/incremental_v2/guards.py`

Implements run-root path containment, protected hashes, state transitions,
experiment/result locks, frozen-test access control, and terminal failure.

### `ai/incremental_v2/experiment.py`

Orchestrates A/B provisional evaluation, count-matched bootstrap diagnostics,
final fits, and the single guarded frozen-test comparison by calling existing
training and evaluation functions.

### `ai/incremental_v2/reporting.py`

Writes dataset, feature, split, bootstrap, validation, frozen-test,
compatibility, protection, limitation, and final-decision reports.

### `ai/run_incremental_v2.py`

Provides the offline CLI and executes the approved state order. It contains no
feature formulas, model implementation, or promotion logic.

## 5. Existing code reused without modification

The new path imports and calls the following existing behavior:

- `ai.browser_ml.contracts.load_feature_contract()`;
- `ai.browser_ml.legacy_extraction.extract_source_features()`;
- the existing MediaPipe face and pose landmarker constructors;
- `BrowserFeatureStream`, which executes the current TypeScript
  `FrontV2FeaturePipeline`;
- `ai.browser_ml.legacy_dataset.join_source_labels()` for feature/interval
  alignment and finite-vector validation;
- `ai.focus_v3_aug.experiments.fit_gaussian_nb()` and
  `evaluate_experiment()`;
- `ai.focus_v3_aug.metrics.classification_report()`;
- `ai.browser_ml.export.export_sklearn_onnx()`;
- the existing `validate-focus-v2-candidate.ts` browser compatibility script.

No second 34-feature implementation is allowed.

## 6. Run-directory isolation

Every execution writes to a new path:

```text
ai/browser_ml/artifacts/incremental-v2/<run-id>/
├── inventory/
├── lineage/
├── cache/
├── datasets/
├── split/
├── experiments/
│   ├── A_control/
│   ├── B_incremental/
│   └── count_control/
├── compatibility/
├── guards/
├── state/
└── reports/
```

Creation is exclusive. An existing run directory is never reused.

All writes go through `RunWriter`. Before each directory creation, temporary
write, atomic replacement, or final write, it must:

1. canonicalize the destination;
2. prove the canonical destination is below the canonical run root;
3. reject `..`, outside absolute paths, other drives, and UNC escape paths;
4. inspect every existing path component from the run root to the target;
5. reject symlinks and Windows reparse points, including junctions;
6. reject every protected input/artifact path explicitly;
7. reject overwrite of an existing final artifact.

Temporary files used for atomic writes must also be inside the run root.

## 7. Pairing and input normalization

### 7.1 Filename pairing

Pairing compares normalized stems. The only approved transformations are:

1. URL-decode `%20` to a space;
2. replace `_` with a space in the observed timestamp filename;
3. preserve every other character.

This maps ten CSVs to ten videos without renaming a source file. The manifest
stores both the original stem and normalized stem.

CSV row-level source references may end in a Windows duplicate suffix such as
`(1)` or `(2)`. That suffix may be removed only for source-reference
validation, not for file discovery. A row is accepted only if the resulting
reference matches the CSV/video pair.

### 7.2 Supported CSV schemas

The observed interval schemas are:

```text
source_video, subject_id, variant, start_sec, end_sec, duration_sec,
label, include_train, confidence, sample_weight, notes
```

and:

```text
source_file, start_time, end_time, duration_sec, label, confidence,
sample_weight, clip_file?, note
```

`start_sec`/`end_sec` are numeric seconds. `start_time`/`end_time` use the
observed minute/second notation and are converted to integer milliseconds.

The parser must not invent a third input schema. Unknown headers or ambiguous
time fields fail closed and remain visible in lineage.

### 7.3 Subject supplementation

All ten videos belong to one person. Every accepted or excluded new-data row
uses:

```text
subject_id = same_subject_01
subject_id_source = explicit_csv | supplemented_run_contract
```

The original CSV remains unchanged. Subject supplementation happens only in
lineage and generated datasets.

## 8. Row decisions and interval validation

Every source CSV row receives exactly one status:

- `accepted`;
- `excluded`;
- `quarantined`.

Stable reasons include:

- `accepted_model_label`;
- `excluded_label_exclude`;
- `excluded_unlabeled_interval`;
- `excluded_feature_vector_not_ready`;
- `excluded_missing_or_nonfinite_feature`;
- `quarantined_source_reference_mismatch`;
- `quarantined_invalid_time`;
- `quarantined_conflicting_overlap`;
- `quarantined_unsupported_label`.

Each lineage decision records the source CSV hash, original row number,
canonical row-content hash, original reference, normalized reference, time
interval, label, confidence, sample weight, subject provenance, and reason.

The first seven rows of `2026-08-09 15-11-08.csv` reference
`2026-08-09 15-07-13(1).mp4`. They must be quarantined as
`quarantined_source_reference_mismatch`. They must not be corrected or joined
to either supplied video.

`exclude` rows remain lineage records but never become training targets.
Unlabeled gaps are reported as generated interval records and never receive an
inferred label. No supported label name is remapped.

Validation checks include:

- video without CSV and CSV without video;
- empty or malformed CSV;
- invalid or non-finite time;
- negative time;
- start not less than end;
- interval beyond video duration;
- conflicting accepted overlap within the same source;
- unsupported label;
- duplicate file path, video hash, CSV hash, and row identity;
- uncovered video intervals.

Problems are not repaired in place.

## 9. Feature extraction and dataset construction

Each accepted source is processed chronologically at one sample per second:

```text
merged source frame
→ existing front-half verification
→ existing MediaPipe Face/Pose
→ existing TypeScript BrowserFeatureStream
→ existing causal calibration and temporal window
→ ordered 34-feature values
→ existing interval/timestamp join
→ incremental subject, lineage, and split enrichment
```

Extraction begins at the start of the recording and includes causal history
even when the first accepted label begins later. Feature rows in unlabeled or
excluded intervals may provide causal context but never become model samples.

A model row is accepted only when all 34 ordered features are present and
finite and the existing feature stream marks the vector ready. Missing values,
NaN, and infinity are never replaced with zero.

Generated model rows record:

- `subject_id`;
- `video_id` and `source_group_id`;
- `source_sha256` and `csv_sha256`;
- `timestamp_ms`;
- original label-row identity;
- ordered 34 features;
- label;
- split;
- A/B provisional inclusion;
- A/B final-fit inclusion.

## 10. Development split

Existing train and validation group assignments are copied exactly from the
authoritative v3 selected split. Existing rows are never reassigned.

New data is never assigned to frozen test. New data is split only between
`new_train` and `new_validation` using whole `video_id`/`source_group_id`
groups. Every row from one video has one split.

The deterministic split uses seed `20260808` and only accepted label support
from development inputs. The selection objective is, in order:

1. zero group/hash/identity leakage;
2. non-empty new train and new validation;
3. preserve all model classes in combined B train and common validation when
   available;
4. target approximately 20 percent of accepted new support in new validation;
5. maximize new-validation class coverage;
6. deterministic seeded/lexicographic tie-breaking.

Because all new recordings are `same_subject_01`, video grouping prevents
adjacent-frame leakage but does not establish person-disjoint generalization.
This limitation is mandatory in every report.

## 11. Fixed A/B model contract

A and B use the existing fixed v3 control policy:

```text
model_type = GaussianNB
priors = null
var_smoothing = 1e-9
scaler = none
sample_weight_enabled = true
sample_weight_rule = compute_sample_weight("balanced", y_train)
feature_order = exact focus-state-v2 order
class_order = drowsy, focus, gaze_down, gaze_side
seed = 20260808
```

Sample weights are recomputed from each experiment's actual training labels
using the same rule. The rule, not one experiment's weight vector, is shared.

No model family, parameter, threshold, feature policy, or label mapping is
tuned in this run.

## 12. Approved experiment order

The immutable run order is:

```text
development ingestion/split
→ A/B provisional training
→ common validation evaluation
→ sample-count diagnostic
→ experiment lock
→ A/B final fit
→ frozen-test guard
→ one shared frozen-test evaluation
→ result lock
→ deterministic final reporting
```

### 12.1 Provisional training

```text
A provisional train = existing_train
B provisional train = existing_train + new_train
common validation   = existing_validation + new_validation
```

`new_validation` must not appear in B provisional training through a source,
hash, label identity, sample identity, cache identity, or derived manifest.

A and B validation predictions must contain the same ordered validation row
identities. Both prediction manifests and the identity equality proof are
saved.

### 12.2 Count-matched diagnostic

The count control resamples A's existing provisional training rows with
replacement until each bootstrap has B's provisional training row count.
Twenty deterministic bootstraps use one-based indices `1..20` and the exact
formula `bootstrap_seed = 20260808 + bootstrap_index`.

Each bootstrap stores:

- derived seed;
- ordered sampled-row identity manifest;
- sampled manifest SHA-256;
- validation prediction identities;
- complete validation metrics;
- absolute and relative deltas from original A.

The bootstrap adds duplicate observations, not new independent samples. The
report must state this limitation.

Interpretation is fixed before frozen test:

- if B's validation improvement is above the bootstrap 95th percentile, this
  supports evidence that signal/distribution diversity, not row count alone,
  contributed;
- otherwise there is insufficient evidence to separate new-data effects from
  sample-count effects;
- the second outcome must not be described as proof that the new data has no
  effect.

### 12.3 Final fit

After validation artifacts and settings are locked, both models are fit:

```text
A final = existing_train + existing_validation
B final = existing_train + existing_validation + new_train + new_validation
```

A never includes a new-data row. B provisional training includes only
`new_train`; `new_validation` must not appear in that fit by any direct or
derived identity. B final fit includes all accepted model-ready `new_train`
and `new_validation` rows, so final fit is the first time `new_validation`
enters a training matrix. Both final input manifests and model hashes are
saved.

## 13. Experiment lock and frozen-test non-materialization

Before `EXPERIMENT_LOCKED`, the run may hold only a frozen manifest reference:

- frozen manifest path;
- manifest SHA-256;
- declared row count;
- ordered row identities and their identity hash;
- declared source groups.

The frozen feature vectors and labels must not be loaded into evaluation data
structures during ingestion, split, provisional training, validation,
bootstrap, or configuration selection.

The experiment lock canonically hashes:

- run ID and seed;
- input hashes and ingestion decisions;
- feature schema and class mapping;
- existing/new split manifests;
- A/B provisional training manifests;
- common validation manifest;
- A/B validation predictions and metrics;
- all 20 bootstrap manifests, metrics, and deltas;
- model and sample-weight policy;
- production and candidate protection snapshot;
- frozen manifest reference and identity hash;
- source-code/model provenance hashes required for reproduction.

Any change requires a new run ID and experiment lock.

## 14. Monotonic atomic state machine

### 14.1 Success transitions

The only success transitions are:

| Current | Next |
|---|---|
| `INIT` | `DEVELOPMENT_READY` |
| `DEVELOPMENT_READY` | `VALIDATION_COMPLETE` |
| `VALIDATION_COMPLETE` | `EXPERIMENT_LOCKED` |
| `EXPERIMENT_LOCKED` | `FINAL_FIT_COMPLETE` |
| `FINAL_FIT_COMPLETE` | `FROZEN_CLAIMED` |
| `FROZEN_CLAIMED` | `FROZEN_LOADED` |
| `FROZEN_LOADED` | `A_PREDICTED` |
| `A_PREDICTED` | `B_PREDICTED` |
| `B_PREDICTED` | `TEST_METRICS_WRITTEN` |
| `TEST_METRICS_WRITTEN` | `RESULT_LOCKED` |
| `RESULT_LOCKED` | `COMPLETE` |

`RESULT_LOCKED` is scientifically immutable: the only outgoing transition is
the metadata-only transition to `COMPLETE`, and it may not modify a locked
model, metric, prediction, lineage, split, dataset, manifest, or result lock.
`COMPLETE` and `TERMINAL_FAILED` have no outgoing transitions.

Every non-terminal state may transition to `TERMINAL_FAILED` on an error. A
failed run is never resumed.

The explicit table must reject, among others:

- `VALIDATION_COMPLETE → FINAL_FIT_COMPLETE`;
- `DEVELOPMENT_READY → EXPERIMENT_LOCKED`;
- `FROZEN_LOADED → B_PREDICTED`;
- any rollback to an earlier state;
- any transition after `COMPLETE` or `TERMINAL_FAILED`;
- scientific artifact changes after `RESULT_LOCKED`.

### 14.2 Atomic and integrity-protected state

Each state event is canonical JSON containing:

- run ID;
- monotonically increasing sequence number;
- previous state;
- next state;
- event type;
- UTC timestamp;
- previous event SHA-256;
- relevant artifact hashes;
- failure detail when applicable.

The event is written with exclusive creation under `state/history/`. The
current-state pointer is written to an in-run temporary file, flushed, and
atomically replaced. A transition succeeds only after both the history event
and current pointer pass a read-back integrity check.

The event hash chain, ordered history hash, current-state hash, and transition
table version are included in the experiment and result locks. Missing,
reordered, duplicated, rewritten, or hash-inconsistent state events invalidate
the run.

## 15. Single frozen-test access

Only `evaluate_frozen_test_once()` may materialize frozen feature and label
payloads. It requires:

1. current state `FINAL_FIT_COMPLETE`;
2. valid state-history hash chain;
3. valid experiment lock;
4. unchanged protected hashes;
5. exact A/B final model contract;
6. absence of frozen identities from all development inputs;
7. no existing frozen access claim.

The access claim is created with exclusive-create semantics. The ordered event
sequence is:

```text
claim created
→ frozen rows loaded and identity/content verified
→ A prediction completed
→ B prediction completed
→ A/B metrics written
→ result lock written
```

A and B receive the same frozen matrix and ordered identity manifest in one
function call. No independent A-only or B-only frozen evaluator exists.

If any step after claim creation fails, the run writes:

- failure cause and exception type;
- last successful state;
- ordered frozen access events completed so far;
- claim hash;
- state-history integrity information;
- `TERMINAL_FAILED`.

The claim remains consumed. The same run ID cannot retry frozen evaluation.
A new run ID and experiment lock are required.

## 16. Post-test prohibition

After frozen metrics exist, the run must not perform:

- retraining;
- hyperparameter changes;
- sample-weight policy changes;
- threshold changes;
- feature addition, removal, or reorder;
- label mapping changes;
- further A/B selection experiments;
- frozen-test reevaluation.

Frozen results may be used only for the final comparison and as evidence for
designing a separate future experiment.

## 17. Metrics and deltas

Validation and frozen test are reported separately. Each includes:

- Balanced Accuracy;
- Macro Precision;
- Macro Recall;
- Macro F1;
- Weighted F1;
- per-class Precision, Recall, F1, and Support;
- raw confusion matrix;
- row-normalized confusion matrix;
- focus, gaze-side, gaze-down, and drowsy recall;
- A-to-B absolute delta;
- A-to-B relative delta.

Existing evaluation functions provide per-class values and confusion
matrices. Incremental reporting derives Macro Precision and Macro Recall from
the existing per-class report without changing the evaluator.

Relative delta is:

```text
(B - A) / abs(A)
```

When A is zero, relative delta is `null` with reason `baseline_zero`; no
fabricated percentage is reported.

The report explicitly classifies:

- validation improved and frozen test improved;
- validation improved but frozen test degraded;
- validation degraded but frozen test improved;
- validation and frozen test both degraded.

Class-specific improvements and regressions are never hidden by aggregate
metrics.

## 18. Candidate artifacts and compatibility

The run stores both reproducible final models:

```text
experiments/A_control/final-model.*
experiments/B_incremental/final-model.*
```

Each includes an offline pickle, ONNX model, metadata, final input manifest,
model hash, and metrics. B is labeled `candidate_not_active`; A is labeled
`control_not_active`.

Both ONNX models must pass:

- static ONNX validation;
- one float32 input of width 34;
- declared four-class probability output;
- runtime prediction with finite probabilities;
- metadata schema/order/normalization validation;
- existing browser candidate compatibility script.

No metadata URL or production model path is changed.

## 19. Reports

The final JSON and Markdown reports contain:

1. input inventory and pairing;
2. original video/CSV hashes;
3. accepted, excluded, and quarantined lineage counts and records;
4. feature count/order, quality, failures, NaN, infinity, and extraction rate;
5. label and video distributions;
6. existing/new train and validation groups;
7. frozen manifest identity and invariance proof;
8. common-validation identity equality proof;
9. A/B validation metrics and predictions;
10. all bootstrap count-control evidence;
11. A/B final-fit manifests;
12. A/B frozen-test metrics and predictions;
13. aggregate and per-class deltas;
14. compatibility results;
15. pre/post protected hashes;
16. state history and lock integrity;
17. limitations and final A-E conclusion.

The conclusion must state whether B improved over A, which classes improved or
regressed, what the count-control evidence supports, and that person
generalization is unverified because all new recordings belong to
`same_subject_01`.

## 20. Error policy

Input anomalies are recorded rather than silently fixed. A row-level known
anomaly may be quarantined while independent valid rows continue. The run
fails before training when any safety invariant is violated, including:

- feature/class contract mismatch;
- protected hash change;
- output path escape;
- split leakage;
- frozen identity in development;
- non-identical A/B validation identities;
- `new_validation` in B provisional training;
- missing required class in a fit input;
- experiment/state lock mismatch;
- unauthorized frozen payload materialization;
- invalid state transition;
- post-result-lock scientific artifact mutation.

## 21. TDD and review sequence

Implementation follows red-green-refactor for each bounded task:

1. write the smallest failing test;
2. run the narrow test and confirm the expected failure;
3. implement the minimum behavior;
4. rerun the narrow test;
5. run related regression tests;
6. obtain a specification-compliance review;
7. obtain a code-quality review;
8. resolve findings before the next task.

The planned task order is:

1. run writer and atomic monotonic state machine;
2. pairing, interval parser, input hashing, and lineage;
3. feature extraction adapter and dataset join;
4. deterministic video-group split and frozen reference guard;
5. A/B provisional training and common validation proof;
6. twenty count-matched bootstraps;
7. experiment lock and A/B final fit;
8. single-use frozen evaluator and result lock;
9. ONNX export and browser compatibility;
10. final reports and decision;
11. full verification and the real ten-video run.

Required negative tests include path traversal, outside absolute paths,
symlink escape, Windows junction/reparse-point escape, transition skip,
rollback, post-terminal transition, post-result-lock mutation, frozen loader
before lock, duplicate frozen claim, partial frozen failure, frozen retry,
validation identity mismatch, new-validation training contamination, and
protected artifact mutation.

Each task receives reviewer/subagent review as requested. Review findings are
fixed and re-reviewed before advancing.

## 22. Verification and completion criteria

Before the real run:

- all new incremental-v2 unit and integration tests pass;
- existing legacy-v2 and focus-v3 tests pass;
- relevant frontend feature/loader tests pass;
- frontend production build passes;
- production and candidate baseline hashes match their initial snapshot.

The real ten-video run is complete only when:

- all ten video/CSV pairs are inventoried;
- the known seven rows are quarantined;
- subject supplementation is recorded without source modification;
- no source/video group crosses new train/validation;
- the existing frozen test is unchanged and absent from development;
- A/B common validation identities match;
- all 20 bootstrap artifacts exist;
- experiment lock validates;
- both final models are fit and exported;
- the frozen test is evaluated exactly once for both models in one guarded
  call;
- result/state locks validate;
- both models pass compatibility checks;
- protected and source hashes are unchanged;
- final JSON and Markdown reports provide the required metrics, deltas,
  limitations, and A-E conclusion.
