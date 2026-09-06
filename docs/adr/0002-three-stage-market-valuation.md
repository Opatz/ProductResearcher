# 0002 Three-Stage Market Valuation & 10-Site LLM Research

## Status
Accepted

## Context
Initial single-prompt market evaluation lacked sufficient pricing accuracy and empirical grounding. Antiques and collectibles exhibit extreme price variances across different platforms (e.g. speculative dealer asking prices on Pamono/1stDibs vs. actual realized sales on eBay vs. local classifieds on Kleinanzeigen). Furthermore, Google does not provide a free standalone Google Lens API, and external scraping services (like SerpApi) require separate paid subscription accounts.

## Decision
We implement a three-stage market valuation and research pipeline within Prompt 2:

1. **Multimodal Visual Identification & Discovery**:
   Gemini Vision inspects all scanned object images to extract physical attributes, dimensions, materials, and fine condition defects (e.g., crack length, chips, missing parts) and generates an initial sales description. It uses Gemini's native Google Search Grounding to discover up to 10 specific product comparison URLs without requiring third-party subscriptions like SerpApi.

2. **Parallel Dedicated LLM Site Research Agents**:
   Each discovered website is inspected by a dedicated LLM scraping agent. It extracts structured data: product title, price normalized to EUR, price type (`Realized Price` vs. `Asking Price`), reference condition, and match confidence, discarding or flagging unpriced/blocked pages.

3. **Appraiser LLM Synthesis & Discrepancy Resolution**:
   A final Appraiser LLM analyzes all collected price points, eliminates outliers, strictly prioritizes realized sales over asking prices, applies calibrated condition discounts based on the user's item defects, and outputs the final estimated retail price (`geschaetzter_retail_preis_eur`) and range.

4. **Multi-Sheet Reporting**:
   All 10 evaluated reference listings are preserved row-by-row in a dedicated Excel sheet (`Marktrecherche_Webpreise`) with clickable `=HYPERLINK` formulas, while the summary retail price, range, and physical attributes/description remain front and center on `Hauptempfehlung`.

## Considered Options
- **SerpApi for Google Lens**: Rejected to avoid external subscription dependencies and extra recurring costs; native Gemini multimodal grounding achieves visual matching with the existing Google API key.
- **Pure Statistical Median/Average**: Rejected because asking prices and sold prices cannot be averaged naively without misrepresenting true market liquidity.
- **Flat Single-Sheet Excel**: Rejected in favor of a dual presentation (`Hauptempfehlung` summary + detailed `Marktrecherche_Webpreise` comparison sheet) to keep the main sheet uncluttered while providing full transparency.
