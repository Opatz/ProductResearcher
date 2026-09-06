# 02: Appraiser LLM Reconciliation & Synthesis

**What to build:**
A dedicated valuation synthesis stage where the Appraiser LLM takes the structured results from the 10 independent site research queries, reconciles divergent pricing across platforms, eliminates outliers, applies calibrated condition discounts based on the user's item damage report, and produces an authoritative retail valuation.

**Blocked by:** 01: Visual Analysis & 10 Independent Site Research Prompts

**Status: resolved**

- [x] Reconciles price discrepancies across disparate platforms (e.g. Pamono/1stDibs gallery prices vs. eBay realized sales vs. Kleinanzeigen).
- [x] Strictly prioritizes verified `Realized Prices` (completed auction/sales results) over unconfirmed `Asking Prices` (active dealer offers), treating asking prices as upper speculative ceilings.
- [x] Weeds out clear outliers, reproductions, or irrelevant listings, documenting the exclusion rationale.
- [x] Evaluates the condition differentials between intact reference items and the scanned item's specific flaws (cracks, chips, missing parts), applying calibrated condition discounts.
- [x] Synthesizes and outputs:
  - `geschaetzter_retail_preis_eur` (primary recommended retail price)
  - `preisspanne_min_eur` and `preisspanne_max_eur`
  - `median_web_preis_eur` (statistical median of valid scraped prices)
  - `anzahl_gefundene_preise`
  - `begruendung_preisfindung` (transparent appraisal rationale)
  - `ausreisser_bereinigung_notiz`
- [x] Fully preserves the original sales-ready product description, physical dimensions, material, and damage protocol alongside the synthesized valuation.

## Answer

Implemented the Appraiser LLM Reconciliation & Synthesis stage (Stage 3 of Market Research Valuation) in `services/appraiser_service.py`, wired into `services/web_research_service.py` and `pipeline/orchestrator.py`, with domain model `RetailPriceSynthesis` in `pipeline/models.py`, state integration in `pipeline/state.py`, prompt template in `prompts/prompt_2_appraiser_synthesis.txt`, and comprehensive unit tests in `tests/test_appraiser_service.py`.

Key achievements:
1. **Platform Reconciliation & Realized Price Priority**: Reconciles disparate platforms (dealer galleries vs auction hammer vs classifieds), prioritizing verified `Realized Prices` as empirical market anchors while treating unconfirmed `Asking Prices` as speculative upper ceilings.
2. **Outlier Filtering & Rationale Documentation**: Excludes non-matches (`kein_treffer`), unpriced/blocked sites, and extreme dealer asking markups, documenting the full exclusion rationale in `ausreisser_bereinigung_notiz`.
3. **Calibrated Condition Discounts**: Analyzes scanned item damages/flaws (cracks, chips, scratches, stains, missing parts) against intact comparables to apply calibrated condition discounts (-15% for scratches/wear, -35% for cracks/chips, -50% for broken/defective items).
4. **Authoritative Valuation Output**: Synthesizes `geschaetzter_retail_preis_eur`, `preisspanne_min_eur`, `preisspanne_max_eur`, `median_web_preis_eur`, `anzahl_gefundene_preise`, transparent `begruendung_preisfindung`, and saves `06_retail_price_synthesis.json`.
5. **Full Catalog Preservation**: Fully preserves sales-ready product descriptions, physical dimensions, material, and damage protocols in `step2_analysis_json`.
6. **Testing**: 10 new unit tests covering all edge cases; full test suite passes (52 tests OK).

