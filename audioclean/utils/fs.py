from __future__ import annotations

import re
from pathlib import Path

from audioclean.utils.tags import TagInfo


_INVALID_CHARS = re.compile(r'[<>:"/\\\\|?*]')
_WHITESPACE = re.compile(r"\s+")


def sanitize_component(value: str) -> str:
    value = _INVALID_CHARS.sub("_", value)
    value = _WHITESPACE.sub(" ", value).strip()
    return value


def normalize_title(title: str) -> str:
    return title.replace("feat.", "feat.").replace("Feat.", "feat.").strip()


def render_layout(template: str, tags: TagInfo) -> Path:
    payload = {
        "album_artist": tags.album_artist or tags.artist or "Unknown Artist",
        "album": tags.album or "Unknown Album",
        "year": tags.year or "0000",
        "disc": tags.disc or 1,
        "track": tags.track or 0,
        "title": normalize_title(tags.title or "Unknown Title"),
    }
    rendered = template.format(**payload)
    parts = [sanitize_component(part) for part in rendered.split("/")]
    return Path(*parts)


def format_bytes(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"
