# 05: Single-Item Re-Appraisal with Custom Keyword Hints and Session History Dropdown

**What to build:** An on-demand re-appraisal trigger allowing operators to re-run multimodal analysis for a single article from Tab 2, optionally providing custom search keyword hints (e.g. 'Meissen Schwertermarke 1880') via a modal dialog. In addition, an Execution Batch session dropdown in the header allows switching between historical execution runs (`output/execution_<timestamp>/`) without restarting the server.

**Blocked by:** 02 (Split-Screen Item Inspection, 80-Char Title Limit, and Red Validation Guardrails)

**Status:** ready-for-agent

- [ ] Modal dialog to trigger on-demand single item re-run with optional custom search keywords
- [ ] Backend endpoint `/api/reanalyze_item` executing single-item appraisal and updating master Excel
- [ ] Backend endpoint `/api/sessions` listing available historical execution batches
- [ ] Header dropdown to switch active execution batch dynamically
- [ ] Automated tests for single-item re-appraisal and session switching
