from __future__ import annotations

from pathlib import Path
from typing import Iterable

from audioclean.engine.analyzer import analyze
from audioclean.engine.applier import apply_plan, undo
from audioclean.core.config import Config, default_config_path, load_config
from audioclean.core.db import connect
from audioclean.engine.meta import collect_meta_issues, meta_fix, meta_report
from audioclean.core.models import Journal, Plan
from audioclean.engine.planner import plan as plan_ops
from audioclean.core.reporter import Reporter
from audioclean.engine.scanner import scan


class Audioclean:
    """Programmatic API for embedding audioclean in other applications."""

    def __init__(self, config: Config, config_path: Path | None = None) -> None:
        self.config = config
        self.config_path = config_path

    @classmethod
    def from_config(cls, config_path: Path | None = None) -> "Audioclean":
        config_path = config_path or default_config_path()
        config = load_config(config_path if config_path.exists() else None)
        return cls(config=config, config_path=config_path)

    def scan(self, paths: Iterable[Path], jobs: int | None = None) -> dict[str, int]:
        conn = connect(self.config.db_path)
        reporter = Reporter(quiet=True, progress=False)
        return scan(list(paths), conn, jobs or self.config.jobs, reporter)

    def analyze(self, paths: Iterable[Path]) -> dict[str, int]:
        conn = connect(self.config.db_path)
        reporter = Reporter(quiet=True, progress=False)
        root = next(iter(paths), None)
        return analyze(conn, reporter, root)

    def plan(
        self,
        paths: Iterable[Path],
        dedupe_mode: str | None = None,
        dupe_dir: Path | None = None,
        layout: str | None = None,
        art_only: bool = False,
        auto_accept_above: float = 0.90,
        require_review_below: float = 0.75,
    ) -> Plan:
        conn = connect(self.config.db_path)
        reporter = Reporter(quiet=True, progress=False)
        return plan_ops(
            root_paths=list(paths),
            conn=conn,
            reporter=reporter,
            config=self.config,
            dedupe_mode=dedupe_mode or self.config.dedupe_mode,
            dupe_dir=dupe_dir or self.config.dupe_dir,
            layout=layout or self.config.layout_template,
            art_only=art_only,
            confidence_threshold=self.config.confidence_threshold,
            auto_accept_above=auto_accept_above,
            require_review_below=require_review_below,
        )

    def apply(
        self,
        plan: Plan,
        dry_run: bool = False,
        force_low_confidence: bool = False,
        quarantine: Path | None = None,
        quarantine_enabled: bool | None = None,
    ) -> Journal:
        conn = connect(self.config.db_path)
        reporter = Reporter(quiet=True, progress=False)
        use_quarantine = self.config.quarantine_enabled if quarantine_enabled is None else quarantine_enabled
        quarantine_dir = quarantine or self.config.quarantine_dir
        return apply_plan(
            plan,
            conn,
            reporter,
            self.config.journal_dir,
            dry_run=dry_run,
            force_low_confidence=force_low_confidence,
            quarantine_enabled=use_quarantine,
            quarantine_dir=quarantine_dir,
        )

    def undo(self, journal_id: str, dry_run: bool = False) -> None:
        reporter = Reporter(quiet=True, progress=False)
        undo(journal_id, reporter, self.config.journal_dir, dry_run=dry_run)

    def meta_check(self, paths: Iterable[Path], format_str: str | None = None) -> list[dict]:
        format_str = format_str or self.config.filename_format
        issues = collect_meta_issues(paths, format_str, self.config)
        return [issue.to_dict() for issue in issues]

    def meta_fix(
        self,
        paths: Iterable[Path],
        format_str: str | None = None,
        dry_run: bool | None = None,
        force: bool = False,
    ) -> None:
        reporter = Reporter(quiet=True, progress=False)
        format_str = format_str or self.config.filename_format
        use_dry_run = dry_run if dry_run is not None else self.config.dry_run_default
        meta_fix(paths, format_str, self.config, reporter, dry_run=use_dry_run, force=force)

    def meta_report(self, paths: Iterable[Path], out_path: Path, format_str: str | None = None) -> None:
        reporter = Reporter(quiet=True, progress=False)
        format_str = format_str or self.config.filename_format
        meta_report(paths, format_str, self.config, reporter, out_path)
