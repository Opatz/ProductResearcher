# 01: Dual-Format Media Ingestion & Ordering Engine

**What to build:** An ingestion engine that accepts raw media files from multiple formats (WhatsApp timestamped exports and Camera/phone sequence numbers), sorts them in strict chronological and numerical order, and normalizes target filenames by stripping superfluous prefixes (`WhatsApp Image ...` and `IMG_...`).

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] Auto-detects WhatsApp timestamp naming convention (`WhatsApp Image YYYY-MM-DD at HH.MM.SS (n)`) and extracts exact datetime and sub-index.
- [x] Auto-detects Camera/phone naming convention (`IMG_4793.mp4`, `IMG_4794.jpg`, `DSC_...`) and extracts sequential numeric index.
- [x] Sorts incoming media files deterministically based on timestamp/sequence index with EXIF/filesystem mtime fallback.
- [x] Normalizes target filenames by removing `WhatsApp <Type> ` and camera prefixes (`IMG_`, `DSC_`), producing clean names such as `2026-08-30 at 11.20.06.jpeg` and `4793.mp4`.
- [x] Unit tests verify ordering and filename standardization across mixed batches.

## Comments

Implemented in `services/sorter_service.py`:
- Added `MediaSortKey` encapsulating format detection (`WHATSAPP`, `CAMERA`, `FALLBACK`), timestamp, sub-index, camera prefix, and sequential numeric index. Supports full tuple unpacking (`dt, sub_idx, name = key`) for backward compatibility.
- Updated `_clean_target_filename` to strip WhatsApp prefixes (`WhatsApp Image `, `WhatsApp Video `, `WhatsApp Unknown `) and camera prefixes (`IMG_`, `DSC_`, `VID_`, `PIC_`), producing clean names such as `4793.mp4` and `2026-08-30 at 11.20.06.jpeg`.
- Updated `_get_chronological_key` with EXIF `DateTimeOriginal`/`DateTimeDigitized`/`DateTime` parsing and `mtime` fallback.
- Added comprehensive unit tests in `tests/test_sorter_service.py` verifying WhatsApp timestamp extraction, camera sequence sorting, EXIF fallback, filename normalization, and end-to-end sorting across mixed batches.