from __future__ import annotations

import csv
import fnmatch
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

from audioclean import __version__
from audioclean.engine.analyzer import analyze
from audioclean.engine.applier import apply_plan, undo
from audioclean.core import db as db_layer
from audioclean.core.config import (
    Config,
    config_default_toml,
    config_to_toml,
    default_config_path,
    load_config,
    parse_trust_list,
)
from audioclean.core.db import connect
from audioclean.engine.duplicates import (
    format_canonical_label,
    group_by_id,
    group_stats,
    list_duplicate_groups,
    resolve_group_actions,
)
from audioclean.engine.meta import meta_check, meta_fix, meta_report
from audioclean.core.models import Plan
from audioclean.engine.planner import plan as plan_ops
from audioclean.core.reporter import Reporter
from audioclean.engine.scanner import scan
from audioclean.utils.fs import format_bytes


app = typer.Typer(add_completion=False, no_args_is_help=True, invoke_without_command=True)
config_app = typer.Typer()
cache_app = typer.Typer()
duplicates_app = typer.Typer()
actions_app = typer.Typer(invoke_without_command=True)
group_app = typer.Typer(invoke_without_command=True)
settings_app = typer.Typer(invoke_without_command=True)
meta_app = typer.Typer()
app.add_typer(config_app, name="config")
app.add_typer(cache_app, name="cache")
app.add_typer(duplicates_app, name="duplicates")
app.add_typer(actions_app, name="actions")
app.add_typer(group_app, name="group")
app.add_typer(settings_app, name="settings")
app.add_typer(meta_app, name="meta")


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Show version and exit"),
    db_path: Optional[Path] = typer.Option(None, "--db", help="SQLite cache path"),
    config_path: Optional[Path] = typer.Option(None, "--config", help="Config file path"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress output"),
    verbose: bool = typer.Option(False, "--verbose", help="Verbose output"),
    debug: bool = typer.Option(False, "--debug", help="Debug output"),
    jobs: Optional[int] = typer.Option(None, "--jobs", help="Parallel jobs"),
    min_art: Optional[int] = typer.Option(None, "--min-art", help="Minimum art resolution"),
    trust: Optional[str] = typer.Option(None, "--trust", help="Trust order list"),
    confidence: Optional[float] = typer.Option(None, "--confidence", help="Confidence threshold"),
    no_network: bool = typer.Option(False, "--no-network", help="Disable network"),
    progress: Optional[bool] = typer.Option(
        None, "--progress/--no-progress", help="Progress UI"
    ),
):
    if version:
        typer.echo(__version__)
        raise typer.Exit()

    ctx.ensure_object(dict)
    config_path = config_path or default_config_path()
    ctx.obj["config_path"] = config_path
    ctx.obj["config"] = load_config(config_path if config_path.exists() else None)
    if db_path:
        ctx.obj["config"].db_path = db_path
    if min_art is not None:
        ctx.obj["config"].min_art = min_art
    ctx.obj["config"].trust_order = parse_trust_list(trust, ctx.obj["config"].trust_order)
    if confidence is not None:
        ctx.obj["config"].confidence_threshold = confidence
    if no_network:
        ctx.obj["config"].no_network = True
        ctx.obj["config"].allow_network = False
    ctx.obj["jobs"] = jobs if jobs is not None else ctx.obj["config"].jobs
    progress_enabled = progress if progress is not None else ctx.obj["config"].show_progress
    ctx.obj["reporter"] = Reporter(json_output=json_output, quiet=quiet, progress=progress_enabled)
    ctx.obj["verbose"] = verbose
    ctx.obj["debug"] = debug


@app.command("scan")
def scan_cmd(
    ctx: typer.Context,
    path: list[Path] = typer.Argument(None),
):
    """Scan a library and update the cache DB."""
    reporter = ctx.obj["reporter"]
    config: Config = ctx.obj["config"]
    if not path:
        if not config.default_library_path:
            reporter.info("Missing PATH. Set default_library_path in settings or pass a path.")
            raise typer.Exit(code=2)
        path = [config.default_library_path]
    conn = connect(config.db_path)
    stats = scan(path, conn, ctx.obj["jobs"], reporter)
    if reporter.json_output:
        reporter.emit_json(stats)
    else:
        reporter.info(f"Scanned {stats['files_scanned']} files")
        reporter.info(f"Fingerprints: {stats['fingerprints_computed']}")
        reporter.info(f"Hashes: {stats['hashes_computed']}")


