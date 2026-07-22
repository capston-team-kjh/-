# FocusAI Direct-Label State Classifier Report

- Label source: `codex_visual_direct_labels`
- Accepted intervals: 342
- Train samples: 5210
- Test samples: 1270
- Test accuracy: 0.380315
- Test macro F1: 0.206391
- Source-group overlap: []
- Evaluation split: source-isolated (no source appears in both train and test)

## Per-class test metrics

| Class | Support | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| drowsy | 60 | 0.176471 | 0.050000 | 0.077922 |
| focus | 600 | 0.757576 | 0.041667 | 0.078989 |
| gaze_down | 100 | 0.000000 | 0.000000 | 0.000000 |
| gaze_side | 110 | 0.143979 | 0.500000 | 0.223577 |
| unknown | 400 | 0.483092 | 1.000000 | 0.651466 |

## Interpretation

These held-out direct-label metrics measure generalization across source videos.
A loadable model artifact does not imply production readiness; low per-class recall should be addressed with more direct labels or stronger features.
