# Spec: Three-Stage Market Valuation, 10-Site LLM Research & Multi-Sheet Excel Reporting

Status: ready-for-agent

## Problem Statement

When antique appraisers and vintage catalogers process scanned collectibles, single-prompt LLM valuation produces imprecise and volatile price indications. Antiques exhibit extreme pricing divergence across platforms—ranging from speculative dealer asking prices that linger unsold for months, to actual realized auction hammer prices, to low-price bargains on local classifieds. 

Additionally, operators lack empirical grounding: they cannot see the underlying web sources that informed an estimate, cannot audit individual listing prices or conditions, and have no direct links to verify comparables. A simple average or unweighted prompt calculation fails because asking prices cannot be treated equally with realized sales, and differences in condition (chips, scratches, repairs on the scanned object versus pristine reference pieces) are not systematically reconciled. Furthermore, existing external image-search APIs (such as SerpApi for Google Lens) require costly separate recurring subscriptions, creating friction and dependency.

## Solution

Implement an empirical, grounded **Three-Stage Market Valuation & Research Pipeline** that leverages existing multimodal capabilities and Google Search Grounding to evaluate up to 10 comparison websites, synthesizes a reconciled retail valuation via a dedicated **Appraiser LLM**, and exports all discovered references into a structured multi-sheet Excel workbook with clickable hyperlinks:

1. **Multimodal Visual Identification & Discovery (Stage 1)**:
   - Evaluates all **Object Images** to detect maker's marks, stamps, material, period, and exact physical dimensions (height, width, length, diameter, weight).
   - Records an exhaustive damage and condition protocol (noting flaws, cracks, chips, and their dimensions/severity) and generates a complete, professional, sales-ready product description.
   - Formulates targeted visual search queries and identifies up to 10 specific product comparison URLs using native search grounding with the existing API configuration (avoiding paid third-party subscriptions).

2. **Parallel Dedicated LLM Site Research (Stage 2)**:
   - Dispatches a dedicated LLM scraping agent for each of the 10 target websites to analyze page content in parallel.
   - Normalizes and extracts structured **Reference Listings**: listing title, price converted to EUR, price classification (**Realized Price** versus **Asking Price**), match confidence, and reference object condition, gracefully marking inaccessible or unpriced pages.

3. **Appraiser LLM Synthesis & Discrepancy Reconciliation (Stage 3)**:
   - Acts as a professional market arbitrator to resolve price discrepancies between different platforms.
   - Weeds out speculative dealer outliers, enforces strict priority for verified **Realized Prices** over unconfirmed **Asking Prices**, and applies calibrated condition adjustments based on the flaws identified on the user's item.
   - Establishes a realistic retail estimate (`geschaetzter_retail_preis_eur`), plausible price range (`preisspanne_min_eur`, `preisspanne_max_eur`), statistical median, and transparent appraisal reasoning.

4. **Multi-Sheet Reporting with Clickable Hyperlinks**:
   - Generates a dedicated **Web Price Sheet** (`Marktrecherche_Webpreise`) recording all 10 evaluated reference listings row-by-row with item ID, website name, listing title, price in EUR, price type, match confidence, condition notes, and clickable Excel hyperlinks.
   - Enhances the primary summary sheet (`Hauptempfehlung`) with the estimated retail price, price range, median scraped web price, count of verified web prices, top reference links, complete physical dimensions, material, damage log, and sales-ready product description.

## User Stories

