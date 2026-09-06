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

**Appraiser LLM**:
The dedicated valuation synthesis stage that resolves price discrepancies across diverse platforms, weeds out outliers, accounts for condition differentials, and establishes the estimated retail price.
_Avoid_: Price calculator, prompt 2, summarizer

**Web Price Sheet**:
The dedicated worksheet (`Marktrecherche_Webpreise`) recording all evaluated external reference listings row-by-row with clickable hyperlinks.
_Avoid_: Links tab, price tab, scrape sheet

