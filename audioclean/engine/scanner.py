from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

from mutagen import File

from audioclean.core import db as db_layer
from audioclean.core.models import FileRecord, Fingerprint
from audioclean.core.reporter import Reporter
from audioclean.utils.fpcalc import FingerprintError, chromaprint
from audioclean.utils.hash import blake3_file
from audioclean.utils.tags import has_embedded_art


AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus"}


def discover_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for root in paths:
        if root.is_file() and root.suffix.lower() in AUDIO_EXTENSIONS:
            files.append(root)
            continue
        if not root.is_dir():
            continue
        for dirpath, _, filenames in os.walk(root):
            for filename in filenames:
                path = Path(dirpath) / filename
                if path.suffix.lower() in AUDIO_EXTENSIONS:
                    files.append(path)
    return files


def scan(paths: Iterable[Path], conn, jobs: int, reporter: Reporter) -> dict[str, int]:
    files = discover_files(paths)
    stats = {
        "files_scanned": 0,
        "fingerprints_computed": 0,
        "hashes_computed": 0,
        "errors": 0,
    }
    pending = []
    for path in files:
        existing = db_layer.get_file_by_path(conn, path)
        if existing and existing["size"] == path.stat().st_size and existing["mtime"] == path.stat().st_mtime:
            continue
        pending.append(path)

    with reporter.progress("Scanning files") as progress:
        task = progress.add_task("scan", total=len(files))
        for _ in range(len(files) - len(pending)):
            stats["files_scanned"] += 1
            progress.advance(task, 1)
        if jobs and jobs > 1:
            with ThreadPoolExecutor(max_workers=jobs) as executor:
                future_map = {executor.submit(_scan_one, path): path for path in pending}
                for future in as_completed(future_map):
                    stats["files_scanned"] += 1
                    try:
                        record, fingerprinted = future.result()
                        file_id = db_layer.upsert_file(conn, record)
                        if fingerprinted:
                            db_layer.upsert_fingerprint(
                                conn, Fingerprint(file_id=file_id, chromaprint=fingerprinted)
                            )
                            stats["fingerprints_computed"] += 1
                        stats["hashes_computed"] += 1
                    except Exception:
                        stats["errors"] += 1
                    progress.advance(task, 1)
        else:
            for path in pending:
                stats["files_scanned"] += 1
                try:
                    record, fingerprinted = _scan_one(path)
                    file_id = db_layer.upsert_file(conn, record)
                    if fingerprinted:
                        db_layer.upsert_fingerprint(
                            conn, Fingerprint(file_id=file_id, chromaprint=fingerprinted)
                        )
                        stats["fingerprints_computed"] += 1
                    stats["hashes_computed"] += 1
                except Exception:
                    stats["errors"] += 1
                progress.advance(task, 1)
    conn.commit()
    return stats


def _scan_one(path: Path) -> tuple[FileRecord, str | None]:
    stat = path.stat()
    audio = File(path)
    record = FileRecord(
        id=None,
        path=path,
        size=stat.st_size,
        mtime=stat.st_mtime,
        blake3=blake3_file(path),
        codec=audio.mime[0] if audio and audio.mime else None,
        container=audio.__class__.__name__ if audio else None,
        duration=float(audio.info.length) if audio and audio.info else None,
        bitrate=int(audio.info.bitrate) if audio and audio.info and hasattr(audio.info, "bitrate") else None,
        sample_rate=int(audio.info.sample_rate) if audio and audio.info and hasattr(audio.info, "sample_rate") else None,
        channels=int(audio.info.channels) if audio and audio.info and hasattr(audio.info, "channels") else None,
        has_art=has_embedded_art(path),
    )
    fingerprinted: str | None = None
    try:
        fingerprinted = chromaprint(path)
    except FingerprintError:
        fingerprinted = None

    return record, fingerprinted
