import json
import unittest
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

from pipeline.models import (
    PriceType,
    MatchGenauigkeit,
    RechercheStatus,
    ReferenceListing,
    RetailPriceSynthesis,
)
from pipeline.state import PipelineState


class TestRetailPriceSynthesisModel(unittest.TestCase):
    """Prüft das Datenmodell RetailPriceSynthesis und State-Integration (Slice 1)."""

    def test_model_validates_required_fields_and_preserves_catalog(self):
        payload = {
            "geschaetzter_retail_preis_eur": "285.50",
            "preisspanne_min_eur": "240.0",
            "preisspanne_max_eur": 350,
            "median_web_preis_eur": "290.00",
            "anzahl_gefundene_preise": "6",
            "begruendung_preisfindung": "Realisierte Verkäufe bei 280 € bilden den Anker.",
            "ausreisser_bereinigung_notiz": "Pamono-Angebotspreis von 660 € als Händler-Aufschlag bereinigt.",
            "produktbeschreibung": "Authentischer Vintage Teaktisch 1960er.",
            "physische_merkmale": {"material": "Teakholz", "breite_cm": 80.0},
            "zustandsbericht": {"zustand": "gebraucht", "maengel": ["Kratzer 5cm"]}
        }
        synthesis = RetailPriceSynthesis(**payload)

        self.assertEqual(synthesis.geschaetzter_retail_preis_eur, 285.50)
        self.assertEqual(synthesis.preisspanne_min_eur, 240.0)
        self.assertEqual(synthesis.preisspanne_max_eur, 350.0)
        self.assertEqual(synthesis.median_web_preis_eur, 290.0)
        self.assertEqual(synthesis.anzahl_gefundene_preise, 6)
        self.assertIn("Realisierte Verkäufe", synthesis.begruendung_preisfindung)
        self.assertIn("Pamono", synthesis.ausreisser_bereinigung_notiz)
        self.assertEqual(synthesis.produktbeschreibung, "Authentischer Vintage Teaktisch 1960er.")
        self.assertEqual(synthesis.physische_merkmale["material"], "Teakholz")
        self.assertEqual(synthesis.zustandsbericht["zustand"], "gebraucht")

    def test_pipeline_state_has_stage3_fields(self):
        state = PipelineState(
            video_path=Path("dummy.mp4"),
            run_dir=Path("dummy_run")
        )
        self.assertTrue(hasattr(state, "retail_price_synthesis_json"))
        self.assertTrue(hasattr(state, "discovered_web_sources"))
        self.assertTrue(hasattr(state, "web_price_summary"))
        self.assertIsNone(state.retail_price_synthesis_json)
        self.assertEqual(state.discovered_web_sources, [])
        self.assertIsNone(state.web_price_summary)


