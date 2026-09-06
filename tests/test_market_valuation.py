import json
import os
import sys
import tempfile
import shutil
import unittest
import subprocess
from pathlib import Path
from typing import Dict, Any, List

import openpyxl
import pandas as pd

from config.settings import AppConfig, GoogleSettings, PipelineSettings
from pipeline.models import (
    PriceType,
    MatchGenauigkeit,
    RechercheStatus,
    TargetWebsiteSuggestion,
    ReferenceListing,
    VisualAnalysisResult,
    RetailPriceSynthesis,
)
from pipeline.orchestrator import VideoLLMPipeline
from pipeline.state import PipelineState
from services.export_service import ExportService
from services.web_research_service import WebResearchService
from services.appraiser_service import AppraiserService


class TestPhase1And2Parsing(unittest.TestCase):
    """Prüft das Parsing von Phase 1 (Visuelle Analyse) und Phase 2 (10 Plattform-Recherchen)."""

    def setUp(self):
        self.web_service = WebResearchService(gemini_service=None)

    def test_phase1_visual_analysis_parsing_and_ten_targets(self):
        raw_payload = {
            "id": "ARTIKEL-100",
            "titel": "Kaiser Idell Schreibtischlampe Modell 6631",
            "kategorie": "Beleuchtung",
            "produktbeschreibung": "Originale Christian Dell Kaiser Idell Lampe in Schwarz mit Patina.",
            "hersteller_oder_marke": "Gebr. Kaiser & Co. / Christian Dell",
            "modell_oder_epoche": "Bauhaus 1930er",
            "physische_merkmale": {
                "hoehe_cm": 45.0,
                "durchmesser_cm": 28.5,
                "material": "Stahlblech lackiert, Messing"
            },
            "zustandsbericht": {
                "zustand": "gut",
                "maengel": ["Leichte Kratzer am Lampenschirm", "Originalverkabelung gealtert"]
            },
            "ziel_webseiten": [
                {
                    "website_name": "Pamono",
                    "target_url": "https://www.pamono.de/kaiser-idell",
                    "suchbegriff": "Kaiser Idell 6631 Christian Dell",
                    "plattform_typ": "design_galerie",
                    "begruendung": "Führende Plattform für Bauhaus-Designklassiker"
                },
                {
                    "website_name": "eBay",
                    "target_url": "https://www.ebay.de",
                    "suchbegriff": "Kaiser Idell 6631 Original",
                    "plattform_typ": "auktionshaus",
                    "begruendung": "Realisierte Verkäufe zur Marktpreisverifizierung"
                }
            ]
        }

        result = self.web_service.parse_visual_analysis_payload(raw_payload, ensure_ten=True)
        self.assertIsInstance(result, VisualAnalysisResult)
        self.assertEqual(result.titel, "Kaiser Idell Schreibtischlampe Modell 6631")
        self.assertEqual(result.kategorie, "Beleuchtung")
        self.assertEqual(result.hersteller_oder_marke, "Gebr. Kaiser & Co. / Christian Dell")
        self.assertEqual(result.physische_merkmale.get("hoehe_cm"), 45.0)
        self.assertEqual(len(result.zustandsbericht.get("maengel", [])), 2)
        
        # Sicherstellung, dass auf genau 10 Ziel-Webseiten aufgefüllt wurde
        self.assertEqual(len(result.ziel_webseiten), 10)
        site_names = [t.website_name for t in result.ziel_webseiten]
        self.assertIn("Pamono", site_names)
        self.assertIn("eBay", site_names)

    def test_phase2_site_research_response_parsing_success(self):
        target = TargetWebsiteSuggestion(
            website_name="Dorotheum",
            target_url="https://www.dorotheum.com/lot/9988",
            suchbegriff="Christian Dell Schreibtischleuchte"
        )
        object_summary = {
            "titel": "Kaiser Idell 6631",
            "hersteller_oder_marke": "Christian Dell",
            "modell_oder_epoche": "Bauhaus",
            "kategorie": "Beleuchtung",
            "geschaetzter_preis": 350.0
        }

        # Mock-Ergebnis generieren
        listing = self.web_service._create_mock_single_listing(
            site_name=target.website_name,
            target_url=target.target_url,
            object_summary=object_summary
        )

        self.assertIsInstance(listing, ReferenceListing)
        self.assertEqual(listing.website_name, "Dorotheum")
        self.assertIsNotNone(listing.preis_eur)
        self.assertGreater(listing.preis_eur, 0)
        self.assertEqual(listing.urspruengliche_waehrung, "EUR")
        self.assertEqual(listing.preis_typ, PriceType.REALISIERTER_VERKAUFSPREIS)
        self.assertEqual(listing.match_genauigkeit, MatchGenauigkeit.EXAKTER_TREFFER)
        self.assertEqual(listing.recherche_status, RechercheStatus.ERFOLGREICH)
        self.assertTrue(listing.quell_url.startswith("http"))

    def test_phase2_site_research_error_and_blocked_handling(self):
        target = TargetWebsiteSuggestion(
            website_name="BlockedPlatform",
            target_url="https://blocked.example.com",
            suchbegriff="Bauhaus Lampe"
        )
        object_summary = {"titel": "Test Lampe", "geschaetzter_preis": 200.0}

        # Simuliere Exception in GeminiService für research_single_site
        class MockGeminiBlocked:
            def execute_text_prompt(self, *args, **kwargs):
                raise RuntimeError("403 Client Error: Forbidden for url: https://blocked.example.com")

        svc = WebResearchService(gemini_service=MockGeminiBlocked())
        listing = svc.research_single_site(target=target, object_summary=object_summary)

        self.assertEqual(listing.website_name, "BlockedPlatform")
        self.assertIsNone(listing.preis_eur)
        self.assertEqual(listing.recherche_status, RechercheStatus.ZUGRIFF_BLOCKIERT)
        self.assertEqual(listing.preis_typ, PriceType.UNBEKANNT)

    def test_phase2_parallel_mock_execution_returns_ten_listings(self):
        targets = [
            TargetWebsiteSuggestion(website_name=f"Site_{i}", target_url=f"https://site{i}.com")
            for i in range(1, 11)
        ]
        object_summary = {"titel": "Mid-Century Tisch", "geschaetzter_preis": 300.0}

        results = self.web_service.research_all_sites_parallel(
            targets=targets,
            object_summary=object_summary,
            max_workers=5,
            timeout=5.0
        )

        self.assertEqual(len(results), 10)
        for r in results:
            self.assertIsInstance(r, ReferenceListing)
            self.assertTrue(r.website_name.startswith("Site_"))


