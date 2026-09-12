import re
import html
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union
from datetime import datetime
import pandas as pd

from config.settings import EbaySettings

logger = logging.getLogger(__name__)


class EbayService:
    """
    Service zur Vorbereitung, Validierung und Generierung von eBay-Listings.
    Unterstützt:
    - Human-in-the-Loop Datenfilterung (nach VerkaufsOrt und Freigabe-Status)
    - Offizielles eBay Seller Hub / File Exchange CSV-Format
    - eBay Sell Inventory / Offer API JSON-Payloads
    - Einhaltung von eBay-Restriktionen (80-Zeichen Titellimit, ConditionIDs)
    - Responsives HTML-Template für die Artikelbeschreibung
    """

    # Offizielle eBay Condition IDs für Gebrauchtwaren / Antiquitäten
    CONDITION_MAPPING = {
        "neu": (1000, "Neu / Unbenutzt"),
        "neuwertig": (1000, "Neuwertiger Zustand ohne Gebrauchsspuren"),
        "wie_neu": (1500, "Hervorragender Zustand mit minimalsten Lagerspuren"),
        "sehr_gut": (3000, "Sehr guter gebrauchter Zustand"),
        "gut": (3000, "Guter gebrauchter Zustand mit altersüblichen Spuren"),
        "gebraucht": (3000, "Gebrauchter Zustand"),
        "akzeptabel": (3000, "Deutliche Gebrauchsspuren / Altersspuren"),
        "defekt": (7000, "Als Ersatzteil / defekt / restaurierungsbedürftig")
    }

    def __init__(self, settings: Optional[EbaySettings] = None, output_dir: Optional[Path] = None):
        self.settings = settings or EbaySettings()
        self.output_dir = Path(output_dir) if output_dir else Path("output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def map_condition(self, condition_raw: Any) -> Tuple[int, str]:
        """Mappt interne Zustandsangaben auf offizielle eBay ConditionIDs."""
        if not condition_raw:
            return 3000, "Gebrauchter Zustand"

        s = str(condition_raw).strip().lower().replace(" ", "_").replace("-", "_")
        for key, (cid, desc) in self.CONDITION_MAPPING.items():
            if key in s:
                return cid, desc

        return 3000, "Gebraucht"

    def format_ebay_title(self, raw_title: str, max_length: int = 80) -> str:
        """
        Formatiert und kürzt den Artikeltitel auf maximal 80 Zeichen (eBay-Standard).
        Verhindert unsauber abgeschnittene Wörter am Ende.
        """
        clean_title = re.sub(r"\s+", " ", str(raw_title or "").strip())
        if not clean_title:
            return "Antikes Sammlerobjekt / Vintage"

        if len(clean_title) <= max_length:
            return clean_title

        truncated = clean_title[:max_length]
        last_space = truncated.rfind(" ")
        if last_space > 40:
            truncated = truncated[:last_space].strip()

        logger.warning(
            f"eBay-Titel überschritt {max_length} Zeichen und wurde gekürzt:\n"
            f"  Original: '{clean_title}'\n"
            f"  Gekürzt:  '{truncated}'"
        )
        return truncated

    def format_html_description(self, item: Dict[str, Any]) -> str:
        """
        Erstellt eine verkaufsfertige, ansprechende und responsive HTML-Artikelbeschreibung
        für eBay mit Spezifikationstabelle, Zustandsdetails und Maßen.
        """
        title = html.escape(str(item.get("titel") or "Objekt"))
        desc = html.escape(str(item.get("produktbeschreibung") or "")).replace("\n", "<br>")
        kategorie = html.escape(str(item.get("kategorie") or "Antiquität / Sammlerstück"))
        hersteller = html.escape(str(item.get("hersteller_oder_marke") or "Nicht bezeichnet / Unbekannt"))
        epoche = html.escape(str(item.get("modell_oder_epoche") or item.get("geschaetztes_jahr_oder_epoche") or "Vintage"))
        material = html.escape(str(item.get("material") or "Unbekannt"))
        farbe = html.escape(str(item.get("farbe") or "Siehe Bilder"))
        zustand = html.escape(str(item.get("zustand") or "Gebraucht"))
        stempel = html.escape(str(item.get("erkannte_nummern_oder_stempel") or "Keine / Nicht erkennbar"))
        
        maengel = item.get("maengel")
        maengel_str = html.escape(str(maengel)) if maengel and str(maengel).strip() else "Keine wesentlichen Mängel festgestellt"
        
        fehlende_teile = item.get("fehlende_teile")
        fehlende_str = html.escape(str(fehlende_teile)) if fehlende_teile and str(fehlende_teile).strip() else "Vollständig / Keine"

        l = item.get("laenge_cm")
        b = item.get("breite_cm")
        h = item.get("hoehe_cm")
        d = item.get("durchmesser_cm")
        g = item.get("gewicht_kg")
        logistik = html.escape(str(item.get("logistik_kategorie") or "Paketversand"))

        dim_parts = []
        if l: dim_parts.append(f"Länge: {l} cm")
        if b: dim_parts.append(f"Breite: {b} cm")
        if h: dim_parts.append(f"Höhe: {h} cm")
        if d: dim_parts.append(f"Ø: {d} cm")
        if g: dim_parts.append(f"Gewicht: {g} kg")
        massen_str = ", ".join(dim_parts) if dim_parts else "Siehe Detailfotos"

        html_template = f"""<div style="font-family: Arial, Helvetica, sans-serif; max-width: 900px; margin: 0 auto; color: #333; line-height: 1.6; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.05);">
  <div style="background-color: #1f4e79; color: #ffffff; padding: 20px 25px;">
    <h1 style="margin: 0; font-size: 22px; font-weight: bold;">{title}</h1>
    <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">Kategorie: {kategorie} | Epoche: {epoche}</p>
  </div>

  <div style="padding: 25px;">
    <h3 style="color: #1f4e79; border-bottom: 2px solid #1f4e79; padding-bottom: 5px; margin-top: 0;">Artikelbeschreibung</h3>
    <p style="font-size: 15px; margin-bottom: 20px;">{desc}</p>

    <h3 style="color: #1f4e79; border-bottom: 2px solid #1f4e79; padding-bottom: 5px;">Objektdaten & Merkmale</h3>
    <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 14px;">
      <tr style="background-color: #f8f9fa;">
        <td style="padding: 8px 12px; font-weight: bold; width: 35%; border-bottom: 1px solid #e9ecef;">Hersteller / Manufaktur:</td>
        <td style="padding: 8px 12px; border-bottom: 1px solid #e9ecef;">{hersteller}</td>
      </tr>
      <tr>
        <td style="padding: 8px 12px; font-weight: bold; border-bottom: 1px solid #e9ecef;">Modell / Epoche:</td>
        <td style="padding: 8px 12px; border-bottom: 1px solid #e9ecef;">{epoche}</td>
      </tr>
      <tr style="background-color: #f8f9fa;">
        <td style="padding: 8px 12px; font-weight: bold; border-bottom: 1px solid #e9ecef;">Material & Farbe:</td>
        <td style="padding: 8px 12px; border-bottom: 1px solid #e9ecef;">{material} ({farbe})</td>
      </tr>
      <tr>
        <td style="padding: 8px 12px; font-weight: bold; border-bottom: 1px solid #e9ecef;">Stempel / Signaturen:</td>
        <td style="padding: 8px 12px; border-bottom: 1px solid #e9ecef;">{stempel}</td>
      </tr>
      <tr style="background-color: #f8f9fa;">
        <td style="padding: 8px 12px; font-weight: bold; border-bottom: 1px solid #e9ecef;">Abmessungen & Gewicht:</td>
        <td style="padding: 8px 12px; border-bottom: 1px solid #e9ecef;">{massen_str}</td>
      </tr>
    </table>

    <h3 style="color: #1f4e79; border-bottom: 2px solid #1f4e79; padding-bottom: 5px;">Zustandsbericht</h3>
    <div style="background-color: #fdfdfe; border-left: 4px solid #1f4e79; padding: 12px 15px; margin-bottom: 20px; font-size: 14px;">
      <p style="margin: 0 0 6px 0;"><strong>Einstufung:</strong> {zustand}</p>
      <p style="margin: 0 0 6px 0;"><strong>Besonderheiten / Mängel:</strong> {maengel_str}</p>
      <p style="margin: 0;"><strong>Fehlende Teile:</strong> {fehlende_str}</p>
    </div>

    <h3 style="color: #1f4e79; border-bottom: 2px solid #1f4e79; padding-bottom: 5px;">Versand & Verpackung</h3>
    <p style="font-size: 14px; margin-bottom: 0;">
      Sorgfältige und bruchsichere Verpackung. Versandart: <strong>{logistik}</strong>.
      Kombiversand bei mehreren Artikeln auf Anfrage möglich.
    </p>
  </div>
  
  <div style="background-color: #f1f3f5; padding: 12px 25px; font-size: 12px; color: #6c757d; text-align: center; border-top: 1px solid #e0e0e0;">
    Hinweis: Bitte beachten Sie alle hochauflösenden Originalfotos, da diese integraler Bestandteil der Zustandsbeschreibung sind.
  </div>
</div>"""
        return html_template

    def calculate_shipping_cost(self, logistik_kategorie: Any) -> float:
        """Ermittelt die Standard-Versandkosten basierend auf der Logistikeinstufung."""
        s = str(logistik_kategorie or "").strip().lower()
        if "spedition" in s or "freight" in s:
            return self.settings.default_freight_shipping_cost
        elif "sperrgut" in s or "bulky" in s:
            return self.settings.default_bulky_shipping_cost
        return self.settings.default_shipping_cost

    def load_items_from_source(
        self,
        source_path: Union[str, Path],
        status_filter: Optional[str] = "all",
        platform_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Lädt Artikel aus einer Excel-, CSV- oder JSON-Datei.
        Alle Artikel werden standardmäßig für eBay übernommen (kein VerkaufsOrt-Zwang).
        """
        source_path = Path(source_path).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Eingabedatei nicht gefunden: {source_path}")

        records: List[Dict[str, Any]] = []

        if source_path.suffix.lower() in [".xlsx", ".xls"]:
            xl = pd.ExcelFile(source_path)
            sheet_name = None
            for cand in ["Alle_Artikel", "Hauptempfehlung", xl.sheet_names[0]]:
                if cand in xl.sheet_names:
                    sheet_name = cand
                    break
            df = pd.read_excel(source_path, sheet_name=sheet_name)
            records = df.to_dict(orient="records")
        elif source_path.suffix.lower() == ".csv":
            try:
                df = pd.read_csv(source_path, sep=";", encoding="utf-8-sig")
            except Exception:
                df = pd.read_csv(source_path, sep=",", encoding="utf-8-sig")
            records = df.to_dict(orient="records")
        elif source_path.suffix.lower() == ".json":
            with open(source_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    records = data
                elif isinstance(data, dict):
                    records = [data]
        else:
            raise ValueError(f"Nicht unterstütztes Dateiformat: {source_path.suffix}")

        filtered: List[Dict[str, Any]] = []
        for r in records:
            clean_item = {}
            for k, v in r.items():
                k_clean = str(k).strip()
                if k_clean in ["id", "Artikel_ID"] and pd.notna(v):
                    clean_item[k_clean] = str(int(v)) if isinstance(v, (int, float)) and int(v) == v else str(v)
                else:
                    clean_item[k_clean] = v if pd.notna(v) else ""

            verkaufs_ort = str(clean_item.get("VerkaufsOrt", "")).strip().lower()
            status = str(clean_item.get("Status", "")).strip().lower()

            # Optionaler Plattform-Filter (nur wenn explizit gewünscht)
            if platform_filter and platform_filter.lower() != "all":
                if verkaufs_ort and platform_filter.lower() not in verkaufs_ort:
                    continue

            # Optionaler Status-Filter (nur wenn nicht 'all')
            if status_filter and status_filter.lower() != "all":
                accepted_statuses = ["freigegeben", "ready", "ok", "genehmigt", "abgenommen", "aktiv"]
                target_status = status_filter.lower()
                
                if status:
                    if target_status in accepted_statuses and status not in accepted_statuses:
                        continue
                    elif target_status not in accepted_statuses and status != target_status:
                        continue

            filtered.append(clean_item)

        return filtered

    def find_item_images(self, item_id: str, item_name: str = "") -> List[str]:
        """
        Ermittelt alle vorhandenen Bilddateien für einen Artikel aus den bekannten Medienverzeichnissen.
        WICHTIG: Das erste Bild (ID-Bild / Tag-Foto) wird strikt für eBay ausgeschlossen und nicht veröffentlicht!
        """
        image_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic"}
        base_dir = Path(__file__).resolve().parent.parent
        search_dirs = [
            base_dir / "input" / "completed",
            base_dir / "input" / "artikel",
            base_dir / "input" / "processed",
            base_dir / "input" / "raw",
            base_dir / "output"
        ]

        target_names = {
            str(item_id).strip().lower(),
            f"artikel_{item_id}".lower(),
            str(item_name).strip().lower(),
            f"artikel_{item_name}".lower()
        }

        found_images: List[Path] = []
        id_image_name: Optional[str] = None

        for root in search_dirs:
            if not root.exists():
                continue
            for sub in root.iterdir():
                if sub.is_dir() and sub.name.lower() in target_names:
                    # Prüfe sort_info.json auf explizites first_image_id
                    sort_info_file = sub / "sort_info.json"
                    if sort_info_file.exists():
                        try:
                            with open(sort_info_file, "r", encoding="utf-8") as f:
                                si = json.load(f)
                                id_image_name = si.get("first_image_id") or si.get("id_image")
                        except Exception:
                            pass

                    for f in sorted(sub.iterdir(), key=lambda x: x.name):
                        if f.is_file() and f.suffix.lower() in image_exts:
                            found_images.append(f)
                    if found_images:
                        break
            if found_images:
                break

        # Ausschluss des 1. Bildes (ID-Tag / Zettelbild)
        publishable_images: List[Path] = []
        if id_image_name:
            publishable_images = [img for img in found_images if img.name != id_image_name]
        elif len(found_images) > 1:
            publishable_images = found_images[1:]
        else:
            publishable_images = found_images

        # Formatierung: Entweder mit Base-URL oder als relative Dateinamen
        image_urls = []
        base_url = (self.settings.image_base_url or "").rstrip("/")
        for img in publishable_images:
            if base_url:
                folder_name = img.parent.name
                image_urls.append(f"{base_url}/{folder_name}/{img.name}")
            else:
                image_urls.append(img.name)

        return image_urls

    def build_ebay_file_exchange_rows(
        self,
        items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Erstellt Zeilen im offiziellen eBay File Exchange / Seller Hub CSV-Format inklusive PicURL.
        """
        rows = []
        for item in items:
            item_id = str(item.get("id") or item.get("Artikel_ID") or "N/A").strip()
            item_folder = str(item.get("ordner_name") or f"Artikel_{item_id}").strip()
            raw_title = item.get("titel") or item.get("Produkt_Titel") or f"Artikel {item_id}"
            title = self.format_ebay_title(raw_title)

            raw_price = (
                item.get("ErzielterPreis") 
                or item.get("Empfohlener_Retail_Preis_EUR") 
                or item.get("Preis_EUR") 
                or 0.0
            )
            try:
                price_float = float(str(raw_price).replace("€", "").replace(",", ".").strip())
            except Exception:
                price_float = 0.0

            if price_float <= 0.0:
                logger.warning(f"Artikel '{item_id}' hat keinen gültigen Preis ({raw_price}). Standardpreis 1.00 EUR gesetzt.")
                price_float = 1.00

            condition_val = item.get("zustand") or item.get("Zustand") or ""
            cid, cdesc = self.map_condition(condition_val)
            html_desc = self.format_html_description(item)
            shipping_cost = self.calculate_shipping_cost(item.get("logistik_kategorie"))

            # Bilder ermitteln
            images = self.find_item_images(item_id=item_id, item_name=item_folder)
            pic_url_str = "|".join(images) if images else ""

            action_header = f"Action(SiteID={self.settings.site_id}|Country={self.settings.country}|Currency={self.settings.currency})"

            # Format (FixedPrice vs Auction)
            listing_format = str(item.get("AngebotsFormat") or self.settings.listing_type).strip()
            if "auktion" in listing_format.lower() or "auction" in listing_format.lower():
                format_val = "Auction"
                duration_val = "Days_7"
            else:
                format_val = "FixedPrice"
                duration_val = self.settings.listing_duration

            row = {
                action_header: "Add",
                "CustomLabel": item_id,
                "Title": title,
                "Description": html_desc,
                "PicURL": pic_url_str,
                "Format": format_val,
                "Duration": duration_val,
                "StartPrice": f"{price_float:.2f}",
                "BuyItNowPrice": f"{price_float:.2f}",
                "Quantity": 1,
                "ConditionID": cid,
                "ConditionDescription": cdesc,
                "PostalCode": self.settings.postal_code,
                "Location": f"Deutschland, PLZ {self.settings.postal_code}",
                "DispatchTimeMax": self.settings.default_dispatch_days,
                "ShippingService-1:Option": "DE_StandardversandPaket",
                "ShippingService-1:Cost": f"{shipping_cost:.2f}",
                "ReturnsAcceptedOption": "ReturnsAccepted",
                "ReturnsWithinOption": "Days_14",
                "ShippingCostPaidByOption": "Buyer"
            }
            rows.append(row)

        return rows

    def build_ebay_api_payloads(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Erstellt strukturierte JSON-Objekte kompatibel zur eBay Sell Inventory & Offer API inklusive imageUrls."""
        payloads = []
        for item in items:
            item_id = str(item.get("id") or item.get("Artikel_ID") or "N/A").strip()
            item_folder = str(item.get("ordner_name") or f"Artikel_{item_id}").strip()
            raw_title = item.get("titel") or item.get("Produkt_Titel") or f"Artikel {item_id}"
            title = self.format_ebay_title(raw_title)

            raw_price = (
                item.get("ErzielterPreis") 
                or item.get("Empfohlener_Retail_Preis_EUR") 
                or item.get("Preis_EUR") 
                or 0.0
            )
            try:
                price_float = float(str(raw_price).replace("€", "").replace(",", ".").strip())
            except Exception:
                price_float = 0.0

            cid, cdesc = self.map_condition(item.get("zustand"))
            html_desc = self.format_html_description(item)
            shipping_cost = self.calculate_shipping_cost(item.get("logistik_kategorie"))

            # Bilder ermitteln
            images = self.find_item_images(item_id=item_id, item_name=item_folder)

            inventory_item = {
                "sku": item_id,
                "product": {
                    "title": title,
                    "description": html_desc,
                    "imageUrls": images,
                    "aspects": {
                        "Marke": [str(item.get("hersteller_oder_marke") or "Unbekannt")],
                        "Material": [str(item.get("material") or "Unbekannt")],
                        "Farbe": [str(item.get("farbe") or "Unbekannt")],
                        "Epoche": [str(item.get("modell_oder_epoche") or "Vintage")]
                    }
                },
                "condition": "USED_EXCELLENT" if cid == 3000 else ("FOR_PARTS_OR_NOT_WORKING" if cid == 7000 else "NEW"),
                "conditionDescription": cdesc,
                "availability": {
                    "shipToLocationAvailability": {
                        "quantity": 1
                    }
                }
            }

            offer = {
                "sku": item_id,
                "marketplaceId": "EBAY_DE",
                "format": "FIXED_PRICE",
                "pricingSummary": {
                    "price": {
                        "value": f"{price_float:.2f}",
                        "currency": self.settings.currency
                    }
                },
                "listingDuration": "GTC",
                "shippingDetails": {
                    "shippingCost": f"{shipping_cost:.2f}"
                }
            }

            payloads.append({
                "inventory_item": inventory_item,
                "offer": offer
            })

        return payloads

    def export_ebay_batch(
        self,
        items: List[Dict[str, Any]],
        output_dir: Optional[Path] = None,
        filename_prefix: str = "ebay_listings"
    ) -> Dict[str, Any]:
        """
        Exportiert eine Liste von Artikeln in:
        1. eBay Seller Hub File Exchange CSV (`ebay_listings_<timestamp>.csv`)
        2. eBay REST API Payload JSON (`ebay_listings_payload_<timestamp>.json`)
        """
        target_dir = Path(output_dir) if output_dir else self.output_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = target_dir / f"{filename_prefix}_{timestamp_str}.csv"
        json_path = target_dir / f"{filename_prefix}_payload_{timestamp_str}.json"

        # 1. File Exchange CSV
        fe_rows = self.build_ebay_file_exchange_rows(items)
        if fe_rows:
            df = pd.DataFrame(fe_rows)
            df.to_csv(csv_path, index=False, sep=",", encoding="utf-8-sig")
            logger.info(f"eBay File Exchange CSV erfolgreich erstellt: {csv_path} ({len(fe_rows)} Artikel)")
        else:
            logger.warning("Keine Artikel für den eBay-Export vorhanden.")
            pd.DataFrame().to_csv(csv_path, index=False)

        # 2. JSON Payload
        api_payloads = self.build_ebay_api_payloads(items)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(api_payloads, f, ensure_ascii=False, indent=2)
        logger.info(f"eBay API Payloads erfolgreich gespeichert: {json_path}")

        return {
            "csv": csv_path,
            "json": json_path,
            "count": len(items)
        }
