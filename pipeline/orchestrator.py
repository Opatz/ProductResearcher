import json
import logging
import re
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
    Haupt-Orchestrator für die agentische Video- und LLM-Pipeline.
    Führt alle Verarbeitungs- und Prompt-Schritte (1 bis 9) sequentiell aus:
    - Audio-Extraktion & Transkription
    - 5s-Schnitt & Visuelle ID-Erkennung
    - Prompt 1: Filterung (JSON)
    - Prompt 2: Vertiefte Analyse (JSON)
    - Prompt 3: Varianten & Szenarien (JSON)
    - Prompt 4: PreisSteigererBewerter / Arbitrage & VER-Berechnung (JSON)
    - Export: CSV & Multi-Sheet Excel (.xlsx)
    """

    def __init__(self, config: AppConfig, execution_dir: Optional[Path] = None, mock_mode: bool = False):
        self.config = config
        self.mock_mode = mock_mode
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

        if not self.mock_mode:
            self.gemini_service = GeminiService(
                api_key=config.google.api_key,
                default_model=config.google.model_name
            )
        else:
            self.gemini_service = None
            logger.warning("Pipeline läuft im MOCK-MODUS (keine echten API-Aufrufe).")

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
        """Führt die komplette Pipeline für ein Item (Video + optionale Bilder) aus."""
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
        logger.info(f"🖼️ Bilder: {len(resolved_images)} Bilddatei(en) für Prompt 2 gefunden.")
        logger.info(f"📂 Speicherort aller Zwischenschritte: {video_run_dir}")
        logger.info("=" * 65)

        try:
            # ==========================================
            # SCHRITT 1: Audio aus Video extrahieren
            # ==========================================
            logger.info("▶ [1/9] Extrahiere Audiospur aus dem Video (.mp3)...")
            audio_path = video_run_dir / "01_extracted_audio.mp3"
            if not self.mock_mode:
                state.audio_path = self.video_service.extract_audio(video_path, audio_path)
            else:
                if video_path.stat().st_size < 1024:
                    audio_path.write_bytes(b"MOCK_AUDIO_DATA")
                    state.audio_path = audio_path
                else:
                    try:
                        state.audio_path = self.video_service.extract_audio(video_path, audio_path)
                    except Exception as e:
                        logger.debug(f"Mock-Modus: Audio-Extraktion fehlgeschlagen ({e}), verwende Mock-Audio.")
                        audio_path.write_bytes(b"MOCK_AUDIO_DATA")
                        state.audio_path = audio_path

            # ==========================================
            # SCHRITT 2: Audio transkribieren
            # ==========================================
            logger.info("▶ [2/9] Transkribiere Audio via Gemini API...")
            if not self.mock_mode:
                state.transcription = self.gemini_service.transcribe_audio(
                    audio_path=state.audio_path,
                    language=self.config.pipeline.transcription_language
                )
            else:
                state.transcription = (
                    "Hier ist eine beispielhafte Transkription: Ein gebrauchter Vintage-Designertisch "
                    "mit leichten Kratzern auf der Oberfläche. Aktueller Zustand befriedigend. "
                    "Neupreis lag bei 1.200 €. Aktueller Marktwert ca. 300 € im Ist-Zustand. "
                    "Mit einer fachmännischen Politur könnte er für 700 € verkauft werden."
                )
            
            self._save_text(video_run_dir / "02_raw_transcription.txt", state.transcription)
            logger.info(f"Transkription gesichert ({len(state.transcription)} Zeichen).")

            # ==========================================
            # SCHRITT 3: Video auf erste 5 Sekunden schneiden
            # ==========================================
            logger.info(f"▶ [3/9] Schneide Video auf erste {self.config.pipeline.preview_duration_sec}s...")
            preview_video_path = video_run_dir / "03_preview_first_5s.mp4"
            if not self.mock_mode:
                state.trimmed_video_path = self.video_service.trim_video(
                    video_path=video_path,
                    output_video_path=preview_video_path,
                    duration_sec=self.config.pipeline.preview_duration_sec
                )
            else:
                if video_path.stat().st_size < 1024:
                    preview_video_path.write_bytes(b"MOCK_VIDEO_DATA")
                    state.trimmed_video_path = preview_video_path
                else:
                    try:
                        state.trimmed_video_path = self.video_service.trim_video(
                            video_path=video_path,
                            output_video_path=preview_video_path,
                            duration_sec=self.config.pipeline.preview_duration_sec
                        )
                    except Exception as e:
                        logger.debug(f"Mock-Modus: Video-Schnitt fehlgeschlagen ({e}), verwende Mock-Clip.")
                        preview_video_path.write_bytes(b"MOCK_VIDEO_DATA")
                        state.trimmed_video_path = preview_video_path

            # ==========================================
            # SCHRITT 4: Sichtbare Zahl / ID aus den ersten 5s extrahieren
            # ==========================================
            logger.info("▶ [4/9] Extrahiere ID / Zahl aus dem 5s-Clip via Gemini Vision...")
            id_prompt = self.prompt_manager.load_prompt("prompt_id.txt")
            self._save_text(video_run_dir / "04_prompt_id_sent.txt", id_prompt)

            if not self.mock_mode:
                vision_result = self.gemini_service.extract_id_from_video(
                    trimmed_video_path=state.trimmed_video_path,
                    prompt=id_prompt
                )
                self._save_text(video_run_dir / "04_vision_id_raw_response.txt", vision_result["raw_text"])
                state.id_data = vision_result["parsed_json"]
                detected_from_vid = (
                    state.id_data.get("detected_id", "N/A") 
                    if isinstance(state.id_data, dict) else "N/A"
                )
                # Falls im Video eine eindeutige ID erkannt wurde und bisher keine vorlag:
                if (not internal_id or internal_id == "N/A") and detected_from_vid and detected_from_vid != "N/A":
                    internal_id = detected_from_vid
                    state.detected_id = internal_id
            else:
                mock_raw = '{"detected_id": "' + internal_id + '", "confidence": "high", "visual_description": "Objekt-ID im Intro"}'
                self._save_text(video_run_dir / "04_vision_id_raw_response.txt", mock_raw)
                state.id_data = {
                    "detected_id": internal_id,
                    "confidence": "high",
                    "visual_description": "Objekt-ID im Intro"
                }

            self._save_json(video_run_dir / "04_id_parsed.json", state.id_data)
            logger.info(f"Verbindliche Interne Artikel-ID: '{internal_id}'")

            # ==========================================
            # SCHRITT 5: Prompt 1 - Relevante Details filtern (JSON)
            # ==========================================
            logger.info("▶ [5/9] Prompt 1: Filtere relevante Details aus Transkription zu JSON...")
            ctx_1 = self.prompt_manager.get_assembled_context("prompt_1_filter")
            prompt_1 = self.prompt_manager.format_prompt(
                "prompt_1_filter.txt",
                id=internal_id,
                transcription=state.transcription,
                zusatz_kontext=ctx_1
            )
            self._save_text(video_run_dir / "05_prompt_1_sent.txt", prompt_1)
            
            if not self.mock_mode:
                p1_result = self.gemini_service.execute_text_prompt(prompt_1, expect_json=True)
                self._save_text(video_run_dir / "05_prompt_1_raw_llm_response.txt", p1_result["raw_text"])
                state.step1_filter_json = p1_result["parsed_json"]
            else:
                mock_p1 = {
                    "titel": "Vintage-Designertisch Mid-Century Teak",
                    "kategorie": "Möbel",
                    "hersteller_oder_marke": "Dänisches Design (unbekannt)",
                    "modell_oder_epoche": "Mid-Century 60er/70er Jahre",
                    "erkannte_nummern_oder_stempel": [state.detected_id or "ARTIKEL-4092", "Made in Denmark"],
                    "laenge_cm": 120.0,
                    "breite_cm": 80.0,
                    "hoehe_cm": 75.0,
                    "durchmesser_cm": None,
                    "gewicht_kg": 22.0,
                    "logistik_kategorie": "sperrgut",
                    "material": "Massivholz Teak",
                    "farbe": "Braun / Teak Natur",
                    "zustand": "gebraucht",
                    "maengel": [
                        "Kratzer auf der Oberseite ca. 5 cm",
                        "Leichte Wasserflecken am Rand"
                    ],
                    "preise": {
                        "einkaufspreis_eur": 150.0,
                        "erwarteter_preis_eur": 450.0,
                        "gewuenschter_mindestpreis_eur": 350.0
                    },
                    "fehlende_teile": [],
                    "notizen_aus_transkript": "Vintage Tisch im Wert von ca. 300 € im Ist-Zustand. Mit fachmännischer Politur erzielbar bis 700 €."
                }
                self._save_text(video_run_dir / "05_prompt_1_raw_llm_response.txt", json.dumps(mock_p1, indent=2))
                state.step1_filter_json = mock_p1
            
            self._save_json(video_run_dir / "05_prompt_1_parsed.json", state.step1_filter_json)

            # ==========================================
            # SCHRITT 6: Prompt 2 - Phase 1 (Visuelle Analyse) & Phase 2 (10 Plattform-Recherchen)
            # ==========================================
            logger.info("▶ [6/9] Prompt 2: Führe Phase 1 (Visuelle Analyse & 10 Zielseiten) und Phase 2 (10 Plattform-Recherchen) durch...")
            ctx_2 = self.prompt_manager.get_assembled_context("prompt_2_analysis")

            # Protokolliere verwendete Bilder
            if state.image_paths:
                img_list_str = "\n".join(str(p.name) for p in state.image_paths)
                self._save_text(video_run_dir / "06_prompt_2_images_used.txt", img_list_str)

            # Phase 1: Visuelle Analyse & 10 Ziel-Webseiten
            visual_analysis = self.web_research_service.analyze_visual_and_suggest_targets(
                video_filename=video_path.name,
                item_id=state.detected_id or internal_id or "N/A",
                image_paths=state.image_paths,
                step1_json=state.step1_filter_json,
                zusatz_kontext=ctx_2,
                enable_google_search=self.config.google.enable_google_search
            )
            state.visual_analysis_json = visual_analysis.model_dump(mode="json")
            self._save_json(video_run_dir / "06_initial_visual_analysis.json", state.visual_analysis_json)

            # Phase 2: 10 Unabhängige Plattform-Recherche-Aufrufe (parallel via ThreadPool)
            p1_title = visual_analysis.titel or (state.step1_filter_json.get("titel", "") if state.step1_filter_json else "")
            p1_cat = visual_analysis.kategorie or (state.step1_filter_json.get("kategorie", "") if state.step1_filter_json else "")
            p1_price = (
                state.step1_filter_json.get("preise", {}).get("erwarteter_preis_eur", 300.0) 
                if state.step1_filter_json and isinstance(state.step1_filter_json.get("preise"), dict) 
                else 300.0
            )

            obj_summary = {
                "titel": p1_title,
                "kategorie": p1_cat,
                "hersteller_oder_marke": visual_analysis.hersteller_oder_marke,
                "modell_oder_epoche": visual_analysis.modell_oder_epoche,
                "material": visual_analysis.physische_merkmale.get("material", ""),
                "zustand": visual_analysis.zustandsbericht.get("zustand", ""),
                "erkannte_nummern_oder_stempel": visual_analysis.erkannte_nummern_oder_stempel,
                "geschaetzter_preis": p1_price
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
            logger.info("▶ [6/9 Phase 3] Appraiser LLM: Führe Schlichtung, Ausreißerbereinigung und Retail-Preissynthese durch...")
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
                "notizen_aus_transkript": state.step1_filter_json.get("notizen_aus_transkript", "") if state.step1_filter_json else "",
                "geschaetzter_preis": p1_price
            }

            synthesis_result = self.appraiser_service.synthesize_valuation(
                catalog_data=synthesis_catalog,
                reference_listings=reference_listings,
                enable_google_search=self.config.google.enable_google_search
            )
            state.retail_price_synthesis_json = synthesis_result.model_dump(mode="json")
            state.web_price_summary = state.retail_price_synthesis_json
            self._save_json(video_run_dir / "06_retail_price_synthesis.json", state.retail_price_synthesis_json)

            # Zusammenführung in step2_analysis_json unter Erhalt der Katalog- und Zustandsdaten
            state.step2_analysis_json = dict(state.visual_analysis_json)
            state.step2_analysis_json["geschaetzter_retail_preis_eur"] = synthesis_result.geschaetzter_retail_preis_eur
            state.step2_analysis_json["preisspanne_min_eur"] = synthesis_result.preisspanne_min_eur
            state.step2_analysis_json["preisspanne_max_eur"] = synthesis_result.preisspanne_max_eur
            state.step2_analysis_json["median_web_preis_eur"] = synthesis_result.median_web_preis_eur
            state.step2_analysis_json["anzahl_gefundene_preise"] = synthesis_result.anzahl_gefundene_preise
            state.step2_analysis_json["begruendung_preisfindung"] = synthesis_result.begruendung_preisfindung
            state.step2_analysis_json["ausreisser_bereinigung_notiz"] = synthesis_result.ausreisser_bereinigung_notiz

            # Strukturierte 'preise' Section für Abwärtskompatibilität (ExportService etc.)
            p_dict = dict(state.step1_filter_json.get("preise", {})) if state.step1_filter_json and isinstance(state.step1_filter_json.get("preise"), dict) else {}
            p_dict.update({
                "prognostizierter_preis_realistisch_eur": synthesis_result.geschaetzter_retail_preis_eur,
                "prognostizierter_preis_min_eur": synthesis_result.preisspanne_min_eur,
                "prognostizierter_preis_max_eur": synthesis_result.preisspanne_max_eur,
                "preis_begruendung": synthesis_result.begruendung_preisfindung,
                "median_web_preis_eur": synthesis_result.median_web_preis_eur,
                "anzahl_gefundene_preise": synthesis_result.anzahl_gefundene_preise,
                "ausreisser_bereinigung_notiz": synthesis_result.ausreisser_bereinigung_notiz
            })
            state.step2_analysis_json["preise"] = p_dict
            self._save_json(video_run_dir / "06_prompt_2_parsed.json", state.step2_analysis_json)

            # ==========================================
            # SCHRITT 7: Prompt 3 - Varianten & Szenarien (VORÜBERGEHEND AUSKOMMENTIERT)
            # ==========================================
            # logger.info("▶ [7/9] Prompt 3: Generiere Varianten & Szenarien...")
            # ctx_3 = self.prompt_manager.get_assembled_context("prompt_3_varianten")
            # prompt_3 = self.prompt_manager.format_prompt(
            #     "prompt_3_varianten.txt",
            #     video_filename=video_path.name,
            #     id=state.detected_id or "N/A",
            #     step1_json=json.dumps(state.step1_filter_json, ensure_ascii=False, indent=2),
            #     step2_json=json.dumps(state.step2_analysis_json, ensure_ascii=False, indent=2),
            #     zusatz_kontext=ctx_3
            # )
            # self._save_text(video_run_dir / "07_prompt_3_sent.txt", prompt_3)
            # 
            # if not self.mock_mode:
            #     p3_result = self.gemini_service.execute_text_prompt(prompt_3, expect_json=True)
            #     self._save_text(video_run_dir / "07_prompt_3_raw_llm_response.txt", p3_result["raw_text"])
            #     state.step3_varianten_json = p3_result["parsed_json"]
            # else:
            #     mock_p3 = {
            #         "titel": "Vintage-Designertisch Mid-Century Teak",
            #         "kategorie": "Möbel",
            #         "hersteller_oder_marke": "Dänisches Design",
            #         "modell_oder_epoche": "Mid-Century 1960er",
            #         "geschaetztes_jahr_oder_epoche": "ca. 1962–1965",
            #         "erkannte_nummern_oder_stempel": [state.detected_id or "ARTIKEL-4092"],
            #         "laenge_cm": 120.0,
            #         "breite_cm": 80.0,
            #         "hoehe_cm": 75.0,
            #         "durchmesser_cm": None,
            #         "gewicht_kg": 22.0,
            #         "logistik_kategorie": "sperrgut",
            #         "material": "Massivholz Teak",
            #         "farbe": "Braun / Teak Natur",
            #         "zustand": "gebraucht",
            #         "maengel": ["Kratzer auf der Oberseite ca. 5 cm"],
            #         "fehlende_teile": [],
            #         "notizen_aus_transkript": "Vintage Tisch...",
            #         "preise": {
            #             "einkaufspreis_eur": 150.0,
            #             "erwarteter_preis_eur": 450.0,
            #             "gewuenschter_mindestpreis_eur": 350.0,
            #             "prognostizierter_preis_min_eur": 250.0,
            #             "prognostizierter_preis_max_eur": 350.0,
            #             "prognostizierter_preis_realistisch_eur": 300.0,
            #             "preis_begruendung": "Solider Zustand mit Patina."
            #         },
            #         "zustands_und_marktanalyse": {
            #             "detaillierte_zustandsbeschreibung": "Stabiler Mid-Century Tisch aus Teakholz.",
            #             "altersbestimmung_und_merkmale": "Typische dänische Konstruktionsmerkmale der 1960er Jahre.",
            #             "authentizitaet": "original",
            #             "ausreisser_bereinigung_notiz": "Ausreißer bereinigt."
            #         },
            #         "varianten": [
            #             {
            #                 "variante_nr": 1,
            #                 "bezeichnung": "Ist-Zustand (Direktverkauf as-is)",
            #                 "massnahme_beschreibung": "Verkauf im aktuellen unberührten Zustand",
            #                 "prognostizierter_preis_min_eur": 250.0,
            #                 "prognostizierter_preis_max_eur": 350.0,
            #                 "prognostizierter_preis_realistisch_eur": 300.0
            #             },
            #             {
            #                 "variante_nr": 2,
            #                 "bezeichnung": "Aufbereitung / Oberflächenreinigung",
            #                 "massnahme_beschreibung": "Holz reinigen und mit Teak-Öl pflegen",
            #                 "prognostizierter_preis_min_eur": 400.0,
            #                 "prognostizierter_preis_max_eur": 550.0,
            #                 "prognostizierter_preis_realistisch_eur": 480.0
            #             },
            #             {
            #                 "variante_nr": 3,
            #                 "bezeichnung": "Fachmännische Politur & Reparatur",
            #                 "massnahme_beschreibung": "Fachmännische Politur und Beseitigung der Kratzer",
            #                 "prognostizierter_preis_min_eur": 600.0,
            #                 "prognostizierter_preis_max_eur": 800.0,
            #                 "prognostizierter_preis_realistisch_eur": 700.0
            #             }
            #         ]
            #     }
            #     self._save_text(video_run_dir / "07_prompt_3_raw_llm_response.txt", json.dumps(mock_p3, indent=2))
            #     state.step3_varianten_json = mock_p3
            # 
            # self._save_json(video_run_dir / "07_prompt_3_parsed.json", state.step3_varianten_json)

            # ==========================================
            # SCHRITT 8: Prompt 4 - PreisSteigererBewerter & Rentabilitätsbewertung (VORÜBERGEHEND AUSKOMMENTIERT)
            # ==========================================
            # logger.info("▶ [8/9] Prompt 4: Führe Arbitrage- & Rentabilitätsbewertung (VER-Berechnung) durch...")
            # ctx_4 = self.prompt_manager.get_assembled_context("prompt_4_bewertung")
            # prompt_4 = self.prompt_manager.format_prompt(
            #     "prompt_4_PreisSteigererBewerter.txt",
            #     video_filename=video_path.name,
            #     id=state.detected_id or "N/A",
            #     step1_json=json.dumps(state.step1_filter_json, ensure_ascii=False, indent=2),
            #     step2_json=json.dumps(state.step2_analysis_json, ensure_ascii=False, indent=2),
            #     step3_json=json.dumps(state.step3_varianten_json, ensure_ascii=False, indent=2),
            #     zusatz_kontext=ctx_4
            # )
            # self._save_text(video_run_dir / "08_prompt_4_sent.txt", prompt_4)
            # 
            # if not self.mock_mode:
            #     p4_result = self.gemini_service.execute_text_prompt(prompt_4, expect_json=True)
            #     self._save_text(video_run_dir / "08_prompt_4_raw_llm_response.txt", p4_result["raw_text"])
            #     state.step4_preis_steigerer_json = p4_result["parsed_json"]
            # else:
            #     mock_p4 = {
            #         "artikel_uebersicht": {
            #             "id": state.detected_id or "ARTIKEL-4092",
            #             "titel": "Vintage-Designertisch Mid-Century Teak",
            #             "artikel_details_kurz": "Mid-Century Teakholztisch, ca. 1962–1965, guter Zustand mit Oberflächenkratzern",
            #             "modell_oder_epoche": "Mid-Century 1960er",
            #             "geschaetztes_jahr_oder_epoche": "ca. 1962–1965",
            #             "verkaufs_ort": "eBay Kleinanzeigen / Pamono",
            #             "preistreiber": "Gereinigt & geölt, Teak-Massivholz, Datierung 1960er",
            #             "aktueller_ist_wert_eur": 300.0
            #         },
            #         "massnahmen_bewertungen": [
            #             {
            #                 "variante_nr": 1,
            #                 "bezeichnung": "Ist-Zustand (Direktverkauf as-is)",
            #                 "art_der_massnahme": "keine",
            #                 "konkrete_schritte": "Sofort auf Kleinanzeigen inserieren",
            #                 "erwarteter_verkaufspreis_eur": 300.0,
            #                 "geschaetzte_kosten_eur": 0.0,
            #                 "geschaetzter_zeitaufwand_stunden": 0.5,
            #                 "netto_gewinn_zuwachs_eur": 0.0,
            #                 "ver_stundenlohn_eur": 0.0,
            #                 "risiko": "gering",
            #                 "wirtschaftlich_sinnvoll": False,
            #                 "begruendung": "Kein Mehrwert geschöpft."
            #             },
            #             {
            #                 "variante_nr": 2,
            #                 "bezeichnung": "Fachmännische Politur & Reparatur",
            #                 "art_der_massnahme": "fachreparatur_extern",
            #                 "konkrete_schritte": "Zum Restaurator bringen und versiegeln lassen",
            #                 "erwarteter_verkaufspreis_eur": 700.0,
            #                 "geschaetzte_kosten_eur": 80.0,
            #                 "geschaetzter_zeitaufwand_stunden": 0.75,
            #                 "netto_gewinn_zuwachs_eur": 320.0,
            #                 "ver_stundenlohn_eur": 426.67,
            #                 "risiko": "gering",
            #                 "wirtschaftlich_sinnvoll": True,
            #                 "begruendung": "Exzellenter Hebel: 80 € Kosten und 0.75 h Aufwand bringen 320 € Netto-Gewinnzuwachs (VER: 426.67 €/h)."
            #             }
            #         ],
            #         "finale_handlungsempfehlung": {
            #             "empfohlene_variante_nr": 2,
            #             "empfohlene_massnahme": "Fachmännische Politur & Reparatur",
            #             "strategie": "profi_aufbereitung_und_resale",
            #             "genaue_anleitung_massnahme": "Tisch zum Möbelrestaurator übergeben, Platte abschleifen und mit Teak-Öl finishen lassen, danach professionelle Fotos erstellen.",
            #             "verworfen_alternative_massnahmen": "Var 1 (Direktverkauf): VER 0 €/h - 320 € Mehrerlös verschenkt.",
            #             "erwarteter_endgewinn_eur": 320.0,
            #             "begruendung_gesamt": "Höchster kalkulatorischer Stundenlohn (VER 426.67 €/h) bei minimalem Eigenaufwand.",
            #             "excel_export_row": {
            #                 "id": state.detected_id or "ARTIKEL-4092",
            #                 "video_datei": video_path.name,
            #                 "titel": "Vintage-Designertisch Mid-Century Teak",
            #                 "artikel_details_kurz": "Mid-Century Teakholztisch, 60er Jahre, Teak massiv",
            #                 "modell_oder_epoche": "Mid-Century 1960er",
            #                 "geschaetztes_jahr_oder_epoche": "ca. 1962–1965",
            #                 "verkaufs_ort": "eBay Kleinanzeigen / Pamono",
            #                 "preistreiber": "Gereinigt & geölt, Teak-Massivholz",
            #                 "ist_wert": 300.0,
            #                 "beste_massnahme": "Fachmännische Politur & Reparatur",
            #                 "genaue_anleitung_massnahme": "Tisch zum Restaurator bringen, schleifen und ölen lassen.",
            #                 "verworfen_alternative_massnahmen": "Var 1 verworfen wegen verschenktem Mehrerlös.",
            #                 "investitionskosten_eur": 80.0,
            #                 "zeitaufwand_h": 0.75,
            #                 "ziel_verkaufspreis_eur": 700.0,
            #                 "netto_profit_eur": 320.0,
            #                 "ver_effizienz": 426.67,
            #                 "handlung": "Aufbereiten und für 700 € verkaufen"
            #             }
            #         }
            #     }
            #     self._save_text(video_run_dir / "08_prompt_4_raw_llm_response.txt", json.dumps(mock_p4, indent=2))
            #     state.step4_preis_steigerer_json = mock_p4
            # 
            # self._save_json(video_run_dir / "08_prompt_4_parsed.json", state.step4_preis_steigerer_json)

            # ==========================================
            # SCHRITT 9: Export nach CSV und Excel (.xlsx)
            # ==========================================
            logger.info("▶ [9/9] Exportiere finale Daten nach CSV und Multi-Sheet Excel (.xlsx)...")
            
            # Exportdaten vorbereiten
            export_payload = state.step4_preis_steigerer_json or state.step3_varianten_json or state.step2_analysis_json
            state.export_data = export_payload

            # Vollständiger Multi-Sheet Export im Video-spezifischen Ordner
            local_exporter = ExportService(video_run_dir)
            local_export = local_exporter.export_single_item(
                state=state,
                base_filename=f"{video_path.stem}_result"
            )

            state.csv_path = local_export["csv"]
            state.excel_path = local_export["excel"]
            state.status = "SUCCESS"
            state.completed_at = datetime.now()

            # Gesamten Zustand als Zusammenfassung sichern
            self._save_json(video_run_dir / "pipeline_trace.json", state.model_dump(mode="json"))

            logger.info("✅ VIDEO-VERARBEITUNG ERFOLGREICH ABGESCHLOSSEN!")
            logger.info(f"📊 CSV:   {state.csv_path}")
            logger.info(f"📗 Excel: {state.excel_path}")
            logger.info(f"📁 Ordner: {video_run_dir}")

            return state

        except Exception as e:
            logger.exception(f"❌ Fehler während der Pipeline-Ausführung: {e}")
            state.status = "FAILED"
            state.error_message = str(e)
            state.completed_at = datetime.now()
            self._save_json(video_run_dir / "pipeline_trace_error.json", state.model_dump(mode="json"))
            raise
