# FocusAI v3 Augmentation Experiment Design

## 1. Goal

Build an isolated, reproducible `focus_v3_aug` offline experiment around the
current `focus-state-v2` feature extractor. The experiment must audit label and
feature quality, re-extract all augmented features through the existing
MediaPipe plus browser-v2 feature stream, and compare three controlled
experiments on the existing frozen test set.

The latest legacy-v2 candidate run at
`ai/browser_ml/artifacts/legacy-v2/20260807T234316` is the baseline source. Its
held-out test result is Macro F1 `0.264509`, Balanced Accuracy `0.294412`, and
Focus Recall `0.0` on 65 samples from source group
`2026-06-28 16-04-40`.

This design does not promote, replace, or mutate any production or existing
candidate artifact. It does not modify an original label.

## 2. Non-negotiable boundaries

- Treat Production v1 ONNX, v1 metadata, and the existing v2 candidate as
  read-only.
- Record their SHA-256 values before the run and verify them after every
  mutating phase and at run completion.
- Freeze the current test group and all 65 test rows by identity and content.
- Never use test data for augmentation, split construction, model selection,
  threshold selection, hyperparameter selection, label-review thresholds, or
  failure-policy thresholds.
- Use only non-test development groups to construct train and validation.
- Never augment validation or test rows.
- Keep the 34-feature `focus-state-v2` schema and class mapping unchanged.
- Keep A/B/C model type, preprocessing, and hyperparameters identical.
- Do not tune until the augmentation comparison has finished.
- Never auto-promote a result, replace an existing model, or auto-correct a
  label.
- Preserve all pre-existing uncommitted user changes.

## 3. Chosen architecture

### 3.1 Source and output isolation

New reusable experiment code lives under `ai/focus_v3_aug/`. The CLI entry
point is `ai/run_focus_v3_aug.py`.

Every execution writes to a new path:

```text
ai/experiments/focus_v3_aug/runs/<UTC-run-id>/
```

An existing run path is never overwritten. Generated data, review material,
models, and reports remain inside that run. Candidate models are experiment
artifacts only and cannot be written to `frontend/public/**`, `ai/models/**`,
or an existing `ai/browser_ml/artifacts/**` candidate directory.

### 3.2 Modules

- `config.py`: immutable experiment configuration and pre-test thresholds.
- `guards.py`: protected-artifact hashes, frozen-test manifest, lock checks,
  lineage checks, and split-leakage checks.
- `failure_analysis.py`: multi-cause feature failure analysis.
- `label_review.py`: review-priority generation without label mutation.
- `splitting.py`: deterministic development-group validation analysis.
- `augmentation.py`: SAFE transforms and deterministic assignment.
- `extraction.py`: adapter over the existing MediaPipe and browser-v2 feature
  stream.
- `lineage.py`: stable sample identity and original/derived relationships.
- `duplicates.py`: exact and near-duplicate feature-vector analysis.
- `experiments.py`: fixed GaussianNB A/B/C training and prediction.
- `metrics.py`: validation/test metrics, confusion matrices, deltas, and
  prediction concentration.
- `reporting.py`: CSV, JSON, and Markdown outputs plus final diagnosis.

The implementation reuses the current `BrowserFeatureStream` and MediaPipe
extraction path from `ai/browser_ml/legacy_extraction.py`. It does not create a
second 34-feature implementation.

## 4. Immutable identities and lineage

### 4.1 Original sample identity

`original_sample_id` is a SHA-256 digest of the canonical tuple:

```text
source_sha256 | source_group_id | timestamp_ms | current_label | label_source
```

Canonical encoding is UTF-8 with normalized separators and base-10 integer
timestamps. This ID is stable across reruns with the same input data.

### 4.2 Derived sample identity

`sample_id` for an augmented row is a SHA-256 digest of:

```text
original_sample_id | augmentation_type | canonical_parameters_json | seed
```

Every augmented record contains:

```text
sample_id
original_sample_id
source_file
source_sha256
source_group_id
timestamp_ms
original_label
augmentation_type
augmentation_parameters
seed
subject_id
split
```

