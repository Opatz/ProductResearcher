# Specification: End-to-End Non-Technical Human-in-the-Loop Review Studio & Marketplace Workflow

## Problem Statement

Antique dealers, auction operators, and non-technical staff handling inventory appraisal need a graphical desktop application to process multimodal media (photographs and overview video recordings of vintage objects), evaluate AI-generated market valuations and item descriptions, fine-tune listing metadata with visual feedback, and authorize listings for commercial marketplaces (e.g., eBay).

Currently, running terminal commands, navigating multi-level folder directories, and manually verifying generated CSV/Excel tables requires technical knowledge, creates cognitive friction, and risks pushing unverified listings or zero-data valuations directly to live marketplaces without human oversight.

## Solution

A standalone graphical desktop application (**Human-in-the-Loop Review Hub**) structured into an intuitive 3-stage lifecycle:
1. **Media Ingestion & Run**: A drag-and-drop dropzone for raw images and video files conforming strictly to the `Raw Ingest` pattern (`ID Image` $\rightarrow$ `Object Images` $\rightarrow$ `Object Video`), an overview preview of staged items, and a 1-click execution button (*„Recherche & Beschreibung generieren“*) with live progress reporting.
2. **Review & Fine-Tuning**: A split-screen studio displaying item metadata and empirical web research comparables on the left alongside high-resolution photo galleries and video playback on the right. Visual guardrails immediately highlight zero-data prices ($0,00\ \text{€}$) and length violations in red. Operators can re-run single items with optional keyword hints and use a 1-click `Sequential Review Wizard` (*„💾 Speichern & Nächster Artikel“*) to approve items sequentially.
3. **Marketplace Upload & Confirmation**: An overview dashboard of all approved items offering both 1-click German eBay Seller Hub File Exchange CSV export and direct eBay REST API publishing gated strictly behind a `Marketplace Confirmation Modal`.

---

## User Stories

1. As an antique dealer, I want to double-click a desktop launcher, so that the Item Research Studio opens automatically in my browser without typing terminal commands.
2. As an operator, I want to drag and drop a bundle of object photos and videos into a central dropzone, so that I can stage new inventory items effortlessly.
3. As an operator, I want the system to parse dropped media following the chronological Raw Ingest sequence (`ID Image` $\rightarrow$ `Object Images` $\rightarrow$ `Object Video`), so that object media is grouped into dedicated Article Folders automatically.
4. As an operator, I want unidentifiable or broken media sequences to be moved to an Inspection Folder, so that valid items proceed while incomplete items are isolated for manual check.
5. As an operator, I want to see a clear overview grid of all staged raw files and pre-sorted folders before starting, so that I know exactly how much inventory is about to be processed.
6. As an operator, I want a single prominent button labeled *„Recherche & Beschreibung generieren“*, so that I can trigger multimodal transcription, visual analysis, 10-site web research, and appraisal synthesis in one click.
7. As an operator, I want to see real-time progress percentages and live log updates while the pipeline runs, so that I understand what stage each item is in.
8. As an operator, I want the app to automatically focus and unlock the *„Artikel prüfen“* review tab once processing is complete, so that I can immediately start inspecting results.
9. As an operator, I want a full sidebar listing all processed articles with thumbnails, detected IDs, titles, prices, and status badges, so that I can easily navigate across all items.
10. As an operator, I want quick filter pills (*Alle*, *Entwürfe*, *Freigegeben*), so that I can focus specifically on unreviewed or approved inventory.
11. As an appraiser, I want to see an AI Valuation Card showing the recommended retail price, price span (min-max), web price median, source count, and valuation rationale, so that I understand the empirical basis for each suggested price.
12. As an appraiser, I want a collapsible reference table directly under the valuation card listing discovered Reference Listings with platform names, extracted prices, condition tags, and clickable external hyperlinks, so that I can verify source listings on eBay, Pamono, Catawiki, or 1stDibs in one click.
13. As an operator, I want an editable Title field with a live 80-character limit counter, so that I can ensure marketplace compliance for eBay titles.
14. As an operator, I want any title exceeding 80 characters or any item with a price of $0,00\ \text{€}$ to be visually highlighted in bold red, so that I am immediately alerted to missing or invalid data.
15. As an operator, I want editable input fields for product description, manufacturer, epoch/year, material, color, dimensions ($L \times B \times H$), weight, and condition rating, so that I can adjust or correct AI descriptions before publishing.
16. As an operator, I want a high-resolution photo viewer with thumbnail carousel on the right pane, so that I can inspect condition hallmarks, stamps, and details side-by-side with the metadata.
17. As an operator, I want an embedded video player tab for items with an associated Object Video, so that I can watch visual sweeps and listen to verbal descriptions.
18. As an operator, I want a button to re-run analysis for a single article with an optional keyword hint (e.g. *„Meissen Schwertermarke 1880“*), so that I can refine web research without re-running the entire batch.
19. As an operator, I want a fixed bottom bar with *„💾 Speichern & Nächster Artikel ➔“*, so that I can approve an item and advance to the next item in sequence with a single click.
20. As an operator, I want every save action to sync in-place to the master Excel file and write an audit log entry, so that my work is never lost.
21. As an operator, I want a session history dropdown in the header, so that I can review and edit previous Execution Batches at any time.
22. As an operator, I want a clean language selector in the header (e.g., German / English), so that operators can use the interface in their preferred language.
23. As an operator, I want a dedicated *„eBay Upload & Export“* tab displaying approved items with total inventory retail value, so that I have a clear publishing overview.
24. As an operator, I want a 1-click button to download the German eBay Seller Hub File Exchange CSV, so that I can perform zero-setup bulk uploads in Seller Hub.
25. As an operator, I want direct eBay REST API publishing to require a pre-flight confirmation modal, so that listings are never published to live marketplaces without explicit human authorization.
26. As an operator, I want per-item live feedback during eBay API publishing with direct clickable `https://www.ebay.de/itm/<listingId>` links and specific error callouts on failures, so that I can verify live listings or retry failed items immediately.

