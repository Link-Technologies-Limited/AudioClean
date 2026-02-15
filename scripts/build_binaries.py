#!/usr/bin/env python3
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
RELEASE_DIR = ROOT / "release"
ENTRYPOINT = ROOT / "audioclean" / "__main__.py"


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=ROOT, check=True)


def artifact_name() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    ext = ".exe" if system == "windows" else ""
    return f"audioclean-{system}-{machine}{ext}"


def main() -> int:
    if importlib.util.find_spec("PyInstaller") is None:
        print("PyInstaller is not installed. Run: pip install -e .[build]", file=sys.stderr)
        return 2

    pyinstaller = [sys.executable, "-m", "PyInstaller"]
    build_cmd = pyinstaller + [
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "audioclean",
        str(ENTRYPOINT),
    ]
    run(build_cmd)

    source_name = "audioclean.exe" if platform.system().lower() == "windows" else "audioclean"
    source = DIST_DIR / source_name
    if not source.exists():
        raise FileNotFoundError(f"Expected binary not found: {source}")

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    target = RELEASE_DIR / artifact_name()
    shutil.copy2(source, target)
    print(f"Built binary: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
