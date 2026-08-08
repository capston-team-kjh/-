"""Fail-closed guards for protected artifacts, test isolation, and run locks."""

from dataclasses import asdict, dataclass, is_dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .config import ExperimentConfig, canonical_json_bytes, canonical_sha256


LOCK_KEYS = (
    'selected_split',
    'frozen_test_manifest',
    'feature_schema',
    'class_mapping',
    'seed',
    'model_config',
    'sample_weight_policy',
    'sample_weight_hashes',
    'augmentation_config',
    'transform_eligibility',
    'accepted_augmentation',
    'augmentation_rejected',
    'duplicates',
    'training_inputs',
    'validation_metrics',
    'validation_predictions',
    'validation_confusions',
    'decision_thresholds',
)


class GuardViolation(RuntimeError):
    """A protected experiment invariant was violated."""


@dataclass(frozen=True)
class ProtectedSnapshot:
    roots: tuple[str, ...]
    file_hashes: Mapping[str, str]


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _files_for_roots(roots: Sequence[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            raise GuardViolation(f'protected path is missing: {root}')
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(path for path in root.rglob('*') if path.is_file())
        else:
            raise GuardViolation(f'protected path is not a file or directory: {root}')
    return sorted(set(files), key=lambda path: str(path).casefold())


def snapshot_protected(paths: Iterable[Path | str]) -> ProtectedSnapshot:
    roots = tuple(Path(path).resolve() for path in paths)
    files = _files_for_roots(roots)
    return ProtectedSnapshot(
        roots=tuple(str(path) for path in roots),
        file_hashes={str(path): _sha256_file(path) for path in files},
    )


def verify_protected(snapshot: ProtectedSnapshot) -> None:
    current = snapshot_protected(Path(path) for path in snapshot.roots)
    if dict(current.file_hashes) != dict(snapshot.file_hashes):
        before = dict(snapshot.file_hashes)
        after = dict(current.file_hashes)
        changed = sorted(
            path
            for path in set(before) | set(after)
            if before.get(path) != after.get(path)
        )
        raise GuardViolation(f'protected artifact changed: {changed}')


def build_frozen_test_manifest(
    rows: Iterable[Mapping[str, object]], config: ExperimentConfig
) -> dict[str, object]:
    selected = [dict(row) for row in rows if str(row['split']) == 'test']
    groups = sorted({str(row['source_group_id']) for row in selected})
    if (
        len(selected) != config.expected_test_rows
        or groups != [config.expected_test_group]
    ):
        raise GuardViolation(
            'frozen test must contain the expected 65 rows and one group'
        )
    canonical_rows = sorted(
        selected, key=lambda row: str(row['original_sample_id'])
    )
    return {
        'row_count': len(canonical_rows),
        'groups': groups,
        'rows': canonical_rows,
        'manifest_sha256': canonical_sha256(_json_value(canonical_rows)),
    }


def _row_mappings(value: object):
    if isinstance(value, Mapping):
        if any(
            key in value
            for key in ('sample_id', 'original_sample_id', 'source_group_id', 'split')
        ):
            yield value
        for nested in value.values():
            yield from _row_mappings(nested)
    elif isinstance(value, (list, tuple, set)):
        for nested in value:
            yield from _row_mappings(nested)


def assert_test_isolation(
    frozen_manifest: Mapping[str, object], *collections: object
) -> None:
    test_rows = frozen_manifest.get('rows', [])
    test_ids = {
        str(row['original_sample_id'])
        for row in test_rows
        if isinstance(row, Mapping) and row.get('original_sample_id') is not None
    }
    test_groups = {str(group) for group in frozen_manifest.get('groups', [])}

    for collection in collections:
        for row in _row_mappings(collection):
            original_id = row.get('original_sample_id')
            group_id = row.get('source_group_id')
            if str(row.get('split', '')).lower() == 'test':
                raise GuardViolation('frozen test row entered development input')
            if original_id is not None and str(original_id) in test_ids:
                raise GuardViolation('frozen test lineage entered development input')
            if group_id is not None and str(group_id) in test_groups:
                raise GuardViolation('frozen test group entered development input')


def _json_value(value: object) -> object:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, set):
        return sorted((_json_value(item) for item in value), key=repr)
    item = getattr(value, 'item', None)
    if callable(item):
        return item()
    return value


def _lock_payload(state: Mapping[str, object]) -> dict[str, object]:
    missing = [key for key in LOCK_KEYS if key not in state]
    if missing:
        raise GuardViolation(f'missing experiment lock key: {missing[0]}')
    unexpected = sorted(set(state) - set(LOCK_KEYS))
    if unexpected:
        raise GuardViolation(f'unexpected experiment lock key: {unexpected[0]}')
    artifacts = {
        key: canonical_sha256(_json_value(state[key])) for key in LOCK_KEYS
    }
    return {
        'format': 'focus-v3-experiment-lock-1',
        'artifact_sha256': artifacts,
        'state_sha256': canonical_sha256(artifacts),
    }


def write_experiment_lock(
    state: Mapping[str, object], path: Path | str
) -> dict[str, object]:
    destination = Path(path)
    if destination.exists():
        raise FileExistsError(f'refusing to overwrite experiment lock: {destination}')
    payload = _lock_payload(state)
    payload['lock_sha256'] = canonical_sha256(payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json_bytes(payload))
    return payload


def verify_experiment_lock(
    path: Path | str, state: Mapping[str, object]
) -> dict[str, object]:
    source = Path(path)
    try:
        stored = json.loads(source.read_text(encoding='utf-8'))
        stored_without_hash = dict(stored)
        stored_hash = stored_without_hash.pop('lock_sha256')
        current = _lock_payload(state)
        current['lock_sha256'] = canonical_sha256(current)
    except (OSError, KeyError, TypeError, ValueError, GuardViolation) as error:
        raise GuardViolation('INVALIDATED_LOCK_CHANGED') from error

    if stored_hash != canonical_sha256(stored_without_hash) or stored != current:
        raise GuardViolation('INVALIDATED_LOCK_CHANGED')
    return stored
