import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

import {
  extractFrontMeasurements,
  FRONT_V2_FACE_LANDMARK_INDICES,
  FRONT_V2_POSE_LANDMARK_INDICES,
} from "../src/ai/continuous-features";
import { FRONT_V2_SCHEMA, frontV2RuntimeConfig } from "../src/ai/feature-schema";
import { FrontV2FeaturePipeline } from "../src/ai/front-v2-pipeline";
import type { NormalizedLandmarkLike } from "../src/ai/types";


type SparseLandmarks = Readonly<Record<string, NormalizedLandmarkLike>>;

export interface OfflineLandmarkSample {
  timestamp_ms: number;
  face_landmarks: SparseLandmarks | null;
  pose_landmarks: SparseLandmarks | null;
}

export interface OfflineFeatureRow {
  timestamp_ms: number;
  calibrationValid: boolean;
  values: Readonly<Record<string, number | null>>;
  missingFeatures: readonly string[];
  vector: readonly number[] | null;
}

export interface OfflineFeatureDescription {
  schema_version: string;
  feature_names: readonly string[];
  class_names: readonly string[];
  normalization: Readonly<Record<string, unknown>>;
  runtime_config: ReturnType<typeof frontV2RuntimeConfig>;
  face_landmark_indices: readonly number[];
  pose_landmark_indices: readonly number[];
}

const expandSparseLandmarks = (
  sparse: SparseLandmarks | null,
  indices: readonly number[],
): NormalizedLandmarkLike[] | null => {
  if (sparse === null) return null;
  const landmarks: NormalizedLandmarkLike[] = [];
  for (const index of indices) {
    const point = sparse[String(index)];
    if (point !== undefined) landmarks[index] = point;
  }
  return landmarks;
};

export const createOfflineFeatureProcessor = () => {
  const pipeline = new FrontV2FeaturePipeline(frontV2RuntimeConfig());
  return {
    describe(): OfflineFeatureDescription {
      return {
        schema_version: FRONT_V2_SCHEMA.schema_version,
        feature_names: FRONT_V2_SCHEMA.feature_names,
        class_names: FRONT_V2_SCHEMA.class_names,
        normalization: FRONT_V2_SCHEMA.normalization,
        runtime_config: frontV2RuntimeConfig(),
        face_landmark_indices: FRONT_V2_FACE_LANDMARK_INDICES,
        pose_landmark_indices: FRONT_V2_POSE_LANDMARK_INDICES,
      };
    },
    process(sample: OfflineLandmarkSample): OfflineFeatureRow {
      const face = expandSparseLandmarks(sample.face_landmarks, FRONT_V2_FACE_LANDMARK_INDICES);
      const pose = expandSparseLandmarks(sample.pose_landmarks, FRONT_V2_POSE_LANDMARK_INDICES);
      const result = pipeline.process(
        sample.timestamp_ms,
        extractFrontMeasurements(face, pose),
      );
      return {
        timestamp_ms: sample.timestamp_ms,
        calibrationValid: result.calibrationValid,
        values: result.values,
        missingFeatures: result.missingFeatures,
        vector: result.vector === null ? null : Array.from(result.vector),
      };
    },
  };
};

export const runJsonLineStream = async (): Promise<void> => {
  const processor = createOfflineFeatureProcessor();
  const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
  for await (const line of lines) {
    if (!line.trim()) continue;
    try {
      const request = JSON.parse(line) as ({ command: "describe" } | OfflineLandmarkSample);
      const response = "command" in request && request.command === "describe"
        ? processor.describe()
        : processor.process(request as OfflineLandmarkSample);
      process.stdout.write(`${JSON.stringify({ ok: true, result: response })}\n`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      process.stdout.write(`${JSON.stringify({ ok: false, error: message })}\n`);
    }
  }
};

const invokedPath = process.argv[1] ? resolve(process.argv[1]) : "";
if (invokedPath && resolve(fileURLToPath(import.meta.url)) === invokedPath) {
  await runJsonLineStream();
}
