from __future__ import annotations

import csv
import hashlib
import json
import pickle
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import FeatureContract
from .export import export_sklearn_onnx
from .legacy_sources import sha256_file
from .metrics import classification_metrics


CANDIDATE_NAMES = (
    "logistic_regression",
    "random_forest",
    "gradient_boosting",
    "gaussian_nb",
)


@dataclass(frozen=True)
class LegacyTrainingResult:
    model_name: str
    candidate_validation_metrics: dict[str, dict[str, object]]
    test_metrics: dict[str, object]
    artifacts: dict[str, Path]
    split_groups: dict[str, tuple[str, ...]]


def _dependencies() -> dict[str, Any]:
    try:
        import numpy as np
        from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.naive_bayes import GaussianNB
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.utils.class_weight import compute_sample_weight
    except ImportError as error:
        raise RuntimeError(
            "offline training dependencies are missing; install ai/browser_ml/requirements-training.txt"
        ) from error
    return {
        "np": np,
        "GradientBoostingClassifier": GradientBoostingClassifier,
        "RandomForestClassifier": RandomForestClassifier,
        "LogisticRegression": LogisticRegression,
        "GaussianNB": GaussianNB,
        "Pipeline": Pipeline,
        "StandardScaler": StandardScaler,
        "compute_sample_weight": compute_sample_weight,
    }


def _make_candidate(name: str, random_seed: int) -> Any:
    dependency = _dependencies()
    if name == "logistic_regression":
        return dependency["Pipeline"](
            [
                ("scale", dependency["StandardScaler"]()),
                (
                    "classifier",
                    dependency["LogisticRegression"](
                        max_iter=2_000,
                        class_weight="balanced",
                        random_state=random_seed,
                    ),
                ),
            ]
        )
    if name == "random_forest":
        return dependency["RandomForestClassifier"](
            n_estimators=300,
            max_depth=14,
            min_samples_leaf=2,
            class_weight="balanced_subsample",
            random_state=random_seed,
            n_jobs=-1,
        )
    if name == "gradient_boosting":
        return dependency["GradientBoostingClassifier"](
            n_estimators=150,
            learning_rate=0.05,
            max_depth=3,
            random_state=random_seed,
        )
    if name == "gaussian_nb":
        return dependency["GaussianNB"]()
    raise ValueError(f"unsupported candidate: {name}")


def _partition(
    rows: Sequence[Mapping[str, Any]],
    split: str,
    contract: FeatureContract,
) -> tuple[Any, Any, list[Mapping[str, Any]]]:
    dependency = _dependencies()
    selected = [row for row in rows if str(row.get("split") or "") == split]
    if not selected:
        raise ValueError(f"dataset split is empty: {split}")
    features = dependency["np"].asarray(
        [[float(row[name]) for name in contract.feature_names] for row in selected],
        dtype=dependency["np"].float32,
    )
    labels = dependency["np"].asarray([str(row["label"]) for row in selected])
    return features, labels, selected


def _fit(model: Any, name: str, features: Any, labels: Any) -> Any:
    if name in {"gradient_boosting", "gaussian_nb"}:
        weights = _dependencies()["compute_sample_weight"]("balanced", labels)
        model.fit(features, labels, sample_weight=weights)
    else:
        model.fit(features, labels)
    return model


def _json(path: Path, document: object) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _dataset_digest(rows: Sequence[Mapping[str, Any]], contract: FeatureContract) -> str:
    canonical = [
        {
            "split": str(row.get("split") or ""),
            "label": str(row.get("label") or ""),
            "source_group_id": str(row.get("source_group_id") or ""),
            "source_sha256": str(row.get("source_sha256") or ""),
            "features": [float(row[name]) for name in contract.feature_names],
        }
        for row in rows
    ]
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _groups(rows: Sequence[Mapping[str, Any]], split: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(row.get("source_group_id") or "")
                for row in rows
                if str(row.get("split") or "") == split
            }
        )
    )


