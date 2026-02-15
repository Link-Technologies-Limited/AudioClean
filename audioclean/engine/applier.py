from __future__ import annotations

import json
import shutil
from pathlib import Path

from audioclean.core import db as db_layer
from audioclean.core.models import Journal, Operation, Plan
from audioclean.core.reporter import Reporter


def apply_plan(
    plan: Plan,
    conn,
    reporter: Reporter,
    journal_dir: Path,
    dry_run: bool = False,
    force_low_confidence: bool = False,
    quarantine_enabled: bool = False,
    quarantine_dir: Path | None = None,
) -> Journal:
    journal_dir.mkdir(parents=True, exist_ok=True)
    journal = Journal.create(plan.plan_id)
    thresholds = plan.metadata.get("thresholds", {})
    auto_accept_above = float(thresholds.get("auto_accept_above", 0.0))
    for op in plan.operations:
        if not force_low_confidence:
            if op.status == "review":
                result = _skip_result(op, "review-required")
                journal.entries.append(result)
                continue
            if op.confidence is not None and op.confidence < auto_accept_above:
                result = _skip_result(op, "skipped-low-confidence")
                journal.entries.append(result)
                continue
        result = _apply_operation(
            op,
            dry_run,
            quarantine_enabled=quarantine_enabled,
            quarantine_dir=quarantine_dir,
            root_paths=plan.root_paths,
        )
        journal.entries.append(result)
        db_layer.record_operation(
            conn, plan.plan_id, op.op_id, op.op_type, op.path, op.new_path, result["status"]
        )
    conn.commit()
    journal_path = journal_dir / f"{journal.journal_id}.json"
    journal_path.write_text(json.dumps(journal.to_dict(), indent=2), encoding="utf-8")
    reporter.info(f"Journal: {journal_path}")
    return journal


def _apply_operation(
    op: Operation,
    dry_run: bool,
    quarantine_enabled: bool,
    quarantine_dir: Path | None,
    root_paths: list[Path],
) -> dict[str, str]:
    base = {
        "op_id": op.op_id,
        "op_type": op.op_type,
        "path": str(op.path),
        "reason": op.reason,
        "sources": op.sources,
        "confidence": op.confidence,
        "metadata": op.metadata,
    }
    if dry_run:
        return {**base, "status": "dry-run"}

    if op.op_type in {"move", "rename"}:
        if op.new_path is None:
            return {**base, "status": "skipped"}
        op.new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(op.path), str(op.new_path))
        return {
            **base,
            "status": "moved",
            "new_path": str(op.new_path),
        }
    if op.op_type == "delete":
        if quarantine_enabled and quarantine_dir:
            destination = _quarantine_target(op.path, quarantine_dir, root_paths)
            if dry_run:
                return {**base, "status": "quarantined", "new_path": str(destination)}
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(op.path), str(destination))
            return {**base, "status": "quarantined", "new_path": str(destination)}
        if dry_run:
            return {**base, "status": "dry-run"}
        op.path.unlink(missing_ok=True)
        return {**base, "status": "deleted"}
    return {**base, "status": "noop"}


def _skip_result(op: Operation, status: str) -> dict[str, str]:
    return {
        "op_id": op.op_id,
        "op_type": op.op_type,
        "path": str(op.path),
        "status": status,
        "reason": op.reason,
        "sources": op.sources,
        "confidence": op.confidence,
        "metadata": op.metadata,
    }


def undo(journal_id: str, reporter: Reporter, journal_dir: Path, dry_run: bool = False) -> None:
    journal_path = _resolve_journal_path(journal_id, journal_dir)
    payload = json.loads(journal_path.read_text(encoding="utf-8"))
    entries = list(reversed(payload.get("entries", [])))
    for entry in entries:
        status = entry.get("status")
        path = Path(entry.get("path", ""))
        new_path = Path(entry.get("new_path")) if entry.get("new_path") else None
        if status in {"moved", "quarantined"} and new_path and path.exists() is False:
            if dry_run:
                reporter.info(f"Would restore {new_path} -> {path}")
            else:
                new_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(new_path), str(path))
        elif status == "deleted":
            reporter.info(f"Cannot undo delete for {path}")
    reporter.info("Undo complete")


def _resolve_journal_path(journal_id: str, journal_dir: Path) -> Path:
    journal_dir.mkdir(parents=True, exist_ok=True)
    if journal_id == "last":
        journals = sorted(journal_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not journals:
            raise FileNotFoundError("No journal files found")
        return journals[0]
    candidate = journal_dir / f"{journal_id}.json"
    if not candidate.exists():
        raise FileNotFoundError(f"Journal not found: {journal_id}")
    return candidate


def _quarantine_target(path: Path, quarantine_dir: Path, root_paths: list[Path]) -> Path:
    for root in root_paths:
        try:
            relative = path.relative_to(root)
            return quarantine_dir / relative
        except ValueError:
            continue
    return quarantine_dir / path.name
