import unittest
import time
from typing import Dict, Any, List
from unittest.mock import MagicMock, patch

from pipeline.models import (
    PriceType,
    MatchGenauigkeit,
    RechercheStatus,
    TargetWebsiteSuggestion,
    ReferenceListing,
    VisualAnalysisResult
)
from services.web_research_service import WebResearchService


class TestWebResearchService(unittest.TestCase):
    def setUp(self):
        self.service = WebResearchService(gemini_service=None, prompts_dir=None)

    # -------------------------------------------------------------------------
    # 1. Pydantic Models & Normalization Tests
    # -------------------------------------------------------------------------
    def test_price_type_enum_parsing(self):
        self.assertEqual(PriceType.from_string("realisierter_verkaufspreis"), PriceType.REALISIERTER_VERKAUFSPREIS)
        self.assertEqual(PriceType.from_string("sold price"), PriceType.REALISIERTER_VERKAUFSPREIS)
        self.assertEqual(PriceType.from_string("hammer price"), PriceType.REALISIERTER_VERKAUFSPREIS)
        self.assertEqual(PriceType.from_string("angebotspreis"), PriceType.ANGEBOTSPREIS)
        self.assertEqual(PriceType.from_string("asking price"), PriceType.ANGEBOTSPREIS)
        self.assertEqual(PriceType.from_string("auktionsgebot"), PriceType.AUKTIONSGEBOT)
        self.assertEqual(PriceType.from_string("schaetzpreis"), PriceType.SCHAETZPREIS)
        self.assertEqual(PriceType.from_string("unknown"), PriceType.UNBEKANNT)
        self.assertEqual(PriceType.from_string(None), PriceType.UNBEKANNT)

    def test_match_genauigkeit_enum_parsing(self):
        self.assertEqual(MatchGenauigkeit.from_string("exakter_treffer"), MatchGenauigkeit.EXAKTER_TREFFER)
        self.assertEqual(MatchGenauigkeit.from_string("exact match"), MatchGenauigkeit.EXAKTER_TREFFER)
        self.assertEqual(MatchGenauigkeit.from_string("modellvariante"), MatchGenauigkeit.MODELLVARIANTE)
        self.assertEqual(MatchGenauigkeit.from_string("aehnliches_objekt"), MatchGenauigkeit.AEHNLICHES_OBJEKT)
        self.assertEqual(MatchGenauigkeit.from_string("kein_treffer"), MatchGenauigkeit.KEIN_TREFFER)
        self.assertEqual(MatchGenauigkeit.from_string(None), MatchGenauigkeit.KEIN_TREFFER)

    def test_recherche_status_enum_parsing(self):
        self.assertEqual(RechercheStatus.from_string("erfolgreich"), RechercheStatus.ERFOLGREICH)
        self.assertEqual(RechercheStatus.from_string("success"), RechercheStatus.ERFOLGREICH)
        self.assertEqual(RechercheStatus.from_string("kein_preis_gefunden"), RechercheStatus.KEIN_PREIS_GEFUNDEN)
        self.assertEqual(RechercheStatus.from_string("zugriff_blockiert"), RechercheStatus.ZUGRIFF_BLOCKIERT)
        self.assertEqual(RechercheStatus.from_string("403 forbidden"), RechercheStatus.ZUGRIFF_BLOCKIERT)
        self.assertEqual(RechercheStatus.from_string("nicht_verfuegbar"), RechercheStatus.NICHT_VERFUEGBAR)

    def test_reference_listing_price_normalizer(self):
        # Float price
        item1 = ReferenceListing(website_name="eBay", preis_eur=150.50)
        self.assertEqual(item1.preis_eur, 150.50)

        # String with Euro symbol
        item2 = ReferenceListing(website_name="Kleinanzeigen", preis_eur=" 290,00 € ")
        self.assertEqual(item2.preis_eur, 290.0)

        # String with thousand separator and decimal comma
        item3 = ReferenceListing(website_name="Pamono", preis_eur="1.250,50 EUR")
        self.assertEqual(item3.preis_eur, 1250.50)

        # None / empty / invalid price
        item4 = ReferenceListing(website_name="1stDibs", preis_eur="")
        self.assertIsNone(item4.preis_eur)

        item5 = ReferenceListing(website_name="1stDibs", preis_eur="Preis auf Anfrage")
        self.assertIsNone(item5.preis_eur)

    # -------------------------------------------------------------------------
    # 2. Phase 1: Visual Analysis Parsing Tests
    # -------------------------------------------------------------------------
    def test_parse_visual_analysis_success(self):
        raw_phase1_data = {
            "id": "42",
            "titel": "Mid-Century Teak Schreibtisch",
            "kategorie": "Möbel",
            "produktbeschreibung": "Eleganter dänischer Teak-Schreibtisch aus den 1960er Jahren...",
            "hersteller_oder_marke": "Arne Vodder",
            "modell_oder_epoche": "Mid-Century Modern",
            "geschaetztes_jahr_oder_epoche": "ca. 1965",
            "authentizitaet": "original",
            "erkannte_nummern_oder_stempel": ["Sibast Furniture Control", "Made in Denmark"],
            "physische_merkmale": {
                "material": "Teakholz massiv",
                "farbe": "Teak natur",
                "laenge_cm": 150.0,
                "breite_cm": 75.0,
                "hoehe_cm": 74.0,
                "durchmesser_cm": None,
                "gewicht_kg": 35.0,
                "logistik_kategorie": "spedition"
            },
            "zustandsbericht": {
                "zustand": "gut",
                "maengel": ["Leichte Wasserflecken links", "Oberflächlicher Kratzer 4cm"],
                "fehlende_teile": [],
                "empfohlene_massnahme": "Oberflächenpolitur mit Teaköl"
            },
            "ziel_webseiten": [
                {
                    "website_name": "eBay",
                    "target_url": "https://www.ebay.de/sch/i.html?_nkw=arne+vodder+teak+desk&LH_Sold=1",
                    "suchbegriff": "Arne Vodder Teak Schreibtisch verkauft",
                    "plattform_typ": "marktplatz",
                    "begruendung": "Realisierte Verkäufe auf dem Gebrauchtmarkt"
                },
                {
                    "website_name": "Pamono",
                    "target_url": "https://www.pamono.de/designers/arne-vodder",
                    "suchbegriff": "Arne Vodder Sibast desk",
                    "plattform_typ": "haendlerplattform",
                    "begruendung": "Händlerangebote für skandinavisches Design"
                }
            ]
        }

        result = self.service.parse_visual_analysis_payload(raw_phase1_data)
        self.assertIsInstance(result, VisualAnalysisResult)
        self.assertEqual(result.id, "42")
        self.assertEqual(result.titel, "Mid-Century Teak Schreibtisch")
        self.assertEqual(result.hersteller_oder_marke, "Arne Vodder")
        self.assertEqual(len(result.erkannte_nummern_oder_stempel), 2)
        self.assertEqual(result.physische_merkmale["laenge_cm"], 150.0)
        self.assertEqual(result.zustandsbericht["zustand"], "gut")
        self.assertEqual(len(result.ziel_webseiten), 2)
        self.assertEqual(result.ziel_webseiten[0].website_name, "eBay")
        self.assertEqual(result.ziel_webseiten[1].website_name, "Pamono")

    def test_parse_visual_analysis_fallback_on_empty(self):
        # Empty or partial dictionary should populate safe defaults without error
        result = self.service.parse_visual_analysis_payload({})
        self.assertIsInstance(result, VisualAnalysisResult)
        self.assertEqual(result.titel, "")
        self.assertEqual(result.ziel_webseiten, [])

    # -------------------------------------------------------------------------
    # 3. Phase 2: Single Site Research & Error Handling
    # -------------------------------------------------------------------------
    def test_research_single_site_with_mock_gemini_success(self):
        class MockGemini:
            def execute_text_prompt(self, prompt_text, images=None, expect_json=True, enable_google_search=False):
                return {
                    "raw_text": "{}",
                    "parsed_json": {
                        "website_name": "eBay",
                        "listing_titel": "Original Arne Vodder Schreibtisch Teak Sibast",
                        "preis_eur": 450.0,
                        "urspruengliche_waehrung": "EUR",
                        "preis_typ": "realisierter_verkaufspreis",
                        "match_genauigkeit": "exakter_treffer",
                        "zustand_referenz": "Sehr guter Vintage-Zustand mit leichten Altersspuren",
                        "quell_url": "https://www.ebay.de/itm/123456789",
                        "recherche_status": "erfolgreich"
                    }
                }

        service = WebResearchService(gemini_service=MockGemini())
        target = {
            "website_name": "eBay",
            "target_url": "https://www.ebay.de/sch/...",
            "suchbegriff": "Arne Vodder Desk"
        }
        obj_summary = {"titel": "Teak Schreibtisch", "material": "Teak"}

        listing = service.research_single_site(target=target, object_summary=obj_summary)
        self.assertIsInstance(listing, ReferenceListing)
        self.assertEqual(listing.website_name, "eBay")
        self.assertEqual(listing.preis_eur, 450.0)
        self.assertEqual(listing.urspruengliche_waehrung, "EUR")
        self.assertEqual(listing.preis_typ, PriceType.REALISIERTER_VERKAUFSPREIS)
        self.assertEqual(listing.match_genauigkeit, MatchGenauigkeit.EXAKTER_TREFFER)
        self.assertEqual(listing.recherche_status, RechercheStatus.ERFOLGREICH)
        self.assertEqual(listing.quell_url, "https://www.ebay.de/itm/123456789")

    def test_research_single_site_graceful_on_blocked_access(self):
        class BlockedMockGemini:
            def execute_text_prompt(self, prompt_text, images=None, expect_json=True, enable_google_search=False):
                return {
                    "raw_text": "{}",
                    "parsed_json": {
                        "website_name": "1stDibs",
                        "listing_titel": "",
                        "preis_eur": None,
                        "urspruengliche_waehrung": "EUR",
                        "preis_typ": "unbekannt",
                        "match_genauigkeit": "kein_treffer",
                        "zustand_referenz": "",
                        "quell_url": "https://www.1stdibs.com/dealers/...",
                        "recherche_status": "zugriff_blockiert"
                    }
                }

        service = WebResearchService(gemini_service=BlockedMockGemini())
        target = {"website_name": "1stDibs", "target_url": "https://www.1stdibs.com"}
        listing = service.research_single_site(target=target, object_summary={})

        self.assertEqual(listing.recherche_status, RechercheStatus.ZUGRIFF_BLOCKIERT)
        self.assertIsNone(listing.preis_eur)
        self.assertEqual(listing.website_name, "1stDibs")

    def test_research_single_site_graceful_on_exception(self):
        class CrashingMockGemini:
            def execute_text_prompt(self, prompt_text, images=None, expect_json=True, enable_google_search=False):
                raise RuntimeError("Google API Rate limit or network disconnect")

        service = WebResearchService(gemini_service=CrashingMockGemini())
        target = {"website_name": "Dorotheum", "target_url": "https://www.dorotheum.com"}
        # Must NOT raise exception!
        listing = service.research_single_site(target=target, object_summary={})

        self.assertEqual(listing.website_name, "Dorotheum")
        self.assertEqual(listing.recherche_status, RechercheStatus.NICHT_VERFUEGBAR)
        self.assertIsNone(listing.preis_eur)

    def test_research_single_site_graceful_on_unpriced(self):
        class UnpricedMockGemini:
            def execute_text_prompt(self, prompt_text, images=None, expect_json=True, enable_google_search=False):
                return {
                    "raw_text": "{}",
                    "parsed_json": {
                        "website_name": "Pamono",
                        "listing_titel": "Teak Desk by Arne Vodder",
                        "preis_eur": None,
                        "urspruengliche_waehrung": "EUR",
                        "preis_typ": "angebotspreis",
                        "match_genauigkeit": "exakter_treffer",
                        "zustand_referenz": "Vintage",
                        "quell_url": "https://www.pamono.de/desk",
                        "recherche_status": "kein_preis_gefunden"
                    }
                }

        service = WebResearchService(gemini_service=UnpricedMockGemini())
        target = {"website_name": "Pamono"}
        listing = service.research_single_site(target=target, object_summary={})

        self.assertEqual(listing.recherche_status, RechercheStatus.KEIN_PREIS_GEFUNDEN)
        self.assertIsNone(listing.preis_eur)
        self.assertEqual(listing.match_genauigkeit, MatchGenauigkeit.EXAKTER_TREFFER)

    # -------------------------------------------------------------------------
    # 4. Phase 2: Parallel Concurrent Execution Tests
    # -------------------------------------------------------------------------
    def test_research_all_sites_parallel_concurrency(self):
        # Verify that 10 site requests execute concurrently via thread pool
        targets = [
            {"website_name": f"Platform_{i}", "target_url": f"https://platform{i}.com"}
            for i in range(1, 11)
        ]

        class SlowConcurrentMock:
            def execute_text_prompt(self, prompt_text, images=None, expect_json=True, enable_google_search=False):
                time.sleep(0.05)  # 50ms per site
                return {
                    "raw_text": "{}",
                    "parsed_json": {
                        "website_name": "MockPlatform",
                        "listing_titel": "Vergleichsartikel",
                        "preis_eur": 100.0,
                        "urspruengliche_waehrung": "EUR",
                        "preis_typ": "angebotspreis",
                        "match_genauigkeit": "aehnliches_objekt",
                        "zustand_referenz": "gut",
                        "quell_url": "https://mock.com",
                        "recherche_status": "erfolgreich"
                    }
                }

        service = WebResearchService(gemini_service=SlowConcurrentMock())
        t_start = time.time()
        results = service.research_all_sites_parallel(
            targets=targets,
            object_summary={"titel": "Testobjekt"},
            max_workers=10,
            timeout=5.0
        )
        t_elapsed = time.time() - t_start

        # 10 sites * 50ms = 500ms sequentially, but parallel should be under 250ms
        self.assertEqual(len(results), 10)
        self.assertLess(t_elapsed, 0.40)
        for r in results:
            self.assertIsInstance(r, ReferenceListing)
            self.assertEqual(r.preis_eur, 100.0)

    def test_research_all_sites_parallel_handles_individual_timeouts(self):
        targets = [
            {"website_name": "Fast_Site", "target_url": "https://fast.com"},
            {"website_name": "Hanging_Site", "target_url": "https://hang.com"}
        ]

        def mock_research(target, object_summary):
            if "Hanging" in target.get("website_name", ""):
                time.sleep(1.0)  # Exceeds per-site timeout
                return ReferenceListing(website_name=target["website_name"], recherche_status=RechercheStatus.ERFOLGREICH)
            return ReferenceListing(
                website_name=target["website_name"],
                preis_eur=200.0,
                recherche_status=RechercheStatus.ERFOLGREICH
            )

        service = WebResearchService()
        with patch.object(service, "research_single_site", side_effect=mock_research):
            results = service.research_all_sites_parallel(
                targets=targets,
                object_summary={},
                max_workers=2,
                timeout=0.2  # 200ms timeout
            )

        self.assertEqual(len(results), 2)
        fast_item = next(r for r in results if r.website_name == "Fast_Site")
        hanging_item = next(r for r in results if r.website_name == "Hanging_Site")

        self.assertEqual(fast_item.recherche_status, RechercheStatus.ERFOLGREICH)
        self.assertEqual(fast_item.preis_eur, 200.0)
        self.assertEqual(hanging_item.recherche_status, RechercheStatus.NICHT_VERFUEGBAR)

    # -------------------------------------------------------------------------
    # 5. Mock Mode Generation Tests
    # -------------------------------------------------------------------------
    def test_generate_mock_research_produces_10_varied_listings(self):
        listings = self.service.generate_mock_research(
            object_summary={"titel": "Dänischer Teak Tisch", "geschaetzter_preis": 300.0}
        )

        self.assertEqual(len(listings), 10)
        # Verify diversity of price types
        price_types = {l.preis_typ for l in listings}
        self.assertIn(PriceType.REALISIERTER_VERKAUFSPREIS, price_types)
        self.assertIn(PriceType.ANGEBOTSPREIS, price_types)

        # Verify diversity of statuses
        statuses = {l.recherche_status for l in listings}
        self.assertIn(RechercheStatus.ERFOLGREICH, statuses)
        self.assertTrue(any(l.recherche_status != RechercheStatus.ERFOLGREICH for l in listings))

        # Check valid fields on successful items
        successful = [l for l in listings if l.recherche_status == RechercheStatus.ERFOLGREICH]
        self.assertTrue(len(successful) >= 6)
        for s in successful:
            self.assertIsNotNone(s.preis_eur)
            self.assertGreater(s.preis_eur, 0)
            self.assertTrue(s.quell_url.startswith("http"))
            self.assertTrue(len(s.listing_titel) > 0)


if __name__ == "__main__":
    unittest.main()
