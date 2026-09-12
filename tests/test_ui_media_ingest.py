import io
import os
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from config.settings import AppConfig, GoogleSettings, PipelineSettings, EbaySettings
from services.ui_server import (
    get_staged_media_info,
    parse_multipart_form_data,
    PipelineRunner,
    StudioHTTPRequestHandler,
)


class TestMediaIngestAndPipeline(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.base_dir = Path(self.temp_dir)
        self.raw_dir = self.base_dir / "input" / "raw"
        self.processed_dir = self.base_dir / "input" / "processed"
        self.artikel_dir = self.base_dir / "input" / "artikel"
        self.output_dir = self.base_dir / "output"
        self.completed_dir = self.base_dir / "input" / "completed"

        for d in [self.raw_dir, self.processed_dir, self.artikel_dir, self.output_dir, self.completed_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self.config = AppConfig(
            google=GoogleSettings(api_key="mock-key", model_name="gemini-3.5-flash-lite"),
            pipeline=PipelineSettings(
                raw_dir=self.raw_dir,
                processed_dir=self.processed_dir,
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

        # Reset runner state
        self.runner = PipelineRunner.get_instance()
        self.runner.reset()

    def tearDown(self):
        self.runner.reset()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_staged_media_empty(self):
        info = get_staged_media_info(self.config)
        self.assertEqual(info["raw_count"], 0)
        self.assertEqual(info["raw_images"], 0)
        self.assertEqual(info["raw_videos"], 0)
        self.assertEqual(info["artikel_count"], 0)
        self.assertEqual(len(info["raw_files"]), 0)

    def test_get_staged_media_with_files(self):
        # Create dummy raw files
        (self.raw_dir / "photo1.jpg").write_bytes(b"dummy image")
        (self.raw_dir / "photo2.png").write_bytes(b"dummy png")
        (self.raw_dir / "video1.mp4").write_bytes(b"dummy video")
        (self.raw_dir / "clip.mov").write_bytes(b"dummy mov")

        # Create dummy artikel folder
        art1 = self.artikel_dir / "Artikel_1"
        art1.mkdir()
        (art1 / "tag.jpg").write_bytes(b"tag")
        (art1 / "item.mp4").write_bytes(b"vid")

        info = get_staged_media_info(self.config)
        self.assertEqual(info["raw_count"], 4)
        self.assertEqual(info["raw_images"], 2)
        self.assertEqual(info["raw_videos"], 2)
        self.assertEqual(info["artikel_count"], 1)
        self.assertEqual(len(info["raw_files"]), 4)
        self.assertEqual(info["artikel_folders"][0]["name"], "Artikel_1")
        self.assertEqual(info["artikel_folders"][0]["files_count"], 2)

    def test_parse_multipart_form_data(self):
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        content_type = f"multipart/form-data; boundary={boundary}"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="files"; filename="sample_tag.jpg"\r\n'
            f"Content-Type: image/jpeg\r\n\r\n"
            f"binary_image_content_123\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="files"; filename="sample_vid.mp4"\r\n'
            f"Content-Type: video/mp4\r\n\r\n"
            f"binary_video_content_456\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")

        parsed_files = parse_multipart_form_data(body, content_type)
        self.assertEqual(len(parsed_files), 2)
        self.assertEqual(parsed_files[0][0], "sample_tag.jpg")
        self.assertEqual(parsed_files[0][1], b"binary_image_content_123")
        self.assertEqual(parsed_files[1][0], "sample_vid.mp4")
        self.assertEqual(parsed_files[1][1], b"binary_video_content_456")

    def test_pipeline_runner_lifecycle(self):
        self.assertEqual(self.runner.status, "IDLE")
        self.assertEqual(self.runner.progress, 0)

        # Mock sorting and pipeline execution
        with patch("services.ui_server.run_sorting_process") as mock_sort, \
             patch("services.ui_server.discover_item_tasks") as mock_tasks:
            
            mock_sort.return_value = [self.artikel_dir / "Artikel_1"]
            mock_tasks.return_value = []

            started = self.runner.start_pipeline(self.config)
            self.assertTrue(started)

            # Wait briefly for thread to finish
            if self.runner.worker_thread:
                self.runner.worker_thread.join(timeout=3.0)

    def test_http_server_endpoints(self):
        import urllib.request
        from http.server import HTTPServer
        import threading

        # Configure handler to use test config
        class TestHandler(StudioHTTPRequestHandler):
            config = self.config

        server = HTTPServer(("127.0.0.1", 0), TestHandler)
        port = server.server_port
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        base_url = f"http://127.0.0.1:{port}"
        try:
            # 1. Test GET /api/staged_media
            req = urllib.request.Request(f"{base_url}/api/staged_media")
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data["raw_count"], 0)

            # 2. Test POST /api/upload
            boundary = "----TestBoundary12345"
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="files"; filename="upload_photo.jpg"\r\n'
                f"Content-Type: image/jpeg\r\n\r\n"
                f"test_image_bytes\r\n"
                f"--{boundary}--\r\n"
            ).encode("utf-8")

            upload_req = urllib.request.Request(
                f"{base_url}/api/upload",
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST"
            )
            with urllib.request.urlopen(upload_req) as resp:
                self.assertEqual(resp.status, 200)
                res_data = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(res_data["success"])
                self.assertEqual(res_data["count"], 1)

            # Verify file in filesystem
            self.assertTrue((self.raw_dir / "upload_photo.jpg").exists())
            self.assertEqual((self.raw_dir / "upload_photo.jpg").read_bytes(), b"test_image_bytes")

            # Verify staged_media now has 1 file
            with urllib.request.urlopen(f"{base_url}/api/staged_media") as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data["raw_count"], 1)
                self.assertEqual(data["raw_images"], 1)

            # 3. Test GET /api/pipeline_status
            with urllib.request.urlopen(f"{base_url}/api/pipeline_status") as resp:
                self.assertEqual(resp.status, 200)
                status_data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(status_data["status"], "IDLE")

            # 4. Test POST /api/run_pipeline with mocked backend
            with patch("services.ui_server.run_sorting_process") as mock_sort, \
                 patch("services.ui_server.discover_item_tasks") as mock_tasks:
                mock_sort.return_value = []
                mock_tasks.return_value = []

                run_req = urllib.request.Request(f"{base_url}/api/run_pipeline", data=b"", method="POST")
                with urllib.request.urlopen(run_req) as resp:
                    self.assertEqual(resp.status, 200)
                    run_resp = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(run_resp["success"])

                # Wait for thread to finish
                if self.runner.worker_thread:
                    self.runner.worker_thread.join(timeout=3.0)

                with urllib.request.urlopen(f"{base_url}/api/pipeline_status") as resp:
                    self.assertEqual(resp.status, 200)
                    status_data = json.loads(resp.read().decode("utf-8"))
                    self.assertIn(status_data["status"], ["COMPLETED", "RUNNING"])

        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()