class TestAppraiserServiceReconciliation(unittest.TestCase):
    """Prüft die Preisabstimmung, Priorisierung realisierter Preise und Ausreißerbereinigung (Slice 2)."""

    def setUp(self):
        from services.appraiser_service import AppraiserService
        self.service = AppraiserService()
        self.sample_catalog = {
            "id": "ARTIKEL-42",
            "titel": "Vintage-Designertisch Mid-Century Teak",
            "kategorie": "Möbel",
            "hersteller_oder_marke": "Dänisches Design",
            "modell_oder_epoche": "Mid-Century 1960er",
            "produktbeschreibung": "Eleganter Mid-Century Teakholz-Couchtisch aus Dänemark.",
            "physische_merkmale": {
                "material": "Massivholz Teak",
                "laenge_cm": 120.0,
                "breite_cm": 80.0,
                "hoehe_cm": 75.0,
                "gewicht_kg": 22.0
            },
            "zustandsbericht": {
                "zustand": "gut",
                "maengel": ["Altersübliche Patina"],
                "fehlende_teile": []
            }
        }

    def test_reconciles_platforms_and_prioritizes_realized_prices(self):
        # 10 Reference Listings with disparate platforms
        listings = [
            ReferenceListing(
                website_name="eBay (Beendete Angebote)",
                listing_titel="Teak Couchtisch 60er dänisch verkauft",
                preis_eur=280.0,
                preis_typ=PriceType.REALISIERTER_VERKAUFSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                zustand_referenz="Gebraucht mit leichten Spuren",
                quell_url="https://ebay.de/itm/1",
                recherche_status=RechercheStatus.ERFOLGREICH
            ),
            ReferenceListing(
                website_name="Dorotheum",
                listing_titel="Mid-Century Teaktisch Auktionszuschlag",
                preis_eur=310.0,
                preis_typ=PriceType.REALISIERTER_VERKAUFSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                zustand_referenz="Guter Originalzustand",
                quell_url="https://dorotheum.com/lot/1",
                recherche_status=RechercheStatus.ERFOLGREICH
            ),
            ReferenceListing(
                website_name="Kleinanzeigen",
                listing_titel="Vintage Teak Tisch Couchtisch",
                preis_eur=250.0,
                preis_typ=PriceType.ANGEBOTSPREIS,
                match_genauigkeit=MatchGenauigkeit.MODELLVARIANTE,
                zustand_referenz="Gebraucht",
                quell_url="https://kleinanzeigen.de/1",
                recherche_status=RechercheStatus.ERFOLGREICH
            ),
            ReferenceListing(
                website_name="Pamono",
                listing_titel="Dänischer Teaktisch Galeriepreis",
                preis_eur=750.0,
                preis_typ=PriceType.ANGEBOTSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                zustand_referenz="Hervorragend restauriert",
                quell_url="https://pamono.de/1",
                recherche_status=RechercheStatus.ERFOLGREICH
            ),
            ReferenceListing(
                website_name="1stDibs",
                listing_titel="Rare Mid-Century Teak Coffee Table",
                preis_eur=850.0,
                preis_typ=PriceType.ANGEBOTSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                zustand_referenz="Galerie-Zustand",
                quell_url="https://1stdibs.com/1",
                recherche_status=RechercheStatus.ERFOLGREICH
            ),
            ReferenceListing(
                website_name="Catawiki",
                listing_titel="Dänischer Design-Couchtisch Gebot",
                preis_eur=295.0,
                preis_typ=PriceType.AUKTIONSGEBOT,
                match_genauigkeit=MatchGenauigkeit.MODELLVARIANTE,
                zustand_referenz="Schöne Patina",
                quell_url="https://catawiki.com/1",
                recherche_status=RechercheStatus.ERFOLGREICH
            ),
            ReferenceListing(
                website_name="Invaluable",
                listing_titel="Kein Treffer",
                preis_eur=None,
                recherche_status=RechercheStatus.KEIN_PREIS_GEFUNDEN
            ),
            ReferenceListing(
                website_name="LiveAuctioneers",
                listing_titel="Modernistischer Marmortisch",
                preis_eur=1500.0,
                preis_typ=PriceType.ANGEBOTSPREIS,
                match_genauigkeit=MatchGenauigkeit.KEIN_TREFFER,
                recherche_status=RechercheStatus.ERFOLGREICH
            )
        ]

        result = self.service.synthesize_valuation(self.sample_catalog, listings)

        # Überprüfe:
        # 1. Retail-Preis liegt im realistischen Bereich der Verkäufe (nahe 280-310 €), nicht bei 750-850 €
        self.assertGreaterEqual(result.geschaetzter_retail_preis_eur, 260.0)
        self.assertLessEqual(result.geschaetzter_retail_preis_eur, 360.0)

        # 2. Min-Max Spanne
        self.assertLess(result.preisspanne_min_eur, result.geschaetzter_retail_preis_eur)
        self.assertGreater(result.preisspanne_max_eur, result.geschaetzter_retail_preis_eur)

        # 3. Statistischer Median über valide Treffer (250, 280, 295, 310, 750, 850) -> Median liegt bei (290-302.5 €)
        self.assertAlmostEqual(result.median_web_preis_eur, 302.5, delta=15.0)

        # 4. Ausreißer-Bereinigung erwähnt Pamono / 1stDibs oder Nicht-Treffer
        self.assertTrue(len(result.ausreisser_bereinigung_notiz) > 10)
        self.assertTrue(
            "pamono" in result.ausreisser_bereinigung_notiz.lower()
            or "1stdibs" in result.ausreisser_bereinigung_notiz.lower()
            or "händler" in result.ausreisser_bereinigung_notiz.lower()
            or "ausreißer" in result.ausreisser_bereinigung_notiz.lower()
        )

        # 5. Begründung priorisiert realisierte Preise
        self.assertTrue(
            "realisiert" in result.begruendung_preisfindung.lower()
            or "verkauf" in result.begruendung_preisfindung.lower()
            or "auktion" in result.begruendung_preisfindung.lower()
        )

        # 6. Produktbeschreibung und physische Merkmale bleiben erhalten
        self.assertEqual(result.produktbeschreibung, self.sample_catalog["produktbeschreibung"])
        self.assertEqual(result.physische_merkmale["material"], "Massivholz Teak")

    def test_condition_discount_calibration(self):
        reference_listings = [
            ReferenceListing(
                website_name="eBay",
                listing_titel="Dänischer Teaktisch intakt",
                preis_eur=400.0,
                preis_typ=PriceType.REALISIERTER_VERKAUFSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                zustand_referenz="Sehr gut",
                recherche_status=RechercheStatus.ERFOLGREICH
            ),
            ReferenceListing(
                website_name="Catawiki",
                listing_titel="Teaktisch Auktion",
                preis_eur=400.0,
                preis_typ=PriceType.REALISIERTER_VERKAUFSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                zustand_referenz="Intakt",
                recherche_status=RechercheStatus.ERFOLGREICH
            )
        ]

        # Case 1: Mint condition
        cat_mint = dict(self.sample_catalog)
        cat_mint["zustandsbericht"] = {"zustand": "sehr gut", "maengel": [], "fehlende_teile": []}
        res_mint = self.service.synthesize_valuation(cat_mint, reference_listings)

        # Case 2: Moderate damage (scratches, water stains)
        cat_moderate = dict(self.sample_catalog)
        cat_moderate["zustandsbericht"] = {
            "zustand": "gebraucht",
            "maengel": ["Kratzer auf der Oberseite ca. 5 cm", "Wasserflecken am Rand"],
            "fehlende_teile": []
        }
        res_moderate = self.service.synthesize_valuation(cat_moderate, reference_listings)

        # Case 3: Severe damage (crack, chips)
        cat_severe = dict(self.sample_catalog)
        cat_severe["zustandsbericht"] = {
            "zustand": "defekt",
            "maengel": ["Tiefer Riss durch die Tischplatte", "Abplatzung und Chip am Fuß"],
            "fehlende_teile": []
        }
        res_severe = self.service.synthesize_valuation(cat_severe, reference_listings)

        # Assertions
        # Mint should be highest, moderate should be discounted, severe should be lowest
        self.assertGreater(res_mint.geschaetzter_retail_preis_eur, res_moderate.geschaetzter_retail_preis_eur)
        self.assertGreater(res_moderate.geschaetzter_retail_preis_eur, res_severe.geschaetzter_retail_preis_eur)

        # Quantitative checks: Mint ~ 400.0 (1.0 factor, no markup), Moderate ~ 340 (15% off 400), Severe ~ 200 (50% off 400)
        self.assertAlmostEqual(res_mint.geschaetzter_retail_preis_eur, 400.0, delta=10.0)
        self.assertAlmostEqual(res_moderate.geschaetzter_retail_preis_eur, 340.0, delta=25.0)
        self.assertAlmostEqual(res_severe.geschaetzter_retail_preis_eur, 200.0, delta=25.0)

        # Rationale must cite condition/damage
        self.assertTrue("kratzer" in res_moderate.begruendung_preisfindung.lower() or "abschlag" in res_moderate.begruendung_preisfindung.lower())
        self.assertTrue("defekt" in res_severe.begruendung_preisfindung.lower() or "mängel" in res_severe.begruendung_preisfindung.lower())

    def test_weeds_out_reproductions_and_fakes(self):
        listings = [
            ReferenceListing(
                website_name="Etsy",
                listing_titel="Mid-Century Teaktisch Nachbildung Repro Vintage-Stil",
                preis_eur=120.0,
                preis_typ=PriceType.ANGEBOTSPREIS,
                match_genauigkeit=MatchGenauigkeit.MODELLVARIANTE,
                recherche_status=RechercheStatus.ERFOLGREICH
            ),
            ReferenceListing(
                website_name="eBay",
                listing_titel="Original Teak Couchtisch 60er",
                preis_eur=300.0,
                preis_typ=PriceType.REALISIERTER_VERKAUFSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                recherche_status=RechercheStatus.ERFOLGREICH
            )
        ]
        result = self.service.synthesize_valuation(self.sample_catalog, listings)
        self.assertIn("Nachbildung", result.ausreisser_bereinigung_notiz)
        self.assertEqual(result.anzahl_gefundene_preise, 1)
        self.assertEqual(result.geschaetzter_retail_preis_eur, 285.0)

    def test_asking_prices_safety_discount(self):
        # Nur Angebotspreise vorhanden (keine realisierten Verkäufe)
        listings = [
            ReferenceListing(
                website_name="Kleinanzeigen",
                listing_titel="Mid-Century Teak Tisch",
                preis_eur=400.0,
                preis_typ=PriceType.ANGEBOTSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                recherche_status=RechercheStatus.ERFOLGREICH
            ),
            ReferenceListing(
                website_name="Etsy",
                listing_titel="Vintage Teak Couchtisch",
                preis_eur=400.0,
                preis_typ=PriceType.ANGEBOTSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                recherche_status=RechercheStatus.ERFOLGREICH
            )
        ]
        cat = dict(self.sample_catalog)
        cat["zustandsbericht"] = {"zustand": "gut", "maengel": []}
        result = self.service.synthesize_valuation(cat, listings)
        # Median = 400. 15% safety discount => 340.
        self.assertEqual(result.geschaetzter_retail_preis_eur, 340.0)
        self.assertIn("15% sicherheitsabschlag", result.begruendung_preisfindung.lower())


