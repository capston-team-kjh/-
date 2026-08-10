import { describe, expect, it } from "vitest";

import { resolveHybridDecision, validateMachinePrediction } from "./hybrid-decision";
import type { HybridDecisionInput } from "./hybrid-decision";

const validInput = (overrides: Partial<HybridDecisionInput> = {}): HybridDecisionInput => ({
  signal: {
    personPresent: true,
    faceSeen: true,
    poseSeen: true,
    faceValidRatio: 1,
    poseValidRatio: 1,
    calibrationValid: true,
  },
  prediction: { state: "focus", confidence: 0.9 },
  continuousEyeClosedSec: 0,
  badPosture: false,
  overheadActivity: null,
  ...overrides,
});

describe("hybrid browser decision", () => {
  it("rejects unknown as a machine-learning class", () => {
    expect(() => validateMachinePrediction({ state: "unknown", confidence: 0.9 }))
      .toThrow(/unknown.*not.*model/i);
  });

  it("emits absent without consulting ML when no person is present", () => {
    const decision = resolveHybridDecision(validInput({
      signal: {
        personPresent: false,
        faceSeen: false,
        poseSeen: false,
        faceValidRatio: 0,
        poseValidRatio: 0,
        calibrationValid: false,
      },
      prediction: null,
    }));
    expect(decision).toMatchObject({ state: "absent", decisionSource: "presence_rule", modelState: null });
  });

  it("emits unknown from invalid input quality, not as an ML prediction", () => {
    const decision = resolveHybridDecision(validInput({
      signal: {
        personPresent: true,
        faceSeen: true,
        poseSeen: false,
        faceValidRatio: 0.9,
        poseValidRatio: 0.1,
        calibrationValid: true,
      },
    }));
    expect(decision).toMatchObject({ state: "unknown", decisionSource: "input_quality", modelState: "focus" });
  });

  it("lets long eye closure override a confident focus prediction", () => {
    expect(resolveHybridDecision(validInput({ continuousEyeClosedSec: 9 })))
      .toMatchObject({ state: "focus", decisionSource: "model" });

    const decision = resolveHybridDecision(validInput({ continuousEyeClosedSec: 10.5 }));
    expect(decision).toMatchObject({ state: "drowsy", decisionSource: "drowsy_rule", modelState: "focus" });
  });

  it("keeps drowsy above the gaze-down rule", () => {
    expect(resolveHybridDecision(validInput({ continuousEyeClosedSec: 10, gazeDownRuleMatched: true })))
      .toMatchObject({ state: "drowsy", decisionSource: "drowsy_rule" });
  });

  it("restores gaze_down only when the existing rule matches", () => {
    expect(resolveHybridDecision(validInput({ gazeDownRuleMatched: true })))
      .toMatchObject({ state: "gaze_down", decisionSource: "gaze_down_rule" });
    expect(resolveHybridDecision(validInput({ prediction: { state: "gaze_side", confidence: 0.9 }, gazeDownRuleMatched: false })))
      .toMatchObject({ state: "gaze_side", decisionSource: "model" });
  });

  it("keeps bad posture as an initial hard rule", () => {
    const decision = resolveHybridDecision(validInput({ badPosture: true }));
    expect(decision).toMatchObject({ state: "bad_posture", decisionSource: "posture_rule" });
  });

  it("keeps overhead activity separate from the front model state", () => {
    const decision = resolveHybridDecision(validInput({ overheadActivity: "page_turn" }));
    expect(decision).toMatchObject({ state: "page_turn", decisionSource: "overhead_activity", modelState: "focus" });
  });

  it("uses a confidence gate and otherwise accepts the ML state", () => {
    expect(resolveHybridDecision(validInput({ prediction: { state: "gaze_side", confidence: 0.4 } })))
      .toMatchObject({ state: "unknown", decisionSource: "confidence_gate", modelState: "gaze_side" });
    expect(resolveHybridDecision(validInput({ prediction: { state: "gaze_down", confidence: 0.8 } })))
      .toMatchObject({ state: "gaze_down", decisionSource: "model", modelState: "gaze_down" });
  });

  it("allows the legacy face-only model to disable the pose-quality gate explicitly", () => {
    const decision = resolveHybridDecision(validInput({
      signal: {
        personPresent: true,
        faceSeen: true,
        poseSeen: false,
        faceValidRatio: 1,
        poseValidRatio: 0,
        calibrationValid: true,
      },
      thresholds: { minimumPoseValidRatio: 0 },
    }));
    expect(decision).toMatchObject({ state: "focus", decisionSource: "model" });
  });
});
