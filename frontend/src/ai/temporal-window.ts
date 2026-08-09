export interface TemporalSample {
  timestampMs: number;
  avgEar: number | null;
  irisXRatio: number | null;
  irisYRatio: number | null;
}

export interface TemporalSummary {
  sampleCount: number;
  earRollingMean: number | null;
  earRollingMin: number | null;
  earRollingStd: number | null;
  earSlope: number | null;
  continuousEyeClosedSec: number;
  gazeXRollingMean: number | null;
  gazeYRollingMean: number | null;
  gazeXRollingStd: number | null;
  gazeYRollingStd: number | null;
}

export interface TemporalFeatureWindowOptions {
  windowMs: number;
  eyeClosedThreshold?: number;
}

const finiteValues = (values: readonly (number | null)[]): number[] =>
  values.filter((value): value is number => value !== null && Number.isFinite(value));

const mean = (values: readonly number[]): number | null =>
  values.length === 0 ? null : values.reduce((sum, value) => sum + value, 0) / values.length;

const populationStd = (values: readonly number[]): number | null => {
  const average = mean(values);
  if (average === null) return null;
  return Math.sqrt(values.reduce((sum, value) => sum + (value - average) ** 2, 0) / values.length);
};

const leastSquaresSlopePerSecond = (
  samples: readonly Pick<TemporalSample, "timestampMs" | "avgEar">[],
): number | null => {
  const valid = samples.filter((sample): sample is TemporalSample =>
    sample.avgEar !== null && Number.isFinite(sample.avgEar));
  if (valid.length < 2) return null;

  const origin = valid[0].timestampMs;
  const xs = valid.map((sample) => (sample.timestampMs - origin) / 1_000);
  const ys = valid.map((sample) => sample.avgEar);
  const meanX = mean(xs)!;
  const meanY = mean(ys)!;
  const denominator = xs.reduce((sum, value) => sum + (value - meanX) ** 2, 0);
  if (denominator <= 1e-12) return null;
  return xs.reduce((sum, value, index) => sum + (value - meanX) * (ys[index] - meanY), 0) / denominator;
};

export class TemporalFeatureWindow {
  private readonly windowMs: number;
  private readonly eyeClosedThreshold: number;
  private samples: TemporalSample[] = [];
  private eyeClosureStartMs: number | null = null;

  constructor(options: TemporalFeatureWindowOptions) {
    if (!Number.isFinite(options.windowMs) || options.windowMs <= 0) {
      throw new Error("windowMs must be positive");
    }
    this.windowMs = options.windowMs;
    this.eyeClosedThreshold = options.eyeClosedThreshold ?? 0.2;
  }

  push(sample: TemporalSample): TemporalSummary {
    if (!Number.isFinite(sample.timestampMs)) throw new Error("timestampMs must be finite");
    const previous = this.samples[this.samples.length - 1];
    if (previous && sample.timestampMs <= previous.timestampMs) {
      throw new Error("Temporal samples must have strictly monotonic timestamps");
    }

    if (sample.avgEar !== null && Number.isFinite(sample.avgEar) && sample.avgEar < this.eyeClosedThreshold) {
      this.eyeClosureStartMs ??= sample.timestampMs;
    } else {
      this.eyeClosureStartMs = null;
    }

    this.samples.push({ ...sample });
    const cutoff = sample.timestampMs - this.windowMs;
    this.samples = this.samples.filter((item) => item.timestampMs > cutoff);
    return this.summarize();
  }

  private summarize(): TemporalSummary {
    const ears = finiteValues(this.samples.map((sample) => sample.avgEar));
    const gazeXs = finiteValues(this.samples.map((sample) => sample.irisXRatio));
    const gazeYs = finiteValues(this.samples.map((sample) => sample.irisYRatio));
    const latest = this.samples[this.samples.length - 1];

    const continuousEyeClosedSec = this.eyeClosureStartMs === null
      ? 0
      : (latest.timestampMs - this.eyeClosureStartMs) / 1_000;

    return {
      sampleCount: this.samples.length,
      earRollingMean: mean(ears),
      earRollingMin: ears.length === 0 ? null : Math.min(...ears),
      earRollingStd: populationStd(ears),
      earSlope: leastSquaresSlopePerSecond(this.samples),
      continuousEyeClosedSec,
      gazeXRollingMean: mean(gazeXs),
      gazeYRollingMean: mean(gazeYs),
      gazeXRollingStd: populationStd(gazeXs),
      gazeYRollingStd: populationStd(gazeYs),
    };
  }
}
