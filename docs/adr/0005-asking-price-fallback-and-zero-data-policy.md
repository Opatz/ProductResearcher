# 0005 Asking Price Fallback and Zero-Data Anti-Hallucination Policy

## Status
Accepted

## Context
In ADR 0002, the three-stage market valuation pipeline established strict priority for realized sale prices (`Realized Price`) over unconfirmed asking prices (`Asking Price`). In real-world operation, however, rare or niche antiques and collectibles frequently lack recent completed auction results on platforms like eBay.

When no completed sale records exist:
1. Purely relying on realized sales could lead to failed valuations or empty pricing.
2. Conversely, allowing unconstrained LLM estimations creates significant risk of hallucinating fantasy prices.
3. Active asking prices on marketplaces (e.g. eBay active listings, Kleinanzeigen, Etsy) reflect seller expectations with built-in negotiation room and potential overpricing.

## Decision
We implement a two-level priority cascading research strategy, a calibrated fallback valuation rule, and a strict zero-data policy:

1. **Priority Cascading Search in Platform Research (Stage 2)**:
   - Dedicated platform research agents (e.g. for eBay and auction archives) search primarily for completed sales (`LH_Sold=1`).
   - If no completed sales are found on the target platform, the research agent falls back within the same prompt execution to the most relevant active offering, explicitly tagging `preis_typ: "angebotspreis"`.

2. **Strict Precedence in Mixed Conditions**:
   - If both realized sales and active listings are discovered across the surveyed platforms, the Appraiser LLM (Stage 3) relies strictly on the realized sales as the primary valuation anchor. Active asking prices are not mixed into the baseline.

3. **15% Flat Safety Haircut on Asking Price Fallback**:
   - When **zero** realized sales exist across all inspected platforms, the Appraiser LLM falls back to the median of the cleaned active asking prices.
   - A flat **15% safety haircut / discount** is applied to compensate for negotiation room and seller optimism.
   - The rationale (`begruendung_preisfindung`) explicitly records: *"Fallback auf aktive Angebotspreise mit 15% Sicherheitsabschlag angewendet."*

4. **Zero-Data Anti-Hallucination Policy**:
   - If neither realized sales nor active reference listings are found across the 10 web platforms (`anzahl_gefundene_preise == 0`), the LLM is strictly prohibited from inventing or guessing prices.
   - `geschaetzter_retail_preis_eur`, `preisspanne_min_eur`, and `preisspanne_max_eur` are set to `0.0`.
   - The item is flagged with `Manuelle Begutachtung erforderlich` in the notes.

5. **Reporting Transparency**:
   - The pricing rationale and notes in the main Excel export (`Hauptempfehlung`) and JSON reports clearly document whether the valuation is anchored on realized sales, the 15% asking price fallback, or flagged for manual inspection.

## Considered Options
- **Programmatic Two-Step Network Retry**: Rejected in favor of single-prompt priority cascading to prevent doubling API latency and request volume.
- **Differentiated Per-Platform Haircut Matrix**: Deferred in favor of a universal, flat 15% safety haircut to keep valuation robust across diverse non-Asian item categories.
- **Fallback Heuristic Guessing on Zero Data**: Strictly rejected to eliminate the risk of hallucinated or fantasy prices on rare collector pieces.