@app.command("analyze")
def analyze_cmd(
    ctx: typer.Context,
    path: list[Path] = typer.Argument(None),
):
    """Analyze cached data and report issues."""
    reporter = ctx.obj["reporter"]
    config: Config = ctx.obj["config"]
    if not path:
        if not config.default_library_path:
            reporter.info("Missing PATH. Set default_library_path in settings or pass a path.")
            raise typer.Exit(code=2)
        path = [config.default_library_path]
    conn = connect(config.db_path)
    analyze(conn, reporter, path[0] if path else None)


@app.command("groups")
def groups_cmd(
    ctx: typer.Context,
    largest: bool = typer.Option(False, "--largest", help="Show largest groups first"),
    group_id: Optional[int] = typer.Option(None, "--group", help="Show a specific group"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Limit number of groups"),
    stats: bool = typer.Option(False, "--stats", help="Show group stats"),
):
    """List duplicate groups for review."""
    reporter = ctx.obj["reporter"]
    config: Config = ctx.obj["config"]
    conn = connect(config.db_path)
    groups = list_duplicate_groups(conn, config.prefer_lossless, sort_by="size" if largest else "hash")

    if stats:
        payload = group_stats(groups)
        if reporter.json_output:
            reporter.emit_json(payload)
            return
        reporter.info(f"Groups: {payload['groups']}")
        reporter.info(f"Avg group size: {payload['avg_group_size']:.2f}")
        reporter.info(f"Max group size: {payload['max_group_size']:.0f}")

    if group_id is not None:
        selected = group_by_id(groups, group_id)
        if not selected:
            reporter.info(f"Group {group_id} not found")
            raise typer.Exit(code=1)
        groups = [selected]

    if limit is not None:
        groups = groups[:limit]

    if reporter.json_output:
        payload = []
        for group in groups:
            if not group:
                continue
            actions = resolve_group_actions(
                group, db_layer.get_group_overrides(conn, group.group_hash), config.dedupe_mode
            )
            payload.append(
                {
                    "group_id": group.group_id,
                    "hash": group.group_hash,
                    "canonical": str(Path(group.canonical["path"])),
                    "members": [
                        {"path": str(item["path"]), "action": item["action"], "template": item["template"]}
                        for item in actions
                    ],
                }
            )
        reporter.emit_json(payload)
        return

    for group in groups:
        if not group:
            continue
        overrides = db_layer.get_group_overrides(conn, group.group_hash)
        actions = resolve_group_actions(group, overrides, config.dedupe_mode)
        reporter.info(f"Group #{group.group_id}")
        reporter.info(f"Canonical: {format_canonical_label(group.canonical)}")
        reporter.info("Members:")
        for item in actions:
            label = _format_member_label(item["path"], item["row"])
            reporter.info(f"  [{_action_label(item['action'])}] {label}")


@app.command("review")
def review_cmd(
    ctx: typer.Context,
    largest: bool = typer.Option(False, "--largest", help="Show largest groups first"),
    start: Optional[int] = typer.Option(None, "--start", help="Start review at group id"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Limit number of groups"),
):
    """Interactively review duplicate groups and set overrides."""
    reporter = ctx.obj["reporter"]
    if reporter.json_output:
        reporter.info("Interactive review is not available with --json.")
        raise typer.Exit(code=2)
    config: Config = ctx.obj["config"]
    conn = connect(config.db_path)
    groups = list_duplicate_groups(conn, config.prefer_lossless, sort_by="size" if largest else "hash")
    if start is not None:
        groups = [group for group in groups if group.group_id >= start]
    if limit is not None:
        groups = groups[:limit]
    if not groups:
        reporter.info("No duplicate groups found.")
        return

    reporter.info("Interactive review mode. Enter 'help' for commands.")
    for group in groups:
        if not _review_group_interactive(conn, reporter, config, group):
            reporter.info("Review stopped.")
            break


@duplicates_app.command("export")
def duplicates_export_cmd(
    ctx: typer.Context,
    csv_output: bool = typer.Option(False, "--csv", help="Export as CSV"),
):
    """Export duplicate groups for external review."""
    reporter = ctx.obj["reporter"]
    config: Config = ctx.obj["config"]
    conn = connect(config.db_path)
    groups = list_duplicate_groups(conn, config.prefer_lossless, sort_by="hash")

    if csv_output:
        writer = csv.writer(sys.stdout)
        writer.writerow(
            [
                "group_id",
                "hash",
                "canonical",
                "path",
                "action",
                "confidence",
            ]
        )
        for group in groups:
            overrides = db_layer.get_group_overrides(conn, group.group_hash)
            actions = resolve_group_actions(group, overrides, config.dedupe_mode)
            canonical_path = str(Path(group.canonical["path"]))
            for item in actions:
                action = item["action"]
                writer.writerow(
                    [
                        group.group_id,
                        group.group_hash,
                        canonical_path,
                        str(item["path"]),
                        action,
                        _action_confidence(action),
                    ]
                )
        return

    payload = []
    for group in groups:
        overrides = db_layer.get_group_overrides(conn, group.group_hash)
        actions = resolve_group_actions(group, overrides, config.dedupe_mode)
        payload.append(
            {
                "group_id": group.group_id,
                "fingerprint": group.group_hash,
                "canonical": str(Path(group.canonical["path"])),
                "files": [
                    {
                        "path": str(item["path"]),
                        "action": item["action"],
                        "confidence": _action_confidence(item["action"]),
                    }
                    for item in actions
                ],
            }
        )
    typer.echo(json.dumps(payload, indent=2))


@app.command("plan")
def plan_cmd(
    ctx: typer.Context,
    path: list[Path] = typer.Argument(None),
    dedupe: str = typer.Option("move", "--dedupe", help="off|move|delete"),
    dupe_dir: Optional[Path] = typer.Option(None, "--dupe-dir", help="Duplicate move dir"),
    layout: Optional[str] = typer.Option(None, "--layout", help="Layout template"),
    art_only: bool = typer.Option(False, "--art-only", help="Only plan art fixes"),
    summary_only: bool = typer.Option(False, "--summary-only", help="Show summary only"),
    out_path: Optional[Path] = typer.Option(None, "--out", help="Write plan JSON to file"),
    auto_accept_above: float = typer.Option(0.90, "--auto-accept-above", help="Auto-accept threshold"),
    require_review_below: float = typer.Option(0.75, "--require-review-below", help="Review threshold"),
):
    """Generate an operations plan (JSON) without applying."""
    reporter = ctx.obj["reporter"]
    ui_reporter = Reporter(
        json_output=False,
        quiet=reporter.quiet or reporter.json_output,
        progress=reporter.progress_enabled,
        stderr=True,
    )
    config: Config = ctx.obj["config"]
    if not path:
        if not config.default_library_path:
            reporter.info("Missing PATH. Set default_library_path in settings or pass a path.")
            raise typer.Exit(code=2)
        path = [config.default_library_path]
    conn = connect(config.db_path)
    layout_template = layout or config.layout_template
    plan_obj = plan_ops(
        root_paths=path,
        conn=conn,
        reporter=ui_reporter,
        config=config,
        dedupe_mode=dedupe,
        dupe_dir=dupe_dir,
        layout=layout_template,
        art_only=art_only,
        confidence_threshold=config.confidence_threshold,
        auto_accept_above=auto_accept_above,
        require_review_below=require_review_below,
    )
    summary = plan_obj.metadata.get("summary", {})
    summary_payload = {
        "duplicate_groups": summary.get("duplicate_groups", 0),
        "delete": summary.get("delete", 0),
        "move": summary.get("move", 0),
        "rename": summary.get("rename", 0),
        "review": summary.get("review", 0),
        "art_fetches": summary.get("art_fetches", 0),
        "tag_updates": summary.get("tag_updates", 0),
        "estimated_reclaim_bytes": summary.get("estimated_reclaim_bytes", 0),
        "plan_id": plan_obj.plan_id,
    }

    emit_plan_to_stdout = out_path is None and not summary_only
    if out_path:
        out_path.write_text(plan_obj.to_json(), encoding="utf-8")
    elif not summary_only:
        typer.echo(plan_obj.to_json())

    if summary_only or not emit_plan_to_stdout:
        if reporter.json_output:
            typer.echo(json.dumps(summary_payload, indent=2))
        elif not reporter.quiet:
            _emit_plan_summary(summary_payload, out_path)
    else:
        summary_reporter = Reporter(progress=False, stderr=True)
        _emit_plan_summary(summary_payload, out_path, reporter=summary_reporter)


@app.command("apply")
def apply_cmd(
    ctx: typer.Context,
    plan_path: Path = typer.Argument(..., exists=True, readable=True),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate apply"),
    force_low_confidence: bool = typer.Option(
        False, "--force-low-confidence", help="Apply low-confidence actions"
    ),
    quarantine: Optional[Path] = typer.Option(
        None, "--quarantine", help="Move deletes into quarantine directory"
    ),
    no_quarantine: bool = typer.Option(False, "--no-quarantine", help="Disable quarantine"),
):
    """Apply a plan with journaling."""
    reporter = ctx.obj["reporter"]
    config: Config = ctx.obj["config"]
    conn = connect(config.db_path)
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    plan = Plan.from_dict(payload)
    quarantine_enabled = config.quarantine_enabled
    quarantine_dir = config.quarantine_dir
    if no_quarantine:
        quarantine_enabled = False
    if quarantine:
        quarantine_enabled = True
        quarantine_dir = quarantine
    apply_plan(
        plan,
        conn,
        reporter,
        config.journal_dir,
        dry_run=dry_run,
        force_low_confidence=force_low_confidence,
        quarantine_enabled=quarantine_enabled,
        quarantine_dir=quarantine_dir,
    )


@app.command("undo")
def undo_cmd(
    ctx: typer.Context,
    journal_id: str = typer.Argument(..., help="Journal id or 'last'"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate undo"),
):
    """Undo a previous apply using the journal."""
    reporter = ctx.obj["reporter"]
    config: Config = ctx.obj["config"]
    undo(journal_id, reporter, config.journal_dir, dry_run=dry_run)


@app.command("doctor")
def doctor(ctx: typer.Context):
    """Validate dependencies and config."""
    reporter = ctx.obj["reporter"]
    config: Config = ctx.obj["config"]
    issues = []
    try:
        import subprocess

        result = subprocess.run(["fpcalc", "-version"], capture_output=True, text=True)
        if result.returncode != 0:
            issues.append("fpcalc not available")
    except FileNotFoundError:
        issues.append("fpcalc not found in PATH")
    try:
        import prompt_toolkit  # noqa: F401
    except ImportError:
        issues.append("prompt_toolkit not installed (settings UI unavailable)")

    if reporter.json_output:
        reporter.emit_json({"issues": issues, "db_path": str(config.db_path)})
    else:
        if issues:
            reporter.info("Issues detected:")
            for issue in issues:
                reporter.info(f"- {issue}")
        else:
            reporter.info("All dependencies look good")


@app.command("about")
def about(ctx: typer.Context):
    """Show version and runtime info."""
    reporter = ctx.obj["reporter"]
    config: Config = ctx.obj["config"]
    payload = {
        "name": "audioclean",
        "version": __version__,
        "python": sys.version.split()[0],
        "config_path": str(ctx.obj.get("config_path") or ""),
        "db_path": str(config.db_path),
        "journal_dir": str(config.journal_dir),
    }
    if reporter.json_output:
        reporter.emit_json(payload)
        return
    reporter.info(f"audioclean {payload['version']}")
    reporter.info(f"Python {payload['python']}")
    reporter.info(f"Config: {payload['config_path']}")
    reporter.info(f"DB: {payload['db_path']}")
    reporter.info(f"Journal: {payload['journal_dir']}")


@actions_app.callback(invoke_without_command=True)
def actions_root(
    ctx: typer.Context,
    plan_path: Optional[Path] = typer.Argument(None, help="Plan JSON path"),
):
    """Inspect planned actions without applying."""
    reporter = ctx.obj["reporter"]
    plan = _load_plan(plan_path, reporter)
    ctx.obj["plan"] = plan
    if ctx.invoked_subcommand:
        return
    summary = _summarize_actions(plan)
    if reporter.json_output:
        reporter.emit_json(summary)
        return
    reporter.info("Planned actions:")
    reporter.info(f"Delete: {summary['delete']} files")
    reporter.info(f"Rename: {summary['rename']} files")
    reporter.info(f"Tag updates: {summary['tag_updates']} files")
    reporter.info(f"Album art embeds: {summary['art_fetches']} albums")
    reporter.info(f"Manual review needed: {summary['review']} tracks")


@actions_app.command("delete")
def actions_delete(ctx: typer.Context):
    """List delete actions."""
    plan = ctx.obj.get("plan") or _load_plan(None, ctx.obj["reporter"])
    ops = [op for op in plan.operations if op.op_type == "delete"]
    _emit_action_list(ctx.obj["reporter"], ops)


@actions_app.command("rename")
def actions_rename(ctx: typer.Context):
    """List rename actions."""
    plan = ctx.obj.get("plan") or _load_plan(None, ctx.obj["reporter"])
    ops = [op for op in plan.operations if op.op_type == "rename"]
    _emit_action_list(ctx.obj["reporter"], ops)


@actions_app.command("review")
def actions_review(ctx: typer.Context):
    """List review-required actions."""
    plan = ctx.obj.get("plan") or _load_plan(None, ctx.obj["reporter"])
    ops = [op for op in plan.operations if op.status == "review" or op.op_type == "review"]
    _emit_action_list(ctx.obj["reporter"], ops)


@config_app.command("init")
def config_init(path: Optional[Path] = typer.Argument(None)):
    """Create a default config file."""
    target = path or default_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(config_default_toml(), encoding="utf-8")
    typer.echo(f"Wrote {target}")


@cache_app.command("stats")
def cache_stats(ctx: typer.Context):
    """Show cache DB statistics."""
    reporter = ctx.obj["reporter"]
    config: Config = ctx.obj["config"]
    conn = connect(config.db_path)
    files = conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"]
    fingerprints = conn.execute("SELECT COUNT(*) AS c FROM fingerprints").fetchone()["c"]
    if reporter.json_output:
        reporter.emit_json({"files": files, "fingerprints": fingerprints, "db": str(config.db_path)})
    else:
        reporter.info(f"DB: {config.db_path}")
        reporter.info(f"Files: {files}")
        reporter.info(f"Fingerprints: {fingerprints}")


@settings_app.callback(invoke_without_command=True)
def settings_root(ctx: typer.Context):
    """Interactive settings editor."""
    if ctx.invoked_subcommand:
        return
    reporter = ctx.obj["reporter"]
    if reporter.json_output:
        reporter.info("Settings UI is not available with --json.")
        raise typer.Exit(code=2)
    try:
        from audioclean.ui.settings_ui import diff_config, run_settings_ui
    except ImportError:
        reporter.info("prompt_toolkit not installed; settings UI unavailable.")
        raise typer.Exit(code=1)
    config: Config = ctx.obj["config"]
    updated = run_settings_ui(config)
    if updated is None:
        reporter.info("Settings unchanged.")
        _clear_terminal()
        return
    new_config, diffs = updated
    if diffs:
        reporter.info("Modified:")
        for key, old, new in diffs:
            reporter.info(f"  {key}: {old} -> {new}")
    target = ctx.obj.get("config_path") or default_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(config_to_toml(new_config), encoding="utf-8")
    reporter.info(f"Saved settings to {target}")
    _clear_terminal()


@settings_app.command("reset")
def settings_reset(ctx: typer.Context):
    """Reset config to defaults."""
    reporter = ctx.obj["reporter"]
    target = ctx.obj.get("config_path") or default_config_path()
    if not typer.confirm(f"Reset settings at {target}?", default=False):
        reporter.info("Reset canceled.")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(config_default_toml(), encoding="utf-8")
    reporter.info(f"Reset settings at {target}")


@settings_app.command("export")
def settings_export(
    ctx: typer.Context,
    out_path: Path = typer.Argument(..., help="Export settings to file"),
):
    """Export current settings to a TOML file."""
    config: Config = ctx.obj["config"]
    out_path.write_text(config_to_toml(config), encoding="utf-8")
    ctx.obj["reporter"].info(f"Exported settings to {out_path}")


@settings_app.command("import")
def settings_import(
    ctx: typer.Context,
    in_path: Path = typer.Argument(..., exists=True, readable=True),
):
    """Import settings from a TOML file."""
    reporter = ctx.obj["reporter"]
    target = ctx.obj.get("config_path") or default_config_path()
    if not typer.confirm(f"Import settings from {in_path} to {target}?", default=False):
        reporter.info("Import canceled.")
        return
    config = load_config(in_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(config_to_toml(config), encoding="utf-8")
    reporter.info(f"Imported settings to {target}")


@meta_app.command("check")
def meta_check_cmd(
    ctx: typer.Context,
    path: list[Path] = typer.Argument(None),
    format_str: Optional[str] = typer.Option(None, "--format", help="Filename format"),
):
    """Check filename vs metadata mismatches."""
    reporter = ctx.obj["reporter"]
    config: Config = ctx.obj["config"]
    if not path:
        if not config.default_library_path:
            reporter.info("Missing PATH. Set default_library_path in settings or pass a path.")
            raise typer.Exit(code=2)
        path = [config.default_library_path]
    format_str = format_str or config.filename_format
    meta_check(path, format_str, config, reporter)


@meta_app.command("fix")
def meta_fix_cmd(
    ctx: typer.Context,
    path: list[Path] = typer.Argument(None),
    format_str: Optional[str] = typer.Option(None, "--format", help="Filename format"),
    dry_run: Optional[bool] = typer.Option(
        None, "--dry-run/--no-dry-run", help="Simulate apply"
    ),
    force: bool = typer.Option(False, "--force", help="Apply even below confidence threshold"),
):
    """Fix filenames based on metadata."""
    reporter = ctx.obj["reporter"]
    config: Config = ctx.obj["config"]
    if not path:
        if not config.default_library_path:
            reporter.info("Missing PATH. Set default_library_path in settings or pass a path.")
            raise typer.Exit(code=2)
        path = [config.default_library_path]
    format_str = format_str or config.filename_format
    use_dry_run = dry_run if dry_run is not None else config.dry_run_default
    if not use_dry_run:
        if not typer.confirm("Apply filename fixes?", default=False):
            reporter.info("Meta fix canceled.")
            raise typer.Exit(code=1)
    meta_fix(path, format_str, config, reporter, dry_run=use_dry_run, force=force)


@meta_app.command("report")
def meta_report_cmd(
    ctx: typer.Context,
    out_path: Path = typer.Argument(..., help="Report output path"),
    path: list[Path] = typer.Argument(None),
    format_str: Optional[str] = typer.Option(None, "--format", help="Filename format"),
):
    """Write a report of metadata issues."""
    reporter = ctx.obj["reporter"]
    config: Config = ctx.obj["config"]
    if not path:
        if not config.default_library_path:
            reporter.info("Missing PATH. Set default_library_path in settings or pass a path.")
            raise typer.Exit(code=2)
        path = [config.default_library_path]
    format_str = format_str or config.filename_format
    meta_report(path, format_str, config, reporter, out_path)


def _emit_plan_summary(summary: dict, out_path: Optional[Path], reporter: Reporter | None = None) -> None:
    reporter = reporter or Reporter()
    reporter.info(f"Duplicate groups analyzed: {summary.get('duplicate_groups', 0)}")
    reporter.info(f"Files to delete: {summary.get('delete', 0)}")
    reporter.info(f"Files to rename: {summary.get('rename', 0)}")
    reporter.info(f"Files needing manual review: {summary.get('review', 0)}")
    reporter.info(f"Albums missing art: {summary.get('art_fetches', 0)}")
    reclaimed = format_bytes(int(summary.get("estimated_reclaim_bytes", 0)))
    reporter.info(f"Estimated space reclaimed: ~{reclaimed}")
    if out_path:
        reporter.info(f"Plan written to {out_path}")
    else:
        reporter.info("Plan emitted to stdout")


def _load_plan(plan_path: Optional[Path], reporter: Reporter) -> Plan:
    plan_path = plan_path or Path("plan.json")
    if not plan_path.exists():
        reporter.info(f"Plan not found: {plan_path}")
        raise typer.Exit(code=1)
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    return Plan.from_dict(payload)


def _summarize_actions(plan: Plan) -> dict[str, int]:
    summary = {
        "delete": 0,
        "rename": 0,
        "tag_updates": 0,
        "art_fetches": 0,
        "review": 0,
    }
    for op in plan.operations:
        if op.op_type == "delete":
            summary["delete"] += 1
        elif op.op_type == "rename":
            summary["rename"] += 1
        elif op.op_type == "tag_update":
            summary["tag_updates"] += 1
        elif op.op_type == "art_fetch":
            summary["art_fetches"] += 1
        if op.status == "review" or op.op_type == "review":
            summary["review"] += 1
    return summary


def _emit_action_list(reporter: Reporter, ops: list) -> None:
    if reporter.json_output:
        reporter.emit_json(
            [
                {
                    "path": str(op.path),
                    "new_path": str(op.new_path) if op.new_path else None,
                    "reason": op.reason,
                    "confidence": op.confidence,
                    "sources": op.sources,
                    "status": op.status,
                    "op_type": op.op_type,
                }
                for op in ops
            ]
        )
        return
    for op in ops:
        path = str(op.path)
        if op.new_path:
            path = f"{path} -> {op.new_path}"
        confidence = f"{op.confidence:.2f}" if op.confidence is not None else "n/a"
        sources = ", ".join(op.sources) if op.sources else "unknown"
        reporter.info(f"{path} | {op.reason} | confidence {confidence} | sources {sources}")


def _action_label(action: str) -> str:
    labels = {
        "KEEP": "KEEP",
        "DELETE": "DEL ",
        "MOVE": "MOVE",
        "RENAME": "REN ",
        "SKIP": "SKIP",
        "REVIEW": "REVI",
        "MARK-REVIEW": "REVI",
    }
    return labels.get(action.upper(), action.upper()[:4])


def _action_confidence(action: str) -> float:
    action = action.upper()
    if action == "KEEP":
        return 1.0
    if action in {"DELETE", "MOVE"}:
        return 0.99
    if action == "RENAME":
        return 0.8
    if action in {"REVIEW", "MARK-REVIEW"}:
        return 0.5
    return 0.0


def _format_member_label(path: Path, row) -> str:
    ext = path.suffix.lower()
    bitrate = row["bitrate"] or 0
    descriptor = "lossless" if ext in {".flac", ".wav"} else f"{bitrate} kbps" if bitrate else "unknown"
    return f"{path.name} ({descriptor})"


def _apply_group_override(
    ctx: typer.Context,
    action: str,
    pattern: str,
    template: str | None = None,
) -> None:
    reporter = ctx.obj["reporter"]
    config: Config = ctx.obj["config"]
    group_id = ctx.obj.get("group_id")
    conn = connect(config.db_path)
    groups = list_duplicate_groups(conn, config.prefer_lossless, sort_by="hash")
    group = group_by_id(groups, group_id)
    if not group:
        reporter.info(f"Group {group_id} not found")
        raise typer.Exit(code=1)

    matches = _match_group_members(group, pattern)
    if not matches:
        reporter.info(f"No files matched pattern: {pattern}")
        raise typer.Exit(code=1)

    timestamp = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    for path in matches:
        db_layer.upsert_group_override(
            conn, group.group_hash, path, action, template, timestamp
        )
    conn.commit()
    reporter.info(f"Override set: {action} for {len(matches)} file(s)")


def _match_group_members(group, pattern: str) -> list[Path]:
    matches: list[Path] = []
    for member in group.members:
        path = Path(member["path"])
        if fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(str(path), pattern):
            matches.append(path)
    return matches


@group_app.callback(invoke_without_command=True)
def group_root(
    ctx: typer.Context,
    group_id: int = typer.Argument(..., help="Duplicate group id"),
):
    """Inspect or override a duplicate group."""
    ctx.obj["group_id"] = group_id
    if ctx.invoked_subcommand:
        return
    reporter = ctx.obj["reporter"]
    config: Config = ctx.obj["config"]
    conn = connect(config.db_path)
    groups = list_duplicate_groups(conn, config.prefer_lossless, sort_by="hash")
    group = group_by_id(groups, group_id)
    if not group:
        reporter.info(f"Group {group_id} not found")
        raise typer.Exit(code=1)
    overrides = db_layer.get_group_overrides(conn, group.group_hash)
    actions = resolve_group_actions(group, overrides, config.dedupe_mode)
    reporter.info(f"Group #{group.group_id}")
    reporter.info(f"Canonical: {format_canonical_label(group.canonical)}")
    reporter.info("Members:")
    for item in actions:
        label = _format_member_label(item["path"], item["row"])
        reporter.info(f"  [{_action_label(item['action'])}] {label}")


@group_app.command("keep")
def group_keep(
    ctx: typer.Context,
    pattern: str = typer.Argument(..., help="File name or glob pattern"),
):
    _apply_group_override(ctx, "KEEP", pattern)


@group_app.command("delete")
def group_delete(
    ctx: typer.Context,
    pattern: str = typer.Argument(..., help="File name or glob pattern"),
):
    _apply_group_override(ctx, "DELETE", pattern)


@group_app.command("move")
def group_move(
    ctx: typer.Context,
    pattern: str = typer.Argument(..., help="File name or glob pattern"),
):
    _apply_group_override(ctx, "MOVE", pattern)


@group_app.command("rename")
def group_rename(
    ctx: typer.Context,
    pattern: str = typer.Argument(..., help="File name or glob pattern"),
    template: str = typer.Option(..., "--template", help="Rename template"),
):
    _apply_group_override(ctx, "RENAME", pattern, template=template)


@group_app.command("skip")
def group_skip(
    ctx: typer.Context,
    pattern: str = typer.Argument(..., help="File name or glob pattern"),
):
    _apply_group_override(ctx, "SKIP", pattern)


@group_app.command("mark-review")
def group_mark_review(
    ctx: typer.Context,
    pattern: str = typer.Argument(..., help="File name or glob pattern"),
):
    _apply_group_override(ctx, "MARK-REVIEW", pattern)


def _review_group_interactive(conn, reporter: Reporter, config: Config, group) -> bool:
    while True:
        overrides = db_layer.get_group_overrides(conn, group.group_hash)
        actions = resolve_group_actions(group, overrides, config.dedupe_mode)
        reporter.info("")
        reporter.info(f"Group #{group.group_id}")
        reporter.info(f"Canonical: {format_canonical_label(group.canonical)}")
        reporter.info("Members:")
        for idx, item in enumerate(actions, start=1):
            label = _format_member_label(item["path"], item["row"])
            bitrate = item["row"]["bitrate"] or 0
            duration = item["row"]["duration"] or 0
            sample_rate = item["row"]["sample_rate"] or 0
            reporter.info(
                f"  {idx:>2}. [{_action_label(item['action'])}] {label} "
                f"(bitrate {bitrate or '?'} kbps, {sample_rate or '?'} Hz, {duration:.1f}s)"
            )

        command = input("review> ").strip()
        if command in {"", "n", "next"}:
            return True
        if command in {"q", "quit"}:
            return False
        if command in {"help", "?"}:
            _emit_review_help(reporter)
            continue

        parsed = _parse_review_command(command)
        if parsed is None:
            reporter.info("Invalid command. Type 'help' for options.")
            continue

        action, target, template = parsed
        matches = _resolve_review_targets(group, target)
        if not matches:
            reporter.info(f"No matches for target: {target}")
            continue

        if action == "RENAME" and not template:
            template = input("rename template> ").strip()
            if not template:
                reporter.info("Rename cancelled (no template).")
                continue

        timestamp = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        for path in matches:
            db_layer.upsert_group_override(conn, group.group_hash, path, action, template, timestamp)
        conn.commit()
        reporter.info(f"Override set: {action} for {len(matches)} file(s)")


def _parse_review_command(command: str) -> tuple[str, str, str | None] | None:
    parts = command.split(maxsplit=2)
    if not parts:
        return None
    action_raw = parts[0].lower()
    action_map = {
        "k": "KEEP",
        "keep": "KEEP",
        "d": "DELETE",
        "delete": "DELETE",
        "m": "MOVE",
        "move": "MOVE",
        "r": "RENAME",
        "rename": "RENAME",
        "s": "SKIP",
        "skip": "SKIP",
        "review": "MARK-REVIEW",
        "mark-review": "MARK-REVIEW",
    }
    action = action_map.get(action_raw)
    if not action:
        return None
    if len(parts) < 2:
        return None
    target = parts[1]
    template = parts[2] if len(parts) > 2 else None
    return action, target, template


def _resolve_review_targets(group, target: str) -> list[Path]:
    target = target.strip()
    if target in {"*", "all"}:
        return [Path(member["path"]) for member in group.members]
    if target.isdigit():
        idx = int(target)
        if 1 <= idx <= len(group.members):
            return [Path(group.members[idx - 1]["path"])]
        return []
    return _match_group_members(group, target)


def _emit_review_help(reporter: Reporter) -> None:
    reporter.info("Commands:")
    reporter.info("  keep <n|pattern>      Keep file(s)")
    reporter.info("  delete <n|pattern>    Delete file(s)")
    reporter.info("  move <n|pattern>      Move file(s) to dupe dir")
    reporter.info("  rename <n|pattern>    Rename file(s) using a template")
    reporter.info("  skip <n|pattern>      Skip file(s)")
    reporter.info("  review <n|pattern>    Mark file(s) for review")
    reporter.info("  next                  Continue to next group")
    reporter.info("  quit                  Exit review")


def app_main():
    app()


if __name__ == "__main__":
    app_main()


def _clear_terminal() -> None:
    command = "cls" if os.name == "nt" else "clear"
    os.system(command)
