from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, replace
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Protocol, Sequence

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from ai.browser_ml.contracts import CONTRACT_RELATIVE_PATH, load_feature_contract
from ai.focus_v3_aug.augmentation import (
    SAFE_KINDS,
    _SAFE_PARAMETERS,
    build_minority_plan,
    build_transform_plan,
    evaluate_transform_eligibility,
)
from ai.focus_v3_aug.config import (
    ExperimentConfig,
    canonical_json_bytes,
    canonical_sha256,
    create_run_directory,
    default_config,
)
from ai.focus_v3_aug.duplicates import find_duplicates
from ai.focus_v3_aug.experiments import (
    build_training_input_manifests,
    evaluate_experiment,
    fit_gaussian_nb,
)
from ai.focus_v3_aug.extraction import (
    MediaPipeStreamDependencies,
    StreamExtractionRequest,
    extract_augmented_stream,
    run_selected_train_parity,
)
from ai.focus_v3_aug.failure_analysis import (
    analyze_feature_failures,
    summarize_failures,
)
from ai.focus_v3_aug.guards import (
    GuardViolation,
    ProtectedSnapshot,
    assert_test_isolation,
    build_frozen_test_manifest,
    snapshot_protected,
    verify_experiment_lock,
    verify_protected,
    write_experiment_lock,
)
from ai.focus_v3_aug.label_review import (
    LABEL_REVIEW_FIELDS,
    build_label_review,
    fit_review_reference,
    write_label_review,
)
from ai.focus_v3_aug.lineage import original_sample_id
from ai.focus_v3_aug.metrics import add_a_deltas, classification_report, is_improved
from ai.focus_v3_aug.reporting import (
    build_final_diagnosis,
    write_csv,
    write_final_reports,
    write_json,
)
from ai.focus_v3_aug.splitting import (
    apply_split,
    select_group_validation,
    summarize_split,
)


STAGE_ORDER = (
    'inventory_and_hashes',
    'feature_failure_analysis',
    'label_review',
    'validation_reconstruction',
    'protection_guards',
    'selected_train_pilot_and_parity',
    'full_augmentation',
    'validation_evaluation',
    'experiment_lock',
    'frozen_test_evaluation',
    'post_run_hash_verification',
)


class PipelineDependencies(Protocol):
    def execute(self, stage_name: str, state: 'RunState') -> 'RunState': ...


@dataclass
class RunState:
    config: object
    run_dir: Path | None = None
    stage_trace: list[str] = field(default_factory=list)
    dataset_rows: list[dict[str, object]] = field(default_factory=list)
    feature_rows: list[dict[str, object]] = field(default_factory=list)
    train_rows: list[dict[str, object]] = field(default_factory=list)
    validation_rows: list[dict[str, object]] = field(default_factory=list)
    test_rows: list[dict[str, object]] = field(default_factory=list)
    protected_snapshot: ProtectedSnapshot | None = None
    frozen_test_manifest: dict[str, object] | None = None
    test_status: str = 'NOT_EVALUATED'
    valid_test_metrics: dict[str, object] | None = None
    values: dict[str, object] = field(default_factory=dict)


def run_experiment(
    config: object, dependencies: PipelineDependencies
) -> RunState:
    state = RunState(config=config)
    try:
        for stage_name in STAGE_ORDER:
            if stage_name == 'validation_evaluation' and any(
                str(row.get('split')) == 'test' for row in state.validation_rows
            ):
                raise GuardViolation('frozen test row reached validation evaluation')
            state.stage_trace.append(stage_name)
            state = dependencies.execute(stage_name, state)
            if state.test_status == 'INVALIDATED_LOCK_CHANGED':
                state.valid_test_metrics = None
        return state
    except Exception as error:
        recorder = getattr(dependencies, 'record_failure', None)
        if callable(recorder):
            recorder(state, error)
        raise


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _path_key(value: object) -> str:
    return str(Path(str(value)).resolve()).casefold()


