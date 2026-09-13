import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from config.settings import AppConfig, GoogleSettings, PipelineSettings
from pipeline.orchestrator import VideoLLMPipeline
from pipeline.state import PipelineState
from pipeline.models import VisualAnalysisResult, ReferenceListing, RetailPriceSynthesis, TargetWebsiteSuggestion


class TestCompletedFolderLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp()).resolve()
        self.raw_dir = self.temp_dir / "input" / "raw"
        self.processed_dir = self.temp_dir / "input" / "processed"
        self.artikel_dir = self.temp_dir / "input" / "artikel"
        self.completed_dir = self.temp_dir / "input" / "completed"
        self.output_dir = self.temp_dir / "output"
        self.context_dir = self.temp_dir / "prompt_context"
        self.prompts_dir = self.temp_dir / "prompts"

        for d in [self.raw_dir, self.processed_dir, self.artikel_dir, self.completed_dir, self.output_dir, self.context_dir, self.prompts_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self.config = AppConfig(
            google=GoogleSettings(
                api_key="mock_key",
                model_name="mock_model",
                enable_google_search=False
            ),
            pipeline=PipelineSettings(
                raw_dir=self.raw_dir,
                processed_dir=self.processed_dir,
                artikel_dir=self.artikel_dir,
                input_dir=self.artikel_dir,
                context_dir=self.context_dir,
                completed_dir=self.completed_dir,
                output_dir=self.output_dir,
                preview_duration_sec=5.0,
                transcription_language="de"
            ),
            base_dir=self.temp_dir
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_mock_visual_analysis(self):
        return VisualAnalysisResult(
            titel="Antike Vase",
            kategorie="Porzellan & Keramik",
            hersteller_oder_marke="Meissen",
            modell_oder_epoche="19. Jhdt.",
            physische_merkmale={"material": "Porzellan"},
            zustandsbericht={"zustand": "Sehr gut"},
            erkannte_nummern_oder_stempel=["123"],
            produktbeschreibung="Eine antike handbemalte Vase.",
            ziel_webseiten=[TargetWebsiteSuggestion(website_name="ExampleSite", target_url="https://example.com/item1")]
        )

    def _create_mock_synthesis(self):
        return RetailPriceSynthesis(
            geschaetzter_retail_preis_eur=250.0,
            preisspanne_min_eur=200.0,
            preisspanne_max_eur=300.0,
            median_web_preis_eur=250.0,
            anzahl_gefundene_preise=1,
            begruendung_preisfindung="Sehr gut erhaltene Porzellanvase.",
            ausreisser_bereinigung_notiz="Keine Ausreisser"
        )

    @patch("pipeline.orchestrator.GeminiService")
    @patch("pipeline.orchestrator.VideoService")
    @patch("pipeline.orchestrator.WebResearchService")
    @patch("pipeline.orchestrator.AppraiserService")
    def test_successful_run_moves_article_folder_to_completed(
        self,
        mock_appraiser_cls,
        mock_research_cls,
        mock_video_cls,
        mock_gemini_cls
    ):
        # Setup mock services
        mock_video = mock_video_cls.return_value
        mock_video.extract_audio.return_value = self.temp_dir / "audio.mp3"

        mock_gemini = mock_gemini_cls.return_value
        mock_gemini.transcribe_audio.return_value = "Audio text"

        mock_research = mock_research_cls.return_value
        mock_research.analyze_visual_and_suggest_targets.return_value = self._create_mock_visual_analysis()
        mock_research.research_all_sites_parallel.return_value = [
            ReferenceListing(
                website_name="ExampleSite",
                listing_titel="Vase",
                preis_eur=200.0,
                preis_typ="angebotspreis",
                quell_url="https://example.com"
            )
        ]

        mock_appraiser = mock_appraiser_cls.return_value
        mock_appraiser.synthesize_valuation.return_value = self._create_mock_synthesis()

        # Create article folder in input/artikel/
        item_dir = self.artikel_dir / "Artikel_42"
        item_dir.mkdir(parents=True, exist_ok=True)
        vid_file = item_dir / "42.mp4"
        vid_file.write_text("fake video content")
        img_file = item_dir / "42_01.jpg"
        img_file.write_text("fake image content")
        sort_info = item_dir / "sort_info.json"
        sort_info.write_text('{"detected_id": "42"}')

        pipeline = VideoLLMPipeline(config=self.config)
        pipeline.gemini_service = mock_gemini
        pipeline.video_service = mock_video
        pipeline.web_research_service = mock_research
        pipeline.appraiser_service = mock_appraiser

        state = pipeline.run(video_path=vid_file, image_paths=[img_file], item_name="Artikel_42")

        # Assert status SUCCESS
        self.assertEqual(state.status, "SUCCESS")

        # Assert folder moved from input/artikel/ to input/completed/
        self.assertFalse(item_dir.exists(), "Source folder in input/artikel/ should no longer exist")
        expected_completed = self.completed_dir / "Artikel_42"
        self.assertTrue(expected_completed.exists(), "Destination folder in input/completed/ should exist")
        self.assertTrue((expected_completed / "42.mp4").exists())
        self.assertTrue((expected_completed / "42_01.jpg").exists())
        self.assertTrue((expected_completed / "sort_info.json").exists())
        self.assertEqual(state.archived_path, expected_completed)

    @patch("pipeline.orchestrator.GeminiService")
    @patch("pipeline.orchestrator.VideoService")
    @patch("pipeline.orchestrator.WebResearchService")
    def test_failed_run_preserves_article_folder_in_input(
        self,
        mock_research_cls,
        mock_video_cls,
        mock_gemini_cls
    ):
        mock_video = mock_video_cls.return_value
        mock_video.extract_audio.side_effect = RuntimeError("Extraction failed")

        mock_research = mock_research_cls.return_value
        mock_research.analyze_visual_and_suggest_targets.side_effect = RuntimeError("Vision failed")

        # Create article folder in input/artikel/
        item_dir = self.artikel_dir / "Artikel_99"
        item_dir.mkdir(parents=True, exist_ok=True)
        vid_file = item_dir / "99.mp4"
        vid_file.write_text("fake video content")

        pipeline = VideoLLMPipeline(config=self.config)
        pipeline.gemini_service = mock_gemini_cls.return_value
        pipeline.video_service = mock_video
        pipeline.web_research_service = mock_research

        with self.assertRaises(RuntimeError):
            pipeline.run(video_path=vid_file, item_name="Artikel_99")

        # Assert folder remains in input/artikel/ and nothing is in completed
        self.assertTrue(item_dir.exists(), "Source folder should remain in input/artikel/ on failure")
        self.assertFalse((self.completed_dir / "Artikel_99").exists())

    @patch("pipeline.orchestrator.GeminiService")
    @patch("pipeline.orchestrator.VideoService")
    @patch("pipeline.orchestrator.WebResearchService")
    @patch("pipeline.orchestrator.AppraiserService")
    def test_duplicate_collision_handling_in_completed(
        self,
        mock_appraiser_cls,
        mock_research_cls,
        mock_video_cls,
        mock_gemini_cls
    ):
        mock_video = mock_video_cls.return_value
        mock_video.extract_audio.return_value = self.temp_dir / "audio.mp3"

        mock_gemini = mock_gemini_cls.return_value
        mock_gemini.transcribe_audio.return_value = "Audio text"

        mock_research = mock_research_cls.return_value
        mock_research.analyze_visual_and_suggest_targets.return_value = self._create_mock_visual_analysis()
        mock_research.research_all_sites_parallel.return_value = []

        mock_appraiser = mock_appraiser_cls.return_value
        mock_appraiser.synthesize_valuation.return_value = self._create_mock_synthesis()

        # Pre-create completed folder Artikel_42
        pre_existing = self.completed_dir / "Artikel_42"
        pre_existing.mkdir(parents=True, exist_ok=True)
        (pre_existing / "old.mp4").write_text("old")

        # Create new article in input/artikel/Artikel_42
        item_dir = self.artikel_dir / "Artikel_42"
        item_dir.mkdir(parents=True, exist_ok=True)
        vid_file = item_dir / "42.mp4"
        vid_file.write_text("new video content")

        pipeline = VideoLLMPipeline(config=self.config)
        pipeline.gemini_service = mock_gemini
        pipeline.video_service = mock_video
        pipeline.web_research_service = mock_research
        pipeline.appraiser_service = mock_appraiser

        state = pipeline.run(video_path=vid_file, item_name="Artikel_42")

        self.assertEqual(state.status, "SUCCESS")
        expected_collision_target = self.completed_dir / "Artikel_42_1"
        self.assertTrue(expected_collision_target.exists(), "Duplicate folder should be indexed as Artikel_42_1")
        self.assertTrue((expected_collision_target / "42.mp4").exists())
        self.assertEqual(state.archived_path, expected_collision_target)
        # Verify original pre-existing folder is untouched
        self.assertTrue((pre_existing / "old.mp4").exists())

    @patch("pipeline.orchestrator.GeminiService")
    @patch("pipeline.orchestrator.VideoService")
    @patch("pipeline.orchestrator.WebResearchService")
    @patch("pipeline.orchestrator.AppraiserService")
    def test_loose_files_archived_into_subfolder(
        self,
        mock_appraiser_cls,
        mock_research_cls,
        mock_video_cls,
        mock_gemini_cls
    ):
        mock_video = mock_video_cls.return_value
        mock_video.extract_audio.return_value = self.temp_dir / "audio.mp3"
        mock_gemini = mock_gemini_cls.return_value
        mock_gemini.transcribe_audio.return_value = "Audio text"

        mock_research = mock_research_cls.return_value
        mock_research.analyze_visual_and_suggest_targets.return_value = self._create_mock_visual_analysis()
        mock_research.research_all_sites_parallel.return_value = []

        mock_appraiser = mock_appraiser_cls.return_value
        mock_appraiser.synthesize_valuation.return_value = self._create_mock_synthesis()

        # Place loose files directly in input/artikel/
        vid_file = self.artikel_dir / "loose_item.mp4"
        vid_file.write_text("video content")
        img_file = self.artikel_dir / "loose_item_01.jpg"
        img_file.write_text("img content")

        pipeline = VideoLLMPipeline(config=self.config)
        pipeline.gemini_service = mock_gemini
        pipeline.video_service = mock_video
        pipeline.web_research_service = mock_research
        pipeline.appraiser_service = mock_appraiser

        state = pipeline.run(video_path=vid_file, image_paths=[img_file], item_name="loose_item")

        self.assertEqual(state.status, "SUCCESS")
        # Loose files should be removed from input/artikel/
        self.assertFalse(vid_file.exists())
        self.assertFalse(img_file.exists())

        # And placed in input/completed/Artikel_loose_item
        expected_dest = self.completed_dir / "Artikel_loose_item"
        self.assertTrue(expected_dest.exists())
        self.assertTrue((expected_dest / "loose_item.mp4").exists())
        self.assertTrue((expected_dest / "loose_item_01.jpg").exists())

    def test_load_config_completed_dir(self):
        from config.settings import load_config
        config = load_config()
        self.assertTrue(hasattr(config.pipeline, "completed_dir"))
        self.assertTrue(config.pipeline.completed_dir.exists())
        self.assertTrue(str(config.pipeline.completed_dir).endswith("completed"))


if __name__ == "__main__":
    unittest.main()
