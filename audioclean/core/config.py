from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass
class Config:
    db_path: Path = Path("ac-metadata/cache.sqlite3")
    journal_dir: Path = Path("ac-metadata/journal")
    dry_run_default: bool = False
    quarantine_enabled: bool = False
    quarantine_dir: Path = Path("ac-metadata/quarantine")
    default_library_path: Path | None = None
    min_art: int = 1000
    trust_order: list[str] = field(
        default_factory=lambda: ["embedded", "musicbrainz", "acoustid"]
    )
    confidence_threshold: float = 0.85
    preferred_codecs: list[str] = field(default_factory=lambda: ["flac", "alac", "aac", "mp3"])
    fingerprint_required: bool = True
    prefer_lossless: bool = True
    allow_network: bool = True
    no_network: bool = False
    dedupe_mode: str = "move"
    dupe_dir: Path | None = None
    layout_template: str = "{album_artist}/{album} ({year})/{disc}-{track:02} {title}"
    filename_format: str = "%artist% - %title%"
    tags_override_filename: bool = True
    normalize_unicode: bool = False
    jobs: int = 4
    show_progress: bool = True


def config_default_toml() -> str:
    return (
        "db_path = 'ac-metadata/cache.sqlite3'\n"
        "journal_dir = 'ac-metadata/journal'\n"
        "dry_run_default = false\n"
        "quarantine_enabled = false\n"
        "quarantine_dir = 'ac-metadata/quarantine'\n"
        "default_library_path = ''\n"
        "min_art = 1000\n"
        "trust_order = ['embedded', 'musicbrainz', 'acoustid']\n"
        "confidence_threshold = 0.85\n"
        "preferred_codecs = ['flac', 'alac', 'aac', 'mp3']\n"
        "fingerprint_required = true\n"
        "prefer_lossless = true\n"
        "allow_network = true\n"
        "dedupe_mode = 'move'\n"
        "dupe_dir = ''\n"
        "layout_template = '{album_artist}/{album} ({year})/{disc}-{track:02} {title}'\n"
        "filename_format = '%artist% - %title%'\n"
        "tags_override_filename = true\n"
        "normalize_unicode = false\n"
        "jobs = 4\n"
        "show_progress = true\n"
    )


def load_config(path: Path | None) -> Config:
    if path is None:
        default_path = Path.home() / ".config" / "audioclean" / "config.toml"
        if default_path.exists():
            path = default_path
        else:
            return Config()

    import tomllib

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    cfg = Config()
    if "db_path" in data:
        cfg.db_path = Path(data["db_path"])
    if "journal_dir" in data:
        cfg.journal_dir = Path(data["journal_dir"])
    if "min_art" in data:
        cfg.min_art = int(data["min_art"])
    if "trust_order" in data:
        cfg.trust_order = list(data["trust_order"])
    if "confidence_threshold" in data:
        cfg.confidence_threshold = float(data["confidence_threshold"])
    if "dry_run_default" in data:
        cfg.dry_run_default = bool(data["dry_run_default"])
    if "quarantine_enabled" in data:
        cfg.quarantine_enabled = bool(data["quarantine_enabled"])
    if "quarantine_dir" in data and data["quarantine_dir"]:
        cfg.quarantine_dir = Path(data["quarantine_dir"])
    if "default_library_path" in data and data["default_library_path"]:
        cfg.default_library_path = Path(data["default_library_path"])
    if "preferred_codecs" in data:
        cfg.preferred_codecs = [str(item) for item in data["preferred_codecs"]]
    if "fingerprint_required" in data:
        cfg.fingerprint_required = bool(data["fingerprint_required"])
    if "prefer_lossless" in data:
        cfg.prefer_lossless = bool(data["prefer_lossless"])
    if "allow_network" in data:
        cfg.allow_network = bool(data["allow_network"])
        cfg.no_network = not cfg.allow_network
    if "no_network" in data:
        cfg.no_network = bool(data["no_network"])
        cfg.allow_network = not cfg.no_network
    if "dedupe_mode" in data:
        cfg.dedupe_mode = str(data["dedupe_mode"])
    if "layout_template" in data:
        cfg.layout_template = str(data["layout_template"])
    if "filename_format" in data:
        cfg.filename_format = str(data["filename_format"])
    if "tags_override_filename" in data:
        cfg.tags_override_filename = bool(data["tags_override_filename"])
    if "normalize_unicode" in data:
        cfg.normalize_unicode = bool(data["normalize_unicode"])
    if "jobs" in data:
        cfg.jobs = int(data["jobs"])
    if "show_progress" in data:
        cfg.show_progress = bool(data["show_progress"])
    if "dupe_dir" in data and data["dupe_dir"]:
        cfg.dupe_dir = Path(data["dupe_dir"])
    return cfg


def default_config_path() -> Path:
    return Path.home() / ".config" / "audioclean" / "config.toml"


def config_to_toml(cfg: Config) -> str:
    def _bool(value: bool) -> str:
        return "true" if value else "false"

    def _quote(value: str) -> str:
        escaped = value.replace("'", "\\'")
        return f"'{escaped}'"

    def _list(values: list[str]) -> str:
        return "[" + ", ".join(_quote(str(item)) for item in values) + "]"

    default_library = str(cfg.default_library_path) if cfg.default_library_path else ""
    dupe_dir = str(cfg.dupe_dir) if cfg.dupe_dir else ""
    return (
        f"db_path = {_quote(str(cfg.db_path))}\n"
        f"journal_dir = {_quote(str(cfg.journal_dir))}\n"
        f"dry_run_default = {_bool(cfg.dry_run_default)}\n"
        f"quarantine_enabled = {_bool(cfg.quarantine_enabled)}\n"
        f"quarantine_dir = {_quote(str(cfg.quarantine_dir))}\n"
        f"default_library_path = {_quote(default_library)}\n"
        f"min_art = {int(cfg.min_art)}\n"
        f"trust_order = {_list(cfg.trust_order)}\n"
        f"confidence_threshold = {float(cfg.confidence_threshold):.2f}\n"
        f"preferred_codecs = {_list(cfg.preferred_codecs)}\n"
        f"fingerprint_required = {_bool(cfg.fingerprint_required)}\n"
        f"prefer_lossless = {_bool(cfg.prefer_lossless)}\n"
        f"allow_network = {_bool(cfg.allow_network)}\n"
        f"dedupe_mode = {_quote(cfg.dedupe_mode)}\n"
        f"dupe_dir = {_quote(dupe_dir)}\n"
        f"layout_template = {_quote(cfg.layout_template)}\n"
        f"filename_format = {_quote(cfg.filename_format)}\n"
        f"tags_override_filename = {_bool(cfg.tags_override_filename)}\n"
        f"normalize_unicode = {_bool(cfg.normalize_unicode)}\n"
        f"jobs = {int(cfg.jobs)}\n"
        f"show_progress = {_bool(cfg.show_progress)}\n"
    )


def parse_trust_list(trust: str | None, default: Iterable[str]) -> list[str]:
    if not trust:
        return list(default)
    return [item.strip() for item in trust.split(",") if item.strip()]