def _true(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes'}
    return bool(value)


def _feature_matrix(
    rows: Sequence[Mapping[str, object]], feature_names: Sequence[str]
) -> np.ndarray:
    return np.asarray(
        [[float(row[name]) for name in feature_names] for row in rows],
        dtype=np.float32,
    )


class ProductionPipelineDependencies:
    def __init__(self, config: ExperimentConfig):
        self.config = config
        self._handlers = {
            name: getattr(self, f'_stage_{name}') for name in STAGE_ORDER
        }

    def execute(self, stage_name: str, state: RunState) -> RunState:
        print(f'[focus_v3_aug] stage={stage_name}', flush=True)
        return self._handlers[stage_name](state)

    def record_failure(self, state: RunState, error: Exception) -> None:
        if state.run_dir is None or not state.run_dir.exists():
            return
        path = state.run_dir / 'failure_status.json'
        if path.exists():
            return
        write_json(
            path,
            {
                'status': 'FAILED_CLOSED',
                'error_type': type(error).__name__,
                'error': str(error),
                'attempted_stages': state.stage_trace,
                'test_status': state.test_status,
                'valid_test_metrics': None,
            },
            run_dir=state.run_dir,
        )

    @property
    def protected_paths(self) -> tuple[Path, ...]:
        root = self.config.project_root
        return (
            root / 'frontend' / 'public' / 'focus_classifier.onnx',
            root
            / 'frontend'
            / 'public'
            / 'models'
            / 'focus-state-v1.metadata.json',
            self.config.baseline_run
            / 'candidates'
            / 'focus-state-v2',
        )

    def _stage_inventory_and_hashes(self, state: RunState) -> RunState:
        protected_resolved = [path.resolve() for path in self.protected_paths]
        output = self.config.output_root.resolve()
        for protected in protected_resolved:
            if output == protected or protected in output.parents:
                raise GuardViolation('focus_v3_aug output overlaps a protected path')
        state.run_dir = create_run_directory(self.config)
        contract = load_feature_contract(self.config.project_root)
        if len(contract.feature_names) != 34:
            raise GuardViolation('focus-state-v2 feature schema is not 34-wide')
        if contract.class_names != ('drowsy', 'focus', 'gaze_down', 'gaze_side'):
            raise GuardViolation('focus-state-v2 class mapping changed')

        dataset_path = (
            self.config.baseline_run
            / 'datasets'
            / 'focus-state-v2-legacy.csv'
        )
        dataset_rows: list[dict[str, object]] = []
        for source in _read_csv(dataset_path):
            row: dict[str, object] = dict(source)
            row['original_sample_id'] = original_sample_id(row)
            row['sample_id'] = row['original_sample_id']
            row['augmentation_type'] = 'original'
            dataset_rows.append(row)
        state.dataset_rows = dataset_rows
        state.protected_snapshot = snapshot_protected(self.protected_paths)

        by_source_path: dict[str, dict[str, object]] = {}
        by_source_sha: dict[str, dict[str, object]] = {}
        for row in dataset_rows:
            info = {
                'source_group_id': str(row['source_group_id']),
                'split': str(row['split']),
                'source_sha256': str(row['source_sha256']),
            }
            by_source_path[_path_key(row['source_path'])] = info
            by_source_sha[str(row['source_sha256'])] = info
        for row in _read_csv(
            self.config.baseline_run / 'inventory' / 'label_registry.csv'
        ):
            info = {
                'source_group_id': str(row['source_group_id']),
                'split': str(row.get('split_hint', '')),
                'source_sha256': str(row.get('source_sha256', '')),
            }
            by_source_path.setdefault(_path_key(row['source_path']), info)
            if info['source_sha256']:
                by_source_sha.setdefault(str(info['source_sha256']), info)

        labels_by_source_time = {
            (_path_key(row['source_path']), int(str(row['timestamp_ms']))): row
            for row in dataset_rows
        }
        cache_by_source: dict[str, dict[str, object]] = {}
        feature_rows: list[dict[str, object]] = []
        for metadata_path in sorted(
            (self.config.baseline_run / 'cache').glob('*.metadata.json')
        ):
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
            if tuple(metadata['feature_names']) != contract.feature_names:
                raise GuardViolation('baseline cache feature schema changed')
            source_path = Path(metadata['source_path']).resolve()
            source_key = _path_key(source_path)
            source_sha = str(metadata['identity']['source_sha256'])
            info = by_source_path.get(source_key) or by_source_sha.get(source_sha)
            if info is None:
                info = {
                    'source_group_id': '',
                    'split': '',
                    'source_sha256': source_sha,
                }
            cache_path = metadata_path.with_name(
                metadata_path.name.replace('.metadata.json', '.csv')
            )
            cache_rows = _read_csv(cache_path)
            for cache_row in cache_rows:
                timestamp = int(str(cache_row['timestamp_ms']))
                label_row = labels_by_source_time.get((source_key, timestamp))
                cache_row.update(
                    {
                        'sample_id': sha256(
                            f'{source_sha}|{timestamp}|feature-audit'.encode('utf-8')
                        ).hexdigest(),
                        'source_path': str(source_path),
                        'source_sha256': source_sha,
                        'source_group_id': str(info['source_group_id']),
                        'split': str(
                            label_row['split'] if label_row else info['split']
                        ),
                        'label': str(label_row['label']) if label_row else '',
                    }
                )
                feature_rows.append(cache_row)
            camera_half = str(
                metadata.get('camera_decision', {}).get(
                    'half', metadata['identity'].get('camera_half', '')
                )
            )
            entry = {
                'source_path': source_path,
                'source_sha256': source_sha,
                'source_group_id': str(info['source_group_id']),
                'camera_half': camera_half,
                'rows': cache_rows,
                'metadata_path': metadata_path,
                'cache_path': cache_path,
            }
            cache_by_source[source_key] = entry
            cache_by_source[f'sha256:{source_sha}'] = entry
        state.feature_rows = feature_rows
        state.values.update(
            {
                'contract': contract,
                'dataset_path': dataset_path,
                'dataset_sha256': _sha256_file(dataset_path),
                'feature_schema': json.loads(
                    (
                        self.config.project_root / CONTRACT_RELATIVE_PATH
                    ).read_text(encoding='utf-8')
                ),
                'cache_by_source': cache_by_source,
            }
        )
        write_json(
            state.run_dir / 'protected_hashes_before.json',
            asdict(state.protected_snapshot),
            run_dir=state.run_dir,
        )
        write_json(
            state.run_dir / 'inventory.json',
            {
                'baseline_run': str(self.config.baseline_run),
                'dataset_path': str(dataset_path),
                'dataset_sha256': state.values['dataset_sha256'],
                'dataset_rows': len(dataset_rows),
                'feature_rows': len(feature_rows),
                'cache_sources': len(cache_by_source) // 2,
                'feature_count': len(contract.feature_names),
                'class_names': list(contract.class_names),
                'protected_file_count': len(
                    state.protected_snapshot.file_hashes
                ),
            },
            run_dir=state.run_dir,
        )
        return state

    def _stage_feature_failure_analysis(self, state: RunState) -> RunState:
        contract = state.values['contract']
        failures = analyze_feature_failures(
            state.feature_rows, contract.feature_names
        )
        summary = summarize_failures(failures, len(state.feature_rows))
        if summary['unusable_rows'] != 14_797:
            raise GuardViolation(
                'baseline feature-unusable population changed from 14,797 rows'
            )
        state.values['failures'] = failures
        state.values['failure_summary'] = summary
        failure_rows = [failure.as_dict() for failure in failures]
        write_csv(
            state.run_dir / 'failure_analysis.csv',
            failure_rows,
            (
                'sample_id',
                'primary_reason',
                'additional_reasons',
                'reason_features',
                'split',
                'label',
                'source_group_id',
            ),
            run_dir=state.run_dir,
        )
        write_json(
            state.run_dir / 'failure_analysis_summary.json',
            summary,
            run_dir=state.run_dir,
        )
        return state

    def _stage_label_review(self, state: RunState) -> RunState:
        contract = state.values['contract']
        baseline_train = [
            row for row in state.dataset_rows if row['split'] == 'train'
        ]
        non_test = [
            row for row in state.dataset_rows if row['split'] != 'test'
        ]
        reference = fit_review_reference(baseline_train, contract.feature_names)
        candidates = build_label_review(non_test, reference)
        if any(candidate['split'] == 'test' for candidate in candidates):
            raise GuardViolation('test label review was generated before lock')
        write_label_review(state.run_dir / 'label_review.csv', candidates)
        counts = Counter(str(row['confidence']) for row in candidates)
        review_summary = {
            'candidate_count': len(candidates),
            'priority_counts': {
                level: counts.get(level, 0) for level in ('HIGH', 'MEDIUM', 'LOW')
            },
            'priority_semantics': 'human_review_priority_not_truth',
            'reference_train_rows': len(baseline_train),
            'reference_limitations': list(reference.limitations),
            'source_labels_modified': False,
        }
        state.values.update(
            {
                'label_review_reference': reference,
                'label_review_candidates': candidates,
                'label_review_summary': review_summary,
            }
        )
        write_json(
            state.run_dir / 'label_review_summary.json',
            review_summary,
            run_dir=state.run_dir,
        )
        return state

    def _stage_validation_reconstruction(self, state: RunState) -> RunState:
        development = [
            row for row in state.dataset_rows if row['split'] != 'test'
        ]
        existing = {
            'train_groups': sorted(
                {
                    str(row['source_group_id'])
                    for row in development
                    if row['split'] == 'train'
                }
            ),
            'validation_groups': sorted(
                {
                    str(row['source_group_id'])
                    for row in development
                    if row['split'] == 'validation'
                }
            ),
        }
        decision = select_group_validation(
            development, existing, self.config.validation
        )
        selected = apply_split(state.dataset_rows, decision)
        state.dataset_rows = selected
        state.train_rows = [row for row in selected if row['split'] == 'train']
        state.validation_rows = [
            row for row in selected if row['split'] == 'validation'
        ]
        state.test_rows = [row for row in selected if row['split'] == 'test']
        split_summary = summarize_split(selected)
        state.values.update(
            {'split_decision': decision, 'split_summary': split_summary}
        )
        write_json(
            state.run_dir / 'selected_split.json',
            {
                'reconstructed': decision.reconstructed,
                'train_groups': list(decision.train_groups),
                'validation_groups': list(decision.validation_groups),
                'test_groups': sorted(
                    {str(row['source_group_id']) for row in state.test_rows}
                ),
                'leakage_check': decision.leakage_check,
                'limitations': list(decision.limitations),
                'summary': split_summary,
            },
            run_dir=state.run_dir,
        )
        fields = tuple(selected[0])
        write_csv(
            state.run_dir / 'selected_split_rows.csv',
            selected,
            fields,
            run_dir=state.run_dir,
        )
        return state

    def _stage_protection_guards(self, state: RunState) -> RunState:
        if state.protected_snapshot is None:
            raise GuardViolation('protected hash snapshot is absent')
        verify_protected(state.protected_snapshot)
        frozen = build_frozen_test_manifest(state.dataset_rows, self.config)
        assert_test_isolation(
            frozen,
            state.train_rows,
            state.validation_rows,
        )
        group_sets = {
            split: {
                str(row['source_group_id'])
                for row in state.dataset_rows
                if row['split'] == split
            }
            for split in ('train', 'validation', 'test')
        }
        if (
            group_sets['train'] & group_sets['validation']
            or group_sets['train'] & group_sets['test']
            or group_sets['validation'] & group_sets['test']
        ):
            raise GuardViolation('source group crosses selected splits')
        id_sets = {
            split: {
                str(row['original_sample_id'])
                for row in state.dataset_rows
                if row['split'] == split
            }
            for split in ('train', 'validation', 'test')
        }
        if (
            id_sets['train'] & id_sets['validation']
            or id_sets['train'] & id_sets['test']
            or id_sets['validation'] & id_sets['test']
        ):
            raise GuardViolation('original sample lineage crosses selected splits')
        state.frozen_test_manifest = frozen
        write_json(
            state.run_dir / 'frozen_test_manifest.json',
            frozen,
            run_dir=state.run_dir,
        )
        write_json(
            state.run_dir / 'guard_verification.json',
            {
                'protected_hashes': 'pass',
                'frozen_test_manifest': 'pass',
                'frozen_test_rows': frozen['row_count'],
                'frozen_test_groups': frozen['groups'],
                'group_leakage': 'pass',
                'original_lineage_leakage': 'pass',
                'test_augmentation': 'absent',
            },
            run_dir=state.run_dir,
        )
        return state

    def _cache_entry(
        self, state: RunState, row: Mapping[str, object]
    ) -> Mapping[str, object]:
        cache = state.values['cache_by_source']
        entry = cache.get(_path_key(row['source_path'])) or cache.get(
            f"sha256:{row['source_sha256']}"
        )
        if entry is None:
            raise GuardViolation(f"feature cache missing: {row['source_path']}")
        return entry

    @staticmethod
    def _quality_stats(
        rows: Sequence[Mapping[str, object]], feature_names: Sequence[str]
    ) -> dict[str, float | int]:
        total = len(rows)
        if not total:
            return {
                'comparable_samples': 0,
                'vector_not_ready_rate': 1.0,
                'face_failure_rate': 1.0,
                'pose_failure_rate': 1.0,
                'calibration_failure_rate': 1.0,
            }

        def feature(row: Mapping[str, object], name: str) -> float:
            if 'features' in row:
                values = tuple(row['features'])
                return float(values[feature_names.index(name)])
            return float(row.get(name, 0.0) or 0.0)

        return {
            'comparable_samples': total,
            'vector_not_ready_rate': sum(
                not _true(row.get('vector_ready')) for row in rows
            )
            / total,
            'face_failure_rate': sum(
                row.get('face_detected') is False
                or feature(row, 'face_seen') <= 0.0
                for row in rows
            )
            / total,
            'pose_failure_rate': sum(
                row.get('pose_detected') is False
                or feature(row, 'pose_seen') <= 0.0
                for row in rows
            )
            / total,
            'calibration_failure_rate': sum(
                feature(row, 'calibration_valid') <= 0.0 for row in rows
            )
            / total,
        }

    def _stream_dependencies(self) -> MediaPipeStreamDependencies:
        return MediaPipeStreamDependencies(
            self.config.project_root
            / 'frontend'
            / 'public'
            / 'face_landmarker.task',
            self.config.project_root
            / 'frontend'
            / 'public'
            / 'pose_landmarker.task',
        )

    def _stage_selected_train_pilot_and_parity(self, state: RunState) -> RunState:
        contract = state.values['contract']
        by_source: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in state.train_rows:
            by_source[_path_key(row['source_path'])].append(row)
        candidates = []
        for source, rows in by_source.items():
            unique = {int(str(row['timestamp_ms'])): row for row in rows}
            if len(unique) >= self.config.augmentation.pilot_minimum_samples:
                ordered = [unique[key] for key in sorted(unique)]
                pilot_rows = ordered[: self.config.augmentation.pilot_minimum_samples]
                candidates.append(
                    (int(str(pilot_rows[-1]['timestamp_ms'])), source, pilot_rows)
                )
        if not candidates:
            raise GuardViolation('selected train has no SAFE pilot with 20 rows')
        _, _, pilot_rows = min(candidates, key=lambda item: (item[0], item[1]))
        if any(row['split'] != 'train' for row in pilot_rows):
            raise GuardViolation('SAFE pilot escaped selected train')
        source_row = pilot_rows[0]
        cache_entry = self._cache_entry(state, source_row)
        retain = tuple(sorted(int(str(row['timestamp_ms'])) for row in pilot_rows))
        timeline = tuple(range(0, max(retain) + 1, 1000))
        base_request = StreamExtractionRequest(
            project_root=self.config.project_root,
            source_path=Path(str(source_row['source_path'])),
            source_sha256=str(source_row['source_sha256']),
            source_group_id=str(source_row['source_group_id']),
            split='train',
            camera_half=str(cache_entry['camera_half']),
            timeline_ms=timeline,
            retain_timestamps_ms=retain,
            feature_names=contract.feature_names,
            augmentation_type='no_transform',
            augmentation_parameters={},
            seed=self.config.seed,
        )
        cache_timeline = {
            int(str(row['timestamp_ms'])): row for row in cache_entry['rows']
        }
        original_timeline = [cache_timeline[timestamp] for timestamp in timeline]
        dependencies = self._stream_dependencies()
        parity = run_selected_train_parity(
            base_request,
            original_timeline,
            dependencies=dependencies,
            abs_tol=self.config.parity_abs_tol,
            rel_tol=self.config.parity_rel_tol,
        )
        if not parity.passed:
            raise GuardViolation('selected-train no-transform parity failed')

        original_pilot = [cache_timeline[timestamp] for timestamp in retain]
        original_stats = self._quality_stats(
            original_pilot, contract.feature_names
        )
        transformed_stats: dict[str, Mapping[str, float | int]] = {}
        pilot_manifests = []
        for kind in SAFE_KINDS:
            request = replace(
                base_request,
                augmentation_type=kind,
                augmentation_parameters=dict(_SAFE_PARAMETERS[kind]),
            )
            result = extract_augmented_stream(
                request, dependencies=dependencies
            )
            retained_rows = [
                row
                for row in result.timeline_rows
                if int(row['timestamp_ms']) in set(retain)
            ]
            transformed_stats[kind] = self._quality_stats(
                retained_rows, contract.feature_names
            )
            pilot_manifests.append(
                {
                    'augmentation_type': kind,
                    'source_path': str(source_row['source_path']),
                    'source_group_id': str(source_row['source_group_id']),
                    'split': 'train',
                    'retained_rows': len(retain),
                    'accepted_rows': len(result.accepted_rows),
                    'rejected_rows': len(result.rejected_rows),
                }
            )
        eligibility = evaluate_transform_eligibility(
            original_stats, transformed_stats, self.config.augmentation
        )
        enabled = tuple(
            kind for kind in SAFE_KINDS if eligibility[kind].enabled
        )
        if not enabled:
            raise GuardViolation('all SAFE transforms failed selected-train pilot')
        state.values.update(
            {
                'parity_report': parity,
                'transform_eligibility': eligibility,
                'enabled_transforms': enabled,
                'pilot_manifest': pilot_manifests,
            }
        )
        write_json(
            state.run_dir / 'parity_report.json',
            parity.as_dict(),
            run_dir=state.run_dir,
        )
        write_json(
            state.run_dir / 'transform_eligibility.json',
            {
                kind: result.as_dict() for kind, result in eligibility.items()
            },
            run_dir=state.run_dir,
        )
        write_json(
            state.run_dir / 'safe_pilot_manifest.json',
            pilot_manifests,
            run_dir=state.run_dir,
        )
        return state

    def _stage_full_augmentation(self, state: RunState) -> RunState:
        contract = state.values['contract']
        enabled = state.values['enabled_transforms']
        plan_b = build_transform_plan(
            state.train_rows,
            self.config.augmentation,
            enabled,
            seed=self.config.seed,
        )
        plan_c = build_minority_plan(
            state.train_rows,
            self.config.augmentation,
            enabled,
            seed=self.config.seed,
        )
        original_by_id = {
            str(row['original_sample_id']): row for row in state.train_rows
        }
        request_by_id: dict[str, object] = {}
        experiments_by_id: dict[str, set[str]] = defaultdict(set)
        for request in (*plan_b, *plan_c.requests):
            request_by_id.setdefault(request.sample_id, request)
            experiments_by_id[request.sample_id].add(request.experiment)

        grouped: dict[tuple[str, str], list[object]] = defaultdict(list)
        for request in request_by_id.values():
            original = original_by_id[request.original_sample_id]
            grouped[(_path_key(original['source_path']), request.augmentation_type)].append(
                request
            )

        accepted_by_id: dict[str, dict[str, object]] = {}
        rejected_by_id: dict[str, dict[str, object]] = {}
        dependencies = self._stream_dependencies()
        total_groups = len(grouped)
        for group_index, ((_, kind), requests) in enumerate(
            sorted(grouped.items()), start=1
        ):
            first = requests[0]
            first_original = original_by_id[first.original_sample_id]
            cache_entry = self._cache_entry(state, first_original)
            timestamps = sorted(
                {
                    int(str(original_by_id[request.original_sample_id]['timestamp_ms']))
                    for request in requests
                }
            )
            print(
                '[focus_v3_aug] augmentation_stream='
                f'{group_index}/{total_groups} kind={kind} '
                f'rows={len(requests)} last_ms={timestamps[-1]}',
                flush=True,
            )
            stream_request = StreamExtractionRequest(
                project_root=self.config.project_root,
                source_path=Path(str(first_original['source_path'])),
                source_sha256=str(first_original['source_sha256']),
                source_group_id=str(first_original['source_group_id']),
                split='train',
                camera_half=str(cache_entry['camera_half']),
                timeline_ms=tuple(range(0, timestamps[-1] + 1, 1000)),
                retain_timestamps_ms=tuple(timestamps),
                feature_names=contract.feature_names,
                augmentation_type=kind,
                augmentation_parameters=dict(first.parameters),
                seed=self.config.seed,
            )
            result = extract_augmented_stream(
                stream_request, dependencies=dependencies
            )
            accepted_at = {
                int(row['timestamp_ms']): row for row in result.accepted_rows
            }
            rejected_at = {
                int(row['timestamp_ms']): row for row in result.rejected_rows
            }
            for request in requests:
                original = original_by_id[request.original_sample_id]
                timestamp = int(str(original['timestamp_ms']))
                common = {
                    'sample_id': request.sample_id,
                    'original_sample_id': request.original_sample_id,
                    'source_group_id': request.source_group_id,
                    'source_path': str(original['source_path']),
                    'source_sha256': str(original['source_sha256']),
                    'timestamp_ms': timestamp,
                    'label': request.label,
                    'split': 'train',
                    'augmentation_type': request.augmentation_type,
                    'parameters': dict(request.parameters),
                    'seed': request.seed,
                    'experiments': sorted(experiments_by_id[request.sample_id]),
                }
                if timestamp in accepted_at:
                    features = tuple(accepted_at[timestamp]['features'])
                    accepted_by_id[request.sample_id] = {
                        **common,
                        **{
                            name: float(value)
                            for name, value in zip(contract.feature_names, features)
                        },
                    }
                else:
                    rejection = rejected_at.get(
                        timestamp,
                        {
                            'primary_reason': 'frame_decode_failure',
                            'additional_reasons': [],
                            'available_features': [],
                        },
                    )
                    rejected_by_id[request.sample_id] = {
                        **common,
                        'primary_reason': rejection['primary_reason'],
                        'additional_reasons': rejection['additional_reasons'],
                        'available_features': rejection.get('available_features', []),
                    }

        accepted = list(accepted_by_id.values())
        rejected = list(rejected_by_id.values())
        accepted_b = [
            row for row in accepted if 'B' in row['experiments']
        ]
        accepted_c = [
            row for row in accepted if 'C' in row['experiments']
        ]
        duplicate_report = find_duplicates(
            [*state.train_rows, *accepted],
            contract.feature_names,
            self.config.parity_abs_tol,
            self.config.parity_rel_tol,
        )
        duplicate_rows = [row.as_dict() for row in duplicate_report.rows]
        state.values.update(
            {
                'plan_b': plan_b,
                'plan_c': plan_c,
                'accepted_augmentation': accepted,
                'accepted_b': accepted_b,
                'accepted_c': accepted_c,
                'augmentation_rejected': rejected,
                'duplicate_report': duplicate_report,
                'duplicate_rows': duplicate_rows,
            }
        )
        manifest_fields = (
            'sample_id',
            'original_sample_id',
            'source_group_id',
            'source_path',
            'source_sha256',
            'timestamp_ms',
            'label',
            'split',
            'augmentation_type',
            'parameters',
            'seed',
            'experiments',
        )
        write_csv(
            state.run_dir / 'accepted_augmentation.csv',
            accepted,
            (*manifest_fields, *contract.feature_names),
            run_dir=state.run_dir,
        )
        write_csv(
            state.run_dir / 'augmentation_rejected.csv',
            rejected,
            (
                *manifest_fields,
                'primary_reason',
                'additional_reasons',
                'available_features',
            ),
            run_dir=state.run_dir,
        )
        write_csv(
            state.run_dir / 'duplicates.csv',
            duplicate_rows,
            (
                'duplicate_type',
                'sample_id',
                'original_sample_id',
                'related_sample_id',
                'label',
                'augmentation_type',
                'related_row_count',
                'exclude_from_training',
            ),
            run_dir=state.run_dir,
        )
        accepted_c_counts = Counter(row['label'] for row in accepted_c)
        augmentation_summary = {
            'enabled_transforms': list(enabled),
            'maximum_derivatives_b': self.config.augmentation.maximum_derivatives_b,
            'maximum_derivatives_c': self.config.augmentation.maximum_derivatives_c,
            'b_requested': len(plan_b),
            'b_accepted': len(accepted_b),
            'c_median_count': plan_c.median_count,
            'c_original_counts': plan_c.original_counts,
            'c_targets': plan_c.targets,
            'c_requested_additions': plan_c.requested_additions,
            'c_actual_requested_additions': plan_c.actual_additions,
            'c_accepted_additions': dict(sorted(accepted_c_counts.items())),
            'rejected_count': len(rejected),
            'exact_duplicate_count': duplicate_report.exact_count,
            'near_duplicate_count': duplicate_report.near_count,
        }
        state.values['augmentation_summary'] = augmentation_summary
        write_json(
            state.run_dir / 'augmentation_summary.json',
            augmentation_summary,
            run_dir=state.run_dir,
        )
        return state

    @staticmethod
    def _exclude_exact(
        rows: Sequence[dict[str, object]], duplicate_rows: Sequence[Mapping[str, object]]
    ) -> list[dict[str, object]]:
        excluded = {
            str(row['sample_id'])
            for row in duplicate_rows
            if bool(row['exclude_from_training'])
        }
        return [row for row in rows if str(row['sample_id']) not in excluded]

    def _training_rows(self, state: RunState, *, final: bool) -> dict[str, list[dict[str, object]]]:
        originals = (
            [*state.train_rows, *state.validation_rows]
            if final
            else state.train_rows
        )
        accepted_b = self._exclude_exact(
            state.values['accepted_b'], state.values['duplicate_rows']
        )
        accepted_c = self._exclude_exact(
            state.values['accepted_c'], state.values['duplicate_rows']
        )
        return {
            'A': list(originals),
            'B': [*originals, *accepted_b],
            'C': [*originals, *accepted_c],
        }

    def _stage_validation_evaluation(self, state: RunState) -> RunState:
        if any(row['split'] == 'test' for row in state.validation_rows):
            raise GuardViolation('test reached validation evaluation')
        contract = state.values['contract']
        training = self._training_rows(state, final=False)
        metrics: dict[str, dict[str, object]] = {}
        predictions: dict[str, list[dict[str, str]]] = {}
        confusions: dict[str, dict[str, object]] = {}
        weight_hashes: dict[str, str] = {}
        for name in ('A', 'B', 'C'):
            evaluation = evaluate_experiment(
                training[name],
                state.validation_rows,
                self.config,
                contract.feature_names,
                contract.class_names,
            )
            metrics[name] = evaluation.metrics.as_dict()
            predictions[name] = list(evaluation.predictions)
            confusions[name] = {
                'raw': evaluation.metrics.confusion_raw,
                'row_normalized': evaluation.metrics.confusion_row_normalized,
            }
            weight_hashes[name] = evaluation.sample_weight_sha256
        baseline = metrics['A']
        metrics = {
            name: add_a_deltas(report, baseline)
            for name, report in metrics.items()
        }
        state.values.update(
            {
                'validation_training_rows': training,
                'validation_metrics': metrics,
                'validation_predictions': predictions,
                'validation_confusions': confusions,
                'validation_weight_hashes': weight_hashes,
            }
        )
        write_json(
            state.run_dir / 'validation_metrics.json',
            metrics,
            run_dir=state.run_dir,
        )
        write_json(
            state.run_dir / 'validation_predictions.json',
            predictions,
            run_dir=state.run_dir,
        )
        write_json(
            state.run_dir / 'validation_confusions.json',
            confusions,
            run_dir=state.run_dir,
        )
        return state

    def _stage_experiment_lock(self, state: RunState) -> RunState:
        contract = state.values['contract']
        final_training = self._training_rows(state, final=True)
        final_models = {}
        final_weight_hashes = {}
        for name in ('A', 'B', 'C'):
            model, weight_hash = fit_gaussian_nb(
                final_training[name], self.config, contract.feature_names
            )
            final_models[name] = model
            final_weight_hashes[name] = weight_hash
        training_manifests = build_training_input_manifests(
            [*state.train_rows, *state.validation_rows],
            state.values['accepted_b'],
            state.values['accepted_c'],
            state.values['duplicate_rows'],
        )
        selected_manifest = [
            {
                'original_sample_id': row['original_sample_id'],
                'source_group_id': row['source_group_id'],
                'source_sha256': row['source_sha256'],
                'timestamp_ms': row['timestamp_ms'],
                'label': row['label'],
                'split': row['split'],
            }
            for row in state.dataset_rows
        ]
        lock_state = {
            'selected_split': selected_manifest,
            'frozen_test_manifest': state.frozen_test_manifest,
            'feature_schema': state.values['feature_schema'],
            'class_mapping': {
                'class_names': list(contract.class_names),
                'class_ids': {
                    label: index for index, label in enumerate(contract.class_names)
                },
            },
            'seed': self.config.seed,
            'model_config': asdict(self.config.model),
            'sample_weight_policy': {
                'enabled': self.config.model.sample_weight_enabled,
                'rule': self.config.model.sample_weight_rule,
                'labels': 'each_actual_training_dataset_y_train',
            },
            'sample_weight_hashes': {
                'validation': state.values['validation_weight_hashes'],
                'final': final_weight_hashes,
            },
            'augmentation_config': asdict(self.config.augmentation),
            'transform_eligibility': {
                kind: result.as_dict()
                for kind, result in state.values['transform_eligibility'].items()
            },
            'accepted_augmentation': state.values['accepted_augmentation'],
            'augmentation_rejected': state.values['augmentation_rejected'],
            'duplicates': state.values['duplicate_report'].as_dict(),
            'training_inputs': training_manifests,
            'validation_metrics': state.values['validation_metrics'],
            'validation_predictions': state.values['validation_predictions'],
            'validation_confusions': state.values['validation_confusions'],
            'decision_thresholds': asdict(self.config.decision),
        }
        assert_test_isolation(
            state.frozen_test_manifest,
            state.values['accepted_augmentation'],
            state.values['augmentation_rejected'],
            training_manifests,
        )
        lock_state_path = write_json(
            state.run_dir / 'lock-state.json',
            lock_state,
            run_dir=state.run_dir,
        )
        lock_path = state.run_dir / 'experiment-lock.json'
        lock = write_experiment_lock(lock_state, lock_path)
        verify_experiment_lock(lock_path, lock_state)
        state.values.update(
            {
                'final_training_rows': final_training,
                'final_training_manifests': training_manifests,
                'final_models': final_models,
                'final_weight_hashes': final_weight_hashes,
                'lock_state': lock_state,
                'lock_state_path': lock_state_path,
                'lock_path': lock_path,
                'experiment_lock': lock,
            }
        )
        return state

    def _stage_frozen_test_evaluation(self, state: RunState) -> RunState:
        verify_experiment_lock(
            state.values['lock_path'], state.values['lock_state']
        )
        contract = state.values['contract']
        pending_metrics = {}
        pending_predictions = {}
        pending_confusions = {}
        for name in ('A', 'B', 'C'):
            model = state.values['final_models'][name]
            predicted = [
                str(value)
                for value in model.predict(
                    _feature_matrix(state.test_rows, contract.feature_names)
                )
            ]
            actual = [str(row['label']) for row in state.test_rows]
            report = classification_report(
                actual, predicted, contract.class_names
            )
            pending_metrics[name] = report.as_dict()
            pending_predictions[name] = [
                {
                    'sample_id': str(row['original_sample_id']),
                    'actual': actual[index],
                    'predicted': predicted[index],
                }
                for index, row in enumerate(state.test_rows)
            ]
            pending_confusions[name] = {
                'raw': report.confusion_raw,
                'row_normalized': report.confusion_row_normalized,
            }
        baseline = pending_metrics['A']
        pending_metrics = {
            name: add_a_deltas(report, baseline)
            for name, report in pending_metrics.items()
        }
        test_review = build_label_review(
            state.test_rows, state.values['label_review_reference']
        )
        verify_experiment_lock(
            state.values['lock_path'], state.values['lock_state']
        )
        state.values.update(
            {
                'pending_test_metrics': pending_metrics,
                'pending_test_predictions': pending_predictions,
                'pending_test_confusions': pending_confusions,
                'pending_test_label_review': test_review,
            }
        )
        state.test_status = 'PENDING_POST_HASH_VERIFICATION'
        state.valid_test_metrics = None
        return state

    def _stage_post_run_hash_verification(self, state: RunState) -> RunState:
        if state.protected_snapshot is None:
            raise GuardViolation('protected snapshot is absent after test')
        try:
            verify_protected(state.protected_snapshot)
            verify_experiment_lock(
                state.values['lock_path'], state.values['lock_state']
            )
        except GuardViolation:
            state.test_status = 'INVALIDATED_LOCK_CHANGED'
            state.valid_test_metrics = None
            raise
        after = snapshot_protected(self.protected_paths)
        write_json(
            state.run_dir / 'protected_hashes_after.json',
            asdict(after),
            run_dir=state.run_dir,
        )
        test_metrics = state.values['pending_test_metrics']
        write_json(
            state.run_dir / 'test_metrics.json',
            test_metrics,
            run_dir=state.run_dir,
        )
        write_json(
            state.run_dir / 'test_predictions.json',
            state.values['pending_test_predictions'],
            run_dir=state.run_dir,
        )
        write_json(
            state.run_dir / 'test_confusions.json',
            state.values['pending_test_confusions'],
            run_dir=state.run_dir,
        )
        write_csv(
            state.run_dir / 'label_review_test_informational.csv',
            state.values['pending_test_label_review'],
            LABEL_REVIEW_FIELDS,
            run_dir=state.run_dir,
        )
        experiments = {
            name: {
                'validation': state.values['validation_metrics'][name],
                'test': test_metrics[name],
            }
            for name in ('A', 'B', 'C')
        }
        eligibility_pass = all(
            result.enabled
            for kind, result in state.values['transform_eligibility'].items()
            if kind in state.values['enabled_transforms']
        )
        improvement = {
            name: is_improved(
                {
                    **experiments[name],
                    'safety_gates': {
                        'protected_hashes': True,
                        'lock': True,
                        'leakage': True,
                        'parity': state.values['parity_report'].passed,
                        'transform_eligibility': eligibility_pass,
                    },
                },
                experiments['A'],
                self.config.decision,
            )
            for name in ('B', 'C')
        }
        high_reviews = state.values['label_review_summary']['priority_counts']['HIGH']
        label_score = high_reviews / max(len(state.dataset_rows) - len(state.test_rows), 1)
        feature_score = float(
            state.values['failure_summary']['unusable_rate']
        )
        validation_focus = float(
            experiments['A']['validation']['focus_recall']
        )
        test_focus = float(experiments['A']['test']['focus_recall'])
        split_score = min(1.0, abs(validation_focus - test_focus) + 0.25)
        train_counts = Counter(row['label'] for row in state.train_rows)
        median_count = state.values['plan_c'].median_count
        imbalance_score = max(
            (median_count - train_counts['focus']) / max(median_count, 1), 0.0
        )
        degraded = all(
            float(experiments[name]['test']['macro_f1'])
            < float(experiments['A']['test']['macro_f1'])
            - self.config.decision.minimum_macro_f1_delta
            for name in ('B', 'C')
        )
        diagnosis = build_final_diagnosis(
            {
                'execution_failed': False,
                'needs_review': high_reviews > 0,
                'degraded': degraded,
                'improved_gate': any(result.passed for result in improvement.values()),
                'label_problem_score': label_score,
                'feature_problem_score': feature_score,
                'split_problem_score': split_score,
                'imbalance_problem_score': imbalance_score,
                'limitations': [
                    'test support is 65 rows',
                    'test contains one recording group',
                    'group leakage prevention takes priority over row stratification',
                ],
            },
            self.config.decision,
        )
        report = {
            'execution': {
                'run_id': self.config.run_id,
                'seed': self.config.seed,
                'stage_order': list(STAGE_ORDER),
                'model': asdict(self.config.model),
                'augmentation': asdict(self.config.augmentation),
                'decision_thresholds': asdict(self.config.decision),
                'production_promotion': False,
                'existing_model_replacement': False,
                'source_label_modification': False,
            },
            'protection': {
                'before': asdict(state.protected_snapshot),
                'after': asdict(after),
                'frozen_test_guard': 'pass',
                'leakage_guard': 'pass',
                'experiment_lock': state.values['experiment_lock'],
                'test_status': 'VALID',
            },
            'feature_failure_analysis': state.values['failure_summary'],
            'label_review': state.values['label_review_summary'],
            'split': {
                'summary': state.values['split_summary'],
                'train_groups': list(
                    state.values['split_decision'].train_groups
                ),
                'validation_groups': list(
                    state.values['split_decision'].validation_groups
                ),
                'test_groups': state.frozen_test_manifest['groups'],
                'leakage': 'none',
            },
            'augmentation': state.values['augmentation_summary'],
            'experiments': experiments,
            'improvement_guards': {
                name: {
                    'passed': result.passed,
                    'failed_gates': list(result.failed_gates),
                    'deltas': result.deltas,
                }
                for name, result in improvement.items()
            },
            'cause_evidence': {
                'label_problem_score': label_score,
                'feature_problem_score': feature_score,
                'split_problem_score': split_score,
                'imbalance_problem_score': imbalance_score,
            },
            'decision': diagnosis.as_dict(),
        }
        state.test_status = 'VALID'
        state.valid_test_metrics = test_metrics
        state.values.update(
            {
                'test_metrics': test_metrics,
                'experiments': experiments,
                'improvement': improvement,
                'diagnosis': diagnosis,
                'final_report': report,
            }
        )
        write_json(
            state.run_dir / 'test_status.json',
            {
                'status': state.test_status,
                'row_count': len(state.test_rows),
                'groups': state.frozen_test_manifest['groups'],
            },
            run_dir=state.run_dir,
        )
        write_json(
            state.run_dir / 'run_status.json',
            {
                'status': 'COMPLETE',
                'test_status': state.test_status,
                'stage_trace': state.stage_trace,
                'run_id': self.config.run_id,
            },
            run_dir=state.run_dir,
        )
        write_final_reports(state.run_dir, report)
        return state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command', required=True)
    run = subparsers.add_parser('run')
    run.add_argument('--project-root', type=Path, required=True)
    run.add_argument('--baseline-run', type=Path, required=True)
    run.add_argument('--output-root', type=Path, required=True)
    run.add_argument('--run-id', required=True)
    run.add_argument('--seed', type=int, default=20260808)
    verify = subparsers.add_parser('verify-run')
    verify.add_argument('--run-dir', type=Path, required=True)
    return parser


def verify_completed_run(run_dir: Path) -> dict[str, object]:
    root = run_dir.resolve()
    status = json.loads((root / 'run_status.json').read_text(encoding='utf-8'))
    if status.get('status') != 'COMPLETE' or status.get('stage_trace') != list(
        STAGE_ORDER
    ):
        raise GuardViolation('run is incomplete or stage order changed')
    test_status = json.loads(
        (root / 'test_status.json').read_text(encoding='utf-8')
    )
    if test_status.get('status') != 'VALID' or test_status.get('row_count') != 65:
        raise GuardViolation('frozen test result is not valid for 65 rows')
    frozen = json.loads(
        (root / 'frozen_test_manifest.json').read_text(encoding='utf-8')
    )
    if frozen.get('row_count') != 65 or len(frozen.get('groups', [])) != 1:
        raise GuardViolation('frozen test manifest changed')
    lock_state = json.loads(
        (root / 'lock-state.json').read_text(encoding='utf-8')
    )
    verify_experiment_lock(root / 'experiment-lock.json', lock_state)
    assert_test_isolation(
        frozen,
        lock_state['accepted_augmentation'],
        lock_state['augmentation_rejected'],
        lock_state['training_inputs'],
    )
    before_value = json.loads(
        (root / 'protected_hashes_before.json').read_text(encoding='utf-8')
    )
    after_value = json.loads(
        (root / 'protected_hashes_after.json').read_text(encoding='utf-8')
    )
    before = ProtectedSnapshot(
        tuple(before_value['roots']), dict(before_value['file_hashes'])
    )
    if before_value != after_value:
        raise GuardViolation('protected before/after snapshots differ')
    verify_protected(before)
    test_metrics = json.loads(
        (root / 'test_metrics.json').read_text(encoding='utf-8')
    )
    if sorted(test_metrics) != ['A', 'B', 'C']:
        raise GuardViolation('A/B/C frozen test metrics are incomplete')
    return {
        'status': 'VALID',
        'run_dir': str(root),
        'test_rows': 65,
        'test_groups': frozen['groups'],
        'experiment_lock': 'pass',
        'protected_hashes': 'pass',
        'leakage': 'pass',
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == 'verify-run':
        print(json.dumps(verify_completed_run(args.run_dir), ensure_ascii=False, indent=2))
        return 0
    config = default_config(
        args.project_root,
        args.baseline_run,
        args.output_root,
        run_id=args.run_id,
    )
    config = replace(config, seed=args.seed)
    state = run_experiment(config, ProductionPipelineDependencies(config))
    if state.test_status != 'VALID':
        return 2
    print(
        json.dumps(
            {
                'status': 'COMPLETE',
                'run_dir': str(state.run_dir),
                'test_status': state.test_status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
