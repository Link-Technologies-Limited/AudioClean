from __future__ import annotations

import json
import subprocess
from pathlib import Path


class FingerprintError(RuntimeError):
    pass


def chromaprint(path: Path) -> str:
    try:
        result = subprocess.run(
            ["fpcalc", "-json", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise FingerprintError("fpcalc not found in PATH") from exc

    if result.returncode != 0:
        raise FingerprintError(result.stderr.strip() or "fpcalc failed")

    data = json.loads(result.stdout)
    fingerprint = data.get("fingerprint")
    if not fingerprint:
        raise FingerprintError("fpcalc did not return a fingerprint")
    return fingerprint
