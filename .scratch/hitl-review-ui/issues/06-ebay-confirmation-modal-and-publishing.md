# 06: eBay Marketplace Confirmation Modal and Live Publishing Dashboard (Tab 3)

**What to build:** Tab 3 ('eBay Upload & Export') providing a clean summary dashboard of all approved ('Freigegeben') articles, total inventory valuation KPIs, and two publishing options: 1) 1-Click download of German eBay Seller Hub File Exchange CSV, and 2) Live eBay REST API publishing strictly gated behind a pre-flight Marketplace Confirmation Modal. Live publishing returns per-item status with clickable live eBay listing URLs.

**Blocked by:** 04 (Sequential Review Wizard and Live In-Place Excel Synchronization)

**Status:** ready-for-agent

- [ ] Summary dashboard of approved articles with total inventory retail value KPIs
- [ ] 1-Click download of German eBay Seller Hub File Exchange CSV via `/api/download_ebay_csv`
- [ ] Pre-flight confirmation modal summarizing item count, total value, and listing terms
- [ ] Direct eBay REST API publishing via `EbayApiClient` with live URL feedback
- [ ] Automatic status update to 'Veröffentlicht' on successful listing
- [ ] Automated tests for eBay CSV export and API publish endpoints
