from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .contracts import load_feature_contract


HUMAN_DIRECT = "A_HUMAN_DIRECT"
HUMAN_CORRECTED = "B_HUMAN_CORRECTED"
VISUAL_DIRECT = "C_VISUAL_DIRECT"
RULE_PSEUDO = "D_RULE_PSEUDO"
UNKNOWN_PROVENANCE = "E_UNKNOWN_PROVENANCE"
VIDEO_EXTENSIONS = frozenset({".mp4", ".webm", ".mov", ".avi", ".mkv"})
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class VideoRecord:
    path: Path
    filename: str
    size_bytes: int
    duration_sec: float | None
    width: int | None
    height: int | None
    fps: float | None
    frame_count: int | None
    sha256: str
    source_id: str
    decode_valid: bool
    probe_error: str | None = None


@dataclass(frozen=True)
class LegacyLabel:
    label_id: str
    source_path: Path
    source_group_id: str
    source_id: str
    source_sha256: str
    label: str
    category: str
    label_source: str
    review_status: str
    confidence: str
    annotator: str
    eligible: bool
    exclusion_reason: str | None
    split_hint: str | None = None
    timestamp_ms: int | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    camera_layout: str = "merged"


@dataclass(frozen=True)
class RegistryIssue:
    label_source: str
    record_id: str
    reason: str
    detail: str