The known legacy data has no verified `subject_id`; the field remains empty
and the report explicitly states that subject generalization is unverifiable.

### 4.3 Frozen test manifest

The run derives `frozen-test-manifest.json` from the baseline dataset before
any split work. It must contain exactly the current 65 test rows and the source
group `2026-06-28 16-04-40`, including ordered row identities, labels, feature
vectors, source hashes, and a manifest hash.

Any of the following invalidates the run before training:

- a frozen row is missing or changed;
- a test group appears in train or validation;
- a test `original_sample_id` has a derived row;
- a test row appears in an augmentation request or training matrix;
- the frozen manifest does not contain exactly 65 rows.

## 5. Feature failure analysis

Feature analysis runs before label review, split reconstruction, or
augmentation. The baseline report found 14,797 model-unready rows among 27,951
feature rows, a failure rate of 52.94%; this run must reproduce or explain any
difference from that count before adding data. One row may have multiple
failures. The output records:

```text
sample_id
source_group_id
timestamp_ms
split
label
primary_reason
additional_reasons
missing_features
feature_values
```

The deterministic primary-reason precedence is:

1. frame decode failure
2. face detection failure
3. pose detection failure
4. calibration not ready or failed
5. temporal history insufficient
6. required feature missing
7. NaN or infinite feature
8. hard-domain range violation
9. empirical non-test-train outlier

All other simultaneous causes appear in `additional_reasons`; no row is forced
into a single-cause explanation.

Hard-domain checks include boolean/validity features in `[0, 1]`, validity
ratios in `[0, 1]`, non-negative rolling standard deviations, and non-negative
continuous eye-closure duration. Remaining distribution anomalies are derived
only from valid non-test train rows using median/IQR and are diagnostic rather
than automatic label or feature edits.

The report contains counts and rates by cause, label, split, source group, and
feature. It separates calibration warm-up failures from true detection or
numeric failures so augmentation does not merely multiply unusable rows.

## 6. Label review

`label_review.csv` is a review-priority queue, not a ground-truth decision.
Every report and CSV metadata block states that HIGH/MEDIUM/LOW indicates
human-review priority only.

Review evidence is learned from non-test train data only:

- robust per-label feature distributions;
- group-aware out-of-fold disagreement when enough groups exist;
- high-confidence alternative-class evidence;
- face/pose/calibration quality contradictions;
- feature-distance outliers relative to the current label;
- label provenance and already-recorded ambiguity.

Priority rules are fixed before test evaluation:

- HIGH: at least two independent strong signals, or a strong quality
  contradiction plus high-confidence alternative-class evidence.
- MEDIUM: one strong signal or at least two moderate signals.
- LOW: one moderate anomaly that merits inspection.

`suspected_label` remains empty unless an alternative class has actual model or
distribution evidence. No label is changed or automatically excluded based
only on review priority.

The CSV fields are:

```text
sample_id
source_file
timestamp
split
current_label
suspected_label
reason
confidence
priority_semantics
feature_values
label_source
```

`priority_semantics` is the constant value `human_review_priority_not_truth`
so exported CSV rows cannot be mistaken for corrected ground truth.

Test rows may be scored only after all thresholds and review models have been
fit on train. Test review findings are informational and are never fed back
into training, filtering, thresholds, or augmentation. Review frames are
saved, when decodable, under the run's `review/frames/` directory.

## 7. Validation reconstruction

The frozen test is excluded first. Existing train and validation source groups
form the development pool. Candidate validation splits are deterministic group
subsets; rows from one `source_group_id` never cross train and validation.

The split objective is evaluated in this order:

1. zero group leakage;
2. all four classes represented in train and validation;
3. at least two validation groups per class when the data permits;
4. at least five validation samples per class when the data permits;
5. a validation size near 20% of valid development rows;
6. smallest class-distribution distance from the full development pool.

