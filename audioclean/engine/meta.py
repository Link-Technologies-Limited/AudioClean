from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

from audioclean.engine.applier import apply_plan
from audioclean.core.config import Config
from audioclean.core.db import connect
from audioclean.core.models import Operation, Plan
from audioclean.core.reporter import Reporter
from audioclean.engine.scanner import discover_files
from audioclean.utils.fs import sanitize_component
from audioclean.utils.tags import TagInfo, read_tags


TOKEN_PATTERN = re.compile(r"%([a-zA-Z]+)%")


@dataclass
class MetaIssue:
    path: Path
    confidence: float
    issues: list[str]
    expected: str | None = None
    actual: str | None = None

    def to_dict(self) -> dict[str, object]:
        return _issue_to_dict(self)


def meta_check(paths: Iterable[Path], format_str: str, config: Config, reporter: Reporter) -> None:
    issues = collect_meta_issues(paths, format_str, config)
    if reporter.json_output:
        reporter.emit_json([_issue_to_dict(issue) for issue in issues])
        return
    if not issues:
        reporter.info("No metadata issues found.")
        return
    for issue in issues:
        reporter.info(f"File: {issue.path}")
        for item in issue.issues:
            reporter.info(f"- {item}")
        reporter.info(f"Confidence: {issue.confidence:.2f}")


def meta_report(
    paths: Iterable[Path],
    format_str: str,
    config: Config,
    reporter: Reporter,
    out_path: Path,
) -> None:
    issues = collect_meta_issues(paths, format_str, config)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if reporter.json_output:
        payload = [_issue_to_dict(issue) for issue in issues]
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        reporter.info(f"Wrote JSON report to {out_path}")
        return

    lines = []
    for issue in issues:
        lines.append(f"File: {issue.path}")
        for item in issue.issues:
            lines.append(f"- {item}")
        lines.append(f"Confidence: {issue.confidence:.2f}")
        lines.append("")
    out_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    reporter.info(f"Wrote report to {out_path}")


def meta_fix(
    paths: Iterable[Path],
    format_str: str,
    config: Config,
    reporter: Reporter,
    dry_run: bool,
    force: bool,
) -> None:
    files = discover_files(paths)
    ops: list[Operation] = []
    skipped = 0
    for path in files:
        tags = read_tags(path)
        parsed = _parse_filename(format_str, path.stem, config)
        expected = _render_filename(format_str, tags, parsed, config)
        if not expected:
            skipped += 1
            continue
        expected_path = path.with_name(expected + path.suffix)
        if expected_path == path:
            continue
        confidence = _confidence_score(tags, parsed, expected, path.stem)
        if confidence < config.confidence_threshold and not force:
            skipped += 1
            continue
        if expected_path.exists():
            skipped += 1
            continue
        ops.append(
            Operation.create(
                "rename",
                path,
                expected_path,
                f"Meta fix rename (confidence {confidence:.2f})",
                confidence=confidence,
                sources=["metadata"],
                status="pending" if confidence >= config.confidence_threshold else "review",
                metadata={"expected": expected},
            )
        )

    summary = {
        "rename": len(ops),
        "skipped": skipped,
    }
    if reporter.json_output:
        reporter.emit_json(summary)
    else:
        reporter.info(f"Files to rename: {summary['rename']}")
        reporter.info(f"Skipped: {summary['skipped']}")

    if not ops:
        return

    plan = Plan.create(
        root_paths=list(paths),
        operations=ops,
        metadata={"summary": summary, "thresholds": {"auto_accept_above": config.confidence_threshold}},
    )
    conn = connect(config.db_path)
    apply_plan(
        plan,
        conn,
        reporter,
        config.journal_dir,
        dry_run=dry_run,
        force_low_confidence=force,
        quarantine_enabled=config.quarantine_enabled,
        quarantine_dir=config.quarantine_dir,
    )


