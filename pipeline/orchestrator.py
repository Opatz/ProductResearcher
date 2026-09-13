import json
import logging
import re
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, Union, List
from datetime import datetime

from config.settings import AppConfig
from pipeline.state import PipelineState
from services.video_service import VideoService
from services.gemini_service import GeminiService
from services.prompt_manager import PromptManager
from services.export_service import ExportService
from services.web_research_service import WebResearchService
from services.appraiser_service import AppraiserService

logger = logging.getLogger(__name__)


class VideoLLMPipeline:
    """
    Haupt-Orchestrator für die agentische Video- und Marktbewertungs-Pipeline.
    Führt alle Verarbeitungs- und Bewertungs-Schritte sequentiell aus:
    - Audio-Extraktion & Transkription
    - 5s-Schnitt & Visuelle ID-Erkennung
    - 3-Stufen Marktbewertung (Visuelle Analyse, 10-Site Webrecherche, Appraiser LLM Synthese)
    - Export: CSV & 2-Sheet Excel (.xlsx) mit klickbaren Hyperlinks
    """

    def __init__(self, config: AppConfig, execution_dir: Optional[Path] = None):
        self.config = config
        self.video_service = VideoService()
        self.prompt_manager = PromptManager(
            prompts_dir=config.base_dir / "prompts",
            context_dir=config.pipeline.context_dir
        )

        if execution_dir:
            self.execution_dir = Path(execution_dir).resolve()
        else:
            timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            self.execution_dir = (self.config.pipeline.output_dir / f"execution_{timestamp_str}").resolve()
        
        self.execution_dir.mkdir(parents=True, exist_ok=True)
        self.export_service = ExportService(self.execution_dir)

        if config.google.api_key:
            self.gemini_service = GeminiService(
                api_key=config.google.api_key,
                default_model=config.google.model_name
            )
        else:
            self.gemini_service = None

        self.web_research_service = WebResearchService(
            gemini_service=self.gemini_service,
            prompts_dir=config.base_dir / "prompts",
            context_dir=config.pipeline.context_dir,
            prompt_manager=self.prompt_manager
        )
        self.appraiser_service = AppraiserService(
            gemini_service=self.gemini_service,
            prompts_dir=config.base_dir / "prompts",
            context_dir=config.pipeline.context_dir,
            prompt_manager=self.prompt_manager
        )

    def _save_json(self, path: Path, data: Any) -> None:
        """Speichert Daten formatiert als JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _save_text(self, path: Path, text: str) -> None:
        """Speichert Text/Prompts/Raw-Responses in einer Datei."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def run(
        self, 
        video_path: Union[str, Path], 
        image_paths: Optional[List[Union[str, Path]]] = None,
        item_name: Optional[str] = None
    ) -> PipelineState:
        """Führt die komplette 3-Stufen-Pipeline für ein Item (Video + Bilder) aus."""
        video_path = Path(video_path).resolve()
        resolved_images = [Path(img).resolve() for img in (image_paths or []) if Path(img).exists()]
        effective_item_name = item_name or video_path.stem

        # Eigener Unterordner für dieses Item im zeitgestempelten Ausführungsordner
        video_run_dir = self.execution_dir / effective_item_name
        video_run_dir.mkdir(parents=True, exist_ok=True)

        # 0. Verbindliche interne Artikel-ID ermitteln (Priorität: sort_info.json > Ordnername > Video-Stem)
        internal_id = ""
        sort_info_path = video_path.parent / "sort_info.json"
        if sort_info_path.exists():
            try:
                with open(sort_info_path, "r", encoding="utf-8") as f:
                    sort_info = json.load(f)
                    internal_id = str(sort_info.get("detected_id", "")).strip()
            except Exception as e:
                logger.debug(f"Konnte sort_info.json nicht laden: {e}")

        if not internal_id or internal_id.lower() in {"null", "n/a", "none"}:
            m_folder = re.search(r"Artikel_([A-Za-z0-9_]+)", effective_item_name)
            if m_folder:
                internal_id = m_folder.group(1)
            else:
                internal_id = effective_item_name

        state = PipelineState(
            item_name=effective_item_name,
            video_path=video_path,
            image_paths=resolved_images,
            run_dir=video_run_dir
        )
        state.detected_id = internal_id

        logger.info("=" * 65)
        logger.info(f"🎬 STARTE PIPELINE FÜR ITEM: '{effective_item_name}' (Interne ID: '{internal_id}')")
        logger.info(f"📹 Video:  {video_path.name}")
        logger.info(f"🖼️ Bilder: {len(resolved_images)} Bilddatei(en) für visuelle Analyse gefunden.")
        logger.info(f"📂 Speicherort aller Zwischenschritte: {video_run_dir}")
        logger.info("=" * 65)

        try:
            # ==========================================
            # SCHRITT 1: Audio aus Video extrahieren
            # ==========================================
            logger.info("▶ [1/4] Extrahiere Audiospur aus dem Video (.mp3)...")
            audio_path = video_run_dir / "01_extracted_audio.mp3"
            try:
                state.audio_path = self.video_service.extract_audio(video_path, audio_path)
            except Exception as e:
                logger.warning(f"Audio-Extraktion nicht möglich: {e}")

            # ==========================================
            # SCHRITT 2: Audio transkribieren
            # ==========================================
            if state.audio_path and state.audio_path.exists() and self.gemini_service:
                logger.info("▶ [2/4] Transkribiere Audio via Gemini API...")
                try:
                    state.transcription = self.gemini_service.transcribe_audio(
                        audio_path=state.audio_path,
                        language=self.config.pipeline.transcription_language
                    )
                    self._save_text(video_run_dir / "02_raw_transcription.txt", state.transcription)
                    logger.info(f"Transkription gesichert ({len(state.transcription)} Zeichen).")
                except Exception as e:
                    logger.warning(f"Transkription fehlgeschlagen: {e}")
                    state.transcription = ""
            else:
                state.transcription = ""

            # ==========================================
            # SCHRITT 3: Video auf erste 5s schneiden & ID via Vision erkennen (falls nötig)
            # ==========================================
            if not internal_id or internal_id == "N/A":
                preview_video_path = video_run_dir / "03_preview_first_5s.mp4"
                try:
                    state.trimmed_video_path = self.video_service.trim_video(
                        video_path=video_path,
                        output_video_path=preview_video_path,
                        duration_sec=self.config.pipeline.preview_duration_sec
                    )
                    if state.trimmed_video_path and self.gemini_service:
                        id_prompt = self.prompt_manager.load_prompt("prompt_id.txt")
                        self._save_text(video_run_dir / "04_prompt_id_sent.txt", id_prompt)
                        vision_result = self.gemini_service.extract_id_from_video(
                            trimmed_video_path=state.trimmed_video_path,
                            prompt=id_prompt
                        )
                        self._save_text(video_run_dir / "04_vision_id_raw_response.txt", vision_result.get("raw_text", ""))
                        state.id_data = vision_result.get("parsed_json")
                        detected_from_vid = (
                            state.id_data.get("detected_id", "N/A") 
                            if isinstance(state.id_data, dict) else "N/A"
                        )
                        if detected_from_vid and detected_from_vid != "N/A":
                            internal_id = detected_from_vid
                            state.detected_id = internal_id
                except Exception as e:
                    logger.warning(f"ID-Erkennung aus Video übersprungen / fehlgeschlagen: {e}")

            # ==========================================
            # SCHRITT 4: 3-Stufen Marktbewertung (ADR 0002)
            # ==========================================
            logger.info("▶ [3/4] 3-Stufen Marktbewertung:")
            
            # Phase 1: Multimodale visuelle Analyse & 10 Ziel-Webseiten
            logger.info("   ↳ Phase 1: Visuelle Objektanalyse & 10 Zielseiten via Gemini Vision...")
            if state.image_paths:
                img_list_str = "\n".join(str(p.name) for p in state.image_paths)
                self._save_text(video_run_dir / "06_prompt_2_images_used.txt", img_list_str)

            visual_analysis = self.web_research_service.analyze_visual_and_suggest_targets(
                video_filename=video_path.name,
                item_id=state.detected_id or internal_id or "N/A",
                image_paths=state.image_paths,
                zusatz_kontext=self.prompt_manager.get_assembled_context("prompt_2_visual_analysis"),
                enable_google_search=self.config.google.enable_google_search
            )
            state.visual_analysis_json = visual_analysis.model_dump(mode="json")
            self._save_json(video_run_dir / "06_initial_visual_analysis.json", state.visual_analysis_json)

            # Phase 2: Parallele Plattform-Recherche über bis zu 10 Plattformen
            logger.info("   ↳ Phase 2: Parallele Plattform-Recherche auf bis zu 10 Vergleichsportalen...")
            obj_summary = {
                "titel": visual_analysis.titel,
                "kategorie": visual_analysis.kategorie,
                "hersteller_oder_marke": visual_analysis.hersteller_oder_marke,
                "modell_oder_epoche": visual_analysis.modell_oder_epoche,
                "material": visual_analysis.physische_merkmale.get("material", ""),
                "zustand": visual_analysis.zustandsbericht.get("zustand", ""),
                "erkannte_nummern_oder_stempel": visual_analysis.erkannte_nummern_oder_stempel,
                "geschaetzter_preis": 0.0
            }

            reference_listings = self.web_research_service.research_all_sites_parallel(
                targets=visual_analysis.ziel_webseiten,
                object_summary=obj_summary,
                max_workers=5,
                timeout=30.0
            )
            state.reference_listings = [r.model_dump(mode="json") for r in reference_listings]
            state.discovered_web_sources = list(state.reference_listings)
            self._save_json(video_run_dir / "06_web_research_10_sites.json", state.reference_listings)

            # Phase 3: Appraiser LLM Reconciliation & Valuation Synthesis
            logger.info("   ↳ Phase 3: Appraiser LLM Reconciliation & Retail-Preissynthese...")
            synthesis_catalog = {
                "id": state.detected_id or internal_id,
                "titel": visual_analysis.titel,
                "kategorie": visual_analysis.kategorie,
                "hersteller_oder_marke": visual_analysis.hersteller_oder_marke,
                "modell_oder_epoche": visual_analysis.modell_oder_epoche,
                "produktbeschreibung": visual_analysis.produktbeschreibung,
                "physische_merkmale": visual_analysis.physische_merkmale,
                "zustandsbericht": visual_analysis.zustandsbericht,
                "erkannte_nummern_oder_stempel": visual_analysis.erkannte_nummern_oder_stempel,
                "notizen_aus_transkript": state.transcription or "",
                "geschaetzter_preis": 0.0
            }

            synthesis_result = self.appraiser_service.synthesize_valuation(
                catalog_data=synthesis_catalog,
                reference_listings=reference_listings,
                enable_google_search=self.config.google.enable_google_search
            )
            state.retail_price_synthesis_json = synthesis_result.model_dump(mode="json")
            state.web_price_summary = state.retail_price_synthesis_json
            self._save_json(video_run_dir / "06_retail_price_synthesis.json", state.retail_price_synthesis_json)

            # ==========================================
            # SCHRITT 4 / EXPORT: Export nach CSV und 2-Sheet Excel (.xlsx)
            # ==========================================
            logger.info("▶ [4/4] Exportiere finale Daten nach CSV und 2-Sheet Excel (.xlsx)...")
            state.export_data = state.retail_price_synthesis_json

            local_exporter = ExportService(video_run_dir)
            local_export = local_exporter.export_single_item(
                state=state,
                base_filename=f"{video_path.stem}_result"
            )

            state.csv_path = local_export["csv"]
            state.excel_path = local_export["excel"]
            state.status = "SUCCESS"
            state.completed_at = datetime.now()

            # Automatische Archivierung des verarbeiteten Artikel-Ordners nach input/completed/ (ADR 0004)
            self._archive_completed_item(state)

            # Gesamten Zustand als Zusammenfassung sichern
            self._save_json(video_run_dir / "pipeline_trace.json", state.model_dump(mode="json"))

            logger.info("✅ VERARBEITUNG ERFOLGREICH ABGESCHLOSSEN!")
            logger.info(f"📊 CSV:   {state.csv_path}")
            logger.info(f"📗 Excel: {state.excel_path}")
            if state.archived_path:
                logger.info(f"📦 Archiv: {state.archived_path}")
            logger.info(f"📁 Run:   {video_run_dir}")

            return state

        except Exception as e:
            logger.exception(f"❌ Fehler während der Pipeline-Ausführung: {e}")
            state.status = "FAILED"
            state.error_message = str(e)
            state.completed_at = datetime.now()
            self._save_json(video_run_dir / "pipeline_trace_error.json", state.model_dump(mode="json"))
            raise

    def _archive_completed_item(self, state: PipelineState) -> Optional[Path]:
        """
        Verschiebt den fertig verarbeiteten Artikel-Ordner bzw. die zugehörigen Mediendateien
        in das konfigurierte Completed-Verzeichnis (z. B. input/completed/Artikel_<ID>).
        Löst Namenskollisionen durch automatische Duplikat-Indexierung auf.
        """
        completed_dir = getattr(self.config.pipeline, "completed_dir", None)
        if not completed_dir:
            return None

        completed_dir = Path(completed_dir).resolve()
        completed_dir.mkdir(parents=True, exist_ok=True)

        video_path = state.video_path
        parent_dir = video_path.parent.resolve()
        artikel_root = self.config.pipeline.artikel_dir.resolve()
        input_root = self.config.pipeline.input_dir.resolve()

        # Bestimme Zielordner-Basisnamen
        raw_name = state.item_name or video_path.stem
        if not raw_name.startswith("Artikel_") and state.detected_id:
            folder_base_name = f"Artikel_{state.detected_id}"
        else:
            folder_base_name = raw_name

        # Kollisionsauflösung
        target_path = completed_dir / folder_base_name
        if target_path.exists():
            dup_idx = 1
            while (completed_dir / f"{folder_base_name}_{dup_idx}").exists():
                dup_idx += 1
            target_path = completed_dir / f"{folder_base_name}_{dup_idx}"

        # Fall 1: Das Item liegt in einem eigenen Unterordner (z. B. input/artikel/Artikel_1/)
        if parent_dir != artikel_root and parent_dir != input_root and parent_dir.exists():
            state.source_dir = parent_dir
            try:
                shutil.move(str(parent_dir), str(target_path))
                state.archived_path = target_path
                logger.info(f"📦 Artikel-Ordner erfolgreich archiviert: '{parent_dir.name}' -> '{target_path}'")
                return target_path
            except Exception as e:
                logger.warning(f"Konnte Artikel-Ordner '{parent_dir}' nicht nach '{target_path}' verschieben: {e}")
                return None

        # Fall 2: Lose Dateien direkt im Hauptverzeichnis (input/artikel/)
        state.source_dir = parent_dir
        target_path.mkdir(parents=True, exist_ok=True)
        files_to_move = [video_path] + [p for p in state.image_paths if p.exists()]
        sort_info = parent_dir / "sort_info.json"
        if sort_info.exists():
            files_to_move.append(sort_info)

        for f in files_to_move:
            try:
                if f.exists():
                    shutil.move(str(f), str(target_path / f.name))
            except Exception as e:
                logger.warning(f"Konnte Datei '{f.name}' nicht verschieben: {e}")

        state.archived_path = target_path
        logger.info(f"📦 Lose Mediendateien gebündelt archiviert nach: '{target_path}'")
        return target_path
