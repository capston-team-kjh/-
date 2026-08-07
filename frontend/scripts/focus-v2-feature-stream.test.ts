import { describe, expect, it } from "vitest";

import { FRONT_V2_SCHEMA } from "../src/ai/feature-schema";
import type { NormalizedLandmarkLike } from "../src/ai/types";
import {
  createOfflineFeatureProcessor,
  type OfflineLandmarkSample,
} from "./focus-v2-feature-stream";


const faceLandmarks = (earHeight = 0.035): NormalizedLandmarkLike[] => {
  const face = Array.from({ length: 478 }, () => ({ x: 0.5, y: 0.5 }));
  face[33] = { x: 0.3, y: 0.4 };
  face[133] = { x: 0.4, y: 0.4 };
  face[159] = { x: 0.35, y: 0.4 - earHeight / 2 };
  face[145] = { x: 0.35, y: 0.4 + earHeight / 2 };
  face[160] = { x: 0.34, y: 0.4 - earHeight / 2 };
  face[144] = { x: 0.34, y: 0.4 + earHeight / 2 };
  face[158] = { x: 0.36, y: 0.4 - earHeight / 2 };
  face[153] = { x: 0.36, y: 0.4 + earHeight / 2 };
  face[468] = { x: 0.35, y: 0.4 };
  face[362] = { x: 0.6, y: 0.4 };
  face[263] = { x: 0.7, y: 0.4 };
  face[386] = { x: 0.65, y: 0.4 - earHeight / 2 };
  face[374] = { x: 0.65, y: 0.4 + earHeight / 2 };
  face[385] = { x: 0.64, y: 0.4 - earHeight / 2 };
  face[380] = { x: 0.64, y: 0.4 + earHeight / 2 };
  face[387] = { x: 0.66, y: 0.4 - earHeight / 2 };
  face[373] = { x: 0.66, y: 0.4 + earHeight / 2 };
  face[473] = { x: 0.65, y: 0.4 };
  face[1] = { x: 0.5, y: 0.52 };
  face[152] = { x: 0.5, y: 0.7 };
  return face;
};

const poseLandmarks = (): NormalizedLandmarkLike[] => {
  const pose = Array.from({ length: 33 }, () => ({ x: 0.5, y: 0.5, visibility: 1 }));
  pose[0] = { x: 0.52, y: 0.3, visibility: 1 };
  pose[11] = { x: 0.3, y: 0.7, visibility: 1 };
  pose[12] = { x: 0.7, y: 0.72, visibility: 1 };
  return pose;
};

const sample = (timestampMs: number, earHeight = 0.035): OfflineLandmarkSample => ({
  timestamp_ms: timestampMs,
  face_landmarks: Object.fromEntries(faceLandmarks(earHeight).map((point, index) => [index, point])),
  pose_landmarks: Object.fromEntries(poseLandmarks().map((point, index) => [index, point])),
});


describe("offline browser v2 feature stream", () => {
  it("emits the current production contract in exact order after causal calibration", () => {
    const processor = createOfflineFeatureProcessor();
    const results = Array.from({ length: 6 }, (_, index) => processor.process(sample(index * 1_000)));
    const calibrated = results[5];

    expect(processor.describe().feature_names).toEqual(FRONT_V2_SCHEMA.feature_names);
    expect(Object.keys(calibrated.values)).toEqual(FRONT_V2_SCHEMA.feature_names);
    expect(calibrated.calibrationValid).toBe(true);
    expect(calibrated.missingFeatures).toEqual([]);
    expect(calibrated.vector).toHaveLength(34);
  });

  it("does not let a future observation mutate an already emitted feature row", () => {
    const processor = createOfflineFeatureProcessor();
    let eighth = processor.process(sample(0));
    for (let second = 1; second < 8; second += 1) {
      eighth = processor.process(sample(second * 1_000));
    }
    const snapshot = JSON.parse(JSON.stringify(eighth.values));

    processor.process(sample(8_000, 0.005));

    expect(eighth.values).toEqual(snapshot);
  });
});
