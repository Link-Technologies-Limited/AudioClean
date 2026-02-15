from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mutagen import File


@dataclass
class TagInfo:
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    year: str | None = None
    track: int | None = None
    disc: int | None = None


def _first(value: object) -> str | None:
    if isinstance(value, list):
        return str(value[0]) if value else None
    if value is None:
        return None
    return str(value)


def parse_track(value: str | None) -> int | None:
    if not value:
        return None
    if "/" in value:
        value = value.split("/", 1)[0]
    try:
        return int(value)
    except ValueError:
        return None


def read_tags(path: Path) -> TagInfo:
    audio = File(path)
    if audio is None or not hasattr(audio, "tags") or audio.tags is None:
        return TagInfo()

    tags = audio.tags
    def get_any(keys: list[str]) -> str | None:
        for key in keys:
            if key in tags:
                return _first(tags[key])
        return None

    title = get_any(["TIT2", "title"])
    artist = get_any(["TPE1", "artist"])
    album = get_any(["TALB", "album"])
    album_artist = get_any(["TPE2", "albumartist", "album artist"])
    year = get_any(["TDRC", "date", "year"])
    track = parse_track(get_any(["TRCK", "tracknumber"]))
    disc = parse_track(get_any(["TPOS", "discnumber"]))

    return TagInfo(
        title=title,
        artist=artist,
        album=album,
        album_artist=album_artist,
        year=year,
        track=track,
        disc=disc,
    )


def has_embedded_art(path: Path) -> bool:
    audio = File(path)
    if audio is None or not hasattr(audio, "tags") or audio.tags is None:
        return False
    tags = audio.tags
    for key in ("APIC:", "APIC", "metadata_block_picture", "covr"):
        if key in tags:
            return True
    return False
