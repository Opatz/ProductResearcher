from unittest.mock import patch, MagicMock
import pytest

from services.ebay_api_client import EbayApiClient


@pytest.fixture
def mock_payload():
    return {
        "inventory_item": {
            "sku": "101",
            "product": {
                "title": "Antike Meissener Porzellan Schale",
                "description": "<p>Historische Porzellanschale</p>",
                "aspects": {
                    "Marke": ["Meissen"],
                    "Material": ["Porzellan"]
                }
            },
            "condition": "USED_EXCELLENT",
            "conditionDescription": "Sehr guter Zustand"
        },
        "offer": {
            "sku": "101",
            "marketplaceId": "EBAY_DE",
            "format": "FIXED_PRICE",
            "pricingSummary": {
                "price": {
                    "value": "180.00",
                    "currency": "EUR"
                }
            },
            "listingDuration": "GTC"
        }
    }


def test_client_configuration():
    client = EbayApiClient(user_token="test_user_token", environment="SANDBOX")
    assert client.is_configured
    assert client.base_url == EbayApiClient.SANDBOX_BASE_URL
    assert client.get_access_token() == "test_user_token"

    prod_client = EbayApiClient(user_token="test_prod_token", environment="PRODUCTION")
    assert prod_client.base_url == EbayApiClient.PRODUCTION_BASE_URL


@patch("requests.post")
def test_oauth_token_exchange(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"access_token": "oauth_token_12345"}
    mock_post.return_value = mock_response

    client = EbayApiClient(app_id="my_app", cert_id="my_cert", environment="SANDBOX")
    token = client.get_access_token()

    assert token == "oauth_token_12345"
    assert mock_post.called


@patch("requests.put")
def test_create_inventory_item(mock_put, mock_payload):
    mock_response = MagicMock()
    mock_response.status_code = 204
    mock_put.return_value = mock_response

    client = EbayApiClient(user_token="test_token", environment="SANDBOX")
    res = client.create_or_replace_inventory_item("101", mock_payload["inventory_item"])

    assert res["success"] is True
    assert res["sku"] == "101"
    assert mock_put.called


@patch("requests.post")
def test_create_offer(mock_post, mock_payload):
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"offerId": "offer_999888"}
    mock_post.return_value = mock_response

    client = EbayApiClient(user_token="test_token", environment="SANDBOX")
    res = client.create_offer(mock_payload["offer"])

    assert res["success"] is True
    assert res["offerId"] == "offer_999888"


@patch("requests.post")
def test_publish_offer(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"listingId": "123456789012"}
    mock_post.return_value = mock_response

    client = EbayApiClient(user_token="test_token", environment="SANDBOX")
    res = client.publish_offer("offer_999888")

    assert res["success"] is True
    assert res["listingId"] == "123456789012"
    assert "https://www.ebay.de/itm/123456789012" in res["listingUrl"]


@patch.object(EbayApiClient, "create_or_replace_inventory_item")
@patch.object(EbayApiClient, "create_offer")
@patch.object(EbayApiClient, "publish_offer")
def test_full_publish_item_workflow(mock_pub, mock_off, mock_inv, mock_payload):
    mock_inv.return_value = {"success": True, "sku": "101"}
    mock_off.return_value = {"success": True, "offerId": "offer_101"}
    mock_pub.return_value = {
        "success": True,
        "listingId": "999000111",
        "listingUrl": "https://www.ebay.de/itm/999000111"
    }

    client = EbayApiClient(user_token="test_token", environment="SANDBOX")
    result = client.publish_single_item(mock_payload)

    assert result["status"] == "PUBLISHED_LIVE"
    assert result["sku"] == "101"
    assert result["offerId"] == "offer_101"
    assert result["listingId"] == "999000111"
    assert result["listingUrl"] == "https://www.ebay.de/itm/999000111"
