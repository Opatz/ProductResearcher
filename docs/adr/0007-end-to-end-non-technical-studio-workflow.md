# 0007 End-to-End Non-Technical Studio Workflow and Multi-Language Architecture

## Status
Accepted

## Context
Non-technical antique dealers and inventory operators require a self-contained, guided workflow from the moment they double-click the executable to the final marketplace publication. 

To prevent errors and ensure maximum ease of use, the interaction model must:
1. Provide zero-friction media ingestion (Drag & Drop zone accepting image sequences and video overviews conforming to the canonical Raw Ingest pattern).
2. Deliver clear visual guardrails during review (highlighting $0,00\ \text{€}$ Zero-Data valuations and length limit violations in prominent red).
3. Offer empirical market transparency by linking discovered reference listings directly to the active item with clickable hyperlinks.
4. Separate the evaluation / per-item re-run workflow from the final marketplace publication step.
5. Provide a mandatory pre-flight confirmation dialog before transmitting live listings via the eBay REST API.
6. Support multi-language operations (e.g., German / English) via a clean local translation dictionary and header dropdown.

## Decision

1. **3-Stage Lifecycle Navigation**:
   - **Tab 1: Medien hochladen / Vorbereiten**: Interactive Drag-and-Drop dropzone accepting image sequences and video clips, staged files overview grid, and a prominent *„Recherche & Beschreibung generieren“* button with live progress and streaming logs.
   - **Tab 2: Artikel prüfen & Freigeben**: Split-screen editor with full overview sidebar, AI valuation card, collapsible table of empirical **`Reference Listings`** with clickable hyperlinks, visual red highlights on missing/invalid fields, high-res photo gallery with zoom and video player, per-item re-run capability with optional keyword hints, and a 1-click **`Sequential Review Wizard`** (*„💾 Speichern & Nächster Artikel“*).
   - **Tab 3: eBay Upload & Export**: Summary metrics of all approved items, 1-click Seller Hub CSV export, and live REST API publishing gated behind a **`Marketplace Confirmation Modal`**.

2. **Per-Item Re-Run with Keyword Guidance**:
   - Operators can trigger an on-demand re-appraisal of individual items, optionally supplying a refined keyword hint (e.g. *„Meissen Schwertermarke 1880“*) to focus the AI web research without re-running the entire batch.

3. **Session & History Navigation**:
   - The Studio defaults to the latest **`Execution Batch`** on startup while providing a session selector in the header to switch between historical execution runs.

4. **Multi-Language Architecture (i18n)**:
   - All UI text, tooltips, and validation labels are stored in a localized dictionary structure, selectable via a clean language dropdown in the header and saved in local preferences.

## Consequences
- **Positive**: Complete autonomy for non-technical users, clear visual validation feedback, zero accidental marketplace pushes, and empirical research ground-truthing.
- **Negative**: Adds UI state management for multi-stage tabs, background runner threads, and localization dictionaries.
