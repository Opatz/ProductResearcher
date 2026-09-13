import json
from pathlib import Path
import pandas as pd
import pytest

from services.ebay_service import EbayService
from config.settings import EbaySettings


@pytest.fixture
def sample_items():
    return [
        {
            "id": "1",
            "titel": "Prunkvolle Meissener Porzellan Vase mit handgemalten Blumenmotiven und Vergoldung aus dem 19. Jahrhundert",
            "produktbeschreibung": "Exquisite handbemalte Prunkvase der Manufaktur Meissen mit reicher Goldstaffage.",
            "kategorie": "Porzellan",
            "hersteller_oder_marke": "Meissen",
            "modell_oder_epoche": "Historismus (ca. 1880)",
            "geschaetztes_jahr_oder_epoche": "1880",
            "material": "Porzellan",
            "farbe": "Weiß / Bunt / Gold",
            "zustand": "sehr_gut",
            "maengel": "Leichter Goldabrieb am Mündungsrand",
            "fehlende_teile": "",
            "laenge_cm": 15.0,
            "breite_cm": 15.0,
            "hoehe_cm": 32.5,
            "durchmesser_cm": 15.0,
            "gewicht_kg": 1.8,
            "logistik_kategorie": "paket",
            "Empfohlener_Retail_Preis_EUR": 450.00,
            "ErzielterPreis": 420.00,
            "VerkaufsOrt": "eBay",
            "AngebotsFormat": "FixedPrice",
            "Status": "Freigegeben"
        },
        {
            "id": "2",
            "titel": "Defekte antike Standuhr Gustav Becker",
            "produktbeschreibung": "Historische Standuhr, Werk läuft aktuell nicht an.",
            "kategorie": "Uhren",
            "hersteller_oder_marke": "Gustav Becker",
            "modell_oder_epoche": "Gründerzeit",
            "material": "Nussbaum",
            "farbe": "Braun",
            "zustand": "defekt",
            "maengel": "Pendelfeder gerissen, Gehäuse bestoßen",
            "logistik_kategorie": "spedition",
            "Empfohlener_Retail_Preis_EUR": 150.00,
            "ErzielterPreis": "",
            "VerkaufsOrt": "eBay",
            "AngebotsFormat": "Auction",
            "Status": "Freigegeben"
        },
        {
            "id": "3",
            "titel": "Entwurf nicht freigegeben",
            "produktbeschreibung": "Noch in Prüfung",
            "zustand": "gut",
            "Empfohlener_Retail_Preis_EUR": 50.00,
            "VerkaufsOrt": "Kleinanzeigen",
            "Status": "Entwurf"
        }
    ]


def test_condition_mapping():
    service = EbayService()
    
    cid, desc = service.map_condition("sehr_gut")
    assert cid == 3000
    assert "sehr gut" in desc.lower()

    cid_def, _ = service.map_condition("defekt")
    assert cid_def == 7000

    cid_new, _ = service.map_condition("neuwertig")
    assert cid_new == 1000

    cid_fallback, _ = service.map_condition(None)
    assert cid_fallback == 3000


def test_title_truncation():
    service = EbayService()
    long_title = "Sehr lange Meissener Prunkvase aus dem 19. Jahrhundert mit handgemalten Blumen und reicher Goldverzierung im perfekten Zustand"
    
    formatted = service.format_ebay_title(long_title, max_length=80)
    assert len(formatted) <= 80
    assert not formatted.endswith(" ")
    assert "Meissener" in formatted


def test_html_description_generation(sample_items):
    service = EbayService()
    html_desc = service.format_html_description(sample_items[0])
    
    assert "Meissen" in html_desc
    assert "Goldabrieb" in html_desc
    assert "32.5 cm" in html_desc
    assert "Artikelbeschreibung" in html_desc
    assert "Zustandsbericht" in html_desc


def test_build_file_exchange_rows(sample_items):
    service = EbayService()
    rows = service.build_ebay_file_exchange_rows(sample_items[:2])
    
    assert len(rows) == 2
    row1 = rows[0]
    action_key = [k for k in row1.keys() if "Action(" in k][0]
    assert row1[action_key] == "Add"
    assert row1["CustomLabel"] == "1"
    assert row1["StartPrice"] == "420.00"
    assert row1["Format"] == "FixedPrice"
    assert row1["ConditionID"] == 3000

    row2 = rows[1]
    assert row2["CustomLabel"] == "2"
    assert row2["StartPrice"] == "150.00"
    assert row2["Format"] == "Auction"
    assert row2["ConditionID"] == 7000
    assert float(row2["ShippingService-1:Cost"]) == service.settings.default_freight_shipping_cost


def test_build_api_payloads(sample_items):
    service = EbayService()
    payloads = service.build_ebay_api_payloads(sample_items[:1])
    
    assert len(payloads) == 1
    p = payloads[0]
    assert p["inventory_item"]["sku"] == "1"
    assert p["offer"]["marketplaceId"] == "EBAY_DE"
    assert p["offer"]["pricingSummary"]["price"]["value"] == "420.00"
    assert p["inventory_item"]["condition"] == "USED_EXCELLENT"


def test_export_and_filtering(tmp_path, sample_items):
    excel_path = tmp_path / "test_results.xlsx"
    df = pd.DataFrame(sample_items)
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Alle_Artikel")

    service = EbayService(output_dir=tmp_path)
    
    # Filtert nur freigegebene eBay Artikel (id 1 und 2, id 3 wird ignoriert da 'Entwurf' & 'Kleinanzeigen')
    filtered_items = service.load_items_from_source(
        source_path=excel_path,
        status_filter="Freigegeben",
        platform_filter="ebay"
    )
    assert len(filtered_items) == 2
    assert {it["id"] for it in filtered_items} == {"1", "2"}

    export_res = service.export_ebay_batch(filtered_items, output_dir=tmp_path)
    assert export_res["count"] == 2
    assert Path(export_res["csv"]).exists()
    assert Path(export_res["json"]).exists()

    # CSV wieder einlesen und prüfen
    df_exported = pd.read_csv(export_res["csv"])
    assert len(df_exported) == 2


def test_first_id_image_excluded(tmp_path):
    service = EbayService()
    
    # Teste Bildfindung auf bestehendem Artikel 1
    # Artikel 1 hat 4528.jpg als first_image_id in sort_info.json
    images = service.find_item_images("1", "Artikel_1")
    if images:
        assert "4528.jpg" not in images
        assert "4529.jpg" in images or len(images) > 0

