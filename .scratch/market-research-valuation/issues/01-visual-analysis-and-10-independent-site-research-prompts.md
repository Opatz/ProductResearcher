# 01: Visual Analysis & 10 Independent Site Research Prompts

**What to build:**
A decoupled two-phase research engine where the LLM first performs visual object analysis and suggests 10 target websites for the specific object, followed by 10 separate, independent LLM research requests (one dedicated query per website) to investigate the object on each site and extract structured pricing, listing status, condition, and links.

**Blocked by:** None (can start immediately)

**Status: resolved**

- [x] Phase 1 (Object Analysis & Target Suggestions): Multimodal LLM inspects all object images, identifies material, estimated era, marks/stamps, measures dimensions, compiles an exact damage/flaw report, drafts a complete sales-ready description, and outputs a list of 10 targeted websites suitable for this specific item.
- [x] Phase 2 (10 Independent Site Research Queries): For each of the 10 suggested websites, executes an independent, dedicated research prompt/query to investigate that specific platform for the object.
- [x] Extracts structured `Reference Listing` attributes from each of the 10 independent requests: listing title, price normalized to EUR, original currency, price type (`realisierter_verkaufspreis` vs `angebotspreis` vs `auktionsgebot`), match confidence (`exakter_treffer`, `modellvariante`, `aehnliches_objekt`), reference item condition, and canonical URL.
- [x] Gracefully handles sites that return no price, are blocked, or fail, marking their status without halting the batch or crashing the process.
- [x] Runs the 10 independent site requests concurrently via a thread pool with configurable timeout to minimize execution latency.

## Answer

Implemented the decoupled two-phase research engine in `services/web_research_service.py` with domain models in `pipeline/models.py`, state integration in `pipeline/state.py`, prompt templates in `prompts/prompt_2_visual_analysis.txt` and `prompts/prompt_2_site_research.txt`, and unit test coverage in `tests/test_web_research_service.py`.

Key achievements:
1. **Phase 1 (Visual Analysis & 10 Suggestions)**: Inspects object images, extracts physical measurements and markings, drafts market-ready descriptions, and recommends 10 target platforms tailored to the object.
2. **Phase 2 (10 Independent Site Queries)**: Dispatches independent LLM requests per platform, extracting structured `ReferenceListing` items (EUR price, original currency, price type, match confidence, condition, canonical URL).
3. **Graceful Degradation**: Catches HTTP 403, network timeouts, unpriced listings, and parse errors, setting appropriate `RechercheStatus` without halting execution.
4. **Parallel Execution**: Uses `ThreadPoolExecutor` with configurable timeout and workers to execute site queries concurrently.
5. **Testing**: 13 new unit tests covering all edge cases; full test suite passes (42 tests OK).