class TestAppraiserReconciliationAndDiscounting(unittest.TestCase):
    """Prüft die Gutachter-Schlichtung: Realisierte Preise vs. Angebotspreise & Mängelabschläge."""

    def setUp(self):
        self.appraiser_service = AppraiserService(gemini_service=None)

    def test_realized_price_priority_over_dealer_asking_prices(self):
        catalog = {
            "id": "ITEM-1",
            "titel": "Vintage Teak Esstisch",
            "kategorie": "Möbel",
            "geschaetzter_preis": 300.0,
            "zustandsbericht": {"zustand": "gut", "maengel": []}
        }
        listings = [
            ReferenceListing(
                website_name="eBay",
                listing_titel="Teak Esstisch - Verkauft",
                preis_eur=280.0,
                preis_typ=PriceType.REALISIERTER_VERKAUFSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                recherche_status=RechercheStatus.ERFOLGREICH
            ),
            ReferenceListing(
                website_name="Dorotheum",
                listing_titel="Teak Esstisch Hammerpreis",
                preis_eur=300.0,
                preis_typ=PriceType.REALISIERTER_VERKAUFSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                recherche_status=RechercheStatus.ERFOLGREICH
            ),
            ReferenceListing(
                website_name="Pamono",
                listing_titel="Dänischer Teaktisch Galeriepreis",
                preis_eur=900.0,  # Spekulativer Händler-Galeriepreis
                preis_typ=PriceType.ANGEBOTSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                recherche_status=RechercheStatus.ERFOLGREICH
            ),
            ReferenceListing(
                website_name="1stDibs",
                listing_titel="Mid-Century Teak Tisch",
                preis_eur=1100.0,  # Extremer Galeriepreis
                preis_typ=PriceType.ANGEBOTSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                recherche_status=RechercheStatus.ERFOLGREICH
            )
        ]

        synthesis = self.appraiser_service.synthesize_valuation(catalog, listings)
        self.assertIsInstance(synthesis, RetailPriceSynthesis)

        # Die Schätzung darf keinesfalls in den unrealistischen Galeriebereich (>700 €) abdriften,
        # sondern muss durch die realisierten Verkäufe (280 € / 300 €) geankert sein.
        self.assertLess(synthesis.geschaetzter_retail_preis_eur, 500.0)
        self.assertGreater(synthesis.geschaetzter_retail_preis_eur, 200.0)
        self.assertIn("Händler", synthesis.ausreisser_bereinigung_notiz)

    def test_calibrated_condition_discounting(self):
        base_catalog = {
            "id": "ITEM-2",
            "titel": "Meissen Porzellanfigur",
            "kategorie": "Porzellan",
            "geschaetzter_preis": 500.0
        }
        intact_listings = [
            ReferenceListing(
                website_name="Auktionshaus",
                listing_titel="Meissen Figur Makellos",
                preis_eur=500.0,
                preis_typ=PriceType.REALISIERTER_VERKAUFSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                recherche_status=RechercheStatus.ERFOLGREICH
            )
        ]

        # 1. Fall: Stark beschädigt (Chip / Riss -> ca. 35% Abschlag)
        cat_damaged = dict(base_catalog)
        cat_damaged["zustandsbericht"] = {
            "zustand": "beschädigt",
            "maengel": ["Chip an der Hand", "Haarriss am Sockel"]
        }
        synth_damaged = self.appraiser_service.synthesize_valuation(cat_damaged, intact_listings)

        # 2. Fall: Leichte Gebrauchsspuren / Kratzer (ca. 15% Abschlag)
        cat_scratched = dict(base_catalog)
        cat_scratched["zustandsbericht"] = {
            "zustand": "gebraucht",
            "maengel": ["Leichte Kratzer auf der Unterseite"]
        }
        synth_scratched = self.appraiser_service.synthesize_valuation(cat_scratched, intact_listings)

        # 3. Fall: Neuwertig / sehr gut (kein Abschlag)
        cat_mint = dict(base_catalog)
        cat_mint["zustandsbericht"] = {
            "zustand": "neuwertig",
            "maengel": []
        }
        synth_mint = self.appraiser_service.synthesize_valuation(cat_mint, intact_listings)

        self.assertLess(synth_damaged.geschaetzter_retail_preis_eur, synth_scratched.geschaetzter_retail_preis_eur)
        self.assertLess(synth_scratched.geschaetzter_retail_preis_eur, synth_mint.geschaetzter_retail_preis_eur)
        self.assertIn("Mängelabschlag", synth_damaged.begruendung_preisfindung)


