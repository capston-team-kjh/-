"""Deterministic group-preserving development split selection."""

from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from typing import Iterable, Mapping, Sequence

from .config import ValidationConfig


CLASS_ORDER = ('drowsy', 'focus', 'gaze_down', 'gaze_side')


@dataclass(frozen=True)
class SplitDecision:
    train_groups: tuple[str, ...]
    validation_groups: tuple[str, ...]
    reconstructed: bool
    leakage_check: str
    limitations: tuple[str, ...]
    score: tuple[object, ...] | None
    summary: Mapping[str, Mapping[str, Mapping[str, int]]]


def summarize_split(
    rows: Iterable[Mapping[str, object]],
) -> dict[str, dict[str, dict[str, int]]]:
    materialized = [dict(row) for row in rows]
    return {
        split: {
            label: {
                'support': sum(
                    1
                    for row in materialized
                    if str(row.get('split')) == split
                    and str(row.get('label')) == label
                ),
                'group_count': len(
                    {
                        str(row['source_group_id'])
                        for row in materialized
                        if str(row.get('split')) == split
                        and str(row.get('label')) == label
                    }
                ),
            }
            for label in CLASS_ORDER
        }
        for split in ('train', 'validation', 'test')
    }


def apply_split(
    rows: Iterable[Mapping[str, object]], decision: SplitDecision
) -> list[dict[str, object]]:
    train = set(decision.train_groups)
    validation = set(decision.validation_groups)
    assigned: list[dict[str, object]] = []
    for source in rows:
        row = dict(source)
        group = str(row['source_group_id'])
        if str(row.get('split')) == 'test':
            row['split'] = 'test'
        elif group in train:
            row['split'] = 'train'
        elif group in validation:
            row['split'] = 'validation'
        else:
            raise ValueError(f'development group was not assigned: {group}')
        assigned.append(row)
    return assigned


def _selection_summary(
    rows: Sequence[Mapping[str, object]],
    train_groups: Sequence[str],
    validation_groups: Sequence[str],
) -> dict[str, dict[str, dict[str, int]]]:
    train = set(train_groups)
    validation = set(validation_groups)
    assigned = []
    for source in rows:
        row = dict(source)
        group = str(row['source_group_id'])
        if group in train:
            row['split'] = 'train'
        elif group in validation:
            row['split'] = 'validation'
        assigned.append(row)
    return summarize_split(assigned)


def _coverage_missing(summary: Mapping[str, Mapping[str, Mapping[str, int]]]) -> int:
    return sum(
        summary[split][label]['support'] == 0
        for split in ('train', 'validation')
        for label in CLASS_ORDER
    )


def _minimum_validation_metric(
    summary: Mapping[str, Mapping[str, Mapping[str, int]]], field: str
) -> int:
    return min(summary['validation'][label][field] for label in CLASS_ORDER)


def select_group_validation(
    development_rows: Iterable[Mapping[str, object]],
    existing_split: Mapping[str, Sequence[str]],
    config: ValidationConfig,
) -> SplitDecision:
    rows = [dict(row) for row in development_rows]
    if any(str(row.get('split')) == 'test' for row in rows):
        raise ValueError('frozen test rows cannot participate in validation selection')

    groups = tuple(sorted({str(row['source_group_id']) for row in rows}))
    existing_train = tuple(sorted(str(group) for group in existing_split['train_groups']))
    existing_validation = tuple(
        sorted(str(group) for group in existing_split['validation_groups'])
    )
    if set(existing_train) & set(existing_validation):
        raise ValueError('existing split leaks a source group')
    if set(existing_train) | set(existing_validation) != set(groups):
        raise ValueError('existing split does not cover every development group')

    existing_summary = _selection_summary(
        rows, existing_train, existing_validation
    )
    class_group_counts = {
        label: len(
            {
                str(row['source_group_id'])
                for row in rows
                if str(row['label']) == label
            }
        )
        for label in CLASS_ORDER
    }
    class_support = Counter(str(row['label']) for row in rows)
    if any(
        class_group_counts[label] < config.minimum_groups_per_class
        or class_support[label] < config.minimum_support_per_class
        for label in CLASS_ORDER
    ):
        return SplitDecision(
            train_groups=existing_train,
            validation_groups=existing_validation,
            reconstructed=False,
            leakage_check='pass',
            limitations=('insufficient_group_support',),
            score=None,
            summary=existing_summary,
        )

    group_counts: dict[str, Counter[str]] = {group: Counter() for group in groups}
    for row in rows:
        group_counts[str(row['source_group_id'])][str(row['label'])] += 1
    total_counts = Counter(str(row['label']) for row in rows)
    total_rows = len(rows)
    overall_distribution = {
        label: total_counts[label] / total_rows for label in CLASS_ORDER
    }

    best_score: tuple[object, ...] | None = None
    best_validation: tuple[str, ...] | None = None
    best_summary: dict[str, dict[str, dict[str, int]]] | None = None
    for subset_size in range(1, len(groups)):
        for validation_groups in combinations(groups, subset_size):
            validation_set = set(validation_groups)
            train_groups = tuple(group for group in groups if group not in validation_set)
            validation_counts = Counter()
            validation_class_groups = Counter()
            for group in validation_groups:
                validation_counts.update(group_counts[group])
                for label in CLASS_ORDER:
                    if group_counts[group][label] > 0:
                        validation_class_groups[label] += 1
            train_counts = Counter(
                {
                    label: total_counts[label] - validation_counts[label]
                    for label in CLASS_ORDER
                }
            )
            missing = sum(
                validation_counts[label] == 0 or train_counts[label] == 0
                for label in CLASS_ORDER
            )
            group_deficit = sum(
                max(
                    config.minimum_groups_per_class
                    - validation_class_groups[label],
                    0,
                )
                for label in CLASS_ORDER
            )
            support_deficit = sum(
                max(
                    config.minimum_support_per_class
                    - validation_counts[label],
                    0,
                )
                for label in CLASS_ORDER
            )
            validation_rows = sum(validation_counts.values())
            ratio = validation_rows / total_rows
            distribution_l1 = sum(
                abs(
                    validation_counts[label] / max(validation_rows, 1)
                    - overall_distribution[label]
                )
                for label in CLASS_ORDER
            )
            score: tuple[object, ...] = (
                missing,
                group_deficit,
                support_deficit,
                abs(ratio - config.target_ratio),
                distribution_l1,
                tuple(validation_groups),
            )
            if best_score is None or score < best_score:
                best_score = score
                best_validation = tuple(validation_groups)
                best_summary = _selection_summary(
                    rows, train_groups, validation_groups
                )

    if best_validation is None or best_summary is None:
        return SplitDecision(
            train_groups=existing_train,
            validation_groups=existing_validation,
            reconstructed=False,
            leakage_check='pass',
            limitations=('no_valid_group_subset',),
            score=None,
            summary=existing_summary,
        )

    best_train = tuple(group for group in groups if group not in set(best_validation))
    existing_missing = _coverage_missing(existing_summary)
    best_missing = _coverage_missing(best_summary)
    support_improved = _minimum_validation_metric(
        best_summary, 'support'
    ) > _minimum_validation_metric(existing_summary, 'support')
    groups_improved = _minimum_validation_metric(
        best_summary, 'group_count'
    ) > _minimum_validation_metric(existing_summary, 'group_count')
    should_reconstruct = (
        best_missing <= existing_missing and (support_improved or groups_improved)
    )
    if not should_reconstruct:
        return SplitDecision(
            train_groups=existing_train,
            validation_groups=existing_validation,
            reconstructed=False,
            leakage_check='pass',
            limitations=('no_support_improvement_without_coverage_regression',),
            score=best_score,
            summary=existing_summary,
        )
    return SplitDecision(
        train_groups=best_train,
        validation_groups=best_validation,
        reconstructed=True,
        leakage_check='pass',
        limitations=(),
        score=best_score,
        summary=best_summary,
    )
