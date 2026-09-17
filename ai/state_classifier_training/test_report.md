# FocusAI State Classifier Test Report

Evaluation target: `ai/models/state_classifier.pkl`
Test set: `AI 분석용 영상_3min_exact/test`
Label source: FocusAI rule_state pseudo-labels, not human annotations.

## Overall

- Samples: 633
- Accuracy: 0.9953 (630/633)
- Balanced accuracy: 0.9800
- Macro F1: 0.9889
- Weighted F1: 0.9952

## Per Class

| Class | Support | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| drowsy | 77 | 1.0000 | 1.0000 | 1.0000 |
| focus | 508 | 0.9941 | 1.0000 | 0.9971 |
| gaze_down | 2 | 1.0000 | 1.0000 | 1.0000 |
| gaze_side | 30 | 1.0000 | 0.9000 | 0.9474 |
| unknown | 16 | 1.0000 | 1.0000 | 1.0000 |

## By Clip

| Clip | Samples | Accuracy | Labels |
|---|---:|---:|---|
| 2026-06-28 16-04-40__001__00000-00180s.mp4 | 111 | 1.0000 | drowsy:19, focus:64, gaze_down:2, gaze_side:14, unknown:12 |
| 2026-06-28 16-04-40__002__00180-00360s.mp4 | 181 | 0.9834 | focus:177, gaze_side:3, unknown:1 |
| 2026-06-28 16-04-40__003__00360-00540s.mp4 | 164 | 1.0000 | drowsy:39, focus:111, gaze_side:13, unknown:1 |
| 2026-06-28 16-04-40__004__00540-00720s.mp4 | 177 | 1.0000 | drowsy:19, focus:156, unknown:2 |

## Misclassified Samples

| Clip | t(sec) | Label | Prediction | Confidence |
|---|---:|---|---|---:|
| 2026-06-28 16-04-40__002__00180-00360s.mp4 | 169 | gaze_side | focus | 1.0000 |
| 2026-06-28 16-04-40__002__00180-00360s.mp4 | 170 | gaze_side | focus | 1.0000 |
| 2026-06-28 16-04-40__002__00180-00360s.mp4 | 171 | gaze_side | focus | 1.0000 |

## Notes

- `absent` and `bad_posture` are rule-only states in the current analyzer and were excluded from model training/evaluation.
- This report measures agreement with existing rule labels on held-out video, not agreement with human ground truth.
