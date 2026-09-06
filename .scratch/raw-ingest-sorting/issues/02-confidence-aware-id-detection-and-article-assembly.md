# 02: Confidence-Aware ID Detection & Article Folder Assembly

**What to build:** An evaluation and assembly pipeline that sends candidate ID images to Gemini Vision OCR (`prompts/prompt_id.txt`), parses the detected article ID and OCR confidence level (`high`, `medium`, `low`), and routes media into either standard `input/artikel/Artikel_<ID>/` folders or quarantine inspection folders.

**Blocked by:** 01: Dual-Format Media Ingestion & Ordering Engine

**Status:** resolved

- [x] Executes Gemini Vision OCR using `prompts/prompt_id.txt` to extract `detected_id` and `confidence`.
- [x] Normalizes detected ID strings (removes `Artikel`, `ID`, `#` prefixes, leading zeros, and invalid path characters).
- [x] Routes high and medium confidence detections to `input/artikel/Artikel_<ID>/` (resolving duplicates to `Artikel_<ID>_1`, `Artikel_<ID>_2`).
- [x] Routes low confidence detections to `output/to_inspect/Artikel_<ID>_low_confidence/` for human review before running downstream pipelines.
- [x] Generates `sort_info.json` in created article folders containing metadata (`folder_name`, `detected_id`, `first_image_id`, `video`, `images`, `sorted_at`).
- [x] Generates `inspection_reason.json` in low-confidence quarantine folders detailing the issue and proposed ID.
- [x] Unit and mock tests verify OCR parsing, ID normalization, folder assembly, and collision resolution.

## Comments

Implemented in `services/sorter_service.py`:
- Added `detect_id_from_image` to execute Gemini Vision OCR with `prompt_id.txt` and return structured dictionary (`detected_id`, `confidence`, `visual_description`, `raw_id`, `is_valid`, `gemini_response`).
- Updated `_clean_detected_id` to strip all prefixes (`Artikel`, `ID`, `Item`, `Nr.`, `No.`, `#`, `Kennnummer`), strip leading zeros on numeric IDs (`01` -> `1`, `042` -> `42`), and sanitize invalid filesystem characters (`\/*?:"<>|`).
- Updated `resolve_target_folder_name` to accept optional `suffix` parameter for quarantine naming (`_low_confidence`) and handle collisions via sequential counters (`_1`, `_2`).
- Updated `sort_media_files` to route `high` and `medium` confidence detections to `target_artikel_dir / Artikel_<ID>` with `sort_info.json`, and `low` confidence detections to `inspect_dir / Artikel_<ID>_low_confidence` with `inspection_reason.json` and `sort_info.json`.
- Added unit tests in `tests/test_sorter_service.py` verifying ID normalization, confidence parsing, collision resolution, and high/medium vs. low confidence routing. All 17 tests passing.