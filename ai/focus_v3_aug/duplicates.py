"""Exact and near feature-vector duplicate manifests."""

from dataclasses import asdict, dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class DuplicateRecord:
    duplicate_type: str
    sample_id: str
    original_sample_id: str
    related_sample_id: str
    label: str
    augmentation_type: str
    related_row_count: int
    exclude_from_training: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DuplicateReport:
    exact_count: int
    near_count: int
    rows: tuple[DuplicateRecord, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            'exact_count': self.exact_count,
            'near_count': self.near_count,
            'rows': [row.as_dict() for row in self.rows],
        }


def _sample_id(row: Mapping[str, object], index: int) -> str:
    return str(row.get('sample_id', row.get('original_sample_id', index)))


def _record(
    duplicate_type: str,
    row: Mapping[str, object],
    index: int,
    related: Mapping[str, object],
    related_index: int,
    related_count: int,
) -> DuplicateRecord:
    return DuplicateRecord(
        duplicate_type=duplicate_type,
        sample_id=_sample_id(row, index),
        original_sample_id=str(row.get('original_sample_id', '')),
        related_sample_id=_sample_id(related, related_index),
        label=str(row.get('label', '')),
        augmentation_type=str(row.get('augmentation_type', 'original')),
        related_row_count=related_count,
        exclude_from_training=duplicate_type == 'exact',
    )


def find_duplicates(
    rows: Iterable[Mapping[str, object]],
    feature_names: Sequence[str],
    abs_tol: float,
    rel_tol: float,
) -> DuplicateReport:
    materialized = [dict(row) for row in rows]
    vectors = [
        np.asarray([float(row[name]) for name in feature_names], dtype=np.float64)
        for row in materialized
    ]
    exact_groups: dict[bytes, list[int]] = {}
    for index, vector in enumerate(vectors):
        exact_groups.setdefault(vector.tobytes(), []).append(index)

    exact_records: list[DuplicateRecord] = []
    exact_excluded: set[int] = set()
    representatives: list[int] = []
    for indices in exact_groups.values():
        root = next(
            (
                index
                for index in indices
                if _sample_id(materialized[index], index)
                == str(materialized[index].get('original_sample_id', ''))
            ),
            indices[0],
        )
        representatives.append(root)
        for index in indices:
            if index == root:
                continue
            exact_excluded.add(index)
            exact_records.append(
                _record(
                    'exact',
                    materialized[index],
                    index,
                    materialized[root],
                    root,
                    len(indices),
                )
            )

    near_records: list[DuplicateRecord] = []
    ordered_representatives = sorted(representatives)
    for position, index in enumerate(ordered_representatives):
        for related_index in ordered_representatives[:position]:
            if np.isclose(
                vectors[index],
                vectors[related_index],
                rtol=rel_tol,
                atol=abs_tol,
                equal_nan=False,
            ).all():
                near_records.append(
                    _record(
                        'near',
                        materialized[index],
                        index,
                        materialized[related_index],
                        related_index,
                        2,
                    )
                )
                break

    records = tuple(
        sorted(
            (*exact_records, *near_records),
            key=lambda row: (row.duplicate_type, row.sample_id),
        )
    )
    return DuplicateReport(
        exact_count=len(exact_records),
        near_count=len(near_records),
        rows=records,
    )
