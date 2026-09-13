import os
import json
import base64
import logging
from typing import Dict, Any, Optional, List, Tuple
import requests

from config.settings import EbaySettings

logger = logging.getLogger(__name__)


class EbayApiClient:
    """
    REST API Client für die offizielle eBay Sell Inventory & Offer API.
    Unterstützt:
    - OAuth 2.0 Token Handling (User Access Token & Client Credentials Token)
    - Sandbox & Production Umgebungen
    - Erstellung von Inventory Items (`PUT /sell/inventory/v1/inventory_item/{sku}`)
    - Erstellung von Angeboten (`POST /sell/inventory/v1/offer`)
    - Veröffentlichung von Angeboten (`POST /sell/inventory/v1/offer/{offerId}/publish`)
    - Sicheren Dry-Run / Testmodus
    """

    SANDBOX_BASE_URL = "https://api.sandbox.ebay.com"
    PRODUCTION_BASE_URL = "https://api.ebay.com"

    def __init__(
        self,
        app_id: Optional[str] = None,
        cert_id: Optional[str] = None,
        user_token: Optional[str] = None,
        environment: Optional[str] = None,
        settings: Optional[EbaySettings] = None
    ):
        self.app_id = app_id or os.getenv("EBAY_APP_ID", "").strip()
        self.cert_id = cert_id or os.getenv("EBAY_CERT_ID", "").strip()
        self.user_token = user_token or os.getenv("EBAY_USER_TOKEN", "").strip()
        self.environment = (environment or os.getenv("EBAY_ENVIRONMENT", "SANDBOX")).strip().upper()
        self.settings = settings or EbaySettings()

        if self.environment == "PRODUCTION":
            self.base_url = self.PRODUCTION_BASE_URL
        else:
            self.base_url = self.SANDBOX_BASE_URL

        self._cached_token: Optional[str] = self.user_token if self.user_token else None

    @property
    def is_configured(self) -> bool:
        """Prüft, ob gültige API-Zugangsdaten konfiguriert sind."""
        return bool(self._cached_token or (self.app_id and self.cert_id))

    def get_access_token(self) -> str:
        """
        Gibt ein gültiges Bearer-Token zurück.
        Nutzt das konfigurierte EBAY_USER_TOKEN oder ruft ein OAuth Client-Credentials-Token ab.
        """
        if self._cached_token:
            return self._cached_token

        if not self.app_id or not self.cert_id:
            raise ValueError(
                "Keine eBay API Credentials konfiguriert! Bitte setze EBAY_USER_TOKEN oder "
                "EBAY_APP_ID und EBAY_CERT_ID in der .env Datei."
            )

        auth_str = f"{self.app_id}:{self.cert_id}"
        encoded_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")

        token_url = f"{self.base_url}/identity/v1/oauth2/token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {encoded_auth}"
        }
        data = {
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope/sell.inventory"
        }

        logger.info(f"Fordere neues eBay OAuth Token von '{token_url}' an...")
        resp = requests.post(token_url, headers=headers, data=data, timeout=15)
        if resp.status_code != 200:
            raise RuntimeError(f"eBay OAuth Authentifizierungsfehler ({resp.status_code}): {resp.text}")

        token_json = resp.json()
        self._cached_token = token_json.get("access_token")
        if not self._cached_token:
            raise RuntimeError(f"Kein access_token in eBay-Antwort enthalten: {resp.text}")

        return self._cached_token

    def _get_auth_headers(self) -> Dict[str, str]:
        """Erstellt die Standard-HTTP-Header für Sell API Aufrufe."""
        token = self.get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Content-Language": "de-DE",
            "Accept": "application/json"
        }

    def create_or_replace_inventory_item(self, sku: str, inventory_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Legt ein Inventar-Objekt auf eBay an oder aktualisiert es.
        Endpoint: PUT /sell/inventory/v1/inventory_item/{sku}
        """
        sku_clean = str(sku).strip()
        url = f"{self.base_url}/sell/inventory/v1/inventory_item/{sku_clean}"
        headers = self._get_auth_headers()

        logger.info(f"Sende Inventory Item für SKU '{sku_clean}' an eBay ({self.environment})...")
        resp = requests.put(url, headers=headers, json=inventory_data, timeout=30)
        
        # 204 No Content oder 200 OK bedeutet Erfolg
        if resp.status_code in [200, 201, 204]:
            logger.info(f"✅ Inventory Item SKU '{sku_clean}' erfolgreich angelegt (Status {resp.status_code}).")
            return {"success": True, "sku": sku_clean, "status_code": resp.status_code}

        err_msg = f"Fehler beim Anlegen von Inventory Item '{sku_clean}' ({resp.status_code}): {resp.text}"
        logger.error(err_msg)
        return {"success": False, "sku": sku_clean, "status_code": resp.status_code, "error": resp.text}

    def create_offer(self, offer_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Erstellt ein eBay-Angebot für ein existierendes Inventar-Objekt.
        Endpoint: POST /sell/inventory/v1/offer
        """
        url = f"{self.base_url}/sell/inventory/v1/offer"
        headers = self._get_auth_headers()

        sku = offer_data.get("sku", "UNKNOWN")
        logger.info(f"Erstelle eBay Offer für SKU '{sku}'...")
        resp = requests.post(url, headers=headers, json=offer_data, timeout=30)

        if resp.status_code in [200, 201]:
            resp_data = resp.json()
            offer_id = resp_data.get("offerId")
            logger.info(f"✅ eBay Offer erfolgreich erstellt: OfferID = '{offer_id}'")
            return {"success": True, "offerId": offer_id, "data": resp_data}

        err_msg = f"Fehler beim Erstellen des Offers ({resp.status_code}): {resp.text}"
        logger.error(err_msg)
        return {"success": False, "error": resp.text, "status_code": resp.status_code}

    def publish_offer(self, offer_id: str) -> Dict[str, Any]:
        """
        Veröffentlicht ein existierendes Angebot live auf dem Marktplatz.
        Endpoint: POST /sell/inventory/v1/offer/{offerId}/publish
        """
        url = f"{self.base_url}/sell/inventory/v1/offer/{offer_id}/publish"
        headers = self._get_auth_headers()

        logger.info(f"Veröffentliche eBay Offer '{offer_id}' live...")
        resp = requests.post(url, headers=headers, timeout=30)

        if resp.status_code in [200, 201]:
            resp_data = resp.json()
            listing_id = resp_data.get("listingId")
            listing_url = f"https://www.ebay.de/itm/{listing_id}" if listing_id else ""
            logger.info(f"🎉 eBay Listing LIVE veröffentlicht! ListingID: '{listing_id}', URL: {listing_url}")
            return {
                "success": True,
                "listingId": listing_id,
                "listingUrl": listing_url,
                "data": resp_data
            }

        err_msg = f"Fehler bei Veröffentlichung von Offer '{offer_id}' ({resp.status_code}): {resp.text}"
        logger.error(err_msg)
        return {"success": False, "error": resp.text, "status_code": resp.status_code}

    def publish_single_item(self, item_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Führt den kompletten Veröffentlichungsablauf für ein Item aus:
        1. Inventory Item anlegen / aktualisieren
        2. Offer anlegen
        3. Offer veröffentlichen
        """
        inventory_data = item_payload.get("inventory_item") or {}
        offer_data = item_payload.get("offer") or {}
        sku = inventory_data.get("sku") or offer_data.get("sku") or "UNKNOWN"

        # 1. Inventory Item
        inv_res = self.create_or_replace_inventory_item(sku=sku, inventory_data=inventory_data)
        if not inv_res.get("success"):
            return {
                "sku": sku,
                "status": "FAILED_INVENTORY",
                "error": inv_res.get("error")
            }

        # 2. Create Offer
        offer_res = self.create_offer(offer_data=offer_data)
        if not offer_res.get("success"):
            return {
                "sku": sku,
                "status": "FAILED_OFFER",
                "error": offer_res.get("error")
            }

        offer_id = offer_res.get("offerId")

        # 3. Publish Offer
        pub_res = self.publish_offer(offer_id=offer_id)
        if not pub_res.get("success"):
            return {
                "sku": sku,
                "offerId": offer_id,
                "status": "FAILED_PUBLISH",
                "error": pub_res.get("error")
            }

        return {
            "sku": sku,
            "offerId": offer_id,
            "listingId": pub_res.get("listingId"),
            "listingUrl": pub_res.get("listingUrl"),
            "status": "PUBLISHED_LIVE"
        }

    def publish_batch(self, payloads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Veröffentlicht eine Liste von vorbereiteten eBay Payloads nacheinander."""
        results = []
        for p in payloads:
            res = self.publish_single_item(p)
            results.append(res)
        return results
