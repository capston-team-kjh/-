from __future__ import annotations

import os
import pickle
from typing import Any, Dict, List, Optional


def load_state_classifier(model_path: str) -> Optional[Any]:
    if not model_path or not os.path.exists(model_path):
        return None

    with open(model_path, "rb") as f:
        return pickle.load(f)


def _get_model(classifier_bundle: Any) -> Any:
    if isinstance(classifier_bundle, dict):
        return classifier_bundle.get("model") or classifier_bundle.get("classifier")
    return classifier_bundle


def _get_feature_names(classifier_bundle: Any, feature_dict: Dict[str, Any]) -> List[str]:
    if isinstance(classifier_bundle, dict):
        feature_names = classifier_bundle.get("feature_names") or classifier_bundle.get("features")
        if feature_names:
            return [str(name) for name in feature_names]

    model = _get_model(classifier_bundle)
    feature_names = getattr(model, "feature_names_in_", None)
    if feature_names is not None:
        return [str(name) for name in feature_names]

    return sorted(feature_dict.keys())


def _feature_row(classifier_bundle: Any, feature_dict: Dict[str, Any]) -> List[float]:
    row: List[float] = []
    for name in _get_feature_names(classifier_bundle, feature_dict):
        value = feature_dict.get(name, 0.0)
        if value is None:
            value = 0.0
        row.append(float(value))
    return row


def _get_classes(classifier_bundle: Any) -> List[str]:
    if isinstance(classifier_bundle, dict):
        classes = classifier_bundle.get("classes") or classifier_bundle.get("labels")
        if classes:
            return [str(label) for label in classes]

    model = _get_model(classifier_bundle)
    classes = getattr(model, "classes_", None)
    if classes is not None:
        return [str(label) for label in classes]

    return []


def predict_state_proba(classifier_bundle: Any, feature_dict: Dict[str, Any]) -> Dict[str, float]:
    model = _get_model(classifier_bundle)
    if model is None:
        return {}

    row = [_feature_row(classifier_bundle, feature_dict)]

    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(row)[0]
        classes = _get_classes(classifier_bundle)
        return {
            str(label): float(prob)
            for label, prob in zip(classes, probabilities)
        }

    if hasattr(model, "predict"):
        state = str(model.predict(row)[0])
        return {state: 1.0}

    return {}


def predict_state(classifier_bundle: Any, feature_dict: Dict[str, Any]) -> Optional[str]:
    probabilities = predict_state_proba(classifier_bundle, feature_dict)
    if not probabilities:
        return None

    return max(probabilities.items(), key=lambda item: item[1])[0]
