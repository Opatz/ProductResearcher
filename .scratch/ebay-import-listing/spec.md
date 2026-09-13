# Specification: eBay Marketplace Import & Listing Engine

## Problem Statement

After multimodal AI appraisal and market research are completed on antique and collectible items, sellers must manually copy and reformat item titles, physical dimensions, condition reports, and valuations into eBay. This manual data entry is slow, error-prone, and frequently violates eBay constraints (such as the strict 80-character title limit, standardized Condition IDs, and specific item aspect structures). Furthermore, sellers have no straightforward mechanism to review approved valuations and execute a bulk listing export or direct API publication in a dedicated, isolated workflow call.

## Solution

A dedicated, dual-mode eBay Listing Engine that ingests human-reviewed item records and automatically transforms them into fully compliant eBay listings. The solution provides:
1. An official **eBay Seller Hub / File Exchange CSV** generator for zero-credential 1-click bulk imports.
2. A structured **eBay Sell Inventory and Offer REST API** client for programmatic draft or live listing creation using environment credentials.
3. Automated compliance enforcement: 80-character title truncation with word boundary preservation, condition mapping (1000/3000/7000), shipping category tiering, and responsive HTML description generation.
4. A dedicated CLI workflow (`--ebay-export`, `--ebay-publish`) that filters items by approval status and target platform.

## User Stories

1. As an antique seller, I want to export all reviewed and approved items into an official eBay File Exchange CSV with a single command, so that I can bulk upload dozens of items to eBay Seller Hub without manual entry.
2. As an appraiser, I want the system to enforce eBay's 80-character title constraint automatically without cutting words in half, so that my listings remain readable and compliant with eBay search indexing.
3. As a seller, I want my item's condition rating (e.g. `neuwertig`, `sehr_gut`, `gut`, `defekt`) automatically translated into official eBay Condition IDs (`1000`, `3000`, `7000`), so that buyers see standard condition badges.
4. As a buyer on eBay, I want a well-structured, mobile-responsive HTML item description containing clear sections for object history, maker stamps, dimension tables, and detailed condition flaws, so that I can make an informed purchase.
5. As a seller, I want shipping costs automatically tiered based on the item's logistics classification (standard packet, bulky parcel, or freight/spedition), so that heavy furniture or fragile items are not undercharged.
6. As an automated marketplace operator, I want to provide eBay API credentials in `.env` and trigger direct programmatic listing creation via the eBay Sell Inventory/Offer REST API, so that items can be published without manual file downloads.
7. As an operator, I want a `--dry-run` validation flag on the eBay CLI command, so that I can verify all listing parameters and API payloads before committing them to live marketplaces.
8. As a cataloger, I want the eBay workflow to filter strictly for items where `Status` is `Freigegeben` and `VerkaufsOrt` is `eBay`, so that unfinished drafts or items destined for other channels are not accidentally exported.
9. As a reseller, I want to choose between Fixed Price (Sofort-Kaufen with Good 'Til Cancelled) and Auction format per item, so that rare collector pieces can be auctioned while standard inventory is listed at fixed prices.
10. As a store manager, I want an audit trail of every generated eBay batch saved with timestamps and item counts, so that I can track listing history and verify which items were published.

## Implementation Decisions

1. **Dual-Channel Listing Architecture**:
   - **File Exchange / Seller Hub CSV**: Primary offline bulk mechanism. Formatted with official eBay header syntax `Action(SiteID=Germany|Country=DE|Currency=EUR)` and comma-separated UTF-8-SIG encoding.
   - **REST Sell Inventory & Offer API**: Programmatic online mechanism. Generates JSON payloads matching eBay's `inventory_item` and `offer` schema, with OAuth 2.0 token support.

2. **Seam Placement & Modular Interface**:
   - The eBay listing engine operates at the data export seam (`EbayService`), consuming unified item records from either spreadsheet storage (`.xlsx` / `.csv`) or in-memory pipeline states.
   - It exposes high-level public methods: `load_items_from_source()`, `build_ebay_file_exchange_rows()`, `build_ebay_api_payloads()`, and `export_ebay_batch()`.

3. **Title Optimization Algorithm**:
   - Strips excessive whitespace and checks character length against the 80-character maximum.
   - If length exceeds 80 characters, it locates the last whitespace boundary before index 80 (with a minimum threshold) to truncate cleanly without mid-word splits.

4. **HTML Description Formatting**:
   - Renders a self-contained, inline-styled HTML container featuring:
     - Header with object title, category, and era.
     - Product description body.
     - Maker and material specification table.
     - Dimensions, weight, and logistics category.
     - Dedicated condition report highlighting flaws and missing parts.
     - Shipping and packaging disclaimer.

5. **Human-in-the-Loop Filter Semantics**:
   - Status filtering accepts variations of approval (`Freigegeben`, `Ready`, `OK`, `Genehmigt`, `Aktiv`).
   - Platform filtering checks the `VerkaufsOrt` column (case-insensitive `ebay`), allowing unassigned items to be included only when explicitly requested.

6. **Dedicated Execution Entry Points**:
   - Headless CLI parameters in the main orchestrator:
     - `--ebay-export`: Generates File Exchange CSV and API JSON files.
     - `--ebay-file`: Specifies custom input spreadsheet path.
     - `--ebay-status`: Custom status filter override (default `Freigegeben`).
     - `--ebay-platform`: Custom platform filter override (default `ebay`).
     - `--dry-run`: Validates payload schema without writing files or calling APIs.

## Testing Decisions

1. **External Behavior Focus**:
   - Tests will assert against generated CSV columns, header keys, pricing string formatting, condition ID integers, and HTML description content rather than internal private helpers.
2. **Key Test Suites**:
   - Condition ID mapping: Verifies that keywords (`neuwertig`, `sehr_gut`, `defekt`, `unbekannt`) correctly produce eBay standard numeric IDs.
   - Title truncation: Verifies exact boundary limits (<= 80 chars) and absence of trailing word truncations.
   - File Exchange CSV correctness: Asserts presence of `Action`, `CustomLabel`, `StartPrice`, `Quantity=1`, `Duration=GTC`, and postal code.
   - Filter accuracy: Asserts that unapproved items (`Status=Entwurf`) or non-eBay items (`VerkaufsOrt=Vinted`) are excluded from output batches.
   - API payload structure: Asserts JSON compatibility with eBay Sell Inventory API specifications.
3. **Prior Art**:
   - Aligns with existing export test patterns in `tests/test_export_service.py` and `tests/test_appraiser_service.py`.

## Out of Scope

- Graphical User Interface (GUI) development (tracked separately in `.scratch/hitl-review-ui/`).
- Multi-marketplace connectors for Etsy, Kleinanzeigen, or Shopify (postponed to future iterations).
- Direct scraping of eBay buyer feedback or automated order fulfillment tracking.

## Further Notes

- eBay's production environment requires active user token authentication or OAuth refresh tokens configured via `.env` (`EBAY_APP_ID`, `EBAY_CERT_ID`, `EBAY_USER_TOKEN`).
- File Exchange CSVs require zero developer tokens and can be immediately uploaded by any seller in eBay Seller Hub.
