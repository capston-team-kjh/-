"""Immutable configuration and canonical serialization for FocusAI v3."""

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path


@dataclass(frozen=True)
class ModelConfig:
    model_type: str = 'gaussian_nb'
    priors: tuple[float, ...] | None = None
    var_smoothing: float = 1e-9
    scaler: str = 'none'
    sample_weight_enabled: bool = True
    sample_weight_rule: str = "compute_sample_weight('balanced', y_train)"


@dataclass(frozen=True)
class ValidationConfig:
    target_ratio: float = 0.20
    minimum_groups_per_class: int = 2
    minimum_support_per_class: int = 5


@dataclass(frozen=True)
class AugmentationConfig:
    pilot_minimum_samples: int = 20
    maximum_failure_rate_delta: float = 0.05
    maximum_derivatives_b: int = 1
    maximum_derivatives_c: int = 2


@dataclass(frozen=True)
class DecisionThresholds:
    minimum_macro_f1_delta: float = 0.01
    minimum_balanced_accuracy_delta: float = 0.01
    minimum_focus_recall_delta: float = 0.10
    minimum_focus_precision_when_recall_improves: float = 0.25
    maximum_per_class_recall_drop: float = 0.05
    maximum_validation_metric_regression: float = 0.01
    maximum_focus_precision_drop: float = 0.05
    maximum_prediction_concentration: float = 0.80


@dataclass(frozen=True)
class ExperimentConfig:
    project_root: Path
    baseline_run: Path
    output_root: Path
    run_id: str
    seed: int = 20260808
    expected_test_group: str = '2026-06-28 16-04-40'
    expected_test_rows: int = 65
    parity_abs_tol: float = 1e-9
    parity_rel_tol: float = 1e-9
    model: ModelConfig = field(default_factory=ModelConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    augmentation: AugmentationConfig = field(default_factory=AugmentationConfig)
    decision: DecisionThresholds = field(default_factory=DecisionThresholds)


def canonical_json_bytes(value: object) -> bytes:
    text = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(',', ':')
    ) + '\n'
    return text.encode('utf-8')


def canonical_sha256(value: object) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def create_run_directory(config: ExperimentConfig) -> Path:
    destination = (config.output_root / config.run_id).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    return destination


def default_config(
    project_root: Path | str,
    baseline_run: Path | str,
    output_root: Path | str,
    *,
    run_id: str,
) -> ExperimentConfig:
    return ExperimentConfig(
        Path(project_root).resolve(),
        Path(baseline_run).resolve(),
        Path(output_root).resolve(),
        run_id,
    )
