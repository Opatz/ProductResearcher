# 04: Pipeline Orchestration & End-to-End Verification

**What to build:**
Seamless integration of the 3-stage market valuation and multi-sheet export into the main orchestrator (`VideoLLMPipeline`) and CLI (`main.py`), with complete `--mock` mode support and automated regression tests verifying the entire flow from visual scanning to the final Excel workbook.

**Blocked by:** 03: Multi-Sheet Excel Export with Clickable Hyperlinks

**Status:** resolved

- [x] Replaces the legacy monolithic Prompt 2 step in `VideoLLMPipeline.run()` with the structured 3-stage flow:
  1. Multimodal visual scan & 10 target website suggestions
  2. 10 independent site research queries
  3. Appraiser LLM reconciliation & valuation synthesis
- [x] Saves intermediate artifacts in the execution directory (`06_initial_visual_analysis.json`, `06_web_research_10_sites.json`, `06_retail_price_synthesis.json`) for full auditability.
- [x] Provides complete `--mock` mode support so the entire pipeline can execute deterministically without real network or API calls.
- [x] Adds automated test suite in `tests/test_market_valuation.py` covering:
  - Phase 1 & 2 parsing of mock site research responses into structured `Reference Listings`.
  - Appraiser LLM reconciliation verifying realized price priority and condition discounting.
  - Multi-sheet Excel export checking for `Marktrecherche_Webpreise`, `=HYPERLINK(...)` formulas, and summary columns on `Hauptempfehlung`.
- [x] Passes full pipeline execution test with zero regressions.

## Answer

Integrated and verified the complete Three-Stage Market Valuation & Research Pipeline into `pipeline/orchestrator.py` (`VideoLLMPipeline`) and `main.py`, with complete `--mock` mode support and an end-to-end regression test suite in `tests/test_market_valuation.py`.

Key achievements:
1. **Three-Stage Workflow Integration**: Replaced the legacy monolithic Prompt 2 step in `VideoLLMPipeline.run()` with the 3-stage orchestrator flow:
   - Multimodal visual scanning & 10 platform target recommendations via `WebResearchService.analyze_visual_and_suggest_targets`.
   - Concurrent 10-site independent research execution via `WebResearchService.research_all_sites_parallel`.
   - Platform reconciliation, outlier filtering, condition discounting, and valuation synthesis via `AppraiserService.synthesize_valuation`.
2. **Intermediate Artifact Auditability**: Systematically saves intermediate JSON trace files for auditing:
   - `06_initial_visual_analysis.json`
   - `06_web_research_10_sites.json`
   - `06_retail_price_synthesis.json`
   - `06_prompt_2_parsed.json`
   - `pipeline_trace.json`
3. **Deterministic Mock Mode**: Enhanced `VideoLLMPipeline` and `main.py` with complete `--mock` mode resilience, ensuring synthetic audio/video handling without FFmpeg errors or external network dependencies.
4. **Multi-Sheet Export Integration**: Generates individual item workbooks as well as batch consolidated exports containing both `Hauptempfehlung` (with augmented retail pricing metrics) and `Marktrecherche_Webpreise` (with clickable `=HYPERLINK` formulas and link styling).
5. **Comprehensive Test Suite**: Added 10 automated unit and end-to-end tests in `tests/test_market_valuation.py` covering:
   - Phase 1 & 2 parsing of mock site research responses into structured `Reference Listings`.
   - Appraiser reconciliation prioritizing realized prices over asking prices and applying calibrated condition discounts.
   - Multi-sheet Excel export checking columns and formula generation.
   - End-to-end pipeline and CLI execution in mock mode and degraded network scenarios.
6. **Zero Regressions**: Entire test suite passes cleanly (71 tests OK in `python -m unittest discover tests`).
