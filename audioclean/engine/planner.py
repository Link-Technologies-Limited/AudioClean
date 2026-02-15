from __future__ import annotations

from pathlib import Path

from audioclean.core import db as db_layer
from audioclean.core.config import Config
from audioclean.engine.duplicates import list_duplicate_groups, resolve_group_actions
from audioclean.core.models import Operation, Plan
from audioclean.core.reporter import Reporter
from audioclean.utils.fs import render_layout
from audioclean.utils.tags import read_tags


def plan(
    root_paths: list[Path],
    conn,
    reporter: Reporter,
    config: Config,
    dedupe_mode: str,
    dupe_dir: Path | None,
    layout: str | None,
    art_only: bool,
    confidence_threshold: float,
    auto_accept_above: float,
    require_review_below: float,
) -> Plan:
    operations: list[Operation] = []
    summary = {
        "duplicate_groups": 0,
        "delete": 0,
        "move": 0,
        "rename": 0,
        "review": 0,
        "tag_updates": 0,
        "art_fetches": 0,
        "estimated_reclaim_bytes": 0,
    }

    reporter.info("Planning actions...")
    if not art_only and dedupe_mode != "off":
        reporter.info("Stage: grouping duplicates")
        dedupe_ops, dedupe_summary = _plan_dedupe(
            conn,
            dedupe_mode,
            dupe_dir,
            config.prefer_lossless,
            reporter,
            auto_accept_above,
            require_review_below,
        )
        operations.extend(dedupe_ops)
        _merge_summary(summary, dedupe_summary)

    if not art_only and layout:
        reporter.info("Stage: determining rename targets")
        rename_ops, rename_summary = _plan_rename(
            conn,
            root_paths,
            layout,
            confidence_threshold,
            auto_accept_above,
            require_review_below,
            reporter,
        )
        operations.extend(rename_ops)
        _merge_summary(summary, rename_summary)

    reporter.info("Stage: planning metadata writes")
    reporter.info("Stage: planning album art fetches")
    art_ops, art_summary = _plan_art(conn, reporter, auto_accept_above, require_review_below)
    if art_only:
        operations = art_ops
    else:
        operations.extend(art_ops)
    _merge_summary(summary, art_summary)

    plan_obj = Plan.create(
        root_paths=root_paths,
        operations=operations,
        metadata={
            "summary": summary,
            "thresholds": {
                "auto_accept_above": auto_accept_above,
                "require_review_below": require_review_below,
            },
        },
    )
    return plan_obj


def _plan_dedupe(
    conn,
    dedupe_mode: str,
    dupe_dir: Path | None,
    prefer_lossless: bool,
    reporter: Reporter,
    auto_accept_above: float,
    require_review_below: float,
) -> tuple[list[Operation], dict[str, int]]:
    operations: list[Operation] = []
    summary = {
        "duplicate_groups": 0,
        "delete": 0,
        "move": 0,
        "rename": 0,
        "review": 0,
        "estimated_reclaim_bytes": 0,
    }
    groups = list_duplicate_groups(conn, prefer_lossless)
    summary["duplicate_groups"] = len(groups)

    reporter.info("Stage: resolving canonical tracks")
    reporter.info("Stage: selecting best files")
    reporter.info("Stage: planning deletes and moves")
    with reporter.progress("Analyzing duplicate groups") as progress:
        task = progress.add_task("duplicate groups", total=len(groups))
        for group in groups:
            overrides = db_layer.get_group_overrides(conn, group.group_hash)
            actions = resolve_group_actions(group, overrides, dedupe_mode)
            for action in actions:
                op = _dedupe_action_to_op(
                    action,
                    group,
                    dupe_dir,
                    auto_accept_above,
                    require_review_below,
                )
                if op is None:
                    continue
                operations.append(op)
                _apply_summary_for_op(summary, op, action["row"])
            progress.advance(task, 1)
    return operations, summary


def _plan_rename(
    conn,
    root_paths: list[Path],
    layout: str,
    confidence_threshold: float,
    auto_accept_above: float,
    require_review_below: float,
    reporter: Reporter,
) -> tuple[list[Operation], dict[str, int]]:
    operations: list[Operation] = []
    summary = {
        "rename": 0,
        "review": 0,
    }
    rows = [row for row in db_layer.iter_files(conn)]
    with reporter.progress("Determining rename targets") as progress:
        task = progress.add_task("rename targets", total=len(rows))
        for row in rows:
            path = Path(row["path"])
            if not _in_roots(path, root_paths):
                progress.advance(task, 1)
                continue
            tags = read_tags(path)
            confidence = _estimate_tag_confidence(tags)
            new_relative = render_layout(layout, tags)
            root = _root_for_path(path, root_paths)
            new_path = (root / new_relative) if root else new_relative
            if new_path == path:
                progress.advance(task, 1)
                continue
            status = _status_for_confidence(confidence, auto_accept_above, require_review_below)
            if confidence < confidence_threshold:
                status = "review"
            op = Operation.create(
                "rename",
                path,
                new_path,
                f"Rename to layout (confidence {confidence:.2f})",
                confidence=confidence,
                sources=["tags"],
                status=status,
                metadata={"group": None},
            )
            operations.append(op)
            summary["rename"] += 1
            if status == "review":
                summary["review"] += 1
            progress.advance(task, 1)
    return operations, summary