Group integrity always wins over class stratification. The report shows, for
the existing and proposed split, row support and distinct group count for each
class. If no candidate materially improves support without losing a class or
violating group boundaries, the current split is retained and the limitation
is reported. No synthetic or row-level split is used to force adequacy.

## 8. Augmentation policy

### 8.1 Classification

Automatically eligible SAFE transforms are:

- brightness factor in `[0.90, 1.10]`;
- contrast factor in `[0.90, 1.10]`;
- gamma in `[0.90, 1.10]`;
- Gaussian blur with kernel `3x3` and sigma in `[0.3, 0.8]`;
- zero-mean Gaussian sensor noise with sigma in `[1.0, 3.0]` on the 0-255
  pixel scale.

All parameters come from a deterministic PRNG seeded by the immutable run
configuration. The default seed is `20260808`.

Horizontal flip, rotation, crop, and scale remain CONDITIONAL and are excluded
from the initial A/B/C run. The v2 schema contains gaze-direction deltas,
head/pose asymmetry, and stateful personal baselines; therefore these transforms
require a separate code- and label-semantics proof before any later run may
enable them. Perspective warps, synthetic occlusion, temporal reordering, and
any unlisted transform that can change the observed behavior state are UNSAFE
and are never applied. The run writes the complete SAFE/CONDITIONAL/UNSAFE
classification and rationale before augmentation.

### 8.2 Full-stream re-extraction

For each selected transform and selected train source group, the source
recording is replayed from the beginning in timestamp order using fresh
MediaPipe Face/Pose and `BrowserFeatureStream` state:

```text
source frame
  -> deterministic SAFE image transform
  -> current MediaPipe Face/Pose
  -> current browser-v2 causal calibration and temporal stream
  -> ordered 34-feature vector
```

The stream processes all required chronological context even when only a
subset of labeled timestamps will be retained. Existing CSV features are never
copied, randomized, or numerically perturbed.

### 8.3 SAFE transform eligibility gate

After the final development split is selected, each transform is tested on a
deterministic pilot set drawn only from selected train groups. Selected train
groups are ordered by descending valid labeled support and then by
`source_group_id`; groups are accumulated until at least 20 comparable labeled
samples are available. A transform is automatically disabled if any of the
following exceeds the untransformed pilot by more than 5 percentage points:

- vector-not-ready rate;
- face detection failure rate;
- pose detection failure rate;
- calibration failure rate.

The 5-point threshold, minimum sample count, observed deltas, and exclusion
decision are locked before test evaluation. If the selected train data cannot
provide 20 comparable pilot samples, the transform is disabled with
`insufficient_pilot_support` rather than enabled without evidence.

Validation and frozen-test recordings are prohibited from augmentation
generation, augmentation pilots, transform-eligibility transforms, and parity
augmentation streams. Validation is used only for evaluation of its original
features.

### 8.4 B and C row limits

Experiment B assigns at most one SAFE derivative to each eligible train
original. The transform type is selected by a deterministic hash of
`original_sample_id` plus seed. Replaying more than one transform stream may be
necessary to produce the assigned rows, but the training increase is capped at
one accepted derivative per original.

Experiment C computes the median of the original train class counts. Each
class below the median is a minority class; its target is the median count.
No augmented class may exceed that target. The default C cap is two accepted
derivatives per original, and both the cap and actual maximum are reported.

For C, the report records the median, original count, target, requested rows,
accepted rows, rejected rows, duplicates, and final count for every class.
Rejections and duplicate removal may leave a class below its target; the
pipeline does not compensate by overshooting another class.

## 9. Augmented-row validation and duplicates

An augmented row is rejected for any applicable reason:

- decode failure;
- face or landmark detection failure;
- required feature absent;
- NaN or infinite feature;
- hard-domain feature violation;
- calibration or temporal vector not ready;
- excessive image loss detected by the extractor path;
- schema order or feature-count mismatch.

`augmentation_rejected.csv` records `primary_reason` and
`additional_reasons`, lineage, transform parameters, and available feature
values.

