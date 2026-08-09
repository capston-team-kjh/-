"""Copy the validated B ONNX and derive browser metadata from its artifact."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
B = ROOT / "ai/browser_ml/artifacts/retrained-v2-3class-b/20260809T180352Z"
PUBLIC = ROOT / "frontend/public"


def main() -> None:
    metrics = json.loads((B / "metrics.json").read_text(encoding="utf-8"))
    model = json.loads((B / "metadata.json").read_text(encoding="utf-8"))
    schema = json.loads((PUBLIC / "models/focus-state-v2.schema.json").read_text(encoding="utf-8"))
    source, target = B / "focus-state-v2-3class-b.onnx", PUBLIC / "focus_classifier_3class_b.onnx"
    shutil.copyfile(source, target)
    result = metrics["metrics"]
    metadata = {
        "model_version": "retrained-v2-3class-b-20260809T180352Z",
        "schema_version": schema["schema_version"],
        "feature_names": model["feature_names"],
        "class_names": model["model_classes"],
        "normalization": schema["normalization"],
        "confidence_threshold": 0.0,
        "camera_role": schema["camera_role"],
        "model_path": "/focus_classifier_3class_b.onnx",
        "model_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "input_name": "features",
        "input_shape": [None, len(model["feature_names"])],
        "accuracy": result["accuracy"],
        "macro_f1": result["macro_f1"],
        "drowsy_recall": result["per_class"]["drowsy"]["recall"],
        "onnx_parity": metrics["onnx"]["parity"],
        "prediction_disagreement": metrics["onnx"]["prediction_disagreement"],
        "source_artifact": str(B),
        "hybrid_gaze_down_rule": True,
    }
    (PUBLIC / "focus_classifier_3class_b.metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
