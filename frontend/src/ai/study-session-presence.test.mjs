import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Script } from 'node:vm';
import { ProductionDecision, toTimelinePoint } from './production-decision.mjs';

// Exercise the page's actual decision-to-display integration. Testing only
// ProductionDecision misses frontend guards that overwrite a correct result.
const source = readFileSync(new URL('../pages/study-session.tsx', import.meta.url), 'utf8');
const start = source.indexOf('const rawDecision = decisionRef.current.step(');
const end = source.indexOf('const currentT = startTimeRef.current', start);
assert.ok(start >= 0 && end > start, 'study-session decision block must be available');
const pageDecision = new Script(`${source.slice(start, end)}\n({ decision, deskFallbackActive });`);

function runPage(overrides = {}) {
  const context = {
    decisionRef: { current: new ProductionDecision() },
    nowMs: 1000,
    faceSeen: 0,
    frontPoseRes: { landmarks: [] },
    deskPoseRes: { landmarks: [] },
    deskFaceRes: { faceLandmarks: [] },
    measuredEar: NaN, measuredIrisY: NaN, measuredHead: NaN,
    badPosture: 0, pageTurn: 0, penFidget: 0, restlessHand: 0,
    longEyeClosure: 0, gazeDown: 0, headDown: 0,
    deskRightWrist: null, deskWristMoving: false,
    probabilities: null,
    onnxSessionRef: { current: null }, modelWarning: '',
    setUsingDeskFallback() {}, setModelWarning() {},
    ...overrides,
  };
  return pageDecision.runInNewContext(context);
}

test('empty cameras keep absent in the displayed decision and stored timeline', () => {
  for (const probabilities of [null, [0, 1, 0, 0, 0]]) {
    const { decision } = runPage({ probabilities });
    assert.equal(decision.mediapipe_state, 'absent');
    assert.equal(decision.final_state, 'absent');
    assert.equal(decision.decision_source, 'mediapipe_absent');
    assert.deepEqual(toTimelinePoint(1, decision), { t: 1, state: 'absent' });
  }
});

test('a hidden face with a visible body remains unknown rather than absent', () => {
  const { decision } = runPage({ frontPoseRes: { landmarks: [[{ x: 0.5, y: 0.5 }]] } });
  assert.equal(decision.final_state, 'unknown');
  assert.equal(decision.decision_source, 'front_signal_missing');
});

test('visible desk activity still uses the existing posture fallback', () => {
  const wrist = { x: 0.5, y: 0.5 };
  const { decision, deskFallbackActive } = runPage({
    deskPoseRes: { landmarks: [[wrist]] },
    deskRightWrist: wrist, deskWristMoving: true,
  });
  assert.equal(deskFallbackActive, true);
  assert.equal(decision.final_state, 'bad_posture');
});

test('leaving after calibration records absent and returning resumes focus', () => {
  const decisionRef = { current: new ProductionDecision() };
  const visible = {
    decisionRef, faceSeen: 1, measuredEar: 0.3, measuredIrisY: 0.5,
    measuredHead: 0.5, probabilities: [0, 1, 0, 0, 0],
  };
  for (let nowMs = 0; nowMs < 5000; nowMs += 1000) runPage({ ...visible, nowMs });
  assert.equal(runPage({ ...visible, nowMs: 5000 }).decision.final_state, 'focus');
  for (let nowMs = 6000; nowMs < 10000; nowMs += 1000) {
    assert.equal(runPage({ decisionRef, nowMs }).decision.final_state, 'absent');
  }
  assert.equal(runPage({ ...visible, nowMs: 10000 }).decision.final_state, 'focus');
});
