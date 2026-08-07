# FocusAI Legacy Data to v2 Candidate Design

## Goal

Reuse existing FocusAI source videos and trustworthy existing labels to build a
`focus-state-v2` offline dataset, compare browser-exportable classifiers on
leakage-safe source/session splits, and export a non-production ONNX candidate
with complete provenance and evaluation evidence.

## Non-negotiable boundaries

- `frontend/public/focus_classifier.onnx` remains the active v1 artifact and is
  never overwritten.
- The current browser v2 contract at
  `frontend/src/ai/contracts/focus-state-v2.schema.json` is the only feature and
  class-order source of truth. No feature v3 is introduced.
- Worker, SQS, AWS, backend, and Python real-time inference paths are not run or
  connected to this workflow.
- Existing source videos, labels, review material, datasets, and model files are
  read-only. Every generated artifact goes under a new run directory.
- Overhead imagery never enters the front face-state classifier.

## Chosen architecture

The pipeline has four isolated stages.

1. **Inventory and label registry.** Discover videos only in the confirmed
   FocusAI roots and in source paths referenced by manifests/source maps. Probe
   size, duration, resolution, FPS, hash, and decode validity without moving
   files. Normalize known label formats into a registry that records category
   A-E, review status, confidence, exact source mapping, and eligibility.
2. **Landmark and browser-feature extraction.** Python/OpenCV samples at 1 FPS,
   matching the production page's inference cadence, and MediaPipe Tasks uses
   the same local face/pose `.task` model files. Python sends sparse raw
   landmarks to a persistent TypeScript stream processor. That processor calls
   the existing `extractFrontMeasurements` and `FrontV2FeaturePipeline`
   modules, so the 34 features, causal median/IQR calibration, quality window,
   and 10-second temporal window are not reimplemented in Python.
3. **Dataset and split.** Labels are joined only through explicit source maps,
   clip manifests, filenames with verified paths/hashes, and timestamps. Human
   point labels select the aligned 1 FPS row; visual interval labels cover only
   their stated intervals. Unknown, absent, ambiguous, rejected, invalid, and
   unlabeled rows are excluded from the four-class model dataset but remain in
   audit counts. All clips from one original recording share one split group.
4. **Training, export, and validation.** Logistic Regression, Random Forest,
   Gradient Boosting, and Gaussian Naive Bayes are compared on the same split.
   Selection uses validation macro-F1, then the selected model is evaluated
   once on the held-out human-direct test group. The candidate is exported to
   ONNX in a protected run directory and checked with ONNX static validation,
   ONNX Runtime, and the actual browser model loader plus `onnxruntime-web`.

## Label policy

Labels are kept distinct by provenance.

- **A - Human direct:**
  `focusai_human_labeling/human_train_front_10s_labels.csv` and
  `human_front_10s_labels.csv`. These point labels are the preferred
  validation/test evidence.
- **B - Human corrected:** used only when an explicit human-correction marker
  and source mapping are present. A corrected video filename alone is not proof
  of a corrected label.
- **C - Codex/visual direct:** accepted rows in blind review plus frame-label
  segments with their provisional/confidence status preserved. They may augment
  training but are not reported as human ground truth.
- **D - Rule pseudo-label:** inventoried and optionally usable only for sanity
  checks. They do not enter the held-out evaluation.
- **E - Unknown provenance:** inventoried and excluded.

The existing human holdout recording `2026-06-28 16-04-40` is reserved for
test. `2026-05-27 12-55-27` is reserved for validation because it contains all
four v2 classes. Remaining eligible sources form training. Any source identity
collision removes the conflicting source rather than allowing leakage.

## Subject and metadata semantics

No reliable subject identity is inferred from filenames, video count, or
session count. Generated rows carry an empty external `subject_id`,
`subject_id_known=false`, and a legacy marker. Missing environment and camera
setup values are represented as unknown with corresponding `*_known=false`
flags. Candidate metadata states:

```text
subject_generalization_valid = false
evaluation_scope = source_session_generalization
```

The training loader uses a verified original-recording group when subject IDs
are unavailable. Source, session, video hash, and label-interval identities
must be disjoint across Train/Validation/Test.

## Camera handling

Known 1280-pixel merged recordings use the project's established left/right
split. The front crop is verified with face evidence before extraction; a
stronger face signal on the opposite half causes an explicit swap record.
Single-camera sources are accepted only when their role is known from a
manifest or strong face evidence. Ambiguous layouts are excluded. The inventory
retains overhead availability and any activity labels, but this run does not
train an overhead model without sufficient independent activity ground truth.

## Cache and invalidation

Each source gets a separate feature cache containing source SHA-256, contract
schema/version and digest, extractor version, MediaPipe model hashes, camera
crop decision, and sampling FPS. A cache is reused only when every identity
field matches. Cache files are never overwritten; a stale cache is ignored and
a new keyed cache is written.

## Dataset quality and evaluation

Before training, the workflow reports source/video counts, interval and row
counts, label category proportions, class distribution, camera-role counts,
missing values, invalid rows, calibration failures, and exclusion reasons.
Rows without all 34 finite features are excluded from model training and
counted. Metrics include accuracy, balanced accuracy, macro/weighted F1,
per-class precision/recall/F1/support, and confusion matrices. v1 comparison is
emitted only if predictions can be produced on the exact same held-out label
rows and class semantics; otherwise it is explicitly unavailable.

## Output layout

Every run is created below:

```text
ai/browser_ml/artifacts/legacy-v2/<run-id>/
  inventory/
  cache/
  datasets/
  reports/
  candidates/focus-state-v2/
```

The candidate directory contains the ONNX model, metadata, metrics,
`confusion_matrix.csv`, dataset summary, browser compatibility report, SHA-256,
and excluded-source audit. Existing output directories cause a fail-fast error.

## Failure handling

Corrupt videos, missing label sources, ambiguous camera roles, failed landmark
extraction, and unmatched labels are isolated and reported per source. They do
not abort processing of independent sources. Contract mismatches, leakage,
attempted writes to protected production paths, or an output-directory collision
are fatal because continuing would make the candidate untrustworthy.

## Verification

- Python unit tests: inventory/source mapping, label category policy, exact
  point/interval joins, camera separation, cache invalidation, group split and
  leakage checks, metadata, and ONNX contract validation.
- TypeScript/Vitest tests: the streaming processor calls the current v2
  feature modules and preserves causal normalization/temporal behavior.
- Runtime: ONNX checker, ONNX Runtime inference, browser loader metadata/hash/
  tensor checks, and `onnxruntime-web` inference.
- Regression: existing browser-v2 Python tests, frontend tests, and frontend
  production build. Worker, backend, SQS, and AWS tests are not required for
  this offline-only change.

## Completion conditions

The run is complete only when the A-P report can be generated from artifacts,
the active v1 hash is unchanged, v2 remains inactive, the candidate exists in
its separate directory, and every skipped or failed validation is disclosed.
