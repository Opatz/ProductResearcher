import json
import unittest
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from unittest.mock import MagicMock

from pipeline.models import (
    PriceType,
    MatchGenauigkeit,
    RechercheStatus,
    ReferenceListing,
    RetailPriceSynthesis,
    VisualAnalysisResult,
    TargetWebsiteSuggestion
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
                preis_eur=300.0,
                preis_typ=PriceType.REALISIERTER_VERKAUFSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                zustand_referenz="Guter Originalzustand",
                quell_url="https://dorotheum.com/1",
                recherche_status=RechercheStatus.ERFOLGREICH
            ),
            ReferenceListing(
                website_name="Pamono",
                listing_titel="Danish Teak Coffee Table",
                preis_eur=750.0,
                preis_typ=PriceType.ANGEBOTSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                zustand_referenz="Restauriert",
                quell_url="https://pamono.de/1",
                recherche_status=RechercheStatus.ERFOLGREICH
            )
        ]

        result = self.service.synthesize_valuation(
            catalog_data=self.sample_catalog,
            reference_listings=listings,
            enable_google_search=False
        )

        self.assertIsInstance(result, RetailPriceSynthesis)
        self.assertTrue(250.0 <= result.geschaetzter_retail_preis_eur <= 350.0)
        self.assertIn("realisierte", result.begruendung_preisfindung.lower())

    def test_asking_price_fallback_with_15_percent_discount_when_no_realized_sales(self):
        asking_listings = [
            ReferenceListing(
                website_name="Kleinanzeigen",
                listing_titel="Teak Tisch Mid-Century VB",
                preis_eur=200.0,
                preis_typ=PriceType.ANGEBOTSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                recherche_status=RechercheStatus.ERFOLGREICH
            ),
            ReferenceListing(
                website_name="Etsy",
                listing_titel="Danish Teak Coffee Table Vintage",
                preis_eur=220.0,
                preis_typ=PriceType.ANGEBOTSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                recherche_status=RechercheStatus.ERFOLGREICH
            )
        ]

        result = self.service.synthesize_valuation(
            catalog_data=self.sample_catalog,
            reference_listings=asking_listings,
            enable_google_search=False
        )

        # Median = 210.0, 15% Haircut -> 178.50 Base * 0.95 (Patina condition discount in sample_catalog) -> 169.58
        self.assertIsInstance(result, RetailPriceSynthesis)
        self.assertEqual(result.anzahl_gefundene_preise, 2)
        self.assertIn("15% sicherheitsabschlag", result.begruendung_preisfindung.lower())
        self.assertIn("fallback auf aktive angebotspreise", result.begruendung_preisfindung.lower())
        self.assertAlmostEqual(result.geschaetzter_retail_preis_eur, 169.58, places=1)

    def test_zero_data_anti_hallucination_policy_returns_zero(self):
        no_price_listings = [
            ReferenceListing(
                website_name="eBay",
                listing_titel="Nicht gefunden",
                preis_eur=None,
                preis_typ=PriceType.UNBEKANNT,
                match_genauigkeit=MatchGenauigkeit.KEIN_TREFFER,
                recherche_status=RechercheStatus.NICHT_VERFUEGBAR
            ),
            ReferenceListing(
                website_name="Barnebys",
                listing_titel="",
                preis_eur=None,
                preis_typ=PriceType.UNBEKANNT,
                match_genauigkeit=MatchGenauigkeit.KEIN_TREFFER,
                recherche_status=RechercheStatus.KEIN_PREIS_GEFUNDEN
            )
        ]

        result = self.service.synthesize_valuation(
            catalog_data=self.sample_catalog,
            reference_listings=no_price_listings,
            enable_google_search=False
        )

        self.assertIsInstance(result, RetailPriceSynthesis)
        self.assertEqual(result.geschaetzter_retail_preis_eur, 0.0)
        self.assertEqual(result.preisspanne_min_eur, 0.0)
        self.assertEqual(result.preisspanne_max_eur, 0.0)
        self.assertEqual(result.anzahl_gefundene_preise, 0)
        self.assertIn("zero-data-policy", result.begruendung_preisfindung.lower())
        self.assertIn("manuelle begutachtung erforderlich", result.begruendung_preisfindung.lower())


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
    """Prüft die Einbettung von Stage 3 in VideoLLMPipeline."""

    def test_orchestrator_executes_stage3_and_persists_artifacts(self):
        import tempfile
        from config.settings import AppConfig, GoogleSettings, PipelineSettings, BASE_DIR
        from pipeline.orchestrator import VideoLLMPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            cfg = AppConfig(
                google=GoogleSettings(api_key="test-api-key", model_name="gemini-test", enable_google_search=False),
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

            pipeline = VideoLLMPipeline(config=cfg, execution_dir=tmp_path / "exec")

            pipeline.video_service.extract_audio = MagicMock(return_value=tmp_path / "audio.mp3")
            pipeline.video_service.trim_video = MagicMock(return_value=tmp_path / "preview.mp4")

            # Mock 3-stage valuation
            mock_vis = VisualAnalysisResult(
                id="99",
                titel="Vintage Teaktisch",
                kategorie="Möbel",
                produktbeschreibung="Schöner Mid-Century Teaktisch",
                hersteller_oder_marke="Dänemark",
                modell_oder_epoche="1960er",
                geschaetztes_jahr_oder_epoche="ca. 1965",
                physische_merkmale={"material": "Teak massiv", "breite_cm": 80.0},
                zustandsbericht={"zustand": "gut", "maengel": []},
                ziel_webseiten=[TargetWebsiteSuggestion(website_name="eBay", target_url="https://ebay.de")]
            )
            pipeline.web_research_service.analyze_visual_and_suggest_targets = MagicMock(return_value=mock_vis)

            mock_listing = ReferenceListing(
                website_name="eBay",
                listing_titel="Teaktisch",
                preis_eur=280.0,
                preis_typ=PriceType.REALISIERTER_VERKAUFSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                recherche_status=RechercheStatus.ERFOLGREICH,
                quell_url="https://ebay.de/1"
            )
            pipeline.web_research_service.research_all_sites_parallel = MagicMock(return_value=[mock_listing])

            mock_synthesis = RetailPriceSynthesis(
                geschaetzter_retail_preis_eur=280.0,
                preisspanne_min_eur=240.0,
                preisspanne_max_eur=320.0,
                median_web_preis_eur=280.0,
                anzahl_gefundene_preise=1,
                begruendung_preisfindung="Echtes Auktionsergebnis.",
                ausreisser_bereinigung_notiz="Keine Ausreißer.",
                produktbeschreibung="Schöner Mid-Century Teaktisch",
                physische_merkmale={"material": "Teak massiv"},
                zustandsbericht={"zustand": "gut"}
            )
            pipeline.appraiser_service.synthesize_valuation = MagicMock(return_value=mock_synthesis)

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
            self.assertTrue((run_dir / "06_initial_visual_analysis.json").exists())

            # 3. Inhaltliche Konsistenz
            synthesis = state.retail_price_synthesis_json
            self.assertEqual(synthesis["geschaetzter_retail_preis_eur"], 280.0)
            self.assertEqual(synthesis["begruendung_preisfindung"], "Echtes Auktionsergebnis.")


if __name__ == "__main__":
    unittest.main()