1. As an antique cataloger, I want the system to analyze all photos of an item and detect its physical dimensions, material, stamps, and specific damages, so that the object is comprehensively cataloged before pricing begins.
2. As a cataloger, I want the system to generate a complete, sales-ready product description for online marketplaces, so that I do not need to manually write descriptions for each item.
3. As an appraiser, I want the system to identify up to 10 specific candidate websites/listings matching the item using Google Search Grounding, so that the valuation is backed by real-world market evidence.
4. As a system operator, I want the visual search and discovery to use the existing Google API credentials without requiring an additional SerpApi account or subscription, so that operating costs and external dependencies remain minimal.
5. As a cataloger, I want each of the 10 candidate websites to be evaluated by a dedicated LLM research agent, so that unstructured and complex web pages are accurately interpreted for product details and prices.
6. As an appraiser, I want the research agent to extract the price normalized to EUR, along with the original currency, so that international marketplace listings can be compared uniformly.
7. As an appraiser, I want the research agent to classify each extracted price as either a verified **Realized Price** (sold item/auction hammer) or an unconfirmed **Asking Price** (active dealer listing), so that seller wish-prices are not confused with actual sales.
8. As an appraiser, I want each **Reference Listing** to record match accuracy (exact match, variant, similar item, or mismatch), so that irrelevant items do not distort the valuation.
9. As an appraiser, I want each **Reference Listing** to capture the condition of the reference item, so that differences between mint references and used/damaged originals can be audited.
10. As a cataloger, I want the system to handle blocked, broken, or unpriced websites gracefully without crashing, so that the pipeline continues whenever a reasonable quorum of valid web prices is found.
11. As an appraiser, I want an **Appraiser LLM** to analyze all collected web prices and resolve pricing conflicts between high-end antique galleries and affordable classified listings, so that extreme outlier prices are eliminated.
12. As an appraiser, I want the **Appraiser LLM** to prioritize verified **Realized Prices** over active **Asking Prices**, so that the valuation reflects true market liquidity.
13. As an appraiser, I want the **Appraiser LLM** to apply calibrated condition discounts if the scanned item has flaws (such as chips, cracks, or missing pieces) compared to intact reference items, so that the final price reflects the item's true physical state.
14. As an appraiser, I want the **Appraiser LLM** to output an estimated retail price, a realistic min-max price range, and a clear explanation detailing why certain prices were accepted or dismissed, so that the valuation is transparent and defensible.
15. As a cataloger, I want all 10 evaluated listings to be exported row-by-row into a dedicated **Web Price Sheet** (`Marktrecherche_Webpreise`) in the Excel workbook, so that every investigated website is preserved for auditing.
16. As an Excel user, I want the links in the **Web Price Sheet** to be formatted as clickable Excel hyperlinks, so that I can click directly from the spreadsheet to open the original listing in my browser.
17. As a business owner, I want the main overview sheet (`Hauptempfehlung`) to display the final estimated retail price, price range, median scraped web price, number of valid prices, and top reference links alongside the item description and attributes, so that I can make quick buying or selling decisions without navigating multiple sheets.
18. As a developer, I want the pipeline to support a `--mock` execution mode that simulates web research and Excel generation without incurring API costs or network latency, so that automated tests and regression checks run reliably.

## Implementation Decisions

- **Three-Stage Workflow Architecture**:
  - The market valuation step replaces the monolithic Prompt 2 execution with a three-stage sequential orchestrator:
    1. Visual Object Analysis & Grounded Discovery
    2. Parallel Dedicated Site Scraping & Feature Extraction
    3. Appraiser LLM Reconciliation & Valuation Synthesis
- **Multimodal Discovery & Query Formulation**:
  - Gemini Vision processes all valid object photos in the **Article Folder** along with transcript details from Step 1.
  - Constructs targeted search queries incorporating detected hallmarks, maker names, material, and category.
  - Utilizes Google Search Grounding with the existing client and configuration to retrieve candidate web sources, extracting up to 10 clean target URLs.
- **Dedicated Site Research Agent Interface**:
  - Web fetching module utilizes resilient HTTP requests with standard browser headers and timeout safeguards, retrieving HTML body text and structured schema metadata (JSON-LD Product schemas).
  - The site research prompt accepts the target object's summary and the page content, returning a strictly validated JSON record for the **Reference Listing**:
    - `website_name`: name or domain of the source
    - `listing_titel`: title of the referenced product
    - `preis_eur`: numerical price normalized to EUR (or null if unpriced)
    - `preis_typ`: enum (`realisierter_verkaufspreis`, `angebotspreis`, `auktionsgebot`, `schaetzpreis`, `unbekannt`)
    - `match_genauigkeit`: enum (`exakter_treffer`, `modellvariante`, `aehnliches_objekt`, `kein_treffer`)
    - `zustand_referenz`: description of the reference item's condition
    - `quell_url`: canonical URL of the listing
    - `recherche_status`: enum (`erfolgreich`, `kein_preis_gefunden`, `zugriff_blockiert`, `nicht_verfuegbar`)
  - Concurrency is managed via a thread pool with configurable worker count and per-site timeout to ensure research completes within seconds.