---

## Implementation Decisions

### 1. Unified 3-Stage Client Architecture
- **Tab 1: Medien hochladen / Vorbereiten**:
  - HTML5 drag & drop dropzone accepting image formats (`.jpg`, `.jpeg`, `.png`, `.webp`, `.heic`) and video formats (`.mp4`, `.mov`, `.avi`).
  - Multipart upload handler streaming uploaded files into `input/raw/`.
  - Background asynchronous task manager (`PipelineRunner`) executing raw sorting, audio extraction, visual analysis, 10-site web research, and appraisal synthesis without freezing the UI.
- **Tab 2: Artikel prüfen & Freigeben**:
  - Split-screen workspace layout (Left: Data & Valuation Editor; Right: High-Res Photo Viewer + Video Player).
  - Collapsible **Reference Listings Table** dynamically populated with clickable hyperlinks from the Web Price Sheet.
  - Live character validation and reactive red alert styling on $0,00\ \text{€}$ Zero-Data valuations and length limits.
  - Per-item re-run endpoint `/api/reanalyze_item` accepting optional custom search keywords.
  - Sequential Review Wizard with 1-click save, status transition to `Freigegeben`, in-place openpyxl Excel update, and auto-advance.
- **Tab 3: eBay Upload & Export**:
  - Filtered table of `Freigegeben` records with inventory valuation KPI cards.
  - File Exchange CSV generator conforming to German Seller Hub specs.
  - REST API dispatcher utilizing `EbayApiClient` with a mandatory pre-flight `Marketplace Confirmation Modal`.

### 2. Localization (i18n) Engine
- Centralized UI dictionary object containing key-value mappings for German (`de`) and English (`en`), selectable via a header dropdown and persisted in browser storage.

### 3. Session & Execution Batch Management
- Auto-discovery of all `output/execution_<timestamp>/` directories.
- REST endpoint `/api/sessions` to list available batches and switch active data source without restart.

---

## Testing Decisions

- **Good Test Criteria**: Tests must verify observable HTTP contracts, data integrity, and error handling rather than internal implementation details.
- **Test Seams & Modules Tested**:
  1. **UI Server Endpoints (`tests/test_ui_server.py`)**:
     - `GET /api/staged_media`: Validates staged file discovery and counts.
     - `POST /api/upload`: Tests multipart file ingestion into raw directories.
     - `GET /api/items`: Validates reading items and reference listings from consolidated Excel runs.
     - `POST /api/save_item`: Tests in-place Excel updating, field persistence, and audit logging.
     - `POST /api/export_ebay` & `GET /api/download_ebay_csv`: Tests CSV generation and download attachment headers.
     - `POST /api/publish_ebay`: Tests live/sandbox API publishing dispatch and failure formatting.
  2. **Pipeline Runner & Lifecycle (`tests/test_completed_lifecycle.py`, `tests/test_ebay_service.py`)**:
     - Tests sequence sorting, status transitions, and eBay row formatting.

---

## Out of Scope

- Direct consumer payment checkout or order fulfillment within the review tool (handled natively in eBay Seller Hub).
- Real-time multi-user concurrent editing of the same Excel sheet over local network (single-operator desktop deployment model).
- Automatic publishing to non-eBay platforms (Etsy/Kleinanzeigen/Shop remain exported as drafts/payloads).

---

## Further Notes

- The UI operates completely locally over `http://127.0.0.1:8501`.
- All styling is self-contained with no external CSS/JS CDN dependencies, ensuring full functionality in offline or firewall-restricted auction house environments.
