# Issue 01: eBay File Exchange and Seller Hub CSV Generation

Status: resolved

## Description
Implement the eBay File Exchange CSV builder in `EbayService` with full header compliance, 80-character title truncation without word splitting, condition ID mapping (1000, 3000, 7000), logistics-based shipping cost calculation, and responsive HTML description generation.

## Acceptance Criteria
- [x] Official eBay File Exchange headers formatted with site ID `Action(SiteID=Germany|Country=DE|Currency=EUR)`
- [x] Title truncated to <= 80 characters without cutting words
- [x] Responsive HTML description table with object details, condition report, and dimensions
- [x] Output saved to `output/ebay_listings_<timestamp>.csv`
