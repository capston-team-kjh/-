import type { FocusState, HybridState } from "./types";
import type { OverheadActivity } from "./overhead-activity";

const MODEL_STATES: readonly FocusState[] = ["focus", "gaze_side", "gaze_down", "drowsy"];

export interface MachinePrediction {
  state: FocusState;
  confidence: number;
}

export interface FrontSignalQuality {
  personPresent: boolean;
  faceSeen: boolean;
  poseSeen: boolean;
  faceValidRatio: number;
  poseValidRatio: number;
  calibrationValid: boolean;
}

export interface HybridDecisionThresholds {
  minimumConfidence: number;
  minimumFaceValidRatio: number;
  minimumPoseValidRatio: number;
  drowsyEyeClosedSec: number;
}

export interface HybridDecisionInput {
  signal: FrontSignalQuality;
  prediction: MachinePrediction | null;
  continuousEyeClosedSec: number;
  /** Existing front-camera iris rule: average iris Y ratio is at least 0.62. */
  gazeDownRuleMatched?: boolean;
  badPosture: boolean;
  overheadActivity: OverheadActivity | null;
  thresholds?: Partial<HybridDecisionThresholds>;
}

export type DecisionSource =
  | "presence_rule"
  | "input_quality"
  | "drowsy_rule"
  | "gaze_down_rule"
  | "posture_rule"
  | "overhead_activity"
  | "confidence_gate"
  | "model_unavailable"
  | "model";

export interface HybridDecision {
  state: HybridState;
  modelState: FocusState | null;
  confidence: number | null;
  ruleState: HybridState | null;
  decisionSource: DecisionSource;
}

const DEFAULT_THRESHOLDS: HybridDecisionThresholds = {
  minimumConfidence: 0.65,
  minimumFaceValidRatio: 0.5,
  minimumPoseValidRatio: 0.5,
  drowsyEyeClosedSec: 10,
};

export const validateMachinePrediction = (value: unknown): MachinePrediction => {
  if (!value || typeof value !== "object") throw new Error("Model prediction must be an object");
  const prediction = value as { state?: unknown; confidence?: unknown };
  if (prediction.state === "unknown") {
    throw new Error("unknown is not a model class; derive it from signal quality or confidence");
  }
  if (!MODEL_STATES.includes(prediction.state as FocusState)) {
    throw new Error(`Unsupported model state: ${String(prediction.state)}`);
  }
  if (typeof prediction.confidence !== "number" || !Number.isFinite(prediction.confidence) ||
      prediction.confidence < 0 || prediction.confidence > 1) {
    throw new Error("Model confidence must be a finite number between 0 and 1");
  }
  return { state: prediction.state as FocusState, confidence: prediction.confidence };
};

const ruleDecision = (
  state: HybridState,
  decisionSource: DecisionSource,
  prediction: MachinePrediction | null,
): HybridDecision => ({
  state,
  modelState: prediction?.state ?? null,
  confidence: prediction?.confidence ?? null,
  ruleState: state,
  decisionSource,
});

export const resolveHybridDecision = (input: HybridDecisionInput): HybridDecision => {
  const thresholds = { ...DEFAULT_THRESHOLDS, ...input.thresholds };
  const prediction = input.prediction === null ? null : validateMachinePrediction(input.prediction);

  if (!input.signal.personPresent) {
    return ruleDecision("absent", "presence_rule", prediction);
  }

  const inputValid =
    input.signal.faceSeen &&
    input.signal.calibrationValid &&
    input.signal.faceValidRatio >= thresholds.minimumFaceValidRatio &&
    (thresholds.minimumPoseValidRatio <= 0 || (
      input.signal.poseSeen && input.signal.poseValidRatio >= thresholds.minimumPoseValidRatio
    ));
  if (!inputValid) {
    return ruleDecision("unknown", "input_quality", prediction);
  }

  if (input.continuousEyeClosedSec >= thresholds.drowsyEyeClosedSec) {
    return ruleDecision("drowsy", "drowsy_rule", prediction);
  }

  if (input.badPosture) {
    return ruleDecision("bad_posture", "posture_rule", prediction);
  }

  if (input.overheadActivity !== null) {
    return ruleDecision(input.overheadActivity, "overhead_activity", prediction);
  }

  if (prediction !== null) {
    return {
      state: prediction.state,
      modelState: prediction.state,
      confidence: prediction.confidence,
      ruleState: null,
      decisionSource: "model",
    };
  }

  if (input.gazeDownRuleMatched) {
    return ruleDecision("gaze_down", "gaze_down_rule", null);
  }

  return ruleDecision("unknown", "model_unavailable", null);
};