@dataclass(frozen=True)
class LegacyLabelRegistry:
    labels: tuple[LegacyLabel, ...]
    issues: tuple[RegistryIssue, ...] = ()

    def extend(self, other: "LegacyLabelRegistry") -> "LegacyLabelRegistry":
        return LegacyLabelRegistry(
            labels=(*self.labels, *other.labels),
            issues=(*self.issues, *other.issues),
        )


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_video(path: Path) -> VideoRecord:
    resolved = path.resolve()
    source_hash = sha256_file(resolved)
    size_bytes = resolved.stat().st_size
    try:
        import cv2

        capture = cv2.VideoCapture(str(resolved))
        try:
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            frame_count_float = float(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        finally:
            capture.release()
        valid = fps > 0 and frame_count_float > 0 and width > 0 and height > 0
        frame_count = int(frame_count_float) if frame_count_float > 0 else None
        return VideoRecord(
            path=resolved,
            filename=resolved.name,
            size_bytes=size_bytes,
            duration_sec=(frame_count_float / fps) if valid else None,
            width=width if width > 0 else None,
            height=height if height > 0 else None,
            fps=fps if fps > 0 else None,
            frame_count=frame_count,
            sha256=source_hash,
            source_id=f"SHA256_{source_hash[:16]}",
            decode_valid=valid,
            probe_error=None if valid else "invalid_video_metadata",
        )
    except Exception as error:  # A broken source must not abort independent inventory.
        return VideoRecord(
            path=resolved,
            filename=resolved.name,
            size_bytes=size_bytes,
            duration_sec=None,
            width=None,
            height=None,
            fps=None,
            frame_count=None,
            sha256=source_hash,
            source_id=f"SHA256_{source_hash[:16]}",
            decode_valid=False,
            probe_error=f"{type(error).__name__}: {error}",
        )


def discover_videos(roots: Sequence[Path]) -> tuple[VideoRecord, ...]:
    unique: dict[str, Path] = {}
    for raw_root in roots:
        root = raw_root.resolve()
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else root.rglob("*")
        for path in candidates:
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                resolved = path.resolve()
                unique.setdefault(str(resolved).casefold(), resolved)
    return tuple(probe_video(path) for path in sorted(unique.values(), key=lambda item: str(item).casefold()))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def _milliseconds(value: object, *, field: str) -> int:
    try:
        seconds = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be numeric") from error
    if seconds < 0:
        raise ValueError(f"{field} must be non-negative")
    return int(round(seconds * 1000))


def _model_classes() -> frozenset[str]:
    return frozenset(load_feature_contract(PROJECT_ROOT).class_names)


def _eligibility(label: str, *, status_ok: bool, status_reason: str) -> tuple[bool, str | None]:
    if not status_ok:
        return False, status_reason
    if label not in _model_classes():
        return False, "unsupported_or_quality_label"
    return True, None


def _verified_source(path_value: str, *, record_id: str, label_source: str) -> tuple[Path | None, RegistryIssue | None]:
    if not path_value.strip():
        return None, RegistryIssue(label_source, record_id, "missing_source_path", "source path is blank")
    source = Path(path_value).expanduser().resolve()
    if not source.is_file():
        return None, RegistryIssue(label_source, record_id, "source_not_found", str(source))
    return source, None


def load_human_point_labels(
    labels_csv: Path,
    clip_manifest_csv: Path,
    *,
    split_hint: str,
) -> LegacyLabelRegistry:
    manifest_by_name = {
        str(row.get("clip_name") or Path(str(row.get("clip_file") or "")).name): row
        for row in _read_csv(clip_manifest_csv)
    }
    labels: list[LegacyLabel] = []
    issues: list[RegistryIssue] = []
    for index, row in enumerate(_read_csv(labels_csv), start=2):
        record_id = str(row.get("frame_id") or f"row-{index}")
        clip_name = Path(str(row.get("source_video") or "")).name
        manifest = manifest_by_name.get(clip_name)
        if manifest is None:
            issues.append(RegistryIssue(labels_csv.name, record_id, "manifest_match_missing", clip_name))
            continue
        source, issue = _verified_source(
            str(manifest.get("clip_file") or ""),
            record_id=record_id,
            label_source=labels_csv.name,
        )
        if issue:
            issues.append(issue)
            continue
        assert source is not None
        source_hash = sha256_file(source)
        original_name = Path(str(manifest.get("source_file") or clip_name.split("__", 1)[0])).stem
        label = str(row.get("human_label") or "").strip()
        eligible, exclusion = _eligibility(label, status_ok=True, status_reason="")
        labels.append(
            LegacyLabel(
                label_id=record_id,
                source_path=source,
                source_group_id=original_name,
                source_id=f"SHA256_{source_hash[:16]}",
                source_sha256=source_hash,
                timestamp_ms=_milliseconds(row.get("t"), field=f"{record_id}.t"),
                start_ms=None,
                end_ms=None,
                label=label,
                category=HUMAN_DIRECT,
                label_source=labels_csv.name,
                review_status="accepted",
                confidence="human_direct",
                annotator="human",
                eligible=eligible,
                exclusion_reason=exclusion,
                split_hint=split_hint,
            )
        )
    return LegacyLabelRegistry(tuple(labels), tuple(issues))


def load_blind_visual_labels(review_csv: Path, source_map_csv: Path) -> LegacyLabelRegistry:
    source_by_blind_id = {
        str(row.get("blind_id") or "").strip(): row for row in _read_csv(source_map_csv)
    }
    labels: list[LegacyLabel] = []
    issues: list[RegistryIssue] = []
    for index, row in enumerate(_read_csv(review_csv), start=2):
        record_id = str(row.get("blind_id") or f"row-{index}").strip()
        source_row = source_by_blind_id.get(record_id)
        if source_row is None:
            issues.append(RegistryIssue(review_csv.name, record_id, "source_map_missing", record_id))
            continue
        source, issue = _verified_source(
            str(source_row.get("source_path") or ""),
            record_id=record_id,
            label_source=review_csv.name,
        )
        if issue:
            issues.append(issue)
            continue
        assert source is not None
        source_hash = str(source_row.get("source_sha256") or "").strip() or sha256_file(source)
        status = str(row.get("review_status") or "").strip().lower()
        label = str(row.get("direct_label") or "").strip()
        eligible, exclusion = _eligibility(
            label,
            status_ok=status == "accepted",
            status_reason=status or "not_accepted",
        )
        labels.append(
            LegacyLabel(
                label_id=record_id,
                source_path=source,
                source_group_id=str(source_row.get("source_group") or source_row.get("source_id") or record_id),
                source_id=str(source_row.get("source_id") or f"SHA256_{source_hash[:16]}"),
                source_sha256=source_hash,
                timestamp_ms=None,
                start_ms=_milliseconds(source_row.get("start_sec"), field=f"{record_id}.start_sec"),
                end_ms=_milliseconds(source_row.get("end_sec"), field=f"{record_id}.end_sec"),
                label=label,
                category=VISUAL_DIRECT,
                label_source=review_csv.name,
                review_status=status,
                confidence=str(row.get("confidence") or "").strip().lower(),
                annotator=str(row.get("annotator") or "").strip(),
                eligible=eligible,
                exclusion_reason=exclusion,
            )
        )
    return LegacyLabelRegistry(tuple(labels), tuple(issues))


def load_frame_segment_labels(segments_csv: Path, manifest_json: Path) -> LegacyLabelRegistry:
    document = json.loads(manifest_json.read_text(encoding="utf-8"))
    source_by_video_id = {
        str(item.get("video_id") or ""): item for item in document.get("videos", [])
    }
    labels: list[LegacyLabel] = []
    issues: list[RegistryIssue] = []
    for index, row in enumerate(_read_csv(segments_csv), start=2):
        record_id = str(row.get("segment_id") or f"row-{index}").strip()
        video_id = str(row.get("video_id") or "").strip()
        source_row = source_by_video_id.get(video_id)
        if source_row is None:
            issues.append(RegistryIssue(segments_csv.name, record_id, "manifest_match_missing", video_id))
            continue
        source, issue = _verified_source(
            str(source_row.get("source_path") or ""),
            record_id=record_id,
            label_source=segments_csv.name,
        )
        if issue:
            issues.append(issue)
            continue
        assert source is not None
        source_hash = str(source_row.get("sha256") or "").strip() or sha256_file(source)
        status = str(row.get("review_status") or "").strip().lower()
        label = str(row.get("label") or "").strip()
        eligible, exclusion = _eligibility(
            label,
            status_ok=status not in {"ambiguous", "rejected", "reject", "invalid"},
            status_reason=status or "invalid_review_status",
        )
        labels.append(
            LegacyLabel(
                label_id=record_id,
                source_path=source,
                source_group_id=video_id,
                source_id=f"SHA256_{source_hash[:16]}",
                source_sha256=source_hash,
                timestamp_ms=None,
                start_ms=_milliseconds(row.get("start_sec"), field=f"{record_id}.start_sec"),
                end_ms=_milliseconds(row.get("end_sec"), field=f"{record_id}.end_sec"),
                label=label,
                category=VISUAL_DIRECT,
                label_source=segments_csv.name,
                review_status=status,
                confidence=str(row.get("confidence") or "").strip().lower(),
                annotator="codex_visual_direct",
                eligible=eligible,
                exclusion_reason=exclusion,
            )
        )
    return LegacyLabelRegistry(tuple(labels), tuple(issues))


def combine_registries(registries: Iterable[LegacyLabelRegistry]) -> LegacyLabelRegistry:
    combined = LegacyLabelRegistry(())
    for registry in registries:
        combined = combined.extend(registry)
    return combined