class MockGeminiServiceForAppraiser:
    def __init__(self, should_fail: bool = False, return_data: Optional[Dict[str, Any]] = None):
        self.should_fail = should_fail
        self.return_data = return_data or {
            "geschaetzter_retail_preis_eur": 320.0,
            "preisspanne_min_eur": 270.0,
            "preisspanne_max_eur": 380.0,
            "median_web_preis_eur": 310.0,
            "anzahl_gefundene_preise": 7,
            "begruendung_preisfindung": "LLM Gutachten: Realisierte Verkäufe stützen 320 €.",
            "ausreisser_bereinigung_notiz": "Pamono-Preis ignoriert.",
            "produktbeschreibung": "LLM Verkaufsbeschreibung",
            "physische_merkmale": {"material": "Teakholz"},
            "zustandsbericht": {"zustand": "gut"}
        }

    def execute_text_prompt(self, prompt_text: str, images=None, expect_json=True, enable_google_search=False):
        if self.should_fail:
            raise RuntimeError("Gemini API Rate Limit or 503 Service Unavailable")
        return {
            "raw_text": json.dumps(self.return_data),
            "parsed_json": self.return_data
        }


class TestAppraiserServiceLLM(unittest.TestCase):
    """Prüft die Gemini LLM Integration und das Fehler-Fallback (Slice 4)."""

    def setUp(self):
        from services.appraiser_service import AppraiserService
        self.sample_catalog = {
            "id": "ITEM-101",
            "titel": "Mid-Century Tisch",
            "produktbeschreibung": "Original Beschreibung",
            "physische_merkmale": {"material": "Teak"},
            "zustandsbericht": {"zustand": "gut", "maengel": []}
        }
        self.sample_listings = [
            ReferenceListing(
                website_name="eBay",
                listing_titel="Tisch verkauft",
                preis_eur=300.0,
                preis_typ=PriceType.REALISIERTER_VERKAUFSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                recherche_status=RechercheStatus.ERFOLGREICH
            )
        ]

    def test_llm_synthesis_success(self):
        from services.appraiser_service import AppraiserService
        mock_gemini = MockGeminiServiceForAppraiser(should_fail=False)
        service = AppraiserService(gemini_service=mock_gemini)

        result = service.synthesize_valuation(self.sample_catalog, self.sample_listings)
        self.assertEqual(result.geschaetzter_retail_preis_eur, 320.0)
        self.assertEqual(result.anzahl_gefundene_preise, 7)
        self.assertIn("LLM Gutachten", result.begruendung_preisfindung)

    def test_llm_synthesis_fallback_on_error(self):
        from services.appraiser_service import AppraiserService
        mock_gemini = MockGeminiServiceForAppraiser(should_fail=True)
        service = AppraiserService(gemini_service=mock_gemini)

        # Sollte nicht werfen, sondern auf deterministische Baseline zurückfallen
        result = service.synthesize_valuation(self.sample_catalog, self.sample_listings)
        self.assertIsNotNone(result)
        self.assertEqual(result.geschaetzter_retail_preis_eur, 300.0)
        self.assertEqual(result.anzahl_gefundene_preise, 1)

    def test_web_research_service_delegates_synthesis(self):
        from services.web_research_service import WebResearchService
        web_service = WebResearchService()
        result = web_service.synthesize_retail_valuation(self.sample_catalog, self.sample_listings)
        self.assertIsInstance(result, RetailPriceSynthesis)
        self.assertEqual(result.geschaetzter_retail_preis_eur, 300.0)