An exact feature duplicate has the same ordered 34 IEEE-754 float64 values as
its original or another accepted row. Exact duplicates are reported and are
excluded from augmentation training additions by default.

A near duplicate satisfies both absolute and relative per-feature tolerances
of `1e-9`. Near duplicates are reported separately but are not automatically
removed. Reports include duplicate type, original/derived relationship,
affected sample IDs, and counts by class and transform.

## 10. Protection and parity verification

### 10.1 Implementation verification before an experiment run

Unit, integration, and negative guard tests are implementation verification;
they do not replace or reorder the fixed experiment-run stages in Section 17.
Before an actual run, temporary copies and temporary manifests verify that:

1. mutating a temporary protected-artifact copy makes the SHA guard fail;
2. injecting a frozen-test row into a temporary training manifest makes the
   test guard reject it;
3. injecting test lineage into a temporary augmentation manifest makes the
   leakage guard reject it.

### 10.2 Run-stage protection gate

At fixed run stage 5, the pipeline verifies the live protected-artifact hashes,
the frozen-test manifest, selected split, original lineage, and absence of test
rows from all train and augmentation requests. Failure stops the run before
augmentation generation or training.

### 10.3 Selected-train pilot and parity gate

At fixed run stage 6, the pipeline selects sample recordings only from the
final selected train groups. It then:

1. applies one enabled SAFE transform and verifies that accepted rows contain
   exactly the ordered 34 features;
2. replays an untransformed selected-train stream through the adapter and the
   existing extraction path, comparing every finite feature with
   `abs_tol=1e-9` and `rel_tol=1e-9`;
3. verifies calibration readiness and rolling/temporal outputs arise at the
   same timestamps and use the same causal history;
4. runs group, original-lineage, and test leakage checks across the generated
   pilot manifests.

No validation or frozen-test recording is decoded into an augmented or parity
stream.

The report records the configured tolerances, maximum absolute error, maximum
relative error, feature and timestamp where each maximum occurred, and pass or
failure. Production artifacts are never modified to test a guard.

## 11. Experiment lock

Validation may be used to choose which predeclared SAFE transforms remain
enabled and to confirm thresholds. Test may not be read for those choices.

After validation decisions, the pipeline writes `experiment-lock.json` as a
canonical snapshot of the complete experiment state immediately before test
evaluation. It contains canonical content or hashes for:

- run ID and seed;
- full data and source hashes;
- selected train/validation/test split plus group and row identities;
- frozen-test manifest;
- feature schema, ordered 34 features, and class mapping;
- random seed;
- GaussianNB model type and parameter settings;
- preprocessing/scaler policy;
- sample-weight enablement, calculation rule, and weight-label identity;
- A/B/C validation and final-fit sample-weight vector hashes;
- complete augmentation configuration;
- transform-eligibility results;
- derivative caps and minority targets;
- feature-failure and transform-eligibility thresholds;
- accepted augmentation manifest;
- augmentation-rejected manifest;
- exact and near-duplicate manifest;
- A/B/C final training-input manifests;
- A/B/C validation metrics;
- A/B/C validation predictions;
- A/B/C canonical raw and row-normalized validation confusion matrices;
- metric and final-decision thresholds;
- code/version identifiers needed to reproduce the run.

The lock has its own canonical SHA-256. Test evaluation recomputes every locked
artifact and field before and after predictions. If any listed input, manifest,
validation result, or configuration changes, existing test results are set to
`INVALIDATED_LOCK_CHANGED` and are not presented as valid. Continuing after
such a change requires a new run ID, output directory, and experiment lock.

Any post-test setting change requires a new run ID, a new output directory,
and a new experiment lock. Previous results remain separate and are never
rewritten.

## 12. Controlled experiments

All experiments use the exact legacy baseline fit policy:

```text
model_type = GaussianNB
model_parameters = {priors: null, var_smoothing: 1e-9}
scaler = none
preprocessing = ordered 34-feature float matrix without additional scaling
sample_weight_enabled = true
sample_weight_rule = compute_sample_weight("balanced", y_train)
sample_weight_labels = the actual labels in that experiment's current fit input
```

