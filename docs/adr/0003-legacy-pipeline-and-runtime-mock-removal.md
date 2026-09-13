# 0003 Legacy Pipeline and Runtime Mock Removal

## Status
Accepted

## Context
During early development, the valuation workflow relied on a 4-step monolithic sequential prompt chain (`prompt_1_filter.txt`, `prompt_2_analysis.txt`, `prompt_3_varianten.txt`, `prompt_4_PreisSteigererBewerter.txt`) and included hardcoded mock fallback dictionaries in production services to allow execution without API access.

Following the implementation of ADR 0001 (Sequence Parsing & Lookahead Quarantine) and ADR 0002 (Three-Stage Market Valuation with 10-Site Grounded Research and Appraiser LLM), the legacy sequential prompt chain and restoration measure calculations (Prompt 4) became obsolete. Maintaining both pathways and runtime mock dictionaries created cognitive overhead, fragile state models, and bloated Excel outputs.

## Decision
1. **Sunset Legacy Sequential Prompts**:
   Remove `prompt_1_filter.txt`, `prompt_2_analysis.txt`, `prompt_3_varianten.txt`, and `prompt_4_PreisSteigererBewerter.txt`. The entire valuation pipeline is now driven by `MediaSorterService` (ADR 0001), `WebResearchService`, and `AppraiserService` (ADR 0002).

2. **Purge Production Runtime Mocks**:
   Remove the `--mock` CLI flag and all `_get_mock_*` fallback dictionaries embedded inside production services (`VideoLLMPipeline`, `WebResearchService`, `AppraiserService`). 

3. **Retain Clean Test Mocks**:
   Automated unit tests in `tests/` maintain clean `unittest.mock` / `patch` fixtures to ensure fast, deterministic, and zero-cost CI testing without requiring API keys.

4. **Two-Sheet Consolidated Excel Export**:
   Retain exactly 2 dedicated worksheets:
   - `Hauptempfehlung`: High-level valuation summary, condition analysis, dimensions, materials, and retail price estimates.
   - `Marktrecherche_Webpreise`: Itemized 10-site market comparison results with active `=HYPERLINK` formulas.
   - The legacy `Massnahmen_Bewertung` worksheet (from Prompt 4) is removed.

5. **Pruned State Models**:
   `PipelineState` and `pipeline/models.py` only retain models required by the active 3-stage pipeline.

## Consequences
- **Clean Architecture**: Eliminates dead code branches and reduces codebase surface area.
- **Predictable Exports**: Output reports are concise and directly aligned with appraiser needs.
- **Maintainable Testing**: Test suites rely on standard mocking practices rather than production branching.
