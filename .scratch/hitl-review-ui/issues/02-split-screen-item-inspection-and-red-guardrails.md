# 02: Split-Screen Item Inspection, 80-Char Title Limit, and Red Validation Guardrails (Tab 2)

**What to build:** The core split-screen review studio in Tab 2. The left pane provides an AI Valuation summary card, editable title with live 80-character limit counter, and editable fields for product description, manufacturer, epoch, material, color, dimensions, weight, and condition rating. The right pane provides a high-resolution photo gallery with thumbnail carousel and video player. Any item with a 0.00 EUR Zero-Data price or a title exceeding 80 characters is highlighted with bold red visual warnings.

**Blocked by:** 01 (Media Drag-and-Drop Ingest and Asynchronous Pipeline Execution)

**Status:** ready-for-human

- [x] Split-screen desktop layout (Left: Metadata & Valuation; Right: High-Res Photo Gallery & Video Player)
- [x] Left sidebar listing all processed items with thumbnail, ID, price, and status badge
- [x] Search filter and status filter pills (Alle, Entwürfe, Freigegeben)
- [x] Live 80-character eBay title counter with red visual warning on overflow
- [x] Visual red highlight styling on 0.00 EUR Zero-Data items and invalid required fields
- [x] Backend endpoints `/api/items`, `/api/images_for_item`, and `/api/videos_for_item`
