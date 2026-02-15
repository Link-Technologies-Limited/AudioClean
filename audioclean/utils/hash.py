from __future__ import annotations

from pathlib import Path

from blake3 import blake3


def blake3_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    hasher = blake3()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()
