from __future__ import annotations

from pathlib import Path

from audioclean.core import db as db_layer
from audioclean.core.reporter import Reporter


def analyze(conn, reporter: Reporter, root: Path | None = None) -> dict[str, int]:
    files = list(db_layer.iter_files(conn))
    duplicates = db_layer.get_duplicates_by_hash(conn)
    missing_art = [row for row in files if not row["has_art"]]
    report = {
        "files_total": len(files),
        "duplicate_groups": len(duplicates),
        "duplicate_files": sum(len(group) for group in duplicates),
        "missing_art": len(missing_art),
    }
    if reporter.json_output:
        reporter.emit_json(report)
    else:
        reporter.info(f"Files: {report['files_total']}")
        reporter.info(f"Duplicate groups: {report['duplicate_groups']}")
        reporter.info(f"Missing art: {report['missing_art']}")
    return report
