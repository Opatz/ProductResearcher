import unittest
import tempfile
import shutil
import json
import os
from pathlib import Path
from datetime import datetime

from services.sorter_service import MediaSorterService, MediaSortKey, SortSummary


class TestMediaSorterService(unittest.TestCase):
    def setUp(self):
        self.sorter = MediaSorterService(gemini_service=None)
        self.test_dir = Path(tempfile.mkdtemp())
        self.source_dir = self.test_dir / "raw"
        self.target_dir = self.test_dir / "artikel"
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.target_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # 1. Filename standardization / prefix removal tests
    def test_clean_target_filename_whatsapp(self):
        self.assertEqual(
            self.sorter._clean_target_filename("WhatsApp Image 2026-08-30 at 11.20.06.jpeg"),
            "2026-08-30 at 11.20.06.jpeg"
        )
        self.assertEqual(
            self.sorter._clean_target_filename("WhatsApp Video 2026-08-30 at 11.20.11.mp4"),
            "2026-08-30 at 11.20.11.mp4"
        )
        self.assertEqual(
            self.sorter._clean_target_filename("WhatsApp Unknown 2026-08-30 at 11.22.11.zip"),
            "2026-08-30 at 11.22.11.zip"
        )
        self.assertEqual(
            self.sorter._clean_target_filename("WhatsApp Image 2026-08-30 at 11.20.06 (1).jpeg"),
            "2026-08-30 at 11.20.06 (1).jpeg"
        )

    def test_clean_target_filename_camera(self):
        self.assertEqual(self.sorter._clean_target_filename("IMG_4793.mp4"), "4793.mp4")
        self.assertEqual(self.sorter._clean_target_filename("IMG_4794.jpg"), "4794.jpg")
        self.assertEqual(self.sorter._clean_target_filename("img_4795.jpeg"), "4795.jpeg")
        self.assertEqual(self.sorter._clean_target_filename("DSC_0012.JPG"), "0012.JPG")
        self.assertEqual(self.sorter._clean_target_filename("VID_4796.mp4"), "4796.mp4")
        self.assertEqual(self.sorter._clean_target_filename("PIC_4797.png"), "4797.png")
        self.assertEqual(self.sorter._clean_target_filename("4793.mp4"), "4793.mp4")

    # 2. Key extraction tests
    def test_whatsapp_key_extraction(self):
        f = self.source_dir / "WhatsApp Image 2026-08-30 at 11.20.06 (2).jpeg"
        f.touch()
        key = self.sorter._get_chronological_key(f)
        self.assertEqual(key.file_type, "WHATSAPP")
        self.assertEqual(key.timestamp, datetime(2026, 8, 30, 11, 20, 6))
        self.assertEqual(key.sub_index, 2)
        # Verify tuple unpacking compatibility
        dt, sub_idx, name = key
        self.assertEqual(dt, datetime(2026, 8, 30, 11, 20, 6))
        self.assertEqual(sub_idx, 2)
        self.assertEqual(name, f.name)

    def test_camera_key_extraction(self):
        f = self.source_dir / "IMG_4793.mp4"
        f.touch()
        key = self.sorter._get_chronological_key(f)
        self.assertEqual(key.file_type, "CAMERA")
        self.assertEqual(key.camera_prefix, "IMG")
        self.assertEqual(key.numeric_index, 4793)
        # Verify tuple unpacking compatibility
        dt, num_idx, name = key
        self.assertEqual(num_idx, 4793)
        self.assertEqual(name, f.name)

    def test_dsc_key_extraction(self):
        f = self.source_dir / "DSC_0042.JPG"
        f.touch()
        key = self.sorter._get_chronological_key(f)
        self.assertEqual(key.file_type, "CAMERA")
        self.assertEqual(key.camera_prefix, "DSC")
        self.assertEqual(key.numeric_index, 42)

    def test_exif_datetime_extraction(self):
        from PIL import Image
        img_path = self.source_dir / "test_exif.jpg"
        img = Image.new("RGB", (10, 10), color="blue")
        exif = img.getexif()
        exif[36867] = "2026:08:30 14:15:30"
        img.save(img_path, exif=exif)

        dt = self.sorter._extract_exif_datetime(img_path)
        self.assertEqual(dt, datetime(2026, 8, 30, 14, 15, 30))
        key = self.sorter._get_chronological_key(img_path)
        self.assertEqual(key.timestamp, datetime(2026, 8, 30, 14, 15, 30))

    # 3. Deterministic sorting for pure WhatsApp batches
    def test_whatsapp_batch_ordering(self):
        files = [
            self.source_dir / "WhatsApp Video 2026-08-30 at 11.20.11.mp4",
            self.source_dir / "WhatsApp Image 2026-08-30 at 11.20.06 (1).jpeg",
            self.source_dir / "WhatsApp Image 2026-08-30 at 11.20.06.jpeg",
        ]
        for f in files:
            f.touch()

        keys = [self.sorter._get_chronological_key(f) for f in files]
        sorted_keys = sorted(keys)

        expected_names = [
            "WhatsApp Image 2026-08-30 at 11.20.06.jpeg",
            "WhatsApp Image 2026-08-30 at 11.20.06 (1).jpeg",
            "WhatsApp Video 2026-08-30 at 11.20.11.mp4",
        ]
        self.assertEqual([k.filename for k in sorted_keys], expected_names)

    # 4. Deterministic sorting for pure Camera batches (scrambled order)
    def test_camera_batch_numeric_ordering(self):
        names = [
            "IMG_4795.mp4",
            "IMG_4793.jpg",
            "IMG_4797.mp4",
            "IMG_4794.jpg",
            "IMG_4796.jpg",
        ]
        files = [self.source_dir / n for n in names]
        for f in files:
            f.touch()

        keys = [self.sorter._get_chronological_key(f) for f in files]
        sorted_keys = sorted(keys)

        expected_names = [
            "IMG_4793.jpg",
            "IMG_4794.jpg",
            "IMG_4795.mp4",
            "IMG_4796.jpg",
            "IMG_4797.mp4",
        ]
        self.assertEqual([k.filename for k in sorted_keys], expected_names)

    # 5. Mixed batches: WhatsApp + Camera
    def test_mixed_batch_ordering(self):
        wa_img = self.source_dir / "WhatsApp Image 2026-08-30 at 10.00.00.jpeg"
        wa_vid = self.source_dir / "WhatsApp Video 2026-08-30 at 10.00.15.mp4"
        cam_img = self.source_dir / "IMG_4793.jpg"
        cam_vid = self.source_dir / "IMG_4794.mp4"

        for f in (wa_img, wa_vid, cam_img, cam_vid):
            f.touch()

        # Set mtime on camera files to be after WhatsApp timestamp
        later_ts = datetime(2026, 8, 30, 11, 0, 0).timestamp()
        os.utime(cam_img, (later_ts, later_ts))
        os.utime(cam_vid, (later_ts + 10, later_ts + 10))

        keys = [self.sorter._get_chronological_key(f) for f in [cam_vid, wa_vid, cam_img, wa_img]]
        sorted_keys = sorted(keys)

        expected_order = [
            wa_img.name,
            wa_vid.name,
            cam_img.name,
            cam_vid.name,
        ]
        self.assertEqual([k.filename for k in sorted_keys], expected_order)

    # 6. End-to-end sort_media_files with Camera files
    def test_sort_media_files_camera_integration(self):
        # Create Item 1: IMG_4793.jpg, IMG_4794.jpg, IMG_4795.mp4
        # Create Item 2: IMG_4796.jpg, IMG_4797.mp4
        names = ["IMG_4793.jpg", "IMG_4794.jpg", "IMG_4795.mp4", "IMG_4796.jpg", "IMG_4797.mp4"]
        for n in names:
            (self.source_dir / n).write_bytes(b"dummy media content")

        created_folders = self.sorter.sort_media_files(
            source_dir=self.source_dir,
            target_artikel_dir=self.target_dir,
            move_files=True
        )

        self.assertEqual(len(created_folders), 2)
        # Folder 1
        f1 = created_folders[0]
        manifest1 = json.loads((f1 / "sort_info.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest1["sequence_nr"], 1)
        self.assertEqual(manifest1["video"], "4795.mp4")
        self.assertEqual(manifest1["images"], ["4793.jpg", "4794.jpg"])
        self.assertTrue((f1 / "4793.jpg").exists())
        self.assertTrue((f1 / "4794.jpg").exists())
        self.assertTrue((f1 / "4795.mp4").exists())

        # Folder 2
        f2 = created_folders[1]
        manifest2 = json.loads((f2 / "sort_info.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest2["sequence_nr"], 2)
        self.assertEqual(manifest2["video"], "4797.mp4")
        self.assertEqual(manifest2["images"], ["4796.jpg"])
        self.assertTrue((f2 / "4796.jpg").exists())
        self.assertTrue((f2 / "4797.mp4").exists())

    # 7. End-to-end sort_media_files with WhatsApp files
    def test_sort_media_files_whatsapp_integration(self):
        names = [
            "WhatsApp Image 2026-08-30 at 11.20.06.jpeg",
            "WhatsApp Image 2026-08-30 at 11.20.07.jpeg",
            "WhatsApp Video 2026-08-30 at 11.20.11.mp4",
        ]
        for n in names:
            (self.source_dir / n).write_bytes(b"dummy wa content")

        created_folders = self.sorter.sort_media_files(
            source_dir=self.source_dir,
            target_artikel_dir=self.target_dir,
            move_files=False
        )

        self.assertEqual(len(created_folders), 1)
        f1 = created_folders[0]
        manifest1 = json.loads((f1 / "sort_info.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest1["video"], "2026-08-30 at 11.20.11.mp4")
        self.assertEqual(manifest1["images"], [
            "2026-08-30 at 11.20.06.jpeg",
            "2026-08-30 at 11.20.07.jpeg"
        ])
        self.assertTrue((f1 / "2026-08-30 at 11.20.06.jpeg").exists())
        self.assertTrue((f1 / "2026-08-30 at 11.20.11.mp4").exists())
        # Since move_files=False, source files should still exist
        for n in names:
            self.assertTrue((self.source_dir / n).exists())

    # =========================================================================
    # Issue 02 Tests: Confidence-Aware ID Detection & Article Folder Assembly
    # =========================================================================

    def test_clean_detected_id_normalization(self):
        # Prefix removal and leading zero normalization
        self.assertEqual(self.sorter._clean_detected_id("Artikel 01", 1), "1")
        self.assertEqual(self.sorter._clean_detected_id("ID #042", 1), "42")
        self.assertEqual(self.sorter._clean_detected_id("Nr. 007", 1), "7")
        self.assertEqual(self.sorter._clean_detected_id("Item: 15", 1), "15")
        self.assertEqual(self.sorter._clean_detected_id("Artikel-ID #09", 1), "9")
        self.assertEqual(self.sorter._clean_detected_id("00100", 1), "100")
        # Illegal filesystem characters
        self.assertEqual(self.sorter._clean_detected_id("1/A*B", 1), "1_A_B")
        # Missing / N/A fallback
        self.assertEqual(self.sorter._clean_detected_id("N/A", 5), "5")
        self.assertEqual(self.sorter._clean_detected_id("", 5), "5")
        self.assertEqual(self.sorter._clean_detected_id("unknown", 5), "5")

    def test_detect_id_from_image_with_mock_gemini(self):
        class MockGemini:
            def __init__(self, response_dict):
                self.resp = response_dict

            def execute_text_prompt(self, prompt_text, images=None, expect_json=True):
                return {"parsed_json": self.resp, "raw_response": json.dumps(self.resp)}

        dummy_img = self.source_dir / "tag.jpg"
        dummy_img.touch()

        # 1. High confidence
        sorter_high = MediaSorterService(
            gemini_service=MockGemini({"detected_id": "Artikel 042", "confidence": "high", "visual_description": "tag 42"})
        )
        res_high = sorter_high.detect_id_from_image(dummy_img, fallback_idx=1)
        self.assertEqual(res_high["detected_id"], "42")
        self.assertEqual(res_high["confidence"], "high")
        self.assertTrue(res_high["is_valid"])

        # 2. Low confidence
        sorter_low = MediaSorterService(
            gemini_service=MockGemini({"detected_id": "007", "confidence": "low", "visual_description": "blurry note"})
        )
        res_low = sorter_low.detect_id_from_image(dummy_img, fallback_idx=1)
        self.assertEqual(res_low["detected_id"], "7")
        self.assertEqual(res_low["confidence"], "low")

        # 3. N/A response
        sorter_na = MediaSorterService(
            gemini_service=MockGemini({"detected_id": "N/A", "confidence": "low"})
        )
        res_na = sorter_na.detect_id_from_image(dummy_img, fallback_idx=9)
        self.assertEqual(res_na["detected_id"], "9")
        self.assertFalse(res_na["is_valid"])

    def test_resolve_target_folder_name_with_suffix_and_collisions(self):
        # Base folder
        name1 = self.sorter.resolve_target_folder_name(self.target_dir, "42")
        self.assertEqual(name1, "Artikel_42")
        (self.target_dir / name1).mkdir()

        # First collision
        name2 = self.sorter.resolve_target_folder_name(self.target_dir, "42")
        self.assertEqual(name2, "Artikel_42_1")
        (self.target_dir / name2).mkdir()

        # Second collision
        name3 = self.sorter.resolve_target_folder_name(self.target_dir, "42")
        self.assertEqual(name3, "Artikel_42_2")

        # Suffix with collisions (low confidence)
        inspect_dir = self.test_dir / "inspect"
        inspect_dir.mkdir(parents=True, exist_ok=True)
        q1 = self.sorter.resolve_target_folder_name(inspect_dir, "42", suffix="_low_confidence")
        self.assertEqual(q1, "Artikel_42_low_confidence")
        (inspect_dir / q1).mkdir()

        q2 = self.sorter.resolve_target_folder_name(inspect_dir, "42", suffix="_low_confidence")
        self.assertEqual(q2, "Artikel_42_low_confidence_1")

    def test_sort_media_files_high_and_medium_confidence(self):
        class SequenceMockGemini:
            def __init__(self, responses):
                self.responses = list(responses)

            def execute_text_prompt(self, prompt_text, images=None, expect_json=True):
                resp = self.responses.pop(0) if self.responses else {"detected_id": "99", "confidence": "high"}
                return {"parsed_json": resp, "raw_response": json.dumps(resp)}

        # Item 1: High confidence (ID 101)
        # Item 2: Medium confidence (ID 102)
        mock_gemini = SequenceMockGemini([
            {"detected_id": "Artikel 101", "confidence": "high", "visual_description": "clear tag 101"},
            {"detected_id": "Nr. 0102", "confidence": "medium", "visual_description": "handwritten 102"},
        ])
        sorter = MediaSorterService(gemini_service=mock_gemini)

        (self.source_dir / "IMG_1001.jpg").write_bytes(b"img1")
        (self.source_dir / "IMG_1002.mp4").write_bytes(b"vid1")
        (self.source_dir / "IMG_1003.jpg").write_bytes(b"img2")
        (self.source_dir / "IMG_1004.mp4").write_bytes(b"vid2")

        created = sorter.sort_media_files(
            source_dir=self.source_dir,
            target_artikel_dir=self.target_dir,
            move_files=True
        )

        self.assertEqual(len(created), 2)
        self.assertTrue((self.target_dir / "Artikel_101").exists())
        self.assertTrue((self.target_dir / "Artikel_102").exists())

        m1 = json.loads((self.target_dir / "Artikel_101" / "sort_info.json").read_text(encoding="utf-8"))
        self.assertEqual(m1["detected_id"], "101")
        self.assertEqual(m1["confidence"], "high")

        m2 = json.loads((self.target_dir / "Artikel_102" / "sort_info.json").read_text(encoding="utf-8"))
        self.assertEqual(m2["detected_id"], "102")
        self.assertEqual(m2["confidence"], "medium")

    def test_sort_media_files_low_confidence_quarantine(self):
        class LowConfMockGemini:
            def execute_text_prompt(self, prompt_text, images=None, expect_json=True):
                resp = {"detected_id": "007", "confidence": "low", "visual_description": "blurry label"}
                return {"parsed_json": resp, "raw_response": json.dumps(resp)}

        inspect_dir = self.test_dir / "inspect"
        sorter = MediaSorterService(gemini_service=LowConfMockGemini())

        (self.source_dir / "IMG_2001.jpg").write_bytes(b"img1")
        (self.source_dir / "IMG_2002.mp4").write_bytes(b"vid1")

        created = sorter.sort_media_files(
            source_dir=self.source_dir,
            target_artikel_dir=self.target_dir,
            inspect_dir=inspect_dir,
            move_files=True
        )

        # Standard article folder must NOT be created
        self.assertFalse((self.target_dir / "Artikel_7").exists())

        # Low confidence quarantine folder in inspect_dir must exist
        quarantine_folder = inspect_dir / "Artikel_7_low_confidence"
        self.assertTrue(quarantine_folder.exists())
        self.assertTrue((quarantine_folder / "2001.jpg").exists())
        self.assertTrue((quarantine_folder / "2002.mp4").exists())

        # Verify inspection_reason.json
        inspection_file = quarantine_folder / "inspection_reason.json"
        self.assertTrue(inspection_file.exists())
        reason_data = json.loads(inspection_file.read_text(encoding="utf-8"))
        self.assertEqual(reason_data["quarantine_reason"], "low_confidence_id")
        self.assertEqual(reason_data["proposed_id"], "7")
        self.assertEqual(reason_data["confidence"], "low")
        self.assertEqual(reason_data["video"], "2002.mp4")
        self.assertIn("2001.jpg", reason_data["media_files"])

    def test_sort_media_files_collision_resolution(self):
        class DuplicateIdMockGemini:
            def execute_text_prompt(self, prompt_text, images=None, expect_json=True):
                resp = {"detected_id": "42", "confidence": "high", "visual_description": "tag 42"}
                return {"parsed_json": resp, "raw_response": json.dumps(resp)}

        sorter = MediaSorterService(gemini_service=DuplicateIdMockGemini())

        # Sequence 1
        (self.source_dir / "IMG_3001.jpg").write_bytes(b"img1")
        (self.source_dir / "IMG_3002.mp4").write_bytes(b"vid1")
        # Sequence 2
        (self.source_dir / "IMG_3003.jpg").write_bytes(b"img2")
        (self.source_dir / "IMG_3004.mp4").write_bytes(b"vid2")

        created = sorter.sort_media_files(
            source_dir=self.source_dir,
            target_artikel_dir=self.target_dir,
            move_files=True
        )

        self.assertEqual(len(created), 2)
        self.assertTrue((self.target_dir / "Artikel_42").exists())
        self.assertTrue((self.target_dir / "Artikel_42_1").exists())

    # =========================================================================
    # Issue 03 Tests: Multi-Sequence Quarantine & Stream Resynchronization
    # =========================================================================

    def test_missing_id_quarantine_single_sequence(self):
        class MissingIdMockGemini:
            def execute_text_prompt(self, prompt_text, images=None, expect_json=True):
                resp = {"detected_id": "N/A", "confidence": "low", "visual_description": "no id visible"}
                return {"parsed_json": resp, "raw_response": json.dumps(resp)}

        inspect_dir = self.test_dir / "inspect"
        sorter = MediaSorterService(gemini_service=MissingIdMockGemini())

        (self.source_dir / "IMG_4001.jpg").write_bytes(b"img1")
        (self.source_dir / "IMG_4002.mp4").write_bytes(b"vid1")

        created = sorter.sort_media_files(
            source_dir=self.source_dir,
            target_artikel_dir=self.target_dir,
            inspect_dir=inspect_dir,
            move_files=True
        )

        self.assertEqual(len(created), 1)
        quarantine_folder = inspect_dir / "unassigned_seq_01"
        self.assertTrue(quarantine_folder.exists())
        self.assertTrue((quarantine_folder / "4001.jpg").exists())
        self.assertTrue((quarantine_folder / "4002.mp4").exists())

        # Verify inspection_reason.json
        inspection_file = quarantine_folder / "inspection_reason.json"
        self.assertTrue(inspection_file.exists())
        reason = json.loads(inspection_file.read_text(encoding="utf-8"))
        self.assertEqual(reason["quarantine_reason"], "missing_or_unrecognized_id")
        self.assertEqual(reason["folder_name"], "unassigned_seq_01")
        self.assertIsNone(reason["proposed_id"])
        self.assertEqual(reason["video"], "4002.mp4")
        self.assertEqual(reason["detected_first_image"], "4001.jpg")
        self.assertIn("4001.jpg", reason["media_files"])
        self.assertIn("4002.mp4", reason["media_files"])

        # Verify sort_info.json
        sort_info_file = quarantine_folder / "sort_info.json"
        self.assertTrue(sort_info_file.exists())
        info = json.loads(sort_info_file.read_text(encoding="utf-8"))
        self.assertEqual(info["folder_name"], "unassigned_seq_01")
        self.assertIsNone(info["detected_id"])

    def test_consecutive_missing_ids_quarantine_and_resync(self):
        class SequenceMockGemini:
            def __init__(self, responses):
                self.responses = list(responses)

            def execute_text_prompt(self, prompt_text, images=None, expect_json=True):
                resp = self.responses.pop(0) if self.responses else {"detected_id": "N/A", "confidence": "low"}
                return {"parsed_json": resp, "raw_response": json.dumps(resp)}

        # Item 1: Missing ID (distracted photographer)
        # Item 2: Missing ID (consecutive distraction)
        # Item 3: Valid ID 103 (photographer notices and resynchronizes)
        mock_gemini = SequenceMockGemini([
            {"detected_id": "N/A", "confidence": "low", "visual_description": "no tag"},
            {"detected_id": "unknown", "confidence": "low", "visual_description": "no tag"},
            {"detected_id": "Artikel 103", "confidence": "high", "visual_description": "tag 103"},
        ])

        inspect_dir = self.test_dir / "inspect"
        sorter = MediaSorterService(gemini_service=mock_gemini)

        # Item 1 files
        (self.source_dir / "IMG_5001.jpg").write_bytes(b"item1_img")
        (self.source_dir / "IMG_5002.mp4").write_bytes(b"item1_vid")
        # Item 2 files
        (self.source_dir / "IMG_5003.jpg").write_bytes(b"item2_img")
        (self.source_dir / "IMG_5004.mp4").write_bytes(b"item2_vid")
        # Item 3 files
        (self.source_dir / "IMG_5005.jpg").write_bytes(b"item3_img")
        (self.source_dir / "IMG_5006.mp4").write_bytes(b"item3_vid")

        created = sorter.sort_media_files(
            source_dir=self.source_dir,
            target_artikel_dir=self.target_dir,
            inspect_dir=inspect_dir,
            move_files=True
        )

        self.assertEqual(len(created), 3)

        # Item 1 should be quarantined in unassigned_seq_01
        q1 = inspect_dir / "unassigned_seq_01"
        self.assertTrue(q1.exists())
        self.assertTrue((q1 / "5001.jpg").exists())
        self.assertTrue((q1 / "5002.mp4").exists())
        r1 = json.loads((q1 / "inspection_reason.json").read_text(encoding="utf-8"))
        self.assertEqual(r1["quarantine_reason"], "missing_or_unrecognized_id")

        # Item 2 should be segregated into distinct unassigned_seq_02
        q2 = inspect_dir / "unassigned_seq_02"
        self.assertTrue(q2.exists())
        self.assertTrue((q2 / "5003.jpg").exists())
        self.assertTrue((q2 / "5004.mp4").exists())
        r2 = json.loads((q2 / "inspection_reason.json").read_text(encoding="utf-8"))
        self.assertEqual(r2["quarantine_reason"], "missing_or_unrecognized_id")

        # Item 3 should immediately resynchronize and create Artikel_103 in target_dir
        a3 = self.target_dir / "Artikel_103"
        self.assertTrue(a3.exists())
        self.assertTrue((a3 / "5005.jpg").exists())
        self.assertTrue((a3 / "5006.mp4").exists())
        m3 = json.loads((a3 / "sort_info.json").read_text(encoding="utf-8"))
        self.assertEqual(m3["detected_id"], "103")
        self.assertEqual(m3["confidence"], "high")

    def test_standalone_video_quarantine(self):
        inspect_dir = self.test_dir / "inspect"
        sorter = MediaSorterService(gemini_service=None)

        (self.source_dir / "IMG_6001.mp4").write_bytes(b"standalone_video")

        created = sorter.sort_media_files(
            source_dir=self.source_dir,
            target_artikel_dir=self.target_dir,
            inspect_dir=inspect_dir,
            move_files=True
        )

        self.assertEqual(len(created), 1)
        q_folder = inspect_dir / "unassigned_seq_01"
        self.assertTrue(q_folder.exists())
        self.assertTrue((q_folder / "6001.mp4").exists())

        # Verify inspection_reason.json
        inspection_file = q_folder / "inspection_reason.json"
        self.assertTrue(inspection_file.exists())
        reason = json.loads(inspection_file.read_text(encoding="utf-8"))
        self.assertEqual(reason["quarantine_reason"], "video_without_images")
        self.assertIsNone(reason["proposed_id"])
        self.assertEqual(reason["video"], "6001.mp4")
        self.assertIsNone(reason["detected_first_image"])
        self.assertEqual(reason["media_files"], ["6001.mp4"])

        # Verify sort_info.json
        info = json.loads((q_folder / "sort_info.json").read_text(encoding="utf-8"))
        self.assertEqual(info["folder_name"], "unassigned_seq_01")
        self.assertIsNone(info["detected_id"])
        self.assertEqual(info["video"], "6001.mp4")
        self.assertEqual(info["images"], [])

        # Source dir should be clean
        self.assertFalse((self.source_dir / "IMG_6001.mp4").exists())

    def test_trailing_orphan_media_quarantine(self):
        class ValidIdMockGemini:
            def execute_text_prompt(self, prompt_text, images=None, expect_json=True):
                return {
                    "parsed_json": {"detected_id": "701", "confidence": "high", "visual_description": "item 701"},
                    "raw_response": "{}"
                }

        inspect_dir = self.test_dir / "inspect"
        sorter = MediaSorterService(gemini_service=ValidIdMockGemini())

        # Complete sequence 1: IMG_7001.jpg -> IMG_7002.mp4
        (self.source_dir / "IMG_7001.jpg").write_bytes(b"item1_img")
        (self.source_dir / "IMG_7002.mp4").write_bytes(b"item1_vid")

        # Trailing photos with no concluding video
        (self.source_dir / "IMG_7003.jpg").write_bytes(b"orphan1")
        (self.source_dir / "IMG_7004.jpg").write_bytes(b"orphan2")

        created = sorter.sort_media_files(
            source_dir=self.source_dir,
            target_artikel_dir=self.target_dir,
            inspect_dir=inspect_dir,
            move_files=True
        )

        self.assertEqual(len(created), 2)

        # Article 701 created normally
        a1 = self.target_dir / "Artikel_701"
        self.assertTrue(a1.exists())
        self.assertTrue((a1 / "7001.jpg").exists())
        self.assertTrue((a1 / "7002.mp4").exists())

        # Orphan folder created in inspect_dir
        orphan_folder = inspect_dir / "orphan_trailing_media"
        self.assertTrue(orphan_folder.exists())
        self.assertTrue((orphan_folder / "7003.jpg").exists())
        self.assertTrue((orphan_folder / "7004.jpg").exists())

        # Verify inspection_reason.json
        inspection_file = orphan_folder / "inspection_reason.json"
        self.assertTrue(inspection_file.exists())
        reason = json.loads(inspection_file.read_text(encoding="utf-8"))
        self.assertEqual(reason["quarantine_reason"], "unclosed_sequence_no_video")
        self.assertIsNone(reason["proposed_id"])
        self.assertIsNone(reason["video"])
        self.assertEqual(reason["detected_first_image"], "7003.jpg")
        self.assertEqual(reason["media_files"], ["7003.jpg", "7004.jpg"])

        # Verify sort_info.json
        info = json.loads((orphan_folder / "sort_info.json").read_text(encoding="utf-8"))
        self.assertEqual(info["folder_name"], "orphan_trailing_media")
        self.assertIsNone(info["detected_id"])
        self.assertIsNone(info["video"])
        self.assertEqual(info["images"], ["7003.jpg", "7004.jpg"])

        # Source dir should be completely clean
        self.assertEqual(list(self.source_dir.iterdir()), [])

    def test_mixed_stream_with_distraction_and_orphans(self):
        class MixedMockGemini:
            def __init__(self, responses):
                self.responses = list(responses)

            def execute_text_prompt(self, prompt_text, images=None, expect_json=True):
                resp = self.responses.pop(0) if self.responses else {"detected_id": "999", "confidence": "high"}
                return {"parsed_json": resp, "raw_response": json.dumps(resp)}

        # Responses for images:
        # 1. IMG_8002: high confidence 802
        # 2. IMG_8004: missing ID (N/A)
        # 3. IMG_8006: low confidence 806
        # 4. IMG_8008: high confidence 808
        mock_gemini = MixedMockGemini([
            {"detected_id": "802", "confidence": "high", "visual_description": "tag 802"},
            {"detected_id": "N/A", "confidence": "low", "visual_description": "blurry table"},
            {"detected_id": "806", "confidence": "low", "visual_description": "blurry 806"},
            {"detected_id": "808", "confidence": "high", "visual_description": "tag 808"},
        ])

        inspect_dir = self.test_dir / "inspect"
        sorter = MediaSorterService(gemini_service=mock_gemini)

        # 1. Standalone video
        (self.source_dir / "IMG_8001.mp4").write_bytes(b"vid1")
        # 2. Regular item 802
        (self.source_dir / "IMG_8002.jpg").write_bytes(b"img2")
        (self.source_dir / "IMG_8003.mp4").write_bytes(b"vid3")
        # 3. Forgotten ID item
        (self.source_dir / "IMG_8004.jpg").write_bytes(b"img4")
        (self.source_dir / "IMG_8005.mp4").write_bytes(b"vid5")
        # 4. Low confidence item 806
        (self.source_dir / "IMG_8006.jpg").write_bytes(b"img6")
        (self.source_dir / "IMG_8007.mp4").write_bytes(b"vid7")
        # 5. Resynchronized item 808
        (self.source_dir / "IMG_8008.jpg").write_bytes(b"img8")
        (self.source_dir / "IMG_8009.mp4").write_bytes(b"vid9")
        # 6. Trailing orphan photos
        (self.source_dir / "IMG_8010.jpg").write_bytes(b"img10")
        (self.source_dir / "IMG_8011.jpg").write_bytes(b"img11")

        created = sorter.sort_media_files(
            source_dir=self.source_dir,
            target_artikel_dir=self.target_dir,
            inspect_dir=inspect_dir,
            move_files=True
        )

        # 6 folders in total created:
        # 1. unassigned_seq_01 (standalone video)
        # 2. Artikel_802 (normal)
        # 3. unassigned_seq_02 (missing ID)
        # 4. Artikel_806_low_confidence (low confidence)
        # 5. Artikel_808 (normal resynchronized)
        # 6. orphan_trailing_media (trailing photos)
        self.assertEqual(len(created), 6)

        self.assertTrue((inspect_dir / "unassigned_seq_01" / "8001.mp4").exists())
        self.assertTrue((self.target_dir / "Artikel_802" / "8002.jpg").exists())
        self.assertTrue((self.target_dir / "Artikel_802" / "8003.mp4").exists())
        self.assertTrue((inspect_dir / "unassigned_seq_02" / "8004.jpg").exists())
        self.assertTrue((inspect_dir / "unassigned_seq_02" / "8005.mp4").exists())
        self.assertTrue((inspect_dir / "Artikel_806_low_confidence" / "8006.jpg").exists())
        self.assertTrue((inspect_dir / "Artikel_806_low_confidence" / "8007.mp4").exists())
        self.assertTrue((self.target_dir / "Artikel_808" / "8008.jpg").exists())
        self.assertTrue((self.target_dir / "Artikel_808" / "8009.mp4").exists())
        self.assertTrue((inspect_dir / "orphan_trailing_media" / "8010.jpg").exists())
        self.assertTrue((inspect_dir / "orphan_trailing_media" / "8011.jpg").exists())

        # Source directory must be completely cleared
        self.assertEqual(list(self.source_dir.iterdir()), [])

    # =========================================================================
    # Issue 04 Tests: Standalone Move/Copy Support & Summary Reporting
    # =========================================================================

    def test_sort_summary_tracking(self):
        class MockGeminiSummary:
            def __init__(self, responses):
                self.responses = list(responses)

            def execute_text_prompt(self, prompt_text, images=None, expect_json=True):
                resp = self.responses.pop(0) if self.responses else {"detected_id": "N/A", "confidence": "low"}
                return {"parsed_json": resp, "raw_response": json.dumps(resp)}

        # 1. Standalone video (video_without_images)
        # 2. Regular item 901 (high confidence)
        # 3. Missing ID item (missing_or_unrecognized_id)
        # 4. Low confidence item 903 (low_confidence_id)
        # 5. Trailing orphan photos (unclosed_sequence_no_video)
        mock_gemini = MockGeminiSummary([
            {"detected_id": "901", "confidence": "high", "visual_description": "tag 901"},
            {"detected_id": "N/A", "confidence": "low", "visual_description": "no tag"},
            {"detected_id": "903", "confidence": "low", "visual_description": "blurry 903"},
        ])

        inspect_dir = self.test_dir / "inspect"
        sorter = MediaSorterService(gemini_service=mock_gemini)

        # 1. Standalone video
        (self.source_dir / "IMG_9001.mp4").write_bytes(b"vid1")
        # 2. Item 901
        (self.source_dir / "IMG_9002.jpg").write_bytes(b"img2")
        (self.source_dir / "IMG_9003.mp4").write_bytes(b"vid3")
        # 3. Missing ID
        (self.source_dir / "IMG_9004.jpg").write_bytes(b"img4")
        (self.source_dir / "IMG_9005.mp4").write_bytes(b"vid5")
        # 4. Low confidence 903
        (self.source_dir / "IMG_9006.jpg").write_bytes(b"img6")
        (self.source_dir / "IMG_9007.mp4").write_bytes(b"vid7")
        # 5. Trailing orphan photos
        (self.source_dir / "IMG_9008.jpg").write_bytes(b"img8")

        created = sorter.sort_media_files(
            source_dir=self.source_dir,
            target_artikel_dir=self.target_dir,
            inspect_dir=inspect_dir,
            move_files=True
        )

        self.assertEqual(len(created), 5)
        summary = sorter.last_summary
        self.assertIsNotNone(summary)
        self.assertIsInstance(summary, SortSummary)
        self.assertEqual(summary.total_media_files, 8)
        self.assertEqual(summary.standard_articles, 1)
        self.assertEqual(summary.low_confidence_quarantined, 1)
        self.assertEqual(summary.missing_id_quarantined, 1)
        self.assertEqual(summary.standalone_videos_quarantined, 1)
        self.assertEqual(summary.orphan_trailing_quarantined, 1)
        self.assertEqual(summary.total_quarantined, 4)
        self.assertEqual(summary.total_created, 5)
        self.assertTrue(summary.move_files)
        self.assertEqual(summary.target_artikel_dir, self.target_dir.resolve())
        self.assertEqual(summary.inspect_dir, inspect_dir.resolve())

    def test_move_vs_copy_semantics(self):
        class SimpleMockGemini:
            def execute_text_prompt(self, prompt_text, images=None, expect_json=True):
                return {"parsed_json": {"detected_id": "55", "confidence": "high"}}

        # --- A: Test Copy (move_files=False) ---
        source_copy = self.test_dir / "source_copy"
        target_copy = self.test_dir / "target_copy"
        source_copy.mkdir(parents=True, exist_ok=True)
        target_copy.mkdir(parents=True, exist_ok=True)

        (source_copy / "IMG_5501.jpg").write_bytes(b"copy_img")
        (source_copy / "IMG_5502.mp4").write_bytes(b"copy_vid")

        sorter_copy = MediaSorterService(gemini_service=SimpleMockGemini())
        created_copy = sorter_copy.sort_media_files(
            source_dir=source_copy,
            target_artikel_dir=target_copy,
            move_files=False
        )

        self.assertEqual(len(created_copy), 1)
        self.assertFalse(sorter_copy.last_summary.move_files)
        # Source files must still exist because copy was requested
        self.assertTrue((source_copy / "IMG_5501.jpg").exists())
        self.assertTrue((source_copy / "IMG_5502.mp4").exists())
        # Target files must also exist
        self.assertTrue((target_copy / "Artikel_55" / "5501.jpg").exists())
        self.assertTrue((target_copy / "Artikel_55" / "5502.mp4").exists())

        # --- B: Test Move (move_files=True) ---
        source_move = self.test_dir / "source_move"
        target_move = self.test_dir / "target_move"
        source_move.mkdir(parents=True, exist_ok=True)
        target_move.mkdir(parents=True, exist_ok=True)

        (source_move / "IMG_5503.jpg").write_bytes(b"move_img")
        (source_move / "IMG_5504.mp4").write_bytes(b"move_vid")

        sorter_move = MediaSorterService(gemini_service=SimpleMockGemini())
        created_move = sorter_move.sort_media_files(
            source_dir=source_move,
            target_artikel_dir=target_move,
            move_files=True
        )

        self.assertEqual(len(created_move), 1)
        self.assertTrue(sorter_move.last_summary.move_files)
        # Source files must be moved (source folder is emptied)
        self.assertFalse((source_move / "IMG_5503.jpg").exists())
        self.assertFalse((source_move / "IMG_5504.mp4").exists())
        self.assertEqual(list(source_move.iterdir()), [])
        # Target files must exist
        self.assertTrue((target_move / "Artikel_55" / "5503.jpg").exists())
        self.assertTrue((target_move / "Artikel_55" / "5504.mp4").exists())


if __name__ == "__main__":
    unittest.main()
