export interface GazeSideEvidence {
  irisXRatio: number | null;
  gazeXDeltaFromBaseline: number | null;
  gazeXRollingMean: number | null;
}

// Existing production v1 gaze-side thresholds from docs/analysis-rules.md.
const GAZE_SIDE_LEFT_THRESHOLD = 0.35;
const GAZE_SIDE_RIGHT_THRESHOLD = 0.65;
const AWAY_RATIO_THRESHOLD = 0.35;

const isSideRatio = (value: number | null): boolean =>
  value !== null && Number.isFinite(value) &&
  (value <= GAZE_SIDE_LEFT_THRESHOLD || value >= GAZE_SIDE_RIGHT_THRESHOLD);

export const hasGazeSideEvidence = (evidence: GazeSideEvidence): boolean =>
  isSideRatio(evidence.irisXRatio) ||
  isSideRatio(evidence.gazeXRollingMean) ||
  (evidence.gazeXDeltaFromBaseline !== null &&
    Number.isFinite(evidence.gazeXDeltaFromBaseline) &&
    Math.abs(evidence.gazeXDeltaFromBaseline) >= AWAY_RATIO_THRESHOLD);
