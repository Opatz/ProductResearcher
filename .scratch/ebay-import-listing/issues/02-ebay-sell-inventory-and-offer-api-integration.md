# Issue 02: eBay Sell Inventory and Offer API Integration

Status: resolved

## Description
Implement direct programmatic listing dispatch to the eBay Sell Inventory & Offer REST API using credentials from `.env` (`EBAY_APP_ID`, `EBAY_CERT_ID`, `EBAY_USER_TOKEN` or OAuth token exchange), enabling 1-click live or sandbox listing creation.

## Acceptance Criteria
- [x] Support OAuth token retrieval or user token authentication (`services/ebay_api_client.py`)
- [x] Dispatch `PUT /sell/inventory/v1/inventory_item/{sku}`
- [x] Dispatch `POST /sell/inventory/v1/offer` and `POST /sell/inventory/v1/offer/{offerId}/publish`
- [x] Return live eBay Item ID / Listing URL upon success
- [x] Integrate CLI execution handler `--ebay-publish` in `main.py`
- [x] Unit test suite with mock endpoints in `tests/test_ebay_api_client.py`

## Answer
Implemented `EbayApiClient` in `services/ebay_api_client.py` handling OAuth credentials, inventory item creation, offer generation, and publishing with full error diagnostics and live URL construction. Added `--ebay-publish` to `main.py` and unit tests in `tests/test_ebay_api_client.py`.
