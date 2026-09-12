# 04: Sequential Review Wizard and Live In-Place Excel Synchronization (Tab 2)

**What to build:** A fixed bottom wizard bar allowing operators to review items one by one. Clicking '💾 Speichern & Nächster Artikel ➔' validates the active item, saves modifications in-place to `consolidated_execution_results.xlsx`, transitions the Approval Status to 'Freigegeben', appends an audit entry to `output/reviewed_listings.json`, and immediately advances to the next item without page reload.

**Blocked by:** 03 (Clickable Web Research Comparables and In-Place Reference Linking)

**Status:** ready-for-agent

- [ ] Fixed bottom navigation bar with item counter ('Artikel X von Y') and navigation buttons
- [ ] 1-Click 'Speichern & Nächster Artikel ➔' action updating status to 'Freigegeben'
- [ ] In-place Excel synchronization preserving multi-sheet structure and cell formatting
- [ ] Append-only JSON audit trail in `output/reviewed_listings.json` with timestamps
- [ ] Automated unit tests for `/api/save_item` in-place Excel updating and audit logging
