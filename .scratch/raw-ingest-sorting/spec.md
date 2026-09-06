# Spec: Raw Ingest Sorting, Media Standardization & Sequence Quarantine

Status: resolved

## Problem Statement

When antique appraisers and catalogers photograph items in the field, media files arrive as an unstructured stream in `input/raw/` or `input/processed/` originating from varied sources (WhatsApp exports with datetime stamps or camera/phone uploads with `IMG_XXXX` sequences).

Additionally, field photographers frequently experience momentary lapses in concentration or focus, leading to errors such as:
1. Forgetting to photograph the ID tag before photographing the object and recording the video.
2. Photographing several consecutive items without ID tags before noticing the oversight.
3. Taking blurry, low-confidence ID photos.
4. Pausing a photoshoot and leaving orphan trailing images without a concluding video, or uploading standalone video clips without preceding images.

Without an automated sequence parser and quarantine mechanism, a single tagging error or mixed filename format either crashes the pipeline, halts batch processing, or causes all subsequent items to be merged into incorrect folders or misattributed during downstream AI analysis.

## Solution

Provide a robust, standalone **Raw Ingest** sorting engine and CLI command (`python main.py --sort-raw`) that:
1. **Standardizes Media Filenames**: Auto-detects whether media comes from WhatsApp (`WhatsApp Image YYYY-MM-DD at HH.MM.SS...`) or Camera (`IMG_4793.mp4`, `IMG_4794.jpg`) and strips prefixes (`2026-08-30 at 11.20.06.jpeg` and `4793.mp4` / `4794.jpg`) while preserving strict chronological/numeric order.
2. **Parses Object Sequences**: Treats the **Object Video** as the primary sequence delimiter bounding each item (`[ID Image] -> [Object Images] -> [Object Video]`).
3. **Applies Confidence-Based Routing**: Evaluates the **ID Image** via Gemini Vision:
   - High/Medium confidence: Builds standard **Article Folder** (`input/artikel/Artikel_<ID>/`) with `sort_info.json`.
   - Low confidence: Isolates to **Inspection Folder** (`output/to_inspect/Artikel_<ID>_low_confidence/`) with `inspection_reason.json` for rapid human validation.
   - Missing/Unrecognized ID: Quarantines to **Inspection Folder** (`output/to_inspect/unassigned_seq_XX/`) with `inspection_reason.json`.
4. **Resynchronizes After Multi-Sequence Distractions**: Allows 2 or more consecutive missed IDs to be isolated into distinct `unassigned_seq_XX/` folders and instantly resynchronizes normal processing upon encountering the next valid ID image.
5. **Safeguards Edge Cases**: Quarantines standalone videos (`video_without_images`) and unclosed trailing images (`unclosed_sequence_no_video`) to `output/to_inspect/`, moving raw files by default to ensure `input/raw/` is kept clean.

## User Stories

1. As a cataloger, I want to drop raw WhatsApp media dumps into `input/raw/` and have them sorted chronologically by their WhatsApp timestamp, so that all photos and videos of an antique are grouped in the exact order they were taken.
2. As a photographer using a digital camera or phone, I want media named `IMG_4793.mp4` and `IMG_4794.jpg` to be standardized to `4793.mp4` and `4794.jpg` and sorted by sequential index, so that camera files integrate seamlessly without manual renaming.
3. As a cataloger, I want the system to automatically detect the handwritten or printed ID number from the first image in an item sequence, so that the **Article Folder** is created with the exact ID (e.g., `Artikel_42`).
4. As an operator, I want the system to handle ID collisions gracefully by creating `Artikel_<ID>_1`, `Artikel_<ID>_2`, etc., so that multiple items sharing an identifier or duplicate runs never overwrite each other.
5. As an operator, I want all successfully parsed items to include a `sort_info.json` manifest recording the detected ID, sequence number, video name, and list of image names, so that downstream pipeline stages have clear provenance.
6. As a human reviewer, I want low-confidence ID detections to be quarantined in `output/to_inspect/Artikel_<ID>_low_confidence/` with an `inspection_reason.json`, so that I can quickly verify the ID before expensive AI transcription and valuation models run.
7. As a field appraiser who forgot to take an ID tag photo for an item, I want that item to be moved into `output/to_inspect/unassigned_seq_XX/` rather than corrupting the preceding or following articles.
8. As a field appraiser who lost focus and forgot ID tags for 2 or 3 consecutive items, I want each item sequence to be quarantined in its own separate folder (`unassigned_seq_01/`, `unassigned_seq_02/`), so that I can easily identify each distinct object during manual review.
9. As a pipeline user, I want the ingestion parser to immediately resume standard processing as soon as a valid ID image appears after one or more quarantined sequences, so that a human mistake in the middle of a batch does not invalidate the rest of the run.
10. As a cataloger who uploaded a standalone video clip with no preceding photos, I want the video moved to `output/to_inspect/unassigned_seq_XX/` with reason `video_without_images`, so that no video is lost or left behind in `input/raw/`.
11. As a photographer whose upload was interrupted, leaving trailing photos without a concluding video, I want those trailing photos moved to `output/to_inspect/orphan_trailing_media/` with reason `unclosed_sequence_no_video`, so that my `input/raw/` folder is cleanly cleared.
12. As a CLI user, I want to run `python main.py --sort-raw` to organize raw media without triggering downstream pipeline steps, so that I can perform ingestion independently.
13. As a CLI user, I want `--sort-raw` to move files by default and provide a `--copy` flag when I wish to keep the source files untouched.
14. As a pipeline user, I want custom `--source`, `--target`, and `--inspect` flags on `main.py`, so that I can direct files to custom directory locations when needed.

