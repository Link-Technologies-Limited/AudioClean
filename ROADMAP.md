# AudioClean v1.1 Roadmap

This roadmap targets the current scaffold described in `README.md` and focuses on shipping a reliable metadata + artwork repair release with strong safety guarantees.

## Release Goal

Ship `v1.1.0` with:
- metadata resolution and tagging implemented end-to-end,
- album art repair implemented end-to-end,
- stronger preview/review UX before apply,
- production-grade safety via tests and undo validation.

## Milestone 1: Metadata Core

### Scope
- Implement AcoustID + MusicBrainz resolver in `audioclean/resolver.py`.
- Add deterministic confidence scoring and source attribution.
- Implement tag normalization and writes in `audioclean/tagger.py` for MP3/FLAC/M4A (via `mutagen`).
- Add strict write policy: no overwrite when confidence is below threshold.

### Deliverables
- Resolver module with pluggable providers and timeout/retry handling.
- Tagger module with format-specific adapters.
- CLI flags:
  - `--min-confidence`
  - `--provider-timeout`
  - `--provider-retries`
  - `--no-network` (offline mode)

### Acceptance Criteria
- Given known tracks, resolver returns a stable best match with confidence score and candidate list.
- Tag writes are deterministic across repeated runs (idempotent outputs).
- Low-confidence items are reported but not modified.
- `plan` output includes confidence and provenance per proposed tag change.

## Milestone 2: Album Art Pipeline

### Scope
- Implement art fetch/validate/embed logic in `audioclean/art.py`.
- Add min-resolution policy and duplicate artwork detection.
- Support both embedded art and folder art strategy.

### Deliverables
- Art provider abstraction with configurable source priority.
- Validation rules (size, mime, dimensions, corruption checks).
- CLI flags:
  - `--min-art`
  - `--art-strategy [embed|folder|both]`
  - `--art-only`

### Acceptance Criteria
- Tracks/albums with missing art receive valid artwork meeting min-resolution policy.
- Corrupt or undersized artwork is replaced only when better artwork exists.
- Existing high-quality artwork is preserved.
- `plan --art-only` produces actionable changes without metadata edits.

## Milestone 3: Reviewable Plans and Safer Apply

### Scope
- Improve plan readability with explicit before/after diffs.
- Add conflict handling for ambiguous matches.
- Allow selective acceptance/rejection before apply.

### Deliverables
- Diff-rich plan schema (tags, path renames, art updates, dedupe actions).
- Interactive review mode for ambiguous resolver results.
- Per-item include/exclude controls stored in plan JSON.

### Acceptance Criteria
- Users can inspect before/after for every mutation class.
- Ambiguous items can be resolved interactively without manual JSON edits.
- Excluded items are never touched by `apply`.
- `apply --dry-run` mirrors final action list exactly.

## Milestone 4: Duplicate Intelligence

### Scope
- Extend duplicate detection beyond file hash to acoustic similarity.
- Add "best copy" decision policy (bitrate, completeness, metadata quality).

### Deliverables
- Duplicate groups with reason codes (`hash_exact`, `fingerprint_match`, etc.).
- Configurable keep-policy (`best_quality`, `newest`, `path_priority`).
- Better duplicate reporting in `analyze` and `plan`.

### Acceptance Criteria
- Exact duplicates are detected with zero false negatives on fixture corpus.
- Near-duplicates are grouped when fingerprints match above threshold.
- Keep/discard recommendations are explainable and reproducible.

## Milestone 5: Hardening and Test Coverage

### Scope
- Build fixture corpus and regression tests for scan/plan/apply/undo.
- Add contract tests for resolver/tagger/art modules.
- Validate undo completeness and idempotency.

### Deliverables
- Test fixtures covering MP3/FLAC/M4A with real-world tag edge cases.
- CI test job (lint + unit + integration).
- Failure mode tests: network errors, partial apply, corrupted tags, invalid art.

### Acceptance Criteria
- `apply` followed by `undo` restores prior state for all tested mutation types.
- Re-running `plan` after successful `apply` yields no-op results for unchanged config.
- Core flows are covered by automated integration tests.
- No unhandled exceptions in known failure-path test scenarios.

## Cross-Cutting Non-Functional Requirements

- Safety first: all mutating commands support `--dry-run` and journaling.
- Determinism: same input + config => same plan output ordering and actions.
- Performance: large-library scans remain practical with bounded memory growth.
- Observability: structured logs and clear error reasons in JSON output.

## Suggested Timeline (6 Weeks)

1. Week 1-2: Milestone 1 (Metadata Core)
2. Week 2-3: Milestone 2 (Album Art Pipeline)
3. Week 3-4: Milestone 3 (Reviewable Plans)
4. Week 4-5: Milestone 4 (Duplicate Intelligence)
5. Week 5-6: Milestone 5 (Hardening + Tests)

## Definition of Done for v1.1.0

- Milestones 1-3 are fully complete and accepted.
- Milestone 4 is complete for hash + fingerprint grouping with documented heuristics.
- Milestone 5 integration tests cover scan/plan/apply/undo critical path.
- README updated with full examples for metadata, artwork, and conflict review flows.
- Release notes include known limitations and migration notes from `1.0.0b`.
