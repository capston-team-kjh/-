export type PersonalFeatureValues = Readonly<Record<string, number | null | undefined>>;

export interface RobustBaseline {
  count: number;
  median: number;
  iqr: number;
}

export interface PersonalNormalizationResult {
  calibrationValid: boolean;
  values: Readonly<Record<string, number | null>>;
  baselines: Readonly<Record<string, RobustBaseline | null>>;
}

export interface CausalPersonalNormalizerOptions {
  minSamples: number;
  maxSamples: number;
  minimumScale?: number;
}

const quantile = (sorted: readonly number[], probability: number): number => {
  const index = (sorted.length - 1) * probability;
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  if (lower === upper) return sorted[lower];
  const weight = index - lower;
  return sorted[lower] * (1 - weight) + sorted[upper] * weight;
};

const baselineFor = (values: readonly number[]): RobustBaseline | null => {
  if (values.length === 0) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const firstQuartile = quantile(sorted, 0.25);
  const thirdQuartile = quantile(sorted, 0.75);
  return {
    count: sorted.length,
    median: quantile(sorted, 0.5),
    iqr: thirdQuartile - firstQuartile,
  };
};

export class CausalPersonalNormalizer {
  private readonly minSamples: number;
  private readonly maxSamples: number;
  private readonly minimumScale: number;
  private readonly history = new Map<string, number[]>();

  constructor(options: CausalPersonalNormalizerOptions) {
    if (!Number.isInteger(options.minSamples) || options.minSamples < 1) {
      throw new Error("minSamples must be a positive integer");
    }
    if (!Number.isInteger(options.maxSamples) || options.maxSamples < options.minSamples) {
      throw new Error("maxSamples must be an integer greater than or equal to minSamples");
    }
    this.minSamples = options.minSamples;
    this.maxSamples = options.maxSamples;
    this.minimumScale = options.minimumScale ?? 1e-6;
  }

  observe(values: PersonalFeatureValues): void {
    Object.entries(values).forEach(([featureName, value]) => {
      if (value === null || value === undefined || !Number.isFinite(value)) return;
      const featureHistory = this.history.get(featureName) ?? [];
      if (featureHistory.length >= this.maxSamples) return;
      featureHistory.push(value);
      this.history.set(featureName, featureHistory);
    });
  }

  normalize(values: PersonalFeatureValues): PersonalNormalizationResult {
    const normalizedValues: Record<string, number | null> = {};
    const baselines: Record<string, RobustBaseline | null> = {};
    const requiredFeatures: string[] = [];

    Object.entries(values).forEach(([featureName, value]) => {
      const baseline = baselineFor(this.history.get(featureName) ?? []);
      baselines[featureName] = baseline;
      if (value === null || value === undefined || !Number.isFinite(value)) {
        normalizedValues[featureName] = null;
        return;
      }

      requiredFeatures.push(featureName);
      if (!baseline || baseline.count < this.minSamples) {
        normalizedValues[featureName] = null;
        return;
      }

      normalizedValues[featureName] =
        (value - baseline.median) / Math.max(baseline.iqr, this.minimumScale);
    });

    return {
      calibrationValid:
        requiredFeatures.length > 0 &&
        requiredFeatures.every((featureName) => (baselines[featureName]?.count ?? 0) >= this.minSamples),
      values: normalizedValues,
      baselines,
    };
  }

  process(values: PersonalFeatureValues): PersonalNormalizationResult {
    const result = this.normalize(values);
    this.observe(values);
    return result;
  }
}
