import unittest
import tempfile
import shutil
import subprocess
import sys
import json
from pathlib import Path


class TestCLISortRaw(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp()).resolve()
        self.source_dir = self.test_dir / "raw_input"
        self.target_dir = self.test_dir / "artikel_output"
        self.inspect_dir = self.test_dir / "quarantine_inspect"
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.target_dir.mkdir(parents=True, exist_ok=True)
        self.inspect_dir.mkdir(parents=True, exist_ok=True)
        self.main_py = Path(__file__).resolve().parent.parent / "main.py"

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _run_cli(self, args):
        cmd = [sys.executable, str(self.main_py)] + args
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        return result

    def test_cli_help_flags_present(self):
        res = self._run_cli(["--help"])
        self.assertEqual(res.returncode, 0)
        self.assertIn("--sort-raw", res.stdout)
        self.assertIn("--sort-only", res.stdout)
        self.assertIn("--source", res.stdout)
        self.assertIn("--target", res.stdout)
        self.assertIn("--inspect", res.stdout)
        self.assertIn("--copy", res.stdout)

    def test_cli_sort_raw_standalone_move_by_default(self):
        # Create media files in source
        img = self.source_dir / "IMG_101.jpg"
        vid = self.source_dir / "IMG_102.mp4"
        img.write_bytes(b"dummy image")
        vid.write_bytes(b"dummy video")

        res = self._run_cli([
            "--sort-raw",
            "--source", str(self.source_dir),
            "--target", str(self.target_dir),
            "--inspect", str(self.inspect_dir),
            "--mock"
        ])

        self.assertEqual(res.returncode, 0, f"CLI exited with error: {res.stderr}")
        # Default is MOVE: source directory should be cleared
        self.assertFalse(img.exists())
        self.assertFalse(vid.exists())
        self.assertEqual(list(self.source_dir.iterdir()), [])

        # Target should have created an article folder
        created_subdirs = [p for p in self.target_dir.iterdir() if p.is_dir()]
        self.assertEqual(len(created_subdirs), 1)
        article_folder = created_subdirs[0]
        self.assertTrue(article_folder.name.startswith("Artikel_"))
        self.assertTrue((article_folder / "101.jpg").exists())
        self.assertTrue((article_folder / "102.mp4").exists())
        self.assertTrue((article_folder / "sort_info.json").exists())

        # Check console summary output
        self.assertIn("RAW INGEST STANDALONE-SORTIERUNG GESTARTET", res.stdout)
        self.assertIn("RAW INGEST SORTIERUNG ZUSAMMENFASSUNG", res.stdout)
        self.assertIn("VERSCHOBEN (Move)", res.stdout)
        self.assertIn("Standalone-Sortierung abgeschlossen", res.stdout)

    def test_cli_sort_raw_standalone_copy_flag(self):
        # Create media files in source
        img = self.source_dir / "IMG_201.jpg"
        vid = self.source_dir / "IMG_202.mp4"
        img.write_bytes(b"dummy image 2")
        vid.write_bytes(b"dummy video 2")

        res = self._run_cli([
            "--sort-raw",
            "--copy",
            "--source", str(self.source_dir),
            "--target", str(self.target_dir),
            "--inspect", str(self.inspect_dir),
            "--mock"
        ])

        self.assertEqual(res.returncode, 0, f"CLI exited with error: {res.stderr}")
        # When --copy is specified, source files MUST remain untouched
        self.assertTrue(img.exists())
        self.assertTrue(vid.exists())

        # Target should also have received the files
        created_subdirs = [p for p in self.target_dir.iterdir() if p.is_dir()]
        self.assertEqual(len(created_subdirs), 1)
        article_folder = created_subdirs[0]
        self.assertTrue((article_folder / "201.jpg").exists())
        self.assertTrue((article_folder / "202.mp4").exists())

        # Check console output for COPY
        self.assertIn("KOPIEREN (Copy)", res.stdout)
        self.assertIn("KOPIERT (Copy)", res.stdout)

    def test_cli_sort_raw_custom_inspect_routing(self):
        # Create a standalone video (triggers quarantine: video_without_images)
        standalone_vid = self.source_dir / "IMG_301.mp4"
        standalone_vid.write_bytes(b"standalone video")

        res = self._run_cli([
            "--sort-raw",
            "--source", str(self.source_dir),
            "--target", str(self.target_dir),
            "--inspect", str(self.inspect_dir),
            "--mock"
        ])

        self.assertEqual(res.returncode, 0, f"CLI exited with error: {res.stderr}")
        # Standard target should be empty
        self.assertEqual(list(self.target_dir.iterdir()), [])

        # Quarantine inspect directory should contain unassigned_seq_01
        quarantine_folder = self.inspect_dir / "unassigned_seq_01"
        self.assertTrue(quarantine_folder.exists())
        self.assertTrue((quarantine_folder / "301.mp4").exists())
        self.assertTrue((quarantine_folder / "inspection_reason.json").exists())

        reason_data = json.loads((quarantine_folder / "inspection_reason.json").read_text(encoding="utf-8"))
        self.assertEqual(reason_data["quarantine_reason"], "video_without_images")

        # Check console summary mentions quarantine
        self.assertIn("Quarantnisierte Ordner", res.stdout.replace("ä", ""))

    def test_cli_sort_only_alias_compatibility(self):
        img = self.source_dir / "IMG_401.jpg"
        vid = self.source_dir / "IMG_402.mp4"
        img.write_bytes(b"img4")
        vid.write_bytes(b"vid4")

        res = self._run_cli([
            "--sort-only",
            "--source", str(self.source_dir),
            "--target", str(self.target_dir),
            "--mock"
        ])

        self.assertEqual(res.returncode, 0, f"CLI exited with error: {res.stderr}")
        self.assertFalse(img.exists())
        self.assertFalse(vid.exists())
        created = list(self.target_dir.iterdir())
        self.assertEqual(len(created), 1)


if __name__ == "__main__":
    unittest.main()