def _write_confusion(path: Path, metrics: Mapping[str, Any], class_names: Sequence[str]) -> None:
    confusion = metrics["confusion"]
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(["actual\\predicted", *class_names])
        for actual in class_names:
            writer.writerow([actual, *(confusion[actual][predicted] for predicted in class_names)])


def _validate_onnx_runtime(path: Path, feature_count: int, class_count: int) -> dict[str, Any]:
    import numpy as np
    import onnx
    import onnxruntime as ort

    model = onnx.load(str(path))
    onnx.checker.check_model(model)
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1 or len(outputs) != 2:
        raise ValueError("candidate ONNX must expose one input and two outputs")
    if inputs[0].type != "tensor(float)" or inputs[0].shape[1] != feature_count:
        raise ValueError(f"candidate ONNX input must be float32 [N,{feature_count}]")
    runtime_outputs = session.run(
        None,
        {inputs[0].name: np.zeros((1, feature_count), dtype=np.float32)},
    )
    probabilities = runtime_outputs[1]
    if tuple(probabilities.shape) != (1, class_count) or not np.isfinite(probabilities).all():
        raise ValueError(f"candidate ONNX probabilities must be finite [N,{class_count}]")
    return {
        "static_check": "pass",
        "runtime_check": "pass",
        "input_name": inputs[0].name,
        "input_type": inputs[0].type,
        "input_shape": list(inputs[0].shape),
        "output_names": [output.name for output in outputs],
        "output_types": [output.type for output in outputs],
        "probability_shape": list(probabilities.shape),
    }