These settings are stored in config and the experiment lock. For every
validation and final fit, A/B/C independently recompute
`compute_sample_weight("balanced", y_train)` from that experiment's actual
training labels and pass the result to `GaussianNB.fit`. A's weights are never
copied to B or C. When augmentation changes class support, the same rule is
recalculated against the changed labels. No new scaling or preprocessing is
introduced for only one experiment.

- A: original development rows only.
- B: original rows plus accepted SAFE derivatives, capped at one per train
  original.
- C: original rows plus accepted minority derivatives up to each median-based
  class target, capped at two per train original.

During validation, models train on the reconstructed train groups and evaluate
the untouched validation groups. After the experiment lock is written, each
final model is retrained on the same complete original development pool. B and
C add only the augmentation rows generated from their reconstructed training
groups; validation originals are included unaugmented. All three final models
then evaluate the same frozen test exactly once in that run.

Validation and test results are stored and reported in separate sections. Test
results never cause a setting change within the same run.

## 13. Metrics

For validation and test separately, every experiment records:

- sample count and actual misclassification count;
- Macro F1 and Weighted F1;
- Balanced Accuracy;
- per-class Precision, Recall, F1, and Support;
- Focus Recall and Focus Precision;
- raw-count confusion matrix;
- row-normalized confusion matrix;
- prediction concentration: the maximum predicted-class count divided by all
  predictions, plus the dominant predicted class;
- absolute metric deltas from A.

The fixed pre-test practical-improvement thresholds are:

```text
minimum_macro_f1_delta = 0.01
minimum_balanced_accuracy_delta = 0.01
minimum_focus_recall_delta = 0.10
minimum_focus_precision_when_recall_improves = 0.25
maximum_per_class_recall_drop = 0.05
maximum_validation_metric_regression = 0.01
maximum_focus_precision_drop = 0.05
maximum_prediction_concentration = 0.80
```

These values are stored in config and the experiment lock and cannot be changed
after test results are known. Because test has only 65 rows and one recording
group, reports always pair rates with class support and changed
misclassification counts and limit claims to this frozen test.

## 14. Focus Recall cause analysis

The report separates four hypotheses rather than assigning a cause from one
metric:

- Label quality: priority counts/rates, provenance, ambiguity, and focus-label
  outliers learned without test feedback.
- Feature quality: failure reasons by class, valid-row rates, train/validation
  focus separability, and class feature overlap.
- Split: per-class distinct group counts, concentration in individual groups,
  validation adequacy, and non-test-train versus frozen-test distribution
  shift measured only for final diagnosis.
- Class imbalance: original counts, median targets, and the controlled A versus
  C metric changes.

Test distribution diagnostics are performed only after the lock and cannot
alter the run.

## 15. Final decision

`IMPROVED` requires all of the following relative to A:

- test Macro F1 delta at least `0.01`;
- test Balanced Accuracy delta at least `0.01`;
- test Focus Recall delta at least `0.10`;
- validation and test Focus Precision at least `0.25` when Focus Recall
  increases;
- validation and test Focus Precision drop no greater than `0.05`;
- no validation or test class Recall drop greater than `0.05`, including Focus
  Recall;
- validation Macro F1 and Balanced Accuracy not more than `0.01` below A;
- validation and test prediction concentration no greater than `0.80`;
- no guard, lock, leakage, or parity failure.

A validation class Recall regression above `0.05` blocks `IMPROVED` even when
validation Macro F1 or Balanced Accuracy increases. A Focus Recall increase
also does not qualify if Focus Precision misses the absolute floor or regresses
by more than its locked threshold. All class-level thresholds are fixed in
config and the experiment lock before test is read.

Otherwise the primary outcome is selected from:

- `NO_MEANINGFUL_CHANGE`: valid results but improvements miss practical
  thresholds and no stronger diagnosis dominates.
