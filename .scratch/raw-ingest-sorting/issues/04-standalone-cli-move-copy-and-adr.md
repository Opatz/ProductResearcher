# 04: Standalone CLI Interface, Move/Copy Support & System ADR

**What to build:** The CLI interface and operational tooling in `main.py` enabling users to run raw media sorting independently via `python main.py --sort-raw`, with support for custom paths and move/copy file operations, alongside the formal Architecture Decision Record (ADR 0001).

**Blocked by:** 03: Multi-Sequence Lookahead Quarantine & Stream Resynchronization

**Status:** resolved

- [x] Wires `python main.py --sort-raw` with flags: `--source`, `--target`, `--inspect`, and `--copy`.
- [x] Moves files from source directory by default to ensure `input/raw/` is cleared, or copies them when `--copy` is specified.
- [x] Integrates clean console logging and summary reporting of created articles and quarantined items.
- [x] Creates Architecture Decision Record at `docs/adr/0001-sequence-parsing-and-quarantine-strategy.md`.
- [x] Complete test suite passes with full test coverage for end-to-end sorting scenarios.

## Comments

Implemented in `main.py`, `services/sorter_service.py`, and `docs/adr/`:
- Added `run_sorting_process` helper and CLI argument parsing in `main.py` supporting `--sort-raw`, `--sort-only`, `--source`, `--target`, `--inspect`, and `--copy`. Standalone sort executes and exits cleanly with return code 0 before downstream pipeline orchestration starts.
- Wired move-by-default behavior (`move_files = not args.copy`) ensuring `input/raw/` is cleared, with `--copy` preserving original files.
- Added `SortSummary` dataclass and summary logging in `services/sorter_service.py` tracking counts of standard articles, low-confidence quarantines, missing/unrecognized ID quarantines, standalone videos, and trailing orphans.
- Created formal Architecture Decision Record ADR 0001 at `docs/adr/0001-sequence-parsing-and-quarantine-strategy.md` (and `src/docs/adr/`), re-indexing the market valuation ADR to ADR 0002.
- Created dedicated integration test suite `tests/test_cli_sort_raw.py` and extended `tests/test_sorter_service.py`. All 29 unit and integration tests passing.