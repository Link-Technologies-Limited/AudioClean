# audioclean

CLI-first audio library cleaner focused on safe, explainable, and reversible operations.

## What It Does

- Scans libraries and stores file/fingerprint metadata in SQLite.
- Finds duplicate groups (currently hash-based).
- Generates deterministic plans for rename/move/delete operations.
- Applies plans with journaling so changes can be undone.
- Includes an interactive duplicate review flow and settings UI.

## Current Status

`1.0.0b` is a functional beta with scan/analyze/plan/apply/undo working.
Metadata resolver/tag writing/art fetch are still extension points:

- `audioclean/engine/resolver.py`
- `audioclean/engine/tagger.py`
- `audioclean/engine/art.py`

## Requirements

- Python `3.10+`
- SQLite (bundled with Python)
- Chromaprint `fpcalc` in `PATH` (for fingerprinting)

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Run a typical flow:

```bash
audioclean scan ~/Music --jobs 8
audioclean analyze ~/Music
audioclean plan ~/Music --dedupe=move --dupe-dir ~/Music/_dupes > plan.json
audioclean apply plan.json --dry-run
audioclean apply plan.json
```

Undo last apply:

```bash
audioclean undo last
```

## Common Commands

```bash
# Duplicate review
audioclean groups --largest
audioclean review --largest

# Metadata filename checks/fixes
audioclean meta check ~/Music
audioclean meta fix ~/Music --dry-run

# Settings editor
audioclean settings
```

## Safety Model

- `scan` and `plan` do not modify files.
- `apply` supports `--dry-run`.
- Every apply writes a journal into `ac-metadata/journal/`.
- `undo` replays that journal in reverse.
- Quarantine mode is supported for safer deletes.

## Project Layout

- `audioclean/commands/`: CLI command layer
- `audioclean/core/`: config, DB access, models, reporting
- `audioclean/engine/`: scan/analyze/plan/apply/meta logic
- `audioclean/api/`: Python SDK
- `audioclean/ui/`: interactive settings UI
- `audioclean/utils/`: helper utilities

## Python SDK

```python
from pathlib import Path
from audioclean import Audioclean

client = Audioclean.from_config()
client.scan([Path("/mnt/media/Music")], jobs=8)
plan = client.plan([Path("/mnt/media/Music")])
client.apply(plan, dry_run=True)
```

## Build Native Binaries (Current OS)

```bash
pip install -e .[build]
python scripts/build_binaries.py
```

Outputs:

- one-file executable in `dist/`
- release-ready binary in `release/`
  - Linux: `audioclean-linux-<arch>`
  - macOS: `audioclean-darwin-<arch>`
  - Windows: `audioclean-windows-<arch>.exe`

## Cross-Platform CI and Releases

- CI artifact build: `.github/workflows/build-binaries.yml`
- Release build + publish on `v*` tags: `.github/workflows/release.yml`

## Release Notes Template

Use this template in the GitHub Release description:

```md
## audioclean vX.Y.Z

### Highlights
- 

### Added
- 

### Changed
- 

### Fixed
- 

### Breaking Changes
- None

### Upgrade Notes
- 

### Checksums / Assets
- `audioclean-linux-x86_64`
- `audioclean-darwin-<arch>`
- `audioclean-windows-<arch>.exe`
```