- `DEGRADED`: test generalization or a protected class materially regresses.
- `NEEDS_MORE_REAL_DATA`: support, group diversity, or verified subject data is
  the dominant limitation.
- `LABEL_QUALITY_PROBLEM`: review and provenance evidence is the dominant
  explanation.
- `FEATURE_PROBLEM`: invalidity, overlap, or cross-group feature behavior is
  the dominant explanation.
- `NEEDS_REVIEW`: a safety, lock, parity, validation adequacy, or evidence
  ambiguity prevents a trustworthy conclusion.
- `FAILED_EXPERIMENT`: execution or required verification failed.

The structured result contains:

```json
{
  "decision": "...",
  "primary_cause": "...",
  "secondary_evidence": ["..."],
  "limitations": ["..."]
}
```

An `IMPROVED` result means improvement only on the frozen 65-row test. It does
not establish subject generalization and never triggers production promotion.

## 16. Run outputs

```text
config.json
protected-artifacts.json
frozen-test-manifest.json
experiment-lock.json
inventory/
  sources.csv
  labels.csv
analysis/
  feature-failures.csv
  feature-failure-summary.json
  focus-cause-analysis.json
review/
  label_review.csv
  frames/
splits/
  existing-split.json
  proposed-split.json
  selected-split.json
augmentation/
  augmentation-safety.json
  augmented-samples.csv
  augmentation_rejected.csv
  duplicates.csv
  transform-eligibility.json
experiments/
  A_baseline/
    validation-metrics.json
    validation-predictions.csv
    validation-confusion-raw.csv
    validation-confusion-row-normalized.csv
    test-metrics.json
    test-predictions.csv
    test-confusion-raw.csv
    test-confusion-row-normalized.csv
  B_safe/
    validation-metrics.json
    validation-predictions.csv
    validation-confusion-raw.csv
    validation-confusion-row-normalized.csv
    test-metrics.json
    test-predictions.csv
    test-confusion-raw.csv
    test-confusion-row-normalized.csv
  C_minority/
    validation-metrics.json
    validation-predictions.csv
    validation-confusion-raw.csv
    validation-confusion-row-normalized.csv
    test-metrics.json
    test-predictions.csv
    test-confusion-raw.csv
    test-confusion-row-normalized.csv
reports/
  final-report.json
  final-report.md
```

The Markdown report clearly separates validation from test and follows the
requested sections for data counts, label review, augmentation accepted and
rejected rows, A/B/C metrics, confusion matrices, final judgment, human review
work, changed files, and commands actually executed.

## 17. Fixed experiment run and verification strategy

### 17.1 Fixed experiment run order

The actual experiment run executes these stages in this exact order:

1. Record read-only data and artifact inventory plus hashes.
2. Analyze feature failures.
3. Generate `label_review.csv`.
4. Review and, when valid, reconstruct development-group validation.
5. Verify protection guards.
6. Apply sample SAFE augmentation and 34-feature/temporal parity verification
   using recordings from selected train groups only.
7. Generate all augmentation data and analyze rejects and duplicates.
8. Evaluate A/B/C on validation without reading test.
9. Freeze configuration and canonical validation state in
   `experiment-lock.json`.
10. Evaluate A/B/C final candidates on the same frozen test.
11. Re-verify protected-artifact hashes after execution.

### 17.2 Implementation verification

Unit tests cover canonical identities, frozen-test rejection, protected hashes,
lock invalidation, multi-cause failures, group leakage, deterministic
augmentation assignment, derivative caps, duplicate detection, raw and
normalized confusion matrices, prediction concentration, metric deltas, and
decision gates.

Integration tests use temporary copies and a small non-test recording to cover
full-stream augmentation, MediaPipe re-extraction, 34-feature ordering,
calibration/temporal parity, reject output, and no-write boundaries.

These unit, integration, and negative guard tests run as implementation
verification before the fixed experiment run. During implementation handoff,
the repository test suite, final report checks, and repository diff review are
also executed, but they do not replace or reorder the 11 run stages above.

No success or performance claim is made unless the corresponding command and
result exist in the run report.