def train_legacy_candidates(
    rows: Sequence[Mapping[str, Any]],
    contract: FeatureContract,
    *,
    output_dir: Path,
    dataset_version: str,
    label_source: str,
    random_seed: int = 42,
    confidence_threshold: float = 0.65,
) -> LegacyTrainingResult:
    destination = output_dir.resolve()
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite candidate output directory: {destination}")
    if not 0 <= confidence_threshold <= 1:
        raise ValueError("confidence_threshold must be between zero and one")
    declared = set(contract.class_names)
    unexpected = sorted({str(row.get("label") or "") for row in rows}.difference(declared))
    if unexpected:
        raise ValueError(f"training rows contain unsupported labels: {', '.join(unexpected)}")

    train_features, train_labels, train_rows = _partition(rows, "train", contract)
    validation_features, validation_labels, validation_rows = _partition(rows, "validation", contract)
    test_features, test_labels, test_rows = _partition(rows, "test", contract)
    for split_name, split_labels in (
        ("train", train_labels),
        ("validation", validation_labels),
        ("test", test_labels),
    ):
        missing = sorted(declared.difference(set(split_labels.tolist())))
        if missing:
            raise ValueError(f"{split_name} split is missing classes: {', '.join(missing)}")

    candidate_metrics: dict[str, dict[str, object]] = {}
    for name in CANDIDATE_NAMES:
        model = _fit(_make_candidate(name, random_seed), name, train_features, train_labels)
        predictions = model.predict(validation_features).tolist()
        candidate_metrics[name] = classification_metrics(
            validation_labels.tolist(), predictions, contract.class_names
        )
    selected_name = max(
        CANDIDATE_NAMES,
        key=lambda name: (
            float(candidate_metrics[name]["macro_f1"]),
            float(candidate_metrics[name]["balanced_accuracy"]),
            -CANDIDATE_NAMES.index(name),
        ),
    )

    dependency = _dependencies()
    combined_features = dependency["np"].concatenate((train_features, validation_features), axis=0)
    combined_labels = dependency["np"].concatenate((train_labels, validation_labels), axis=0)
    selected_model = _fit(
        _make_candidate(selected_name, random_seed),
        selected_name,
        combined_features,
        combined_labels,
    )
    test_predictions = selected_model.predict(test_features).tolist()
    test_metrics = classification_metrics(test_labels.tolist(), test_predictions, contract.class_names)
    model_classes = tuple(str(value) for value in selected_model.classes_.tolist())
    if model_classes != contract.class_names:
        raise ValueError(f"model class order {model_classes} does not match contract {contract.class_names}")

    destination.mkdir(parents=True)
    onnx_path = destination / "focus-state-v2-candidate.onnx"
    pickle_path = destination / "focus-state-v2-candidate.offline.pkl"
    metadata_path = destination / "focus-state-v2-candidate.metadata.json"
    metrics_path = destination / "metrics.json"
    confusion_path = destination / "confusion_matrix.csv"
    dataset_summary_path = destination / "dataset_summary.json"
    export_sklearn_onnx(selected_model, feature_count=len(contract.feature_names), output_path=onnx_path)
    onnx_contract = _validate_onnx_runtime(
        onnx_path, len(contract.feature_names), len(contract.class_names)
    )
    with pickle_path.open("wb") as file:
        pickle.dump(
            {
                "model": selected_model,
                "schema_version": contract.schema_version,
                "feature_names": list(contract.feature_names),
                "class_names": list(contract.class_names),
                "offline_only": True,
            },
            file,
        )

    split_groups = {
        "train": _groups(rows, "train"),
        "validation": _groups(rows, "validation"),
        "test": _groups(rows, "test"),
    }
    dataset_sha256 = _dataset_digest(rows, contract)
    created_at = datetime.now(timezone.utc).isoformat()
    metric_document = {
        "selected_model": selected_name,
        "candidate_validation_metrics": candidate_metrics,
        "test": test_metrics,
        "split": {f"{name}_groups": list(groups) for name, groups in split_groups.items()},
        "evaluation_scope": "source_session_generalization",
        "subject_generalization_valid": False,
    }
    dataset_summary = {
        "dataset_version": dataset_version,
        "dataset_sha256": dataset_sha256,
        "row_count": len(rows),
        "split_row_counts": dict(sorted(Counter(str(row["split"]) for row in rows).items())),
        "class_row_counts": dict(sorted(Counter(str(row["label"]) for row in rows).items())),
        "label_category_row_counts": dict(
            sorted(Counter(str(row.get("label_category") or "") for row in rows).items())
        ),
        "source_group_count": len({str(row.get("source_group_id") or "") for row in rows}),
        "subject_generalization_valid": False,
    }
    metadata = {
        "model_version": f"focus-state-v2-candidate-{created_at.replace(':', '').replace('+00:00', 'Z')}",
        "schema_version": contract.schema_version,
        "model_type": selected_name,
        "feature_names": list(contract.feature_names),
        "class_names": list(contract.class_names),
        "normalization": contract.normalization,
        "confidence_threshold": confidence_threshold,
        "camera_role": contract.camera_role,
        "model_path": onnx_path.name,
        "model_sha256": sha256_file(onnx_path),
        "dataset_version": dataset_version,
        "dataset_sha256": dataset_sha256,
        "label_source": label_source,
        "subject_generalization_valid": False,
        "evaluation_scope": "source_session_generalization",
        "metrics": test_metrics,
        "onnx_contract": onnx_contract,
        "created_at": created_at,
        "training": {
            "status": "candidate_not_active",
            "random_seed": random_seed,
            "train_groups": list(split_groups["train"]),
            "validation_groups": list(split_groups["validation"]),
            "test_groups": list(split_groups["test"]),
            "subject_generalization_valid": False,
        },
    }
    _json(metadata_path, metadata)
    _json(metrics_path, metric_document)
    _write_confusion(confusion_path, test_metrics, contract.class_names)
    _json(dataset_summary_path, dataset_summary)
    artifacts = {
        "onnx": onnx_path,
        "offline_pickle": pickle_path,
        "metadata": metadata_path,
        "metrics": metrics_path,
        "confusion_matrix": confusion_path,
        "dataset_summary": dataset_summary_path,
    }
    return LegacyTrainingResult(
        selected_name,
        candidate_metrics,
        test_metrics,
        artifacts,
        split_groups,
    )