- **Appraiser LLM Synthesis Interface**:
  - Receives the scanned item's complete catalog data (physical dimensions, material, detailed damage report, transcript notes) and the list of successful **Reference Listings**.
  - Applies heuristic rules:
    - Eliminates non-matches and extreme price outliers with explicit documentation.
    - Treats **Realized Prices** as strong anchors and active **Asking Prices** as ceilings.
    - Evaluates condition differentials against the user's item damage protocol, applying calibrated discounts.
  - Returns a synthesized valuation payload:
    - `geschaetzter_retail_preis_eur`: primary estimated retail price
    - `preisspanne_min_eur`: conservative lower bound
    - `preisspanne_max_eur`: optimistic upper bound
    - `median_web_preis_eur`: statistical median of valid reference prices
    - `anzahl_gefundene_preise`: count of valid reference listings
    - `begruendung_preisfindung`: detailed appraisal rationale reconciling platform differences
    - `ausreisser_bereinigung_notiz`: notes on excluded or heavily discounted prices
- **State & Manifest Integration**:
  - `PipelineState` models the list of 10 `discovered_web_sources` and the synthesized `web_price_summary`.
  - Saves intermediate artifacts in the run directory (`06_web_research_10_sites.json` and `06_retail_price_synthesis.json`) alongside existing trace files.
- **Excel Multi-Sheet Export & Hyperlink Formatting**:
  - `ExportService` generates a multi-sheet workbook:
    - **Sheet 1 (`Hauptempfehlung`)**: Contains the unified item row, augmented with retail valuation columns (`Empfohlener_Retail_Preis_EUR`, `Preisspanne_Min_EUR`, `Preisspanne_Max_EUR`, `Median_Web_Preis_EUR`, `Anzahl_gefundene_Webpreise`, `Top_Referenz_Links`) while fully preserving `produktbeschreibung`, dimensions, and damage attributes.
    - **Sheet 2 (`Marktrecherche_Webpreise`)**: Lists all 10 examined sites row-by-row. Clickable hyperlinks are written using openpyxl formula syntax `=HYPERLINK("url", "friendly_title")` with distinct visual styling (blue underline).
    - Preserves downstream sheets (`Alle_Massnahmen_Details`, `Varianten_Prompt3`) when available.

## Testing Decisions

- **Testing Principles**:
  - Test external behavior, business outputs, and exported artifacts, not internal private helpers.
  - The primary seam is the end-to-end pipeline execution (`VideoLLMPipeline.run`) and the Excel workbook generator (`ExportService`).
- **Target Modules & Seams**:
  1. `VideoLLMPipeline.run`: Verifies the execution of Stage 1, Stage 2 (web research), Stage 3 (appraisal), and the generation of output JSON and workbook files.
  2. `ExportService`: Verifies that `export_single_item` and batch export produce the new `Marktrecherche_Webpreise` worksheet with valid `=HYPERLINK` formulas and correctly populate the new summary columns on `Hauptempfehlung`.
  3. `WebResearchService`: Verifies resilient parsing and fallback handling when feeding sample HTML and unpriced pages.
- **Prior Art**:
  - Existing sorter unit tests in `src/tests/test_sorter_service.py` provide patterns for temporary directories, mock injection, and filesystem verification.
- **Test Cases**:
  - Full happy-path test with simulated 10-site research results producing the two-sheet Excel file.
  - Discrepancy reconciliation test verifying that realized prices take precedence over outlier asking prices.
  - Hyperlink syntax test ensuring openpyxl cells contain functional `=HYPERLINK(...)` formulas.
  - Robustness test for degraded network conditions (e.g. 4 sites blocked, 6 sites valid).

## Out of Scope

- Implementing browser automation (Playwright/Selenium) or third-party CAPTCHA solving.
- Purchasing or integrating SerpApi subscriptions.
- Live automated order placement or listing creation on eBay/Kleinanzeigen (read-only research).
- Re-enabling or modifying Steps 7 and 8 (Prompts 3 and 4 arbitrage scenarios), which remain optional/commented out.

## Further Notes

- Architecture Decision Record is formally documented in `src/docs/adr/0001-three-stage-market-valuation.md`.
- All domain terminology strictly matches definitions in `src/CONTEXT.md`.
