# 0006 eBay Integration and Human-in-the-Loop Review

## Status
Accepted

## Context
The multimodal appraisal pipeline generates comprehensive item metadata (titles, descriptions, dimensions, condition reports, and estimated retail prices with empirical web price comparables). However, publishing directly to commercial marketplaces (such as eBay) requires:
1. **Human Quality Assurance & Pricing Control (Human-in-the-Loop)**: Appraisers must review, verify, and potentially adjust the AI-suggested title, price, condition notes, or listing category before committing items to public marketplaces.
2. **Marketplace Constraint Compliance**: eBay enforces strict listing constraints (e.g. 80-character title limit, standardized ConditionIDs like 1000/3000/7000, fixed price vs auction format, shipping policies).
3. **Accessibility for Non-Technical Users**: For day-to-day operations by non-developers, relying solely on terminal commands or manual CSV manipulation is error-prone. A 1-click executable visual interface is needed where calculated parameters and high-resolution item photos can be reviewed side-by-side.
4. **Dual Ingestion & Publication Flow**: The system must support zero-setup bulk CSV imports (eBay Seller Hub File Exchange) as well as automated programmatic listing via the eBay Sell Inventory/Offer REST API when credentials are provided in `.env`.

## Decision
We implement a dedicated **eBay Marketplace Integration & Human-in-the-Loop Review Hub**:

1. **Review Hub Architecture (Split-Screen Interface)**:
   - A dedicated desktop web UI accessible via 1-click launcher (`Start_Item_Researcher.bat` / executable `Item Research Studio`) or CLI (`python main.py --review-ui`).
   - **Left Panel**: Extracted item attributes, appraiser price synthesis, 10-site web comparables, dimensions, and condition assessment.
   - **Right Panel**: High-resolution image gallery and carousel with photo zoom.
   - **Bottom/Editing Panel**: Interactive input fields for Title (with live 80-character eBay counter badge), Final Price, Platform dropdown (e.g., `eBay`), Listing Format dropdown (`FixedPrice` / `Auktion`), and Approval Status dropdown (`Entwurf`, `Freigegeben`, `Zurückgehalten`, `Veröffentlicht`).

2. **Persistence & Master Synchronization (Option C)**:
   - Approving or modifying an item updates the active `consolidated_execution_results.xlsx` (and `.csv`) in place, while maintaining a structured `reviewed_listings.json` with audit timestamps.

3. **Hybrid eBay Export & Execution Service (`EbayService`)**:
   - Exposed via dedicated CLI `python main.py --ebay-export` and 1-click UI button.
   - **File Exchange / Seller Hub CSV**: Generates official eBay bulk CSV files (`ebay_listings_<timestamp>.csv`) ready for 1-click upload in eBay Seller Hub without developer registration.
   - **Sell REST API Payloads**: Generates structured JSON payloads (`ebay_listings_payload_<timestamp>.json`) and provides API dispatch for live/sandbox publishing when `.env` credentials (`EBAY_APP_ID`, `EBAY_USER_TOKEN`) are configured.
   - **Automated Validation**: Enforces 80-char title truncation with clean word boundaries, maps internal conditions to official eBay ConditionIDs (1000, 3000, 7000), calculates shipping tiers (standard, bulky, freight), and formats responsive HTML description tables.

4. **1-Click Desktop Packaging**:
   - Provides a double-clickable batch launcher (`Start_Item_Researcher.bat`) and PyInstaller build configuration to generate a standalone executable for non-technical users.

## Considered Options
- **Fully Automated Direct Listing Without Human Review**: Rejected because AI valuations and titles on high-value antique items require human approval before public financial commitments.
- **Pure Terminal Interactive Prompts (CLI Wizard)**: Rejected because assessing visual condition flaws and hallmarks requires side-by-side photo inspection that cannot be rendered effectively in a text-only shell.
- **Solely Live API Mode**: Rejected because requiring eBay Developer API keys and OAuth tokens creates friction for non-technical users who can immediately upload File Exchange CSVs in Seller Hub.
