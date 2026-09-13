# AsiaWorkflow

Automated multimodal analysis pipeline for antiques and collectibles, ingesting media sequences, performing visual OCR, transcription, condition valuation, and market analysis.

## Language

**Raw Ingest**:
A chronologically ordered stream of media files representing one or more objects, structured strictly as a sequence of an ID Image, zero or more Object Images, and an Object Video.
_Avoid_: Raw data, unstructured input, dump

**ID Image**:
The initial photograph in an object sequence capturing the physical tag, handwritten note, or numeric identifier of the item.
_Avoid_: First picture, intro frame, tag photo, ID frame

**Object Images**:
Photographs showing the physical object itself, including condition, hallmarks, stamps, and overall views.
_Avoid_: Detail images, photos, extra pictures, follow-up photos

**Object Video**:
The concluding video recording of an object sequence, containing verbal descriptions in the audio and visual overviews of the object.
_Avoid_: Video, clip, movie, intro video

**Article Folder**:
A dedicated folder containing all grouped media (ID Image, Object Images, Object Video) for a single identified item, named after the detected ID.
_Avoid_: Item folder, output subfolder, batch folder

**Inspection Folder**:
A quarantine directory (e.g., under `output/to_inspect/`) where unidentifiable or broken media sequences (where no ID Image was recognized) are isolated for human review.
_Avoid_: Error folder, trash, dump, lost+found

**Reference Listing**:
An external web offering or completed sale discovered and analyzed for comparison, containing extracted price, price type, condition, and match confidence.
_Avoid_: Web hit, search result, scrap, link

**Realized Price**:
An actual, verified sale price or auction hammer price, which strictly takes precedence over asking prices.
_Avoid_: Sold tag, final bid, closed price

**Asking Price**:
An active, unconfirmed seller offer or listing price, treated as an unverified ceiling rather than an established market value.
_Avoid_: List price, catalog price, seller hope

**Asking Price Fallback**:
A calibrated fallback mechanism that utilizes active asking prices with a flat 15% safety haircut when zero verified realized sales are available, preventing hallucinated valuations while explicitly documenting the discount in the valuation rationale.
_Avoid_: Guess price, active price copy, unadjusted listing price

**Zero-Data Policy**:
A strict anti-hallucination safeguard ensuring that if neither realized sales nor active reference listings exist in empirical web research, the estimated retail price is set to 0.0 / null and flagged for human appraisal rather than generating fantasy prices.
_Avoid_: Fallback guessing, synthetic appraisal, heuristic estimation

**Appraiser LLM**:
The dedicated valuation synthesis stage that resolves price discrepancies across diverse platforms, weeds out outliers, accounts for condition differentials, enforces the strict priority of realized sales over asking prices, and executes the asking price fallback.
_Avoid_: Price calculator, prompt 2, summarizer

**Web Price Sheet**:
The dedicated worksheet (`Marktrecherche_Webpreise`) recording all evaluated external reference listings row-by-row with clickable hyperlinks.
_Avoid_: Links tab, price tab, scrape sheet

**Human-in-the-Loop Review Hub**:
The dedicated split-screen review interface displaying extracted item metadata, research data, and media thumbnails on the left/right, enabling real-time human verification, price adjustments, and listing authorization before publishing.
_Avoid_: Edit form, admin panel, web frontend

**Listing Payload**:
The validated, marketplace-ready structured data (eBay Seller Hub File Exchange CSV and eBay Sell Inventory/Offer JSON) generated strictly from human-approved item records.
_Avoid_: Export file, dump json, listing dump

**Approval Status**:
The definitive human-in-the-loop lifecycle flag (`Entwurf`, `Freigegeben`, `Zurückgehalten`, `Veröffentlicht`) controlling whether an item is eligible for automated marketplace export or publishing.
_Avoid_: Status flag, check state, ready marker

**Execution Batch**:
A timestamped run directory (e.g. `output/execution_<timestamp>/`) containing consolidated master tables, manifests, and item subfolders for a single processing cycle, switchable via the Studio session history.
_Avoid_: Run folder, export folder, batch dump

**Sequential Review Wizard**:
The guided, 1-click step-by-step review mechanism in the Human-in-the-Loop Review Hub that validates required fields, highlights zero-data entries in red, updates the Approval Status to `Freigegeben`, syncs in-place to the master table, and advances to the next item.
_Avoid_: Next button, form stepper, quick approve

**Marketplace Confirmation Modal**:
The mandatory human-in-the-loop confirmation dialog in the Studio presenting total inventory count, cumulative valuation, and format summary before transmitting live listings to marketplace REST APIs.
_Avoid_: Popup, upload dialog, alert box

**Sort-Only Execution**:
The isolated preprocessing phase that structures unstructured incoming media sequences into Article Folders and quarantines invalid sequences without triggering multimodal LLM valuation or web research calls.
_Avoid_: Ingest dump, preliminary run, quick sort

**Research-Only Execution**:
The dedicated valuation and description phase running audio transcription, visual analysis, 10-portal web research, and appraisal synthesis exclusively on pre-sorted Article Folders without modifying raw ingest sources.
_Avoid_: Second phase, evaluation dump, batch scan

**End-to-End Pipeline**:
The fully automated composite execution sequence combining Sort-Only Execution directly followed by Research-Only Execution in a single uninterrupted run.
_Avoid_: Full dump, mega run, complete scan



