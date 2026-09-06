# 03: Multi-Sequence Lookahead Quarantine & Stream Resynchronization

**What to build:** A fault-tolerant sequence parser and quarantine engine that handles human error (such as a distracted photographer forgetting ID tags across 1, 2, or more items), isolating each unidentifiable video-delimited item into its own quarantine folder (`output/to_inspect/unassigned_seq_XX/`) and automatically resynchronizing normal article processing as soon as a valid ID tag appears on a subsequent item.

**Blocked by:** 02: Confidence-Aware ID Detection & Article Folder Assembly

**Status:** resolved

- [x] Delimits media sequences by terminating `Object Video` files (`.mp4`, `.mov`, etc.).
- [x] Quarantines unidentifiable item chunks (where no valid ID was found) to `output/to_inspect/unassigned_seq_XX/` with auto-incrementing indices.
- [x] Handles consecutive missed ID errors across multiple items by segregating each video chunk into separate `unassigned_seq_XX/` folders without crashing.
- [x] Immediately resynchronizes and resumes normal article creation upon encountering the next valid ID image in the stream.
- [x] Safely quarantines standalone videos (videos with zero preceding images) with `quarantine_reason: "video_without_images"`.
- [x] Safely quarantines trailing orphan photos (photos at end of stream with no concluding video) to `output/to_inspect/orphan_trailing_media/` with `quarantine_reason: "unclosed_sequence_no_video"`.
- [x] Unit tests verify multi-sequence distraction recovery, stream resynchronization, standalone videos, and trailing orphan media.

## Comments

Implemented in `services/sorter_service.py`:
- Added `resolve_unassigned_seq_folder_name` supporting auto-incrementing folders `unassigned_seq_01`, `unassigned_seq_02`, etc., avoiding collisions and tracking reserved folder names within active runs.
- Added `resolve_orphan_media_folder_name` resolving `orphan_trailing_media` (or `orphan_trailing_media_1` if collision occurs).
- Updated `sort_media_files` sequence parser:
  - Treats `Object Video` files (`.mp4`, `.mov`, etc.) as sequence delimiters.
  - Quarantines unidentifiable chunks (missing or unrecognized ID: "N/A", empty, null, etc.) to `output/to_inspect/unassigned_seq_XX/` with `quarantine_reason: "missing_or_unrecognized_id"`.
  - Quarantines standalone videos (zero preceding images) to `output/to_inspect/unassigned_seq_XX/` with `quarantine_reason: "video_without_images"`.
  - Quarantines trailing orphan photos (at end of stream without closing video) to `output/to_inspect/orphan_trailing_media/` with `quarantine_reason: "unclosed_sequence_no_video"`.
  - Automatically recovers and resynchronizes regular article processing (`input/artikel/Artikel_<ID>/`) as soon as the next valid ID image appears after one or more distraction sequences.
  - Generates comprehensive `sort_info.json` and `inspection_reason.json` manifests for all quarantine targets.
- Added comprehensive unit tests in `tests/test_sorter_service.py` verifying single missing ID quarantine, consecutive distraction recovery, standalone videos, trailing orphans, and mixed stream end-to-end processing. All 22 tests passing.