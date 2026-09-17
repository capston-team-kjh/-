import type { NormalizedLandmarkLike } from "./types";

export interface FrontMeasurements {
  leftEar: number | null;
  rightEar: number | null;
  avgEar: number | null;
  irisXRatio: number | null;
  irisYRatio: number | null;
  faceHeadDownRatio: number | null;
  faceHeadTiltRatio: number | null;
  poseHeadDropRatio: number | null;
  poseHeadTiltRatio: number | null;
  shoulderSlope: number | null;
  faceSeen: boolean;
  poseSeen: boolean;
}

export const FRONT_V2_FACE_LANDMARK_INDICES = Object.freeze([
  1, 33, 133, 144, 145, 152, 153, 158, 159, 160, 263, 362, 373, 374, 380,
  385, 386, 387, 468, 473,
]);

export const FRONT_V2_POSE_LANDMARK_INDICES = Object.freeze([0, 11, 12]);

type Point = Pick<NormalizedLandmarkLike, "x" | "y">;

const distance = (a: Point, b: Point): number =>
  Math.hypot(a.x - b.x, a.y - b.y);

const isFinitePoint = (point: NormalizedLandmarkLike | undefined): point is NormalizedLandmarkLike =>
  point !== undefined && Number.isFinite(point.x) && Number.isFinite(point.y);

const isVisiblePoint = (point: NormalizedLandmarkLike | undefined): point is NormalizedLandmarkLike =>
  isFinitePoint(point) &&
  (point.visibility === undefined || point.visibility >= 0.5) &&
  (point.presence === undefined || point.presence >= 0.5);

const safeRatio = (numerator: number, denominator: number): number | null =>
  Number.isFinite(numerator) && Number.isFinite(denominator) && Math.abs(denominator) > 1e-8
    ? numerator / denominator
    : null;

const calculateEar = (
  face: readonly NormalizedLandmarkLike[],
  cornerAIndex: number,
  cornerBIndex: number,
  verticalPairs: readonly (readonly [number, number])[],
): number | null => {
  const cornerA = face[cornerAIndex];
  const cornerB = face[cornerBIndex];
  const pairs = verticalPairs.map(([topIndex, bottomIndex]) => [face[topIndex], face[bottomIndex]] as const);
  if (!isFinitePoint(cornerA) || !isFinitePoint(cornerB) || pairs.some(([top, bottom]) => !isFinitePoint(top) || !isFinitePoint(bottom))) {
    return null;
  }

  const horizontal = distance(cornerA, cornerB);
  const verticalMean = pairs.reduce((sum, [top, bottom]) => sum + distance(top, bottom), 0) / pairs.length;
  return safeRatio(verticalMean, horizontal);
};

const calculateIrisRatios = (
  face: readonly NormalizedLandmarkLike[],
): Pick<FrontMeasurements, "irisXRatio" | "irisYRatio"> => {
  const eyes = [
    { cornerA: 33, cornerB: 133, top: 159, bottom: 145, iris: 468 },
    { cornerA: 362, cornerB: 263, top: 386, bottom: 374, iris: 473 },
  ] as const;

  const ratios = eyes.map(({ cornerA, cornerB, top, bottom, iris }) => {
    const left = face[cornerA];
    const right = face[cornerB];
    const upper = face[top];
    const lower = face[bottom];
    const center = face[iris];
    if (![left, right, upper, lower, center].every(isFinitePoint)) return null;

    const minX = Math.min(left.x, right.x);
    const minY = Math.min(upper.y, lower.y);
    return {
      x: safeRatio(center.x - minX, Math.abs(right.x - left.x)),
      y: safeRatio(center.y - minY, Math.abs(lower.y - upper.y)),
    };
  });

  if (ratios.some((ratio) => ratio?.x === null || ratio?.y === null || ratio === null)) {
    return { irisXRatio: null, irisYRatio: null };
  }

  return {
    irisXRatio: (ratios[0]!.x! + ratios[1]!.x!) / 2,
    irisYRatio: (ratios[0]!.y! + ratios[1]!.y!) / 2,
  };
};

export const extractFrontMeasurements = (
  face: readonly NormalizedLandmarkLike[] | null,
  pose: readonly NormalizedLandmarkLike[] | null,
): FrontMeasurements => {
  let leftEar: number | null = null;
  let rightEar: number | null = null;
  let irisXRatio: number | null = null;
  let irisYRatio: number | null = null;
  let faceHeadDownRatio: number | null = null;
  let faceHeadTiltRatio: number | null = null;

  const faceSeen = face !== null && [1, 33, 133, 152, 263, 362].every((index) => isFinitePoint(face[index]));
  if (faceSeen && face) {
    rightEar = calculateEar(face, 33, 133, [[159, 145], [160, 144], [158, 153]]);
    leftEar = calculateEar(face, 362, 263, [[386, 374], [385, 380], [387, 373]]);
    ({ irisXRatio, irisYRatio } = calculateIrisRatios(face));

    const rightEye = face[33];
    const leftEye = face[263];
    const nose = face[1];
    const chin = face[152];
    if ([rightEye, leftEye, nose, chin].every(isFinitePoint)) {
      const eyeMidY = (rightEye.y + leftEye.y) / 2;
      const eyeWidth = distance(rightEye, leftEye);
      faceHeadDownRatio = safeRatio(nose.y - eyeMidY, chin.y - eyeMidY);
      faceHeadTiltRatio = safeRatio(Math.abs(rightEye.y - leftEye.y), eyeWidth);
    }
  }

  let poseHeadDropRatio: number | null = null;
  let poseHeadTiltRatio: number | null = null;
  let shoulderSlope: number | null = null;
  const poseSeen = pose !== null && [0, 11, 12].every((index) => isVisiblePoint(pose[index]));
  if (poseSeen && pose) {
    const nose = pose[0];
    const leftShoulder = pose[11];
    const rightShoulder = pose[12];
    const shoulderWidth = Math.abs(leftShoulder.x - rightShoulder.x);
    const shoulderMidX = (leftShoulder.x + rightShoulder.x) / 2;
    const shoulderMidY = (leftShoulder.y + rightShoulder.y) / 2;
    poseHeadDropRatio = safeRatio(shoulderMidY - nose.y, shoulderWidth);
    poseHeadTiltRatio = safeRatio(Math.abs(nose.x - shoulderMidX), shoulderWidth);
    shoulderSlope = Math.abs(leftShoulder.y - rightShoulder.y);
  }

  return {
    leftEar,
    rightEar,
    avgEar: leftEar === null || rightEar === null ? null : (leftEar + rightEar) / 2,
    irisXRatio,
    irisYRatio,
    faceHeadDownRatio,
    faceHeadTiltRatio,
    poseHeadDropRatio,
    poseHeadTiltRatio,
    shoulderSlope,
    faceSeen,
    poseSeen,
  };
};
