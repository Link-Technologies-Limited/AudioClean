# audioclean

CLI-first music fingerprinting and metadata fixer for large libraries. Safe by default,
explainable decisions, and undoable changes.

## Status

This is a v1 scaffolding with a working scanner, cache DB, duplicate detection by hash,
basic plan/apply/undo, and a deterministic rename layout. Metadata resolution, tagging,
and album art repair are stubbed with clear extension points.

## Requirements

- Python 3.10+
- Chromaprint `fpcalc` in PATH for fingerprinting
- SQLite (bundled with Python)

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Examples

```bash
audioclean scan ~/Music --jobs 8
audioclean analyze ~/Music --json > report.json
audioclean plan ~/Music --dedupe=move --dupe-dir ~/Music/_dupes --min-art 1500 > plan.json
audioclean apply plan.json
audioclean undo last
audioclean plan ~/Music --art-only > art_plan.json
audioclean apply art_plan.json --dry-run
```

## Safety

- `scan` and `plan` never modify files.
- `apply` supports `--dry-run`.
- Every apply generates a journal JSON under `.audioclean/journal/` for undo.

## Next

See `audioclean/resolver.py`, `audioclean/tagger.py`, and `audioclean/art.py` for
extension points to integrate MusicBrainz/AcoustID and art fetching.
