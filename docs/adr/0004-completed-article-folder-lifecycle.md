# 0004 Post-Processing Article Folder Lifecycle and Completed Archival

## Status
Accepted

## Context
When `VideoLLMPipeline` processes antique and collectible items, it ingests grouped media from `input/artikel/Artikel_<ID>/`. Previously, processed article folders remained indefinitely in `input/artikel/`.

This introduced several operational and architectural challenges:
1. **Redundant Reprocessing & Idempotency Risk**: Repeated pipeline runs or automated queue invocations without explicit `--item` flags would repeatedly re-discover and re-run already analyzed articles, generating redundant API calls, LLM token expenditure, and duplicated export records.
2. **Queue Pollution**: Operators had no immediate filesystem indicator of which articles were pending, in progress, or completed without manually cross-referencing timestamps in `output/execution_YYYY-MM-DD_HH-MM-SS/`.
3. **Failure State Ambiguity**: If an item failed midway (e.g., network timeout during web research or API rate limits), it was indistinguishable on disk from an article that finished all 4 pipeline stages.

## Decision
We implement an automatic post-processing lifecycle transition for Article Folders:

1. **Successful Execution Trigger**:
   - An Article Folder is only moved to the **Completed Folder** (`input/completed/Artikel_<ID>/`) after **all four pipeline stages** (Audio Extraction/Transcription, Visual ID Analysis, 3-Stage Market Valuation & Appraiser LLM Reconciliation, and Excel/CSV Export) have completed with `status = "SUCCESS"`.
   - If an error occurs at any intermediate stage, the Article Folder remains untouched in `input/artikel/` so that subsequent pipeline runs can naturally retry processing.

2. **Configurable Completed Directory**:
   - The destination directory is configured via `config.ini` under `[PIPELINE]` as `completed_dir = input/completed` (mapped in `PipelineSettings`).
   - The directory structure preserves the original article subfolder name (`Artikel_<ID>`), including all original media files and `sort_info.json`.

3. **Collision & Duplicate Handling**:
   - If `input/completed/Artikel_<ID>` already exists (e.g. from an earlier batch of the same item ID), a sequential duplicate index is appended: `Artikel_<ID>_1`, `Artikel_<ID>_2`, etc., preventing data loss.

4. **Loose Input Media Encapsulation**:
   - In cases where loose video and image files directly in the root of `input/artikel/` are processed without a pre-existing subfolder, they are automatically encapsulated into a new folder `input/completed/Artikel_<ID>/` upon completion.

5. **Execution Trace & Manifest Provenance**:
   - The resulting destination path in the Completed Folder and the original source path are recorded in `PipelineState`, `pipeline_trace.json`, and the batch-level `execution_manifest.json`.

## Considered Options
- **Immediate Move after Visual Analysis (Phase 1)**: Rejected because moving the folder while Phases 2-4 are still active creates race conditions and prevents clean restarts if web research or appraiser synthesis fails.
- **In-Place Marker File (.processed)**: Rejected because keeping processed folders in `input/artikel/` clutters the active working queue and requires custom filtering logic across all discovery tooling.
- **Moving Failed Items to Error Queue**: Considered, but keeping failed items in `input/artikel/` provides immediate at-least-once retry semantics without manual move-back operations.
