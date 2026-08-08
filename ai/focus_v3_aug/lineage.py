"""Stable sample lineage identifiers for original and augmented rows."""

from hashlib import sha256
from typing import Mapping

from .config import canonical_json_bytes


_ORIGINAL_FIELDS = (
    'source_sha256',
    'source_group_id',
    'timestamp_ms',
    'label',
    'label_source',
)


def original_sample_id(row: Mapping[str, object]) -> str:
    identity = '|'.join(str(row[field]) for field in _ORIGINAL_FIELDS)
    return sha256(identity.encode('utf-8')).hexdigest()


def derived_sample_id(
    original_id: str,
    augmentation_type: str,
    parameters: Mapping[str, object],
    seed: int,
) -> str:
    identity = {
        'augmentation_type': augmentation_type,
        'original_sample_id': original_id,
        'parameters': dict(parameters),
        'seed': seed,
    }
    return sha256(canonical_json_bytes(identity)).hexdigest()
