# FocusAI direct-label classifier artifacts

This directory contains the reproducible outputs for the runtime classifier at
`ai/models/state_classifier.pkl`.

## Provenance

- Labels: `ai/direct_labeling/blind_labels.csv`
- Label source: `codex_visual_direct_labels`
- Frozen label SHA-256: `118e22779a2cdf4ad662b3ac9f078935edff117bcaa091f0c796088a70615ffd`
- Reviewed blind intervals: 471
- Accepted for training: 342
- Excluded as ambiguous: 129
- Classes: `drowsy`, `focus`, `gaze_down`, `gaze_side`, `unknown`

The review was completed from label-free contact sheets before any comparison
with the earlier scene labels. No external paid vision API was used. Video
augmentation was not applied. The existing 16 runtime features, classifier
type, model path, confidence threshold, worker behavior, API, and frontend
contract remain unchanged.

## Files

- `interval_report.csv`: accepted blind intervals, source groups, split, and sample counts
- `train_samples.csv`: direct-label training features
- `test_samples.csv`: direct-label held-out features
- `test_predictions.csv`: held-out predictions and correctness
- `test_metrics_detailed.json`: held-out accuracy, macro F1, per-class metrics, and confusion matrix
- `summary.json`: provenance, split groups, counts, and complete metrics
- `test_report.md`: human-readable held-out report and interpretation

The split is isolated by source video. No source group appears in both training
and test data. Current held-out accuracy is `0.380315` and macro F1 is
`0.206391`. These results expose limited generalization, especially for
`gaze_down`, and should not be presented as production-ready performance.

Local contact sheets, private source paths, extracted clips, and analyzer caches
are intentionally excluded from Git.
