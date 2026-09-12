import io
import os
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import urllib.request
from http.server import HTTPServer
import threading
import pandas as pd

from config.settings import AppConfig, GoogleSettings, PipelineSettings, EbaySettings
from services.ui_server import (
    find_item_images,
    find_item_videos,
    StudioHTTPRequestHandler,
)


class TestSplitScreenAndEndpoints(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.base_dir = Path(self.temp_dir)
        self.raw_dir = self.base_dir / "input" / "raw"
        self.artikel_dir = self.base_dir / "input" / "artikel"
        self.output_dir = self.base_dir / "output"
        self.completed_dir = self.base_dir / "input" / "completed"

        for d in [self.raw_dir, self.artikel_dir, self.output_dir, self.completed_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self.config = AppConfig(
            google=GoogleSettings(api_key="mock-key", model_name="gemini-3.5-flash-lite"),
            pipeline=PipelineSettings(
                raw_dir=self.raw_dir,
                processed_dir=self.base_dir / "input" / "processed",
                artikel_dir=self.artikel_dir,
                input_dir=self.artikel_dir,
                context_dir=self.base_dir / "context",
                output_dir=self.output_dir,
                preview_duration_sec=5.0,
                transcription_language="de",
                completed_dir=self.completed_dir,
            ),
            ebay=EbaySettings(),
            base_dir=self.base_dir
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_find_item_images_and_videos(self):
        art1 = self.artikel_dir / "Artikel_1"
        art1.mkdir()
        img1 = art1 / "01_tag.jpg"
        img2 = art1 / "02_detail.png"
        vid1 = art1 / "03_video.mp4"
        vid2 = art1 / "clip.mov"
        doc = art1 / "notes.txt"

        img1.write_bytes(b"img1")
        img2.write_bytes(b"img2")
        vid1.write_bytes(b"vid1")
        vid2.write_bytes(b"vid2")
        doc.write_text("dummy")

        images = find_item_images("1", "Artikel_1", self.base_dir)
        self.assertEqual(len(images), 2)
        self.assertEqual(images[0].name, "01_tag.jpg")
        self.assertEqual(images[1].name, "02_detail.png")

        videos = find_item_videos("1", "Artikel_1", self.base_dir)
        self.assertEqual(len(videos), 2)
        video_names = [v.name for v in videos]
        self.assertIn("03_video.mp4", video_names)
        self.assertIn("clip.mov", video_names)

    def test_api_items_and_media_endpoints(self):
        # Create a sample excel file in output
        art1 = self.artikel_dir / "Artikel_1"
        art1.mkdir(parents=True, exist_ok=True)
        img1 = art1 / "front.jpg"
        img1.write_bytes(b"image_data_jpg")
        vid1 = art1 / "overview.mp4"
        vid1.write_bytes(b"video_data_mp4")

        sample_data = [
            {
                "id": "1",
                "ordner_name": "Artikel_1",
                "titel": "Antike Meissen Porzellan Figur 19. Jhd",
                "produktbeschreibung": "Wunderschöne antike Porzellanfigur.",
                "hersteller_oder_marke": "Meissen",
                "modell_oder_epoche": "Historismus",
                "geschaetztes_jahr_oder_epoche": "1880",
                "material": "Porzellan",
                "farbe": "Weiß/Gold",
                "laenge_cm": 15,
                "breite_cm": 12,
                "hoehe_cm": 25,
                "gewicht_kg": 1.2,
                "zustand": "Sehr gut",
                "maengel": "Keine",
                "fehlende_teile": "",
                "logistik_kategorie": "Paket",
                "Empfohlener_Retail_Preis_EUR": 450.0,
                "Preisspanne_Min_EUR": 380.0,
                "Preisspanne_Max_EUR": 520.0,
                "Median_Web_Preis_EUR": 460.0,
                "Anzahl_gefundene_Webpreise": 6,
                "Begruendung_Preisfindung": "Solide Marktlage für Meissen Figuren.",
                "ErzielterPreis": 450.0,
                "VerkaufsOrt": "eBay",
                "AngebotsFormat": "FixedPrice",
                "Status": "Entwurf"
            },
            {
                "id": "2",
                "ordner_name": "Artikel_2",
                "titel": "Unbekanntes Objekt ohne Preisdaten mit einem sehr sehr langen Titel der die achtzig Zeichen Grenze bei weitem sprengt",
                "produktbeschreibung": "Keine Vergleichsdaten gefunden.",
                "hersteller_oder_marke": "Unbekannt",
                "modell_oder_epoche": "Unbekannt",
                "geschaetztes_jahr_oder_epoche": "Unbekannt",
                "material": "Metall",
                "farbe": "Grau",
                "laenge_cm": 10,
                "breite_cm": 10,
                "hoehe_cm": 10,
                "gewicht_kg": 0.5,
                "zustand": "Gebraucht",
                "maengel": "Kratzer",
                "fehlende_teile": "",
                "logistik_kategorie": "Paket",
                "Empfohlener_Retail_Preis_EUR": 0.0,
                "Preisspanne_Min_EUR": 0.0,
                "Preisspanne_Max_EUR": 0.0,
                "Median_Web_Preis_EUR": 0.0,
                "Anzahl_gefundene_Webpreise": 0,
                "Begruendung_Preisfindung": "Keine Preisquellen ermittelt.",
                "ErzielterPreis": 0.0,
                "VerkaufsOrt": "eBay",
                "AngebotsFormat": "FixedPrice",
                "Status": "Entwurf"
            }
        ]

        df = pd.DataFrame(sample_data)
        excel_path = self.output_dir / "consolidated_execution_results_test.xlsx"
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Alle_Artikel", index=False)

        class TestHandler(StudioHTTPRequestHandler):
            config = self.config
            current_file_path = excel_path

        server = HTTPServer(("127.0.0.1", 0), TestHandler)
        port = server.server_port
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        base_url = f"http://127.0.0.1:{port}"
        try:
            # 1. Test GET /api/items
            req = urllib.request.Request(f"{base_url}/api/items")
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(len(data["items"]), 2)
                item1 = data["items"][0]
                self.assertEqual(item1["id"], "1")
                self.assertEqual(item1["titel"], "Antike Meissen Porzellan Figur 19. Jhd")
                self.assertEqual(item1["hersteller_oder_marke"], "Meissen")
                self.assertTrue("thumbnail_url" in item1)
                self.assertTrue(item1["thumbnail_url"].startswith("/api/image?path="))

            # 2. Test GET /api/images_for_item
            req = urllib.request.Request(f"{base_url}/api/images_for_item?id=1&name=Artikel_1")
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                img_data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(len(img_data["images"]), 1)
                self.assertEqual(img_data["images"][0]["name"], "front.jpg")

            # 3. Test GET /api/videos_for_item
            req = urllib.request.Request(f"{base_url}/api/videos_for_item?id=1&name=Artikel_1")
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                vid_data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(len(vid_data["videos"]), 1)
                self.assertEqual(vid_data["videos"][0]["name"], "overview.mp4")

            # 4. Test GET /api/video
            vid_url = vid_data["videos"][0]["url"]
            req = urllib.request.Request(f"{base_url}{vid_url}")
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.headers.get("Content-Type"), "video/mp4")
                self.assertEqual(resp.read(), b"video_data_mp4")

            # 4b. Test video format MIME types (mov, webm, mkv)
            mov_file = art1 / "test_mov.mov"
            mov_file.write_bytes(b"mov_bytes")
            webm_file = art1 / "test_webm.webm"
            webm_file.write_bytes(b"webm_bytes")

            req_mov = urllib.request.Request(f"{base_url}/api/video?path={urllib.parse.quote(str(mov_file))}")
            with urllib.request.urlopen(req_mov) as resp_mov:
                self.assertEqual(resp_mov.headers.get("Content-Type"), "video/quicktime")

            req_webm = urllib.request.Request(f"{base_url}/api/video?path={urllib.parse.quote(str(webm_file))}")
            with urllib.request.urlopen(req_webm) as resp_webm:
                self.assertEqual(resp_webm.headers.get("Content-Type"), "video/webm")

            # 4c. Test non-existent video/image gives 404
            try:
                urllib.request.urlopen(f"{base_url}/api/video?path=nonexistent.mp4")
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, 404)

            # 5. Test POST /api/save_item with all editable fields
            update_payload = {
                "id": "1",
                "titel": "Meissen Figur 19. Jhdt Bearbeitet",
                "produktbeschreibung": "Aktualisierte Beschreibung.",
                "hersteller_oder_marke": "Meissen Manufaktur",
                "modell_oder_epoche": "Historismus 1880",
                "geschaetztes_jahr_oder_epoche": "1880",
                "material": "Hartporzellan",
                "farbe": "Polychrom",
                "laenge_cm": 16,
                "breite_cm": 13,
                "hoehe_cm": 26,
                "gewicht_kg": 1.3,
                "zustand": "Hervorragend",
                "maengel": "Keine Mängel",
                "fehlende_teile": "",
                "logistik_kategorie": "Sperrgut",
                "ErzielterPreis": 490.0,
                "VerkaufsOrt": "eBay",
                "AngebotsFormat": "FixedPrice",
                "Status": "Freigegeben"
            }

            save_req = urllib.request.Request(
                f"{base_url}/api/save_item",
                data=json.dumps(update_payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(save_req) as resp:
                self.assertEqual(resp.status, 200)
                save_res = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(save_res["success"])

            # Verify saved in Excel
            updated_df = pd.read_excel(excel_path, sheet_name="Alle_Artikel")
            updated_row = updated_df[updated_df["id"].astype(str) == "1"].iloc[0]
            self.assertEqual(updated_row["titel"], "Meissen Figur 19. Jhdt Bearbeitet")
            self.assertEqual(updated_row["Status"], "Freigegeben")
            self.assertEqual(updated_row["hersteller_oder_marke"], "Meissen Manufaktur")
            self.assertEqual(float(updated_row["ErzielterPreis"]), 490.0)

        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