def _plan_art(
    conn,
    reporter: Reporter,
    auto_accept_above: float,
    require_review_below: float,
) -> tuple[list[Operation], dict[str, int]]:
    operations: list[Operation] = []
    rows = [row for row in db_layer.iter_files(conn) if not row["has_art"]]
    summary = {"art_fetches": 0, "review": 0}
    with reporter.progress("Planning album art fetches") as progress:
        task = progress.add_task("album art", total=len(rows))
        for row in rows:
            path = Path(row["path"])
            confidence = 0.6
            status = _status_for_confidence(confidence, auto_accept_above, require_review_below)
            op = Operation.create(
                "art_fetch",
                path,
                None,
                "Missing embedded art",
                confidence=confidence,
                sources=["embedded_art"],
                status=status,
            )
            operations.append(op)
            summary["art_fetches"] += 1
            if status == "review":
                summary["review"] += 1
            progress.advance(task, 1)
    return operations, summary


def _estimate_tag_confidence(tags) -> float:
    score = 0.0
    required = [tags.title, tags.artist, tags.album, tags.track]
    score += 0.6 if all(required) else 0.3 if any(required) else 0.1
    if tags.year:
        score += 0.2
    if tags.album_artist:
        score += 0.2
    return min(score, 0.95)


def _status_for_confidence(confidence: float, auto_accept_above: float, require_review_below: float) -> str:
    if confidence < require_review_below:
        return "review"
    if confidence >= auto_accept_above:
        return "pending"
    return "review"


def _dedupe_action_to_op(
    action_entry: dict,
    group,
    dupe_dir: Path | None,
    auto_accept_above: float,
    require_review_below: float,
) -> Operation | None:
    row = action_entry["row"]
    path = Path(row["path"])
    action = action_entry["action"]
    template = action_entry.get("template")

    if action == "KEEP":
        return None
    if action in {"SKIP"}:
        return None

    reason = "Exact duplicate by blake3"
    sources = ["hash"]
    if action_entry.get("override"):
        sources.append("override")
    confidence = 0.99
    status = _status_for_confidence(confidence, auto_accept_above, require_review_below)
    metadata = {
        "group_id": group.group_id,
        "group_hash": group.group_hash,
        "action": action,
        "size_bytes": int(row["size"]),
    }

    if action in {"REVIEW", "MARK-REVIEW"}:
        return Operation.create(
            "review",
            path,
            None,
            "Manual review requested",
            confidence=0.5,
            sources=["override"],
            status="review",
            metadata=metadata,
        )

    if action == "DELETE":
        return Operation.create(
            "delete",
            path,
            None,
            reason,
            confidence=confidence,
            sources=sources,
            status=status,
            metadata=metadata,
        )

    if action == "MOVE":
        if dupe_dir is None:
            return Operation.create(
                "review",
                path,
                None,
                "Move requested but dupe dir not set",
                confidence=0.4,
                sources=["override"],
                status="review",
                metadata=metadata,
            )
        destination = dupe_dir / path.name
        return Operation.create(
            "move",
            path,
            destination,
            reason,
            confidence=confidence,
            sources=sources,
            status=status,
            metadata=metadata,
        )

    if action == "RENAME":
        tags = read_tags(path)
        if not template:
            return Operation.create(
                "review",
                path,
                None,
                "Rename requested but template missing",
                confidence=0.4,
                sources=["override"],
                status="review",
                metadata=metadata,
            )
        new_relative = render_layout(template, tags)
        new_path = path.parent / new_relative
        rename_confidence = 0.8
        status = _status_for_confidence(rename_confidence, auto_accept_above, require_review_below)
        return Operation.create(
            "rename",
            path,
            new_path,
            f"Rename by override template (confidence {rename_confidence:.2f})",
            confidence=rename_confidence,
            sources=["override", "tags"],
            status=status,
            metadata={**metadata, "template": template},
        )
    return None


def _merge_summary(target: dict[str, int], update: dict[str, int]) -> None:
    for key, value in update.items():
        target[key] = target.get(key, 0) + int(value)


def _apply_summary_for_op(summary: dict[str, int], op: Operation, row) -> None:
    if op.op_type == "delete":
        summary["delete"] = summary.get("delete", 0) + 1
        summary["estimated_reclaim_bytes"] = summary.get("estimated_reclaim_bytes", 0) + int(
            row["size"]
        )
    elif op.op_type == "move":
        summary["move"] = summary.get("move", 0) + 1
    elif op.op_type == "rename":
        summary["rename"] = summary.get("rename", 0) + 1
    elif op.op_type == "review":
        summary["review"] = summary.get("review", 0) + 1


def _in_roots(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _root_for_path(path: Path, roots: list[Path]) -> Path | None:
    for root in roots:
        try:
            path.relative_to(root)
            return root
        except ValueError:
            continue
    return None