class TestPipelineOrchestratorStage3(unittest.TestCase):
    """Prüft die Einbettung von Stage 3 in VideoLLMPipeline (Slice 5)."""

    def test_orchestrator_executes_stage3_and_persists_artifacts(self):
        import tempfile
        from unittest.mock import MagicMock
        from config.settings import AppConfig, GoogleSettings, PipelineSettings, BASE_DIR
        from pipeline.orchestrator import VideoLLMPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            cfg = AppConfig(
                google=GoogleSettings(api_key="", model_name="gemini-test", enable_google_search=False),
                pipeline=PipelineSettings(
                    raw_dir=tmp_path / "raw",
                    processed_dir=tmp_path / "processed",
                    artikel_dir=tmp_path / "artikel",
                    input_dir=tmp_path / "input",
                    context_dir=BASE_DIR / "context",
                    output_dir=tmp_path / "output",
                    preview_duration_sec=5.0,
                    transcription_language="de"
                ),
                base_dir=BASE_DIR
            )

            pipeline = VideoLLMPipeline(config=cfg, execution_dir=tmp_path / "exec", mock_mode=True)

            # Mocke VideoService, damit keine echten Mediendateien benötigt werden
            pipeline.video_service.extract_audio = MagicMock(return_value=tmp_path / "audio.mp3")
            pipeline.video_service.trim_video = MagicMock(return_value=tmp_path / "preview.mp4")

            dummy_video = tmp_path / "Artikel_99" / "dummy_video.mp4"
            dummy_video.parent.mkdir(parents=True, exist_ok=True)
            dummy_video.write_text("fake video content")

            dummy_img = tmp_path / "Artikel_99" / "dummy_image.jpg"
            dummy_img.write_text("fake image content")

            state = pipeline.run(
                video_path=dummy_video,
                image_paths=[dummy_img],
                item_name="Artikel_99"
            )

            # 1. State-Felder müssen befüllt sein
            self.assertIsNotNone(state.retail_price_synthesis_json)
            self.assertIsNotNone(state.web_price_summary)
            self.assertGreater(len(state.discovered_web_sources), 0)

            # 2. Artefakt-Dateien müssen im Run-Verzeichnis existieren
            run_dir = state.run_dir
            self.assertTrue((run_dir / "06_retail_price_synthesis.json").exists())
            self.assertTrue((run_dir / "06_web_research_10_sites.json").exists())
            self.assertTrue((run_dir / "06_prompt_2_parsed.json").exists())

            # 3. Inhaltliche Konsistenz
            synthesis = state.retail_price_synthesis_json
            self.assertIn("geschaetzter_retail_preis_eur", synthesis)
            self.assertIn("begruendung_preisfindung", synthesis)
            self.assertIn("ausreisser_bereinigung_notiz", synthesis)
            self.assertIn("median_web_preis_eur", synthesis)
            self.assertIn("anzahl_gefundene_preise", synthesis)

            # 4. Vollständiger Erhalt von Beschreibung, Maßen und Mängeln in step2_analysis_json
            p2 = state.step2_analysis_json
            self.assertEqual(p2["geschaetzter_retail_preis_eur"], synthesis["geschaetzter_retail_preis_eur"])
            self.assertTrue(len(p2.get("produktbeschreibung", "")) > 10)
            self.assertIn("physische_merkmale", p2)
            self.assertIn("zustandsbericht", p2)
            self.assertEqual(p2["preise"]["prognostizierter_preis_realistisch_eur"], synthesis["geschaetzter_retail_preis_eur"])


if __name__ == "__main__":
    unittest.main()

