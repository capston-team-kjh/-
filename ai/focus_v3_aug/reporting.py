"""Canonical run reports and structured evidence-based diagnosis."""

import csv
from dataclasses import asdict, dataclass, is_dataclass
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .config import DecisionThresholds, canonical_json_bytes


DECISIONS = (
    'IMPROVED',
    'NO_MEANINGFUL_CHANGE',
    'DEGRADED',
    'NEEDS_MORE_REAL_DATA',
    'LABEL_QUALITY_PROBLEM',
    'FEATURE_PROBLEM',
)
_MANDATORY_TEST_LIMITATION = (
    'frozen_test_has_65_rows_from_one_recording_group; '
    'subject_generalization_cannot_be_established'
)


@dataclass(frozen=True)
class FinalDiagnosis:
    decision: str
    primary_cause: str
    secondary_evidence: list[object]
    limitations: list[str]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _json_value(value: object) -> object:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    item = getattr(value, 'item', None)
    if callable(item):
        return item()
    return value


def _safe_destination(path: Path | str, run_dir: Path | str) -> Path:
    root = Path(run_dir).resolve()
    destination = Path(path).resolve()
    try:
        destination.relative_to(root)
    except ValueError as error:
        raise ValueError(f'report path is outside run directory: {destination}') from error
    if destination.exists():
        raise FileExistsError(f'refusing to overwrite report: {destination}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination


def write_json(
    path: Path | str, value: object, *, run_dir: Path | str | None = None
) -> Path:
    destination_path = Path(path)
    destination = _safe_destination(
        destination_path,
        run_dir if run_dir is not None else destination_path.parent,
    )
    destination.write_bytes(canonical_json_bytes(_json_value(value)))
    return destination


def write_csv(
    path: Path | str,
    rows: Iterable[Mapping[str, object]],
    fields: Sequence[str],
    *,
    run_dir: Path | str | None = None,
) -> Path:
    destination_path = Path(path)
    destination = _safe_destination(
        destination_path,
        run_dir if run_dir is not None else destination_path.parent,
    )
    with destination.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for source in rows:
            row = {}
            for field in fields:
                value = source.get(field, '')
                if isinstance(value, (Mapping, list, tuple)):
                    value = json.dumps(
                        _json_value(value),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(',', ':'),
                    )
                row[field] = value
            writer.writerow(row)
    return destination


def _score_evidence(evidence: Mapping[str, object]) -> list[tuple[float, str]]:
    return sorted(
        (
            (float(evidence.get('label_problem_score', 0.0)), 'label_quality'),
            (float(evidence.get('feature_problem_score', 0.0)), 'feature_input'),
            (float(evidence.get('split_problem_score', 0.0)), 'split_support'),
            (float(evidence.get('imbalance_problem_score', 0.0)), 'class_imbalance'),
        ),
        reverse=True,
    )


def build_final_diagnosis(
    evidence: Mapping[str, object], thresholds: DecisionThresholds
) -> FinalDiagnosis:
    scored = _score_evidence(evidence)
    secondary: list[object] = [
        {'cause': cause, 'score': score} for score, cause in scored
    ]
    supplied_limitations = [
        str(value) for value in evidence.get('limitations', [])
    ]
    limitations = list(dict.fromkeys([*supplied_limitations, _MANDATORY_TEST_LIMITATION]))

    if bool(evidence.get('execution_failed')):
        decision = 'NEEDS_MORE_REAL_DATA'
        cause = 'experiment_execution_or_protection_gate_failed'
    elif bool(evidence.get('degraded')):
        decision = 'DEGRADED'
        cause = 'locked_validation_or_test_metrics_regressed'
    elif bool(evidence.get('improved_gate')):
        decision = 'IMPROVED'
        cause = 'all_locked_improvement_and_class_safety_gates_passed'
    elif bool(evidence.get('needs_review')) and float(
        evidence.get('label_problem_score', 0.0)
    ) >= 0.5:
        decision = 'LABEL_QUALITY_PROBLEM'
        cause = 'label_review_evidence_requires_human_resolution'
    else:
        top_score, top_cause = scored[0]
        if top_score < 0.5:
            decision = 'NO_MEANINGFUL_CHANGE'
            cause = 'augmentation_effect_did_not_meet_locked_minimum_deltas'
        elif top_cause == 'label_quality':
            decision = 'LABEL_QUALITY_PROBLEM'
            cause = 'label_quality_evidence_dominates'
        elif top_cause == 'feature_input':
            decision = 'FEATURE_PROBLEM'
            cause = 'feature_input_failure_evidence_dominates'
        elif top_cause == 'split_support':
            decision = 'NEEDS_MORE_REAL_DATA'
            cause = 'group_support_and_split_limitations_dominate'
        else:
            decision = 'NEEDS_MORE_REAL_DATA'
            cause = 'class_imbalance_requires_additional_real_group_support'
    if decision not in DECISIONS:
        raise ValueError(f'unsupported final decision: {decision}')
    secondary.append(
        {
            'maximum_per_class_recall_drop': thresholds.maximum_per_class_recall_drop,
            'minimum_focus_precision_when_recall_improves': (
                thresholds.minimum_focus_precision_when_recall_improves
            ),
        }
    )
    return FinalDiagnosis(decision, cause, secondary, limitations)


def _markdown_section(title: str, value: object) -> list[str]:
    return [
        f'## {title}',
        '',
        '```json',
        json.dumps(
            _json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ),
        '```',
        '',
    ]


def _markdown_report(report: Mapping[str, object]) -> str:
    lines = ['# FocusAI v3 Augmentation Experiment', '']
    section_keys = (
        ('Execution and commands', 'execution'),
        ('Protection guards and SHA-256', 'protection'),
        ('Feature failure analysis', 'feature_failure_analysis'),
        ('Label review priority (not label truth)', 'label_review'),
        ('Split support and group counts', 'split'),
        ('Augmentation accepted, rejected, and duplicates', 'augmentation'),
    )
    for title, key in section_keys:
        if key in report:
            lines.extend(_markdown_section(title, report[key]))
    experiments = report.get('experiments', {})
    if isinstance(experiments, Mapping):
        validation = {
            name: value.get('validation')
            for name, value in experiments.items()
            if isinstance(value, Mapping)
        }
        test = {
            name: value.get('test')
            for name, value in experiments.items()
            if isinstance(value, Mapping)
        }
        lines.extend(_markdown_section('A/B/C Validation', validation))
        lines.extend(_markdown_section('A/B/C Frozen Test', test))
    if 'decision' in report:
        lines.extend(_markdown_section('Final diagnosis', report['decision']))
    return '\n'.join(lines).rstrip() + '\n'


def write_final_reports(
    run_dir: Path | str, report: Mapping[str, object]
) -> dict[str, Path]:
    root = Path(run_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    json_path = write_json(
        root / 'final_report.json', report, run_dir=root
    )
    markdown_path = _safe_destination(root / 'final_report.md', root)
    markdown_path.write_text(_markdown_report(report), encoding='utf-8')
    return {'json': json_path, 'markdown': markdown_path}
