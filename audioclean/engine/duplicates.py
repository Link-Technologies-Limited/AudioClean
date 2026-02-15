from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from audioclean.core import db as db_layer
from audioclean.utils.tags import read_tags


@dataclass(frozen=True)
class DuplicateGroup:
    group_id: int
    group_hash: str
    members: list
    canonical: object
    total_bytes: int


def list_duplicate_groups(conn, prefer_lossless: bool, sort_by: str = "hash") -> list[DuplicateGroup]:
    groups = db_layer.get_duplicates_by_hash(conn)
    ordered = sorted(groups, key=lambda rows: (rows[0]["blake3"] or ""))
    wrapped: list[DuplicateGroup] = []
    for idx, rows in enumerate(ordered, start=1):
        group_hash = rows[0]["blake3"] or ""
        canonical = _select_canonical(rows, prefer_lossless)
        total_bytes = sum(int(row["size"]) for row in rows)
        wrapped.append(
            DuplicateGroup(
                group_id=idx,
                group_hash=group_hash,
                members=list(rows),
                canonical=canonical,
                total_bytes=total_bytes,
            )
        )
    if sort_by == "size":
        wrapped.sort(key=lambda group: (len(group.members), group.total_bytes), reverse=True)
    return wrapped


def group_by_id(groups: Iterable[DuplicateGroup], group_id: int) -> DuplicateGroup | None:
    for group in groups:
        if group.group_id == group_id:
            return group
    return None


def group_stats(groups: Iterable[DuplicateGroup]) -> dict[str, float]:
    groups_list = list(groups)
    if not groups_list:
        return {"groups": 0, "avg_group_size": 0.0, "max_group_size": 0.0}
    sizes = [len(group.members) for group in groups_list]
    avg = sum(sizes) / len(sizes)
    return {
        "groups": len(groups_list),
        "avg_group_size": avg,
        "max_group_size": float(max(sizes)),
    }


def format_canonical_label(row) -> str:
    path = Path(row["path"])
    tags = read_tags(path)
    artist = tags.artist or tags.album_artist or "Unknown Artist"
    title = tags.title or path.stem
    codec = path.suffix.lstrip(".").upper()
    sample_rate = row["sample_rate"] or 0
    sample_khz = f"{sample_rate / 1000:.1f}kHz" if sample_rate else "?"
    return f"{artist} - {title} ({codec}, {sample_khz})"


def resolve_group_actions(group: DuplicateGroup, overrides: dict[str, object], dedupe_mode: str) -> list[dict]:
    canonical_path = Path(group.canonical["path"])
    actions = []
    for member in group.members:
        path = Path(member["path"])
        action = "KEEP" if path == canonical_path else _default_dedupe_action(dedupe_mode)
        override = overrides.get(str(path))
        template = None
        used_override = False
        if override:
            action = str(override["action"]).upper()
            template = override["template"]
            used_override = True
        actions.append(
            {
                "path": path,
                "action": action,
                "template": template,
                "row": member,
                "override": used_override,
            }
        )
    return actions


def _select_canonical(rows, prefer_lossless: bool):
    sorted_group = sorted(rows, key=lambda row: _dedupe_rank(row, prefer_lossless))
    return sorted_group[0]


def _dedupe_rank(row, prefer_lossless: bool) -> tuple[int, int]:
    path = Path(row["path"])
    is_lossless = path.suffix.lower() in {".flac", ".wav"}
    bitrate = row["bitrate"] or 0
    lossless_rank = 0 if (prefer_lossless and is_lossless) else 1
    return (lossless_rank, -bitrate)


def _default_dedupe_action(dedupe_mode: str) -> str:
    if dedupe_mode == "delete":
        return "DELETE"
    if dedupe_mode == "move":
        return "MOVE"
    return "SKIP"
