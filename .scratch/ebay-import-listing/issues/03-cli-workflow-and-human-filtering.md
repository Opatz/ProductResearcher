# Issue 03: Dedicated CLI Workflow and Filtering

Status: resolved

## Description
Expose a dedicated CLI entry point `python main.py --ebay-export` to filter reviewed items from the latest execution file or specific spreadsheet (`--ebay-file`), filter by status (`--ebay-status`), and generate both File Exchange CSV and API JSON payloads.

## Acceptance Criteria
- [x] CLI flag `--ebay-export` / `--ebay` supported in `main.py`
- [x] Supports `--ebay-file`, `--ebay-status`, and `--ebay-platform`
- [x] Detailed execution summary logged to console
