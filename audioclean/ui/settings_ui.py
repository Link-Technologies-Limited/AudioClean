from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prompt_toolkit.shortcuts import (
    input_dialog,
    message_dialog,
    radiolist_dialog,
    yes_no_dialog,
)

from audioclean.core.config import Config


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label: str
    kind: str


SECTIONS: dict[str, list[SettingSpec]] = {
    "General": [
        SettingSpec("dry_run_default", "Default dry-run", "bool"),
        SettingSpec("quarantine_enabled", "Enable quarantine", "bool"),
        SettingSpec("quarantine_dir", "Quarantine directory", "path"),
        SettingSpec("default_library_path", "Default library path", "path"),
    ],
    "Duplicate Detection": [
        SettingSpec("confidence_threshold", "Confidence threshold", "float"),
        SettingSpec("preferred_codecs", "Preferred codecs", "list"),
        SettingSpec("fingerprint_required", "Fingerprint required", "bool"),
    ],
    "Metadata & Filenames": [
        SettingSpec("filename_format", "Filename format", "str"),
        SettingSpec("tags_override_filename", "Tags override filename", "bool"),
        SettingSpec("normalize_unicode", "Normalize unicode", "bool"),
    ],
    "Cover Art": [
        SettingSpec("min_art", "Minimum art resolution", "int"),
    ],
    "Trust & Sources": [
        SettingSpec("trust_order", "Trust order", "list"),
        SettingSpec("allow_network", "Allow network", "bool"),
    ],
    "Performance": [
        SettingSpec("jobs", "Parallel jobs", "int"),
        SettingSpec("show_progress", "Show progress UI", "bool"),
    ],
    "Advanced": [
        SettingSpec("db_path", "Cache database path", "path"),
        SettingSpec("journal_dir", "Journal directory", "path"),
        SettingSpec("layout_template", "Layout template", "str"),
        SettingSpec("dedupe_mode", "Dedupe mode", "str"),
        SettingSpec("dupe_dir", "Duplicate move dir", "path"),
        SettingSpec("prefer_lossless", "Prefer lossless", "bool"),
    ],
}


def run_settings_ui(config: Config) -> tuple[Config, list[tuple[str, str, str]]] | None:
    draft = copy.deepcopy(config)
    while True:
        choice = radiolist_dialog(
            title="audioclean settings",
            text="Select a section or action",
            values=_main_menu_values(),
        ).run()
        if choice is None or choice == "__exit__":
            return None

        if choice == "__discard__":
            draft = copy.deepcopy(config)
            message_dialog(title="audioclean settings", text="Changes discarded.").run()
            continue

        if choice == "__save__":
            diffs = diff_config(config, draft)
            if not diffs:
                message_dialog(title="audioclean settings", text="No changes to save.").run()
                continue
            diff_lines = ["Modified:"]
            for key, old, new in diffs:
                diff_lines.append(f"{key}: {old} -> {new}")
            message_dialog(title="audioclean settings", text="\n".join(diff_lines)).run()
            if not yes_no_dialog(title="audioclean settings", text="Save & exit?").run():
                continue
            return draft, diffs

        if choice in SECTIONS:
            _edit_section(draft, choice)
            continue
        return None


def diff_config(before: Config, after: Config) -> list[tuple[str, str, str]]:
    diffs: list[tuple[str, str, str]] = []
    for spec in _all_specs():
        key = spec.key
        before_val = getattr(before, key)
        after_val = getattr(after, key)
        if before_val != after_val:
            diffs.append((key, _value_str(before_val), _value_str(after_val)))
    return diffs


def _edit_section(config: Config, section: str) -> bool:
    specs = SECTIONS.get(section, [])
    while True:
        values = [(spec.key, f"{spec.label}: {_value_str(getattr(config, spec.key))}") for spec in specs]
        values.append(("__back__", "< Back to main menu"))
        choice = radiolist_dialog(
            title=f"Settings - {section}",
            text="Select a setting to edit",
            values=values,
        ).run()
        if choice in (None, "__back__"):
            return True
        spec = next((item for item in specs if item.key == choice), None)
        if not spec:
            return False
        if not _edit_value(config, spec):
            return False


def _edit_value(config: Config, spec: SettingSpec) -> bool:
    current = getattr(config, spec.key)
    if spec.kind == "bool":
        result = yes_no_dialog(
            title=spec.label,
            text=f"Set {spec.label}?",
        ).run()
        if result is None:
            return True
        setattr(config, spec.key, bool(result))
        if spec.key == "allow_network":
            config.no_network = not config.allow_network
        return True

    if spec.kind == "int":
        value = input_dialog(
            title=spec.label,
            text="Enter value:",
            default=str(current if current is not None else ""),
        ).run()
        if value is None:
            return True
        try:
            setattr(config, spec.key, int(value))
        except ValueError:
            message_dialog(title="Invalid value", text="Enter a valid integer.").run()
        return True

    if spec.kind == "float":
        value = input_dialog(
            title=spec.label,
            text="Enter value:",
            default=str(current if current is not None else ""),
        ).run()
        if value is None:
            return True
        try:
            setattr(config, spec.key, float(value))
        except ValueError:
            message_dialog(title="Invalid value", text="Enter a valid number.").run()
        return True

    if spec.kind == "list":
        value = input_dialog(
            title=spec.label,
            text="Enter comma-separated values:",
            default=", ".join(current) if current else "",
        ).run()
        if value is None:
            return True
        items = [item.strip() for item in value.split(",") if item.strip()]
        setattr(config, spec.key, items)
        return True

    if spec.kind == "path":
        value = input_dialog(
            title=spec.label,
            text="Enter path (leave empty to clear):",
            default=str(current) if current else "",
        ).run()
        if value is None:
            return True
        value = value.strip()
        setattr(config, spec.key, Path(value) if value else None)
        return True

    value = input_dialog(
        title=spec.label,
        text="Enter value:",
        default=str(current if current is not None else ""),
    ).run()
    if value is None:
        return True
    setattr(config, spec.key, value)
    return True


def _value_str(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "(empty)"
    if isinstance(value, Path):
        return str(value)
    if value is None:
        return "(empty)"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _all_specs() -> list[SettingSpec]:
    specs: list[SettingSpec] = []
    for items in SECTIONS.values():
        specs.extend(items)
    return specs


def _main_menu_values() -> list[tuple[str, str]]:
    values = [(name, name) for name in SECTIONS.keys()]
    values.append(("__save__", "Save & exit"))
    values.append(("__discard__", "Discard changes"))
    values.append(("__exit__", "Exit without saving"))
    return values