class TestMultiSheetExcelExportIntegration(unittest.TestCase):
    """Prüft den Export mit Marktrecherche_Webpreise, HYPERLINK-Formeln und Hauptempfehlung."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.export_service = ExportService(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_multisheet_excel_contains_all_required_sheets_and_hyperlinks(self):
        state = PipelineState(
            item_name="Artikel_42",
            video_path=Path("dummy_42.mp4"),
            run_dir=self.test_dir
        )
        state.detected_id = "ARTIKEL-42"
        state.step1_filter_json = {
            "titel": "Art Déco Tischuhr Junghans",
            "kategorie": "Uhren",
            "produktbeschreibung": "Feine Art Déco Kaminuhr aus Nussbaum.",
            "laenge_cm": 25.0,
            "breite_cm": 12.0,
            "hoehe_cm": 18.0,
            "material": "Nussbaum massiv, Messing",
            "maengel": ["Glas leicht berieben"],
            "preise": {"erwarteter_preis_eur": 220.0}
        }
        state.reference_listings = [
            ReferenceListing(
                website_name="eBay",
                listing_titel="Junghans Art Déco Kaminuhr",
                preis_eur=195.0,
                urspruengliche_waehrung="EUR",
                preis_typ=PriceType.REALISIERTER_VERKAUFSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                zustand_referenz="Funktionsfähig mit Patina",
                quell_url="https://www.ebay.de/itm/55667788",
                recherche_status=RechercheStatus.ERFOLGREICH
            ),
            ReferenceListing(
                website_name="Pamono",
                listing_titel="Junghans Tischuhr 1930er",
                preis_eur=480.0,
                urspruengliche_waehrung="EUR",
                preis_typ=PriceType.ANGEBOTSPREIS,
                match_genauigkeit=MatchGenauigkeit.MODELLVARIANTE,
                zustand_referenz="Restauriert",
                quell_url="https://www.pamono.de/junghans-clock",
                recherche_status=RechercheStatus.ERFOLGREICH
            )
        ]
        state.retail_price_synthesis_json = {
            "geschaetzter_retail_preis_eur": 210.0,
            "preisspanne_min_eur": 175.0,
            "preisspanne_max_eur": 250.0,
            "median_web_preis_eur": 195.0,
            "anzahl_gefundene_preise": 2,
            "begruendung_preisfindung": "Guter Marktwert gestützt durch eBay-Verkauf.",
            "ausreisser_bereinigung_notiz": "Pamono Galeriepreis als spekulativer Aufschlag bewertet.",
            "top_referenz_links": ["https://www.ebay.de/itm/55667788"]
        }

        export_paths = self.export_service.export_single_item(state, base_filename="artikel_42_result")
        excel_path = export_paths["excel"]

        self.assertTrue(excel_path.exists())
        wb = openpyxl.load_workbook(excel_path)

        # Beide Pflichtblätter müssen existieren
        self.assertIn("Hauptempfehlung", wb.sheetnames)
        self.assertIn("Marktrecherche_Webpreise", wb.sheetnames)

        # 1. Hauptempfehlung prüfen
        ws_main = wb["Hauptempfehlung"]
        headers_main = [cell.value for cell in ws_main[1]]
        self.assertIn("Empfohlener_Retail_Preis_EUR", headers_main)
        self.assertIn("Preisspanne_Min_EUR", headers_main)
        self.assertIn("Preisspanne_Max_EUR", headers_main)
        self.assertIn("Median_Web_Preis_EUR", headers_main)
        self.assertIn("Anzahl_gefundene_Webpreise", headers_main)
        self.assertIn("Top_Referenz_Links", headers_main)
        self.assertIn("Begruendung_Preisfindung", headers_main)
        self.assertIn("produktbeschreibung", headers_main)
        self.assertIn("material", headers_main)

        # 2. Marktrecherche_Webpreise prüfen
        ws_web = wb["Marktrecherche_Webpreise"]
        headers_web = [cell.value for cell in ws_web[1]]
        expected_web_headers = [
            "Artikel_ID", "Website_Name", "Produkt_Titel", "Preis_EUR",
            "Preis_Typ", "Match_Genauigkeit", "Zustand_Referenz", "Status", "Link_URL"
        ]
        for eh in expected_web_headers:
            self.assertIn(eh, headers_web)

        # Prüfe Formel in Link_URL
        link_col_idx = headers_web.index("Link_URL") + 1
        formula_cell_val = ws_web.cell(row=2, column=link_col_idx).value
        self.assertTrue(str(formula_cell_val).startswith("=HYPERLINK("))
        self.assertIn("https://www.ebay.de/itm/55667788", str(formula_cell_val))


class TestEndToEndPipelineExecution(unittest.TestCase):
    """Prüft die vollständige Pipeline-Ausführung im --mock Modus von visueller Analyse bis Excel."""

    def setUp(self):
        self.test_root = Path(tempfile.mkdtemp())
        self.input_dir = self.test_root / "input"
        self.output_dir = self.test_root / "output"
        self.artikel_dir = self.input_dir / "artikel"
        self.artikel_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Dummy Artikel-Ordner mit Video und 2 Bildern vorbereiten
        self.item_folder = self.artikel_dir / "Artikel_01"
        self.item_folder.mkdir(parents=True, exist_ok=True)
        
        self.video_file = self.item_folder / "video.mp4"
        self.video_file.write_bytes(b"DUMMY_MP4_CONTENT")
        
        self.img1 = self.item_folder / "img_01.jpg"
        self.img1.write_bytes(b"DUMMY_JPG_1")
        self.img2 = self.item_folder / "img_02.jpg"
        self.img2.write_bytes(b"DUMMY_JPG_2")

        # AppConfig erzeugen
        self.config = AppConfig(
            google=GoogleSettings(api_key="", model_name="gemini-3.5-flash-lite", enable_google_search=False),
            pipeline=PipelineSettings(
                raw_dir=self.input_dir / "raw",
                processed_dir=self.input_dir / "processed",
                artikel_dir=self.artikel_dir,
                input_dir=self.input_dir,
                context_dir=self.test_root / "context",
                output_dir=self.output_dir,
                preview_duration_sec=2.0,
                transcription_language="de"
            ),
            base_dir=Path(__file__).resolve().parent.parent
        )

    def tearDown(self):
        shutil.rmtree(self.test_root, ignore_errors=True)

    def test_pipeline_run_mock_mode_end_to_end(self):
        pipeline = VideoLLMPipeline(
            config=self.config,
            execution_dir=self.output_dir / "test_exec",
            mock_mode=True
        )

        state = pipeline.run(
            video_path=self.video_file,
            image_paths=[self.img1, self.img2],
            item_name="Artikel_01"
        )

        self.assertEqual(state.status, "SUCCESS")
        item_dir = self.output_dir / "test_exec" / "Artikel_01"
        self.assertTrue(item_dir.exists())

        # 1. Zwischenschritt-Artefakte für vollständige Nachvollziehbarkeit prüfen
        self.assertTrue((item_dir / "06_initial_visual_analysis.json").exists())
        self.assertTrue((item_dir / "06_web_research_10_sites.json").exists())
        self.assertTrue((item_dir / "06_retail_price_synthesis.json").exists())
        self.assertTrue((item_dir / "06_prompt_2_parsed.json").exists())
        self.assertTrue((item_dir / "pipeline_trace.json").exists())

        # 2. Exportierte Dateien prüfen
        csv_path = item_dir / "video_result.csv"
        excel_path = item_dir / "video_result.xlsx"
        self.assertTrue(csv_path.exists())
        self.assertTrue(excel_path.exists())

        # 3. Excel-Inhalte validieren
        wb = openpyxl.load_workbook(excel_path)
        self.assertIn("Hauptempfehlung", wb.sheetnames)
        self.assertIn("Marktrecherche_Webpreise", wb.sheetnames)

        ws_web = wb["Marktrecherche_Webpreise"]
        # Zeile 1 = Header, Zeilen 2 bis 11 = 10 recherchierte Webseiten
        self.assertEqual(ws_web.max_row, 11)

        ws_main = wb["Hauptempfehlung"]
        self.assertEqual(ws_main.max_row, 2)
        headers = [c.value for c in ws_main[1]]
        self.assertIn("Empfohlener_Retail_Preis_EUR", headers)
        self.assertIn("Median_Web_Preis_EUR", headers)

    def test_pipeline_with_degraded_research_results(self):
        """Prüft, dass die Pipeline auch bei unvollständigen/teilweise blockierten Seiten stabil durchläuft."""
        pipeline = VideoLLMPipeline(
            config=self.config,
            execution_dir=self.output_dir / "test_exec_degraded",
            mock_mode=True
        )

        # Überschreibe web_research_service, um 4 blockierte Seiten zu simulieren
        orig_research_all = pipeline.web_research_service.research_all_sites_parallel
        def mock_degraded_research(*args, **kwargs):
            results = orig_research_all(*args, **kwargs)
            for idx in range(4):
                results[idx].recherche_status = RechercheStatus.ZUGRIFF_BLOCKIERT
                results[idx].preis_eur = None
            return results

        pipeline.web_research_service.research_all_sites_parallel = mock_degraded_research

        state = pipeline.run(
            video_path=self.video_file,
            image_paths=[self.img1],
            item_name="Artikel_Degraded"
        )

        self.assertEqual(state.status, "SUCCESS")
        self.assertIsNotNone(state.retail_price_synthesis_json)
        self.assertGreater(state.retail_price_synthesis_json.get("geschaetzter_retail_preis_eur", 0), 0)

    def test_cli_mock_mode_execution(self):
        """Prüft, dass main.py mit --mock sauber über die Kommandozeile ausgeführt werden kann."""
        cmd = [
            sys.executable,
            str(Path(__file__).resolve().parent.parent / "main.py"),
            "--mock",
            "-v", str(self.video_file),
            "-i", str(self.img1), str(self.img2),
            "--no-sort"
        ]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=str(Path(__file__).resolve().parent.parent)
        )
        self.assertEqual(res.returncode, 0, f"CLI fehlgeschlagen mit Fehler: {res.stderr}")
        self.assertIn("AUSFÜHRUNG BEENDET", res.stdout)


if __name__ == "__main__":
    unittest.main()