## Implementation Decisions

- **Media Delimitation & Sequence Model**:
  - The pipeline models raw media strictly as items delimited by an **Object Video**.
  - Within each chunk:
    - First file is evaluated as the candidate **ID Image**.
    - Subsequent files before the video are classified as **Object Images**.
    - The concluding video is classified as the **Object Video**.
- **Dual-Mode Filename Normalization & Sort Keys**:
  - **WhatsApp Pattern**: Matches `WhatsApp (Image|Video|Unknown) YYYY-MM-DD at HH.MM.SS (n)`. Sort key is `(datetime, subindex, filename)`. Clean target filename strips `WhatsApp <Type> ` prefix.
  - **Camera Pattern**: Matches `(IMG_|DSC_|VID_|PIC_)?(\d+)`. Sort key is `(numeric_index, mtime, filename)`. Clean target filename strips the non-numeric prefix (e.g. `IMG_4793.mp4` -> `4793.mp4`).
  - **Fallback**: EXIF DateTimeOriginal / DateTimeDigitized -> filesystem modification time (`mtime`).
- **OCR ID Extraction & Confidence Thresholds**:
  - Uses `prompts/prompt_id.txt` via `GeminiService.execute_text_prompt(..., expect_json=True)`.
  - JSON schema expects `{"detected_id": string, "confidence": "high"|"medium"|"low", "visual_description": string}`.
  - Normalization removes prefixes (`Artikel`, `ID`, `Nr.`, `#`), leading zeros (`01` -> `1`), and illegal path characters.
  - Routing:
    - `high` / `medium` -> `input/artikel/Artikel_<ID>/`
    - `low` -> `output/to_inspect/Artikel_<ID>_low_confidence/`
    - `N/A`, empty, or unrecognized -> `output/to_inspect/unassigned_seq_XX/`
- **Quarantine & Resynchronization Architecture**:
  - Sequencer iterates through video chunks.
  - When an ID check fails or is missing, a new `unassigned_seq_XX` directory is created in `output/to_inspect/`.
  - An `inspection_reason.json` manifest is written containing `quarantine_reason`, `media_files`, `detected_first_image`, `gemini_response`, and `timestamp`.
  - The sequencer advances to the next chunk without maintaining lingering broken state, allowing immediate recovery when a valid ID image is found.
- **CLI & Module Interface**:
  - `MediaSorterService.sort_media_files(source_dir, target_artikel_dir, inspect_dir, move_files)` serves as the primary engine.
  - `main.py` exposes `--sort-raw`, `--source`, `--target`, `--inspect`, `--copy`, `--sort-only`, and `--no-sort`.

## Testing Decisions

- **Single High-Level Seam**:
  - Test external behavior directly via `MediaSorterService.sort_media_files()` and `main.py` CLI invocations against temporary file trees.
  - Tests will not mock internal helper methods (`_get_chronological_key`, `_clean_target_filename`), but verify the actual resulting directory structure, file names, and manifest contents.
- **Mocking Strategy**:
  - In unit tests, `GeminiService` will be mocked or provided via deterministic responses for `prompt_id.txt` (returning High, Medium, Low confidence, or N/A).
- **Test Matrix**:
  1. WhatsApp stream chronological sorting and prefix removal.
  2. Camera `IMG_XXXX` numeric sorting and prefix removal.
  3. High/Medium confidence happy-path ingestion (`Artikel_1/`, `sort_info.json`).
  4. Collision handling (`Artikel_1_1/`).
  5. Low confidence routing (`output/to_inspect/Artikel_1_low_confidence/`).
  6. Consecutive missing ID handling (quarantining `unassigned_seq_01/`, `unassigned_seq_02/`, followed by normal resync on `Artikel_2/`).
  7. Standalone video with no images.
  8. Trailing orphan images without closing video.
  9. Move vs. Copy file operations.

## Out of Scope

- Modifying downstream prompt analysis steps (Prompts 1-4) or transcription logic.
- Automatic interactive human triage GUI in this phase (human triage remains folder/filesystem based).
- Renaming original files in-place inside external camera memory cards.

## Further Notes

- Architecture Decision Record is maintained at `docs/adr/0001-sequence-parsing-and-quarantine-strategy.md`.
- All domain terminology aligns strictly with `CONTEXT.md`.