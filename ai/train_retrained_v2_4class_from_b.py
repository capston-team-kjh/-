"""Train the fixed B pool with only gaze_down restored, then export a 4-class candidate."""
from __future__ import annotations

import csv
import hashlib
import json
import pickle
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
B_ARTIFACT = ROOT / "ai/browser_ml/artifacts/retrained-v2-3class-b/20260809T180352Z"
CURRENT = ROOT / "ai/browser_ml/artifacts/retrained-v2/20260809T164443Z-retry"
LEGACY = ROOT / "ai/browser_ml/artifacts/legacy-v2/20260807T234316/datasets/focus-state-v2-legacy.csv"
FROZEN = ROOT / "ai/experiments/focus_v3_aug/runs/20260808T124939Z/frozen_test_manifest.json"
OUT = ROOT / "ai/browser_ml/artifacts/retrained-v2-4class-b-plus-gaze-down"
BROWSER_ONNX = ROOT / "frontend/public/focus_classifier_4class_candidate.onnx"
BROWSER_METADATA = ROOT / "frontend/public/focus_classifier_4class_candidate.metadata.json"
SCHEMA = ROOT / "frontend/public/models/focus-state-v2.schema.json"
ACTIVE_BROWSER_METADATA = ROOT / "frontend/public/models/focus-state-v1.metadata.json"
CLASSES = ("focus", "drowsy", "gaze_down", "gaze_side")
THREE_CLASSES = ("focus", "drowsy", "gaze_side")


def sample_signature(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("source_sha256", "")), str(row.get("timestamp_sec", "")), str(row.get("label", "")))


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def eligible(source_rows: list[dict[str, Any]], feature_names: list[str], excluded_groups: set[str], excluded_hashes: set[str], *, train_only: bool) -> list[dict[str, Any]]:
    import math

    selected = []
    for row in source_rows:
        if row.get("label") not in CLASSES or (train_only and row.get("split") != "train"):
            continue
        if row.get("source_group_id") in excluded_groups or row.get("source_sha256") in excluded_hashes:
            continue
        try:
            valid = bool(row.get("source_sha256")) and bool(row.get("label_identity")) and all(math.isfinite(float(row[name])) for name in feature_names)
        except (KeyError, TypeError, ValueError):
            valid = False
        if valid:
            selected.append(row)
    return selected


def label_counts(source_rows: list[dict[str, Any]], labels: tuple[str, ...] = CLASSES) -> dict[str, int]:
    found = Counter(row["label"] for row in source_rows)
    return {label: found[label] for label in labels}


def evaluate(model: Any, x: Any, y: Any, labels: tuple[str, ...]) -> dict[str, Any]:
    from sklearn import metrics as sk

    prediction = model.predict(x)
    report = sk.classification_report(y, prediction, labels=labels, output_dict=True, zero_division=0)
    return {
        "accuracy": float(sk.accuracy_score(y, prediction)),
        "balanced_accuracy": float(sk.balanced_accuracy_score(y, prediction)),
        "macro_precision": float(sk.precision_score(y, prediction, labels=labels, average="macro", zero_division=0)),
        "macro_recall": float(sk.recall_score(y, prediction, labels=labels, average="macro", zero_division=0)),
        "macro_f1": float(sk.f1_score(y, prediction, labels=labels, average="macro", zero_division=0)),
        "weighted_precision": float(sk.precision_score(y, prediction, labels=labels, average="weighted", zero_division=0)),
        "weighted_recall": float(sk.recall_score(y, prediction, labels=labels, average="weighted", zero_division=0)),
        "weighted_f1": float(sk.f1_score(y, prediction, labels=labels, average="weighted", zero_division=0)),
        "mcc": float(sk.matthews_corrcoef(y, prediction)),
        "cohen_kappa": float(sk.cohen_kappa_score(y, prediction, labels=labels)),
        "per_class": {label: {key: float(report[label][key]) for key in ("precision", "recall", "f1-score", "support")} for label in labels},
        "confusion_matrix": sk.confusion_matrix(y, prediction, labels=labels).tolist(),
        "prediction": prediction,
    }


def main() -> None:
    import numpy as np
    import onnxruntime as ort
    from sklearn.naive_bayes import GaussianNB
    from sklearn.utils.class_weight import compute_sample_weight
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType

    feature_names = json.loads((CURRENT / "metadata.json").read_text(encoding="utf-8"))["feature_names"]
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    if schema["feature_names"] != feature_names:
        raise RuntimeError("Browser feature schema does not match B feature schema")
    frozen_all = json.loads(FROZEN.read_text(encoding="utf-8"))["rows"]
    frozen = [row for row in frozen_all if row["label"] in CLASSES]
    frozen_groups = {str(row["source_group_id"]) for row in frozen if row.get("source_group_id")}
    frozen_hashes = {str(row["source_sha256"]) for row in frozen if row.get("source_sha256")}
    frozen_signatures = {sample_signature(row) for row in frozen}
    baseline = eligible(rows(CURRENT / "dataset/focus-state-v2-legacy.csv"), feature_names, frozen_groups, frozen_hashes, train_only=True)
    legacy = eligible(rows(LEGACY), feature_names, frozen_groups, frozen_hashes, train_only=False)
    training = baseline + legacy
    training_groups = {str(row["source_group_id"]) for row in training if row.get("source_group_id")}
    training_hashes = {str(row["source_sha256"]) for row in training if row.get("source_sha256")}
    signature_overlap = {sample_signature(row) for row in training} & frozen_signatures
    if training_groups & frozen_groups or training_hashes & frozen_hashes or signature_overlap:
        raise RuntimeError("Train/Frozen leakage: YES")
    matrix = lambda dataset: np.asarray([[float(row[name]) for name in feature_names] for row in dataset], dtype=np.float32)
    labels = lambda dataset: np.asarray([row["label"] for row in dataset])
    train_x, train_y, test_x, test_y = matrix(training), labels(training), matrix(frozen), labels(frozen)
    model = GaussianNB(var_smoothing=1e-9).fit(train_x, train_y, sample_weight=compute_sample_weight("balanced", train_y))
    metrics_65 = evaluate(model, test_x, test_y, CLASSES)
    subset_mask = np.isin(test_y, THREE_CLASSES)
    subset_metrics = evaluate(model, test_x[subset_mask], test_y[subset_mask], THREE_CLASSES)
    b_metrics = json.loads((B_ARTIFACT / "metrics.json").read_text(encoding="utf-8"))["metrics"]
    destination = OUT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination.mkdir(parents=True, exist_ok=False)
    pkl = destination / "focus-state-v2-4class-b-plus-gaze-down.offline.pkl"
    onnx = destination / "focus-state-v2-4class-b-plus-gaze-down.onnx"
    pkl.write_bytes(pickle.dumps(model))
    onnx.write_bytes(convert_sklearn(model, initial_types=[("features", FloatTensorType([None, len(feature_names)]))], options={id(model): {"zipmap": False}}).SerializeToString())
    onnx_output = ort.InferenceSession(str(onnx), providers=["CPUExecutionProvider"]).run(None, {"features": test_x})
    onnx_prediction, onnx_probability = np.asarray(onnx_output[0]), np.asarray(onnx_output[1], dtype=np.float64)
    onnx_metrics = {"sklearn_accuracy": metrics_65["accuracy"], "onnx_accuracy": float((onnx_prediction == test_y).mean()), "prediction_disagreement": int((onnx_prediction != metrics_65["prediction"]).sum()), "maximum_probability_error": float(np.max(np.abs(model.predict_proba(test_x) - onnx_probability)))}
    onnx_metrics["parity"] = "PASS" if onnx_metrics["prediction_disagreement"] == 0 else "FAIL"
    del metrics_65["prediction"]; del subset_metrics["prediction"]
    source_groups = sorted(training_groups)
    provenance = {"base_model": str(B_ARTIFACT), "training_pool_description": "B recent baseline training pool + every eligible legacy-v2 source, with eligible gaze_down rows restored", "baseline_rows": label_counts(baseline), "legacy_rows": label_counts(legacy), "training_rows": label_counts(training), "training_source_groups": source_groups, "training_source_count": len(source_groups), "frozen_rows": label_counts(frozen), "frozen_source_groups": sorted(frozen_groups), "leakage": {"source_group_overlap": [], "source_sha256_overlap": [], "sample_overlap": [], "status": "NO"}, "feature_count": len(feature_names), "algorithm": "GaussianNB(var_smoothing=1e-9)", "sample_weight": "compute_sample_weight('balanced', train_y)", "preprocessing": "direct float32 conversion of the stored 34 feature columns; no additional transformation"}
    metadata = {"model": provenance["algorithm"], "classes": list(CLASSES), "model_classes": model.classes_.tolist(), "feature_names": feature_names, "input": {"name": "features", "shape": [None, len(feature_names)], "type": "float32"}, "base_model": "retrained-v2-3class-b", "provenance_file": "provenance.json", "onnx": onnx_metrics}
    saved = {"metrics_65": metrics_65, "same_49_subset": subset_metrics, "b_3class_metrics": b_metrics, "onnx": onnx_metrics}
    (destination / "provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    (destination / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (destination / "metrics.json").write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    BROWSER_ONNX.write_bytes(onnx.read_bytes())
    active_metadata = json.loads(ACTIVE_BROWSER_METADATA.read_text(encoding="utf-8"))
    browser_schema_compatible = model.classes_.tolist() == schema["class_names"]
    drop_in_compatible = browser_schema_compatible and active_metadata.get("schema_version") == schema["schema_version"] and active_metadata.get("feature_names") == feature_names
    browser_meta = {"model_version": f"retrained-v2-4class-b-plus-gaze-down-{destination.name}", "base_model": "retrained-v2-3class-b", "schema_version": schema["schema_version"], "feature_names": feature_names, "class_names": model.classes_.tolist(), "normalization": schema["normalization"], "confidence_threshold": 0.0, "camera_role": schema["camera_role"], "model_path": "/focus_classifier_4class_candidate.onnx", "model_sha256": hashlib.sha256(BROWSER_ONNX.read_bytes()).hexdigest(), "input_shape": [None, len(feature_names)], "feature_count": len(feature_names), "training_rows": len(training), "training_sources": len(source_groups), "test_rows": len(frozen), "accuracy": metrics_65["accuracy"], "balanced_accuracy": metrics_65["balanced_accuracy"], "macro_f1": metrics_65["macro_f1"], "weighted_f1": metrics_65["weighted_f1"], "focus_recall": metrics_65["per_class"]["focus"]["recall"], "drowsy_recall": metrics_65["per_class"]["drowsy"]["recall"], "gaze_down_recall": metrics_65["per_class"]["gaze_down"]["recall"], "gaze_side_recall": metrics_65["per_class"]["gaze_side"]["recall"], "onnx_parity": onnx_metrics["parity"], "prediction_disagreement": onnx_metrics["prediction_disagreement"], "browser_schema_compatible": browser_schema_compatible, "drop_in_compatible": drop_in_compatible, "drop_in_reason": "active browser loader currently uses focus-state-v1, not the candidate focus-state-v2 schema", "source_artifact": str(destination), "generated_at": datetime.now(timezone.utc).isoformat()}
    BROWSER_METADATA.write_text(json.dumps(browser_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=" * 60, "\nFocusAI 4-Class ONNX Candidate\nB baseline + gaze_down restored\n", "=" * 60)
    print("Training rows:", len(training), label_counts(training)); print("Training sources:", len(source_groups)); print("Frozen leakage: NO")
    print("\n4-Class Frozen Test\nTest samples:", len(frozen))
    for key in ("accuracy", "balanced_accuracy", "macro_f1", "weighted_f1"): print(f"{key}: {metrics_65[key]:.2%}")
    for label in CLASSES: print(label, metrics_65["per_class"][label])
    print("Confusion Matrix:", metrics_65["confusion_matrix"])
    print("\nB 3-Class vs New 4-Class (same 49-row subset)")
    for key in ("accuracy", "balanced_accuracy", "macro_f1", "weighted_f1"): print(f"{key}: B={b_metrics[key]:.2%} New={subset_metrics[key]:.2%} Delta={subset_metrics[key]-b_metrics[key]:+.2%}")
    print("gaze_down:", metrics_65["per_class"]["gaze_down"])
    print("\nONNX:", onnx_metrics); print("Browser schema compatible:", browser_meta["browser_schema_compatible"]); print("DROP_IN_COMPATIBLE:", browser_meta["drop_in_compatible"])
    print("Artifact:", destination); print("Browser ONNX:", BROWSER_ONNX); print("Browser metadata:", BROWSER_METADATA)


if __name__ == "__main__":
    main()