def collect_meta_issues(paths: Iterable[Path], format_str: str, config: Config) -> list[MetaIssue]:
    issues: list[MetaIssue] = []
    for path in discover_files(paths):
        tags = read_tags(path)
        parsed = _parse_filename(format_str, path.stem, config)
        expected = _render_filename(format_str, tags, parsed, config)
        mismatch_items = []
        if not tags.artist:
            mismatch_items.append("missing artist tag")
        if not tags.title:
            mismatch_items.append("missing title tag")
        if _has_unsafe_filename(path.stem):
            mismatch_items.append("unsafe filename characters")
        if expected:
            if _normalize(expected, config) != _normalize(path.stem, config):
                mismatch_items.append(f'filename mismatch: "{path.stem}" ≠ "{expected}"')
        if parsed:
            mismatch_items.extend(_token_mismatches(tags, parsed, config))
        if mismatch_items:
            confidence = _confidence_score(tags, parsed, expected, path.stem)
            issues.append(
                MetaIssue(
                    path=path,
                    confidence=confidence,
                    issues=mismatch_items,
                    expected=expected,
                    actual=path.stem,
                )
            )
    return issues


def _parse_filename(format_str: str, filename: str, config: Config) -> dict[str, str]:
    tokens = _tokens(format_str)
    if not tokens:
        return {}
    pattern = _format_to_regex(format_str)
    match = re.match(pattern, filename, flags=re.IGNORECASE)
    if not match:
        return {}
    extracted = {key: value.strip() for key, value in match.groupdict().items() if value}
    return {key: _normalize(value, config) for key, value in extracted.items()}


def _render_filename(
    format_str: str,
    tags: TagInfo,
    fallback: dict[str, str],
    config: Config,
) -> str | None:
    tokens = _tokens(format_str)
    if not tokens:
        return None
    values = {}
    tag_map = _tag_values(tags)
    for token in tokens:
        if config.tags_override_filename:
            value = tag_map.get(token) or (fallback.get(token) if fallback else None)
        else:
            value = (fallback.get(token) if fallback else None) or tag_map.get(token)
        if not value:
            value = f"Unknown {token}"
        values[token] = value

    rendered = format_str
    for token, value in values.items():
        rendered = rendered.replace(f"%{token}%", value)
    rendered = sanitize_component(_normalize_whitespace(rendered))
    return rendered


def _token_mismatches(tags: TagInfo, parsed: dict[str, str], config: Config) -> list[str]:
    issues = []
    tag_map = _tag_values(tags)
    for token, parsed_value in parsed.items():
        tag_value = tag_map.get(token)
        if not tag_value:
            continue
        if _normalize(tag_value, config) != parsed_value:
            issues.append(f'{token} mismatch: "{tag_value}" ≠ "{parsed_value}"')
    return issues


def _confidence_score(
    tags: TagInfo,
    parsed: dict[str, str],
    expected: str | None,
    actual: str,
) -> float:
    scores = []
    tag_map = _tag_values(tags)
    for token, value in parsed.items():
        tag_value = tag_map.get(token)
        if tag_value:
            scores.append(_similarity(tag_value, value))
    if expected:
        scores.append(_similarity(expected, actual))
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def _tokens(format_str: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(format_str)]


def _format_to_regex(format_str: str) -> str:
    parts = re.split(r"(%[a-zA-Z]+%)", format_str)
    regex_parts = []
    for part in parts:
        if not part:
            continue
        if part.startswith("%") and part.endswith("%"):
            name = part.strip("%").lower()
            regex_parts.append(f"(?P<{name}>.+?)")
        else:
            escaped = re.escape(part)
            escaped = escaped.replace(r"\ ", r"\s+")
            regex_parts.append(escaped)
    return "^" + "".join(regex_parts) + "$"


def _tag_values(tags: TagInfo) -> dict[str, str]:
    return {
        "artist": tags.artist or "",
        "title": tags.title or "",
        "album": tags.album or "",
        "track": str(tags.track) if tags.track is not None else "",
        "disc": str(tags.disc) if tags.disc is not None else "",
        "year": tags.year or "",
        "albumartist": tags.album_artist or "",
    }


def _normalize(value: str, config: Config) -> str:
    if config.normalize_unicode:
        value = unicodedata.normalize("NFKC", value)
    return _normalize_whitespace(value).lower()


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.strip().split())


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left.lower(), right.lower()).ratio()


def _issue_to_dict(issue: MetaIssue) -> dict[str, object]:
    return {
        "path": str(issue.path),
        "confidence": issue.confidence,
        "issues": issue.issues,
        "expected": issue.expected,
        "actual": issue.actual,
    }


def _has_unsafe_filename(filename: str) -> bool:
    return any(ch in filename for ch in '<>:"/\\|?*')
