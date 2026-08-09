import type { FrontMeasurements } from "./continuous-features";
import { FRONT_V2_SCHEMA, buildFeatureVector } from "./feature-schema";
import { CausalPersonalNormalizer } from "./personal-normalization";
import { TemporalFeatureWindow } from "./temporal-window";

export interface FrontV2FeaturePipelineOptions {
  calibrationMinSamples: number;
  calibrationWindowSamples: number;
  temporalWindowMs: number;
  qualityWindowSamples: number;
}

export interface FrontV2FeatureResult {
  calibrationValid: boolean;
  values: Readonly<Record<string, number | null>>;
  missingFeatures: readonly string[];
  vector: Float32Array | null;
}

const BASELINE_KEYS = [
  "leftEar",
  "rightEar",
  "avgEar",
  "irisXRatio",
  "irisYRatio",
  "faceHeadDownRatio",
  "faceHeadTiltRatio",
  "poseHeadDropRatio",
  "poseHeadTiltRatio",
  "shoulderSlope",
] as const;

type BaselineKey = typeof BASELINE_KEYS[number];

const averageBoolean = (values: readonly boolean[]): number =>
  values.length === 0 ? 0 : values.filter(Boolean).length / values.length;

export class FrontV2FeaturePipeline {
  private readonly normalizer: CausalPersonalNormalizer;
  private readonly temporalWindow: TemporalFeatureWindow;
  private readonly qualityWindowSamples: number;
  private faceQuality: boolean[] = [];
  private poseQuality: boolean[] = [];

  constructor(options: FrontV2FeaturePipelineOptions) {
    if (!Number.isInteger(options.qualityWindowSamples) || options.qualityWindowSamples < 1) {
      throw new Error("qualityWindowSamples must be a positive integer");
    }
    this.normalizer = new CausalPersonalNormalizer({
      minSamples: options.calibrationMinSamples,
      maxSamples: options.calibrationWindowSamples,
    });
    this.temporalWindow = new TemporalFeatureWindow({ windowMs: options.temporalWindowMs });
    this.qualityWindowSamples = options.qualityWindowSamples;
  }

  process(timestampMs: number, measurements: FrontMeasurements): FrontV2FeatureResult {
    this.faceQuality.push(measurements.faceSeen);
    this.poseQuality.push(measurements.poseSeen);
    if (this.faceQuality.length > this.qualityWindowSamples) this.faceQuality.shift();
    if (this.poseQuality.length > this.qualityWindowSamples) this.poseQuality.shift();

    const personalInputs: Record<BaselineKey, number | null> = {
      leftEar: measurements.leftEar,
      rightEar: measurements.rightEar,
      avgEar: measurements.avgEar,
      irisXRatio: measurements.irisXRatio,
      irisYRatio: measurements.irisYRatio,
      faceHeadDownRatio: measurements.faceHeadDownRatio,
      faceHeadTiltRatio: measurements.faceHeadTiltRatio,
      poseHeadDropRatio: measurements.poseHeadDropRatio,
      poseHeadTiltRatio: measurements.poseHeadTiltRatio,
      shoulderSlope: measurements.shoulderSlope,
    };
    const personal = this.normalizer.process(personalInputs);
    const calibrationValid = BASELINE_KEYS.every((key) => personal.values[key] !== null);
    const temporal = this.temporalWindow.push({
      timestampMs,
      avgEar: measurements.avgEar,
      irisXRatio: measurements.irisXRatio,
      irisYRatio: measurements.irisYRatio,
    });

    const delta = (key: BaselineKey): number | null => {
      const current = personalInputs[key];
      const baseline = personal.baselines[key];
      return current === null || personal.values[key] === null || !baseline
        ? null
        : current - baseline.median;
    };

    const values: Record<string, number | null> = {
      left_ear: measurements.leftEar,
      right_ear: measurements.rightEar,
      avg_ear: measurements.avgEar,
      normalized_left_ear: personal.values.leftEar,
      normalized_right_ear: personal.values.rightEar,
      normalized_avg_ear: personal.values.avgEar,
      ear_rolling_mean: temporal.earRollingMean,
      ear_rolling_min: temporal.earRollingMin,
      ear_rolling_std: temporal.earRollingStd,
      ear_slope: temporal.earSlope,
      continuous_eye_closed_sec: temporal.continuousEyeClosedSec,
      iris_x_ratio: measurements.irisXRatio,
      iris_y_ratio: measurements.irisYRatio,
      gaze_x_delta_from_baseline: delta("irisXRatio"),
      gaze_y_delta_from_baseline: delta("irisYRatio"),
      gaze_x_rolling_mean: temporal.gazeXRollingMean,
      gaze_y_rolling_mean: temporal.gazeYRollingMean,
      gaze_x_rolling_std: temporal.gazeXRollingStd,
      gaze_y_rolling_std: temporal.gazeYRollingStd,
      face_head_down_ratio: measurements.faceHeadDownRatio,
      face_head_tilt_ratio: measurements.faceHeadTiltRatio,
      face_head_down_delta: delta("faceHeadDownRatio"),
      face_head_tilt_delta: delta("faceHeadTiltRatio"),
      pose_head_drop_ratio: measurements.poseHeadDropRatio,
      pose_head_tilt_ratio: measurements.poseHeadTiltRatio,
      pose_head_drop_delta: delta("poseHeadDropRatio"),
      pose_head_tilt_delta: delta("poseHeadTiltRatio"),
      shoulder_slope: measurements.shoulderSlope,
      shoulder_slope_delta: delta("shoulderSlope"),
      face_seen: measurements.faceSeen ? 1 : 0,
      pose_seen: measurements.poseSeen ? 1 : 0,
      face_valid_ratio: averageBoolean(this.faceQuality),
      pose_valid_ratio: averageBoolean(this.poseQuality),
      calibration_valid: calibrationValid ? 1 : 0,
    };
    const missingFeatures = FRONT_V2_SCHEMA.feature_names.filter((name) => {
      const value = values[name];
      return value === null || !Number.isFinite(value);
    });

    return {
      calibrationValid,
      values,
      missingFeatures,
      vector: missingFeatures.length === 0 ? buildFeatureVector(FRONT_V2_SCHEMA, values) : null,
    };
  }
}
