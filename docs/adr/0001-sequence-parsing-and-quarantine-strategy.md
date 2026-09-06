# 0001 Sequence Parsing and Quarantine Strategy

## Status
Accepted

## Context
When appraisers, catalogers, and field photographers photograph antiques and collectibles in estate sales or storage facilities, media files arrive as an unstructured stream in `input/raw/` or `input/processed/`. The incoming files originate from heterogeneous hardware and software:
1. **WhatsApp Exports**: Datetime naming conventions (`WhatsApp Image YYYY-MM-DD at HH.MM.SS (n).jpeg`).
2. **Digital Camera / Phone Dumps**: Sequential numeric indices (`IMG_4793.mp4`, `IMG_4794.jpg`, `DSC_0012.JPG`).

Furthermore, physical photo shoots in the field are prone to human lapses in focus and operational errors:
1. **Forgetting the ID Tag**: An appraiser begins inspecting an object and records photos and video without first photographing the physical ID tag or numbered lot note.
2. **Consecutive Missed Tags**: During prolonged cataloging sessions, operators can lose track and photograph 2 or 3 consecutive distinct objects without ID tags before catching their oversight.
3. **Low-Confidence / Blurry Tags**: Difficult lighting, reflective plastic sleeves, or shaky camera work produce ambiguous ID numbers that could lead to mistaken identity.
4. **Standalone Videos and Orphan Trailing Photos**: Upload interruptions or premature shutdowns leave loose video clips without preceding detail photos or trailing photos without a concluding video.

Without a structured sequence parser and fault-tolerant quarantine mechanism, a single missing ID or unexpected filename format either crashes the pipeline, halts batch ingestion, or catastrophically merges distinct physical antique items into a single corrupted article folder, wasting expensive multimodal LLM calls downstream.

## Decision
We implement a robust, video-delimited sequence parsing, confidence-based routing, and lookahead quarantine architecture centered in `MediaSorterService` and exposed via standalone CLI `python main.py --sort-raw`:

1. **Object Video as Sequence Delimiter**:
   Each antique item photoshoot naturally concludes with an **Object Video** (e.g. `.mp4`, `.mov`). The media stream is deterministically chunked such that every item sequence is bounded by its concluding video:
   `[ID Image] -> [0..N Object Images] -> [Object Video]`.

2. **Dual-Format Standardization & Chronological/Numeric Sorting**:
   - `MediaSortKey` auto-detects format types (`WHATSAPP`, `CAMERA`, `FALLBACK`).
   - WhatsApp media is sorted by exact timestamp and sub-index. Camera media is sorted by numeric sequence index. Fallbacks inspect EXIF `DateTimeOriginal` headers and filesystem `mtime`.
   - Target filenames are standardized by stripping superfluous prefixes (`WhatsApp Image ...` and `IMG_` / `DSC_`), producing uniform names such as `2026-08-30 at 11.20.06.jpeg` and `4793.mp4`.

3. **Confidence-Aware ID OCR & Routing**:
   - The candidate **ID Image** (the first image in the sequence) is submitted to Gemini Vision via `prompts/prompt_id.txt` for OCR identification.
   - The raw response is sanitized (removing prefixes like `Artikel`, `ID`, `#` and leading zeros: `01` -> `1`).
   - Routing:
     - **High / Medium Confidence**: Placed in standard **Article Folder** (`input/artikel/Artikel_<ID>/`). Collisions are auto-resolved sequentially (`Artikel_<ID>_1`, `Artikel_<ID>_2`).
     - **Low Confidence**: Isolated to quarantine in `output/to_inspect/Artikel_<ID>_low_confidence/`.
     - **Missing / Unrecognized ID**: Quarantined to `output/to_inspect/unassigned_seq_XX/`.

4. **Multi-Sequence Quarantine & Stream Resynchronization**:
   - Sequences with missing IDs are segregated into separate, auto-incrementing quarantine folders (`unassigned_seq_01`, `unassigned_seq_02`), preserving individual item integrity without mingling photos across different objects.
   - The parser maintains zero broken state across sequence delimiters: encountering a valid ID image on the very next item immediately recovers and resynchronizes regular article folder creation.

5. **Edge-Case Isolation & Manifest Provenance**:
   - Standalone videos (no preceding images) are quarantined to `unassigned_seq_XX/` with `quarantine_reason: "video_without_images"`.
   - Trailing orphan photos (at stream termination with no concluding video) are quarantined to `output/to_inspect/orphan_trailing_media/` with `quarantine_reason: "unclosed_sequence_no_video"`.
   - Every generated article and quarantine folder receives an immutable JSON manifest: `sort_info.json` for item structure and `inspection_reason.json` for human triage.

6. **Operational Tooling & Move/Copy Semantics**:
   - Standalone CLI execution via `python main.py --sort-raw` allows ingestion to run independently of downstream pipeline stages.
   - Supports `--source`, `--target`, and `--inspect` for arbitrary folder routing.
   - By default, files are **moved** (`move_files=True`) to clear `input/raw/`. Supplying `--copy` preserves source files intact.
   - Outputs a clean console summary report detailing all created article folders and quarantined items.

## Considered Options
- **Fixed Frame Count Delimitation**: Rejected because antiques require varying counts of object detail photos (hallmarks, damage, underside) depending on complexity. The concluding video provides an unambiguous physical delimiter.
- **Fail-Fast Pipeline Halting**: Rejected because a single missing ID tag in a 100-item photoshoot would abort the entire run and block hours of downstream processing. Isolating bad items into quarantine keeps the pipeline running continuously.
- **Single Flat Quarantine Dump**: Rejected because dumping media from multiple consecutive unrecognized items into a single folder commingles photos of completely different physical objects, making manual human sorting nearly impossible.
- **In-Place SD Card Renaming**: Rejected to safeguard original field photographer media from accidental file system corruption.
