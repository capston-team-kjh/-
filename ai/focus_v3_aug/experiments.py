"""Fixed weighted GaussianNB A/B/C experiment execution."""

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np
from sklearn.naive_bayes import GaussianNB
from sklearn.utils.class_weight import compute_sample_weight

from .config import ExperimentConfig, ModelConfig, canonical_sha256
from .metrics import ClassificationReport, classification_report


@dataclass(frozen=True)
class ExperimentEvaluation:
    model: GaussianNB
    sample_weight_sha256: str
    predictions: tuple[dict[str, str], ...]
    metrics: ClassificationReport
    training_input_manifest: tuple[dict[str, str], ...]


def _model_config(config: ModelConfig | ExperimentConfig) -> ModelConfig:
    return config.model if isinstance(config, ExperimentConfig) else config


def _matrix(
    rows: Sequence[Mapping[str, object]], feature_names: Sequence[str]
) -> np.ndarray:
    return np.asarray(
        [[float(row[name]) for name in feature_names] for row in rows],
        dtype=np.float32,
    )


def _validate_model(config: ModelConfig) -> None:
    if config.model_type != 'gaussian_nb':
        raise ValueError('A/B/C model type is locked to GaussianNB')
    if config.scaler != 'none':
        raise ValueError('A/B/C preprocessing is locked to no scaler')
    if not config.sample_weight_enabled:
        raise ValueError('A/B/C balanced sample weights must be enabled')
    if config.sample_weight_rule != "compute_sample_weight('balanced', y_train)":
        raise ValueError('A/B/C sample-weight rule changed')


def fit_gaussian_nb(
    rows: Iterable[Mapping[str, object]],
    config: ModelConfig | ExperimentConfig,
    feature_names: Sequence[str],
) -> tuple[GaussianNB, str]:
    materialized = [dict(row) for row in rows]
    if not materialized:
        raise ValueError('GaussianNB training input is empty')
    model_config = _model_config(config)
    _validate_model(model_config)
    y_train = [str(row['label']) for row in materialized]
    weights = compute_sample_weight('balanced', y_train)
    model = GaussianNB(
        priors=model_config.priors,
        var_smoothing=model_config.var_smoothing,
    )
    model.fit(
        _matrix(materialized, feature_names),
        y_train,
        sample_weight=weights,
    )
    weight_values = [float(value) for value in weights]
    return model, canonical_sha256(weight_values)


def _manifest(rows: Iterable[Mapping[str, object]]) -> tuple[dict[str, str], ...]:
    result = []
    for index, row in enumerate(rows):
        result.append(
            {
                'sample_id': str(
                    row.get('sample_id', row.get('original_sample_id', index))
                ),
                'original_sample_id': str(row.get('original_sample_id', '')),
                'source_group_id': str(row.get('source_group_id', '')),
                'label': str(row['label']),
                'augmentation_type': str(
                    row.get('augmentation_type', 'original')
                ),
                'split': str(row.get('split', 'train')),
            }
        )
    return tuple(sorted(result, key=lambda row: row['sample_id']))


def build_training_input_manifests(
    original_rows: Iterable[Mapping[str, object]],
    safe_rows: Iterable[Mapping[str, object]],
    minority_rows: Iterable[Mapping[str, object]],
    duplicate_rows: Iterable[Mapping[str, object]],
) -> dict[str, tuple[dict[str, object], ...]]:
    originals = [dict(row) for row in original_rows]
    safe = [dict(row) for row in safe_rows]
    minority = [dict(row) for row in minority_rows]
    excluded = {
        str(row['sample_id'])
        for row in duplicate_rows
        if bool(row.get('exclude_from_training'))
    }
    safe = [row for row in safe if str(row['sample_id']) not in excluded]
    minority = [row for row in minority if str(row['sample_id']) not in excluded]
    return {
        'A': _manifest(originals),
        'B': _manifest([*originals, *safe]),
        'C': _manifest([*originals, *minority]),
    }


def evaluate_experiment(
    train_rows: Iterable[Mapping[str, object]],
    evaluation_rows: Iterable[Mapping[str, object]],
    config: ModelConfig | ExperimentConfig,
    feature_names: Sequence[str],
    class_order: Sequence[str],
) -> ExperimentEvaluation:
    training = [dict(row) for row in train_rows]
    evaluation = [dict(row) for row in evaluation_rows]
    if not evaluation:
        raise ValueError('evaluation input is empty')
    model, weight_hash = fit_gaussian_nb(training, config, feature_names)
    predicted = [
        str(value) for value in model.predict(_matrix(evaluation, feature_names))
    ]
    actual = [str(row['label']) for row in evaluation]
    predictions = tuple(
        {
            'sample_id': str(
                row.get('sample_id', row.get('original_sample_id', index))
            ),
            'actual': actual[index],
            'predicted': predicted[index],
        }
        for index, row in enumerate(evaluation)
    )
    return ExperimentEvaluation(
        model=model,
        sample_weight_sha256=weight_hash,
        predictions=predictions,
        metrics=classification_report(actual, predicted, class_order),
        training_input_manifest=_manifest(training),
    )
