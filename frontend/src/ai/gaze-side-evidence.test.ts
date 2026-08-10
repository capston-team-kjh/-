import { describe, expect, it } from "vitest";

import { hasGazeSideEvidence } from "./gaze-side-evidence";

describe("gaze-side evidence", () => {
  it("accepts the existing iris-side thresholds", () => {
    expect(hasGazeSideEvidence({ irisXRatio: 0.35, gazeXDeltaFromBaseline: 0, gazeXRollingMean: 0.5 })).toBe(true);
    expect(hasGazeSideEvidence({ irisXRatio: 0.65, gazeXDeltaFromBaseline: 0, gazeXRollingMean: 0.5 })).toBe(true);
  });

  it("accepts the existing away-ratio threshold from the personal baseline", () => {
    expect(hasGazeSideEvidence({ irisXRatio: 0.5, gazeXDeltaFromBaseline: -0.35, gazeXRollingMean: 0.5 })).toBe(true);
    expect(hasGazeSideEvidence({ irisXRatio: 0.5, gazeXDeltaFromBaseline: 0.35, gazeXRollingMean: 0.5 })).toBe(true);
  });

  it("rejects a centered iris without side evidence", () => {
    expect(hasGazeSideEvidence({ irisXRatio: 0.5, gazeXDeltaFromBaseline: 0.1, gazeXRollingMean: 0.5 })).toBe(false);
  });
});
