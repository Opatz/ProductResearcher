import sys
import os
import re
import json
import logging
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

from config.settings import load_config
from pipeline.orchestrator import VideoLLMPipeline
from services.export_service import ExportService
from services.sorter_service import MediaSorterService


@dataclass
class ItemTask:
    """Repräsentiert eine Aufgabe mit einem Video und zugehörigen Bildern."""
    item_name: str
    video_path: Path
    image_paths: List[Path] = field(default_factory=list)


def setup_logging():
    """Konfiguriert das Logging für die Konsole mit UTF-8 Kodierung."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def discover_item_tasks(input_path: Path) -> List[ItemTask]:
    """
    Durchsucht ein Verzeichnis nach:
    1. Unterordnern (1 Unterordner = 1 Artikel mit Video + Bildern)
    2. Direkt abgelegten Videodateien (mit optionalen gleichnamigen Bildern)
    """
    tasks: List[ItemTask] = []
    video_extensions = [".mp4", ".mov", ".mkv", ".avi", ".webm"]
    image_extensions = [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic"]

    input_path = Path(input_path).resolve()
    if not input_path.exists():
        return tasks

    # 1. Prüfe auf Unterordner (z.B. Artikel_1, Artikel_2, Artikel_1_1...)
    subdirs = [p for p in input_path.iterdir() if p.is_dir() and not p.name.startswith(".")]
    
    def _sort_key(folder: Path):
        name = folder.name
        digits = re.findall(r"\d+", name)
        if digits:
            return [int(d) for d in digits]
        return [name]

    try:
        subdirs.sort(key=_sort_key)
    except Exception:
        subdirs.sort(key=lambda x: x.name)
    
    for folder in subdirs:
        # Finde Videos im Unterordner
        videos = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in video_extensions]
        # Finde Bilder im Unterordner
        images = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in image_extensions]
        
        # Sortiere Bilder alphabetisch
        images = sorted(images, key=lambda x: x.name)

        if videos:
            # Erstelle Task für das erste gefundene Video im Ordner
            tasks.append(ItemTask(
                item_name=folder.name,
                video_path=videos[0],
                image_paths=images
            ))

    # 2. Prüfe auf direkt abgelegte Videos im Hauptordner (Fallback / flache Struktur)
    loose_videos = [f for f in input_path.iterdir() if f.is_file() and f.suffix.lower() in video_extensions]
    for vid in loose_videos:
        matching_images = [
            img for img in input_path.iterdir() 
            if img.is_file() and img.suffix.lower() in image_extensions and img.stem.startswith(vid.stem)
        ]
        tasks.append(ItemTask(
            item_name=vid.stem,
            video_path=vid,
            image_paths=matching_images
        ))

    return tasks


def run_sorting_process(
    args: argparse.Namespace,
    config: Any,
    logger: logging.Logger,
    gemini_service: Optional[Any] = None
) -> List[Path]:
    """Führt den Raw Ingest Sortier- und Quarantäneprozess mit konfigurierten Flags aus."""
    # 1. Quellverzeichnisse
    if getattr(args, "source", None):
        source_dirs = [Path(args.source).resolve()]
    else:
        source_dirs = [d for d in [config.pipeline.processed_dir, config.pipeline.raw_dir] if d.exists()]

    # 2. Zielverzeichnis (Standard: input/artikel/)
    if getattr(args, "target", None):
        target_dir = Path(args.target).resolve()
    else:
        target_dir = config.pipeline.artikel_dir.resolve()

    # 3. Quarantäne- und Inspektionsverzeichnis (Standard: output/to_inspect/)
    if getattr(args, "inspect", None):
        inspect_dir = Path(args.inspect).resolve()
    else:
        inspect_dir = (config.pipeline.output_dir / "to_inspect").resolve()

    # 4. Datei-Operation: Verschieben (Move) als Standard, Kopieren (Copy) bei --copy
    move_files = not getattr(args, "copy", False)

    # Gemini-Service initialisieren, falls nicht übergeben und nicht im Mock-Modus
    if gemini_service is None and not getattr(args, "mock", False) and config.google.api_key:
        try:
            from services.gemini_service import GeminiService
            gemini_service = GeminiService(
                api_key=config.google.api_key,
                default_model=config.google.model_name
            )
        except Exception as e:
            logger.warning(f"Konnte GeminiService für ID-Erkennung nicht initialisieren ({e}). Verwende Fallback.")

    sorter = MediaSorterService(
        gemini_service=gemini_service,
        prompts_dir=config.base_dir / "prompts"
    )

    created_folders = sorter.sort_media_files(
        source_dir=source_dirs,
        target_artikel_dir=target_dir,
        inspect_dir=inspect_dir,
        move_files=move_files
    )

    return created_folders


def main():
    setup_logging()
    logger = logging.getLogger("Main")

    parser = argparse.ArgumentParser(
        description="Agentische Video- & Bild-Verarbeitungs-Pipeline mit automatischer Sortierung, Prompt-Chaining und Excel-Export"
    )
    parser.add_argument(
        "-v", "--video", 
        type=str, 
        help="Pfad zu einer einzelnen Videodatei (.mp4, .mov, etc.)"
    )
    parser.add_argument(
        "-i", "--images",
        nargs="*",
        help="Optionale Pfade zu Bildern für Prompt 2 (zusammen mit --video)"
    )
    parser.add_argument(
        "-b", "--batch-dir", 
        type=str, 
        help="Pfad zu einem Verzeichnis mit Artikel-Unterordnern (z. B. input/artikel/)"
    )
    parser.add_argument(
        "--sort-raw",
        action="store_true",
        help="Führt die eigenständige Sortierung von Rohmedien (Raw Ingest) durch und stoppt danach"
    )
    parser.add_argument(
        "--sort-only",
        action="store_true",
        help="Alias für --sort-raw: Führt nur die automatische Sortierung von input/raw durch und stoppt danach"
    )
    parser.add_argument(
        "--source",
        type=str,
        help="Pfad zum Quellverzeichnis mit Rohmedien (Standard: input/processed & input/raw)"
    )
    parser.add_argument(
        "--target",
        type=str,
        help="Pfad zum Zielverzeichnis für Artikel-Ordner (Standard: input/artikel/)"
    )
    parser.add_argument(
        "--inspect",
        type=str,
        help="Pfad zum Quarantäne- und Inspektionsverzeichnis (Standard: output/to_inspect/)"
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Kopiert Dateien statt sie zu verschieben (Standard: Dateien werden verschoben)"
    )
    parser.add_argument(
        "--no-sort",
        action="store_true",
        help="Überspringt die automatische Sortierung von input/raw"
    )
    parser.add_argument(
        "--mock", 
        action="store_true", 
        help="Führt die Pipeline im Test-/Mock-Modus aus (ohne Google API Aufrufe)"
    )
    parser.add_argument(
        "--item",
        type=str,
        help="Verarbeitet nur einen bestimmten Artikel-Ordner (z. B. 'Artikel_1' oder '1')"
    )
    parser.add_argument(
        "--model", 
        type=str, 
        help="Überschreibt das in config.ini festgelegte Gemini-Modell"
    )

    args = parser.parse_args()

    # Konfiguration laden
    config = load_config()
    if args.model:
        config.google.model_name = args.model

    # ==========================================
    # STANDALONE RAW INGEST SORTIERUNG (--sort-raw oder --sort-only)
    # ==========================================
    if args.sort_raw or args.sort_only:
        logger.info("=" * 70)
        logger.info("🤖 RAW INGEST STANDALONE-SORTIERUNG GESTARTET")
        has_key = bool(config.google.api_key)
        mode_str = "MOCK (Testlauf)" if args.mock else ("LIVE (Gemini Vision)" if has_key else "FALLBACK (Kein API-Key)")
        logger.info(f"Modus:              {mode_str}")
        logger.info(f"Datei-Operation:    {'KOPIEREN (Copy)' if args.copy else 'VERSCHIEBEN (Move)'}")
        if args.source:
            logger.info(f"Quellpfad:          {args.source}")
        if args.target:
            logger.info(f"Zielpfad:           {args.target}")
        if args.inspect:
            logger.info(f"Inspektionspfad:    {args.inspect}")
        logger.info("=" * 70)

        created_folders = run_sorting_process(args=args, config=config, logger=logger)
        logger.info(f"🏁 Standalone-Sortierung abgeschlossen: {len(created_folders)} Ordner verarbeitet.")
        sys.exit(0)

    # Zeitgestempelter Ausführungsordner für diesen gesamten Programmlauf
    timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    execution_dir = (config.pipeline.output_dir / f"execution_{timestamp_str}").resolve()
    execution_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 70)
    logger.info("🤖 AGENTISCHE MULTIMODALE VIDEO- & BILD-PIPELINE GESTARTET")
    logger.info(f"Zeitstempel-Ordner: {execution_dir.name}")
    logger.info(f"Standard-Modell:    {config.google.model_name}")
    logger.info(f"Modus:              {'MOCK (Testlauf)' if args.mock else 'LIVE (Google Gemini API)'}")
    logger.info("=" * 70)

    # API-Key Überprüfung für den Live-Modus
    if not args.mock and not config.google.api_key:
        logger.error(
            "❌ Kein Google API Key konfiguriert!\n"
            "Bitte trage deinen Key in 'config/config.ini' ein oder setze die Umgebungsvariable 'GEMINI_API_KEY'.\n"
            "Tipp: Für einen schnellen Funktionstest kannst du das Flag '--mock' verwenden."
        )
        sys.exit(1)

    pipeline = VideoLLMPipeline(config=config, execution_dir=execution_dir, mock_mode=args.mock)

    # ==========================================
    # VORSCHRITT: Automatische Sortierung vor Pipeline-Start
    # ==========================================
    if not args.no_sort:
        if args.source:
            check_dirs = [Path(args.source).resolve()]
        else:
            check_dirs = [d for d in [config.pipeline.processed_dir, config.pipeline.raw_dir] if d.exists()]

        pending_files = []
        for d in check_dirs:
            if d.exists():
                pending_files.extend([f for f in d.iterdir() if f.is_file() and not f.name.startswith(".")])

        if pending_files:
            logger.info(f"\n📦 Gefundene Rohdateien zur Sortierung: {len(pending_files)} Datei(en)")
            logger.info("▶ Starte automatische Sequenz-Sortierung (1. Bild = ID -> Detailbilder -> Video)...")
            new_folders = run_sorting_process(
                args=args,
                config=config,
                logger=logger,
                gemini_service=pipeline.gemini_service if not args.mock else None
            )
            target_disp = args.target or config.pipeline.artikel_dir.name
            logger.info(f"✅ {len(new_folders)} neue Artikel-Ordner in '{target_disp}' einsortiert.\n")

    # Aufgaben ermitteln
    tasks: List[ItemTask] = []

    if args.video:
        vid_path = Path(args.video).resolve()
        if not vid_path.exists():
            logger.error(f"❌ Angegebene Videodatei nicht gefunden: {vid_path}")
            sys.exit(1)
        img_paths = [Path(img).resolve() for img in (args.images or []) if Path(img).exists()]
        tasks.append(ItemTask(
            item_name=vid_path.stem,
            video_path=vid_path,
            image_paths=img_paths
        ))
    else:
        # Priorisiere args.batch_dir, dann args.target, dann config.pipeline.artikel_dir
        if args.batch_dir:
            search_dir = Path(args.batch_dir).resolve()
        elif args.target:
            search_dir = Path(args.target).resolve()
        else:
            search_dir = config.pipeline.artikel_dir
        if not search_dir.exists() or not any(search_dir.iterdir()):
            search_dir = config.pipeline.input_dir

        tasks = discover_item_tasks(search_dir)

        if args.item:
            target = args.item.strip().lower()
            tasks = [
                t for t in tasks 
                if t.item_name.lower() == target 
                or t.item_name.lower() == f"artikel_{target}"
                or t.item_name.lower().endswith(f"_{target}")
            ]

        if not tasks:
            logger.info("ℹ️ Keine verarbeitbaren Artikel-Ordner gefunden.")
            logger.info("👉 Du kannst Rohaufnahmen (Bilder + Videos) einfach in 'input/processed/' oder 'input/raw/' ablegen:")
            logger.info("   input/processed/")
            logger.info("   ├── 2026-08-30 at 11.20.06.jpeg      (Erstes Bild mit ID/Nummer)")
            logger.info("   ├── 2026-08-30 at 11.20.07.jpeg")
            logger.info("   ├── 2026-08-30 at 11.20.11.mp4       (Schließt Artikel 1 ab)")
            logger.info("   ├── 2026-08-30 at 11.20.12.jpeg      (Startet Artikel 2)")
            logger.info("   └── 2026-08-30 at 11.20.16.mp4       (Schließt Artikel 2 ab)")
            sys.exit(0)

    logger.info(f"Gefundene Artikel zur Verarbeitung: {len(tasks)}")
    for i, t in enumerate(tasks, 1):
        logger.info(f"  [{i}] {t.item_name} -> Video: '{t.video_path.name}', Bilder: {len(t.image_paths)}")

    all_rows: List[Dict[str, Any]] = []
    all_measures: List[Dict[str, Any]] = []
    all_web_research: List[Dict[str, Any]] = []
    success_count = 0

    for idx, task in enumerate(tasks, 1):
        logger.info(f"\n[{idx}/{len(tasks)}] Verarbeite Artikel: '{task.item_name}'")
        try:
            state = pipeline.run(
                video_path=task.video_path,
                image_paths=task.image_paths,
                item_name=task.item_name
            )
            if state.status == "SUCCESS":
                success_count += 1
                
                # Vollständige einheitliche Zeile mit allen JSON-Attributen extrahieren
                unified_row = ExportService.build_unified_item_row_from_state(state)
                all_rows.append(unified_row)

                # Web-Research für konsolidiertes Sheet sammeln
                ref_listings = (
                    getattr(state, "reference_listings", None)
                    or getattr(state, "discovered_web_sources", None)
                    or []
                )
                if ref_listings:
                    web_rows = ExportService.build_web_research_rows(unified_row["id"], ref_listings)
                    all_web_research.extend(web_rows)

                # Detaillierte Maßnahmen sammeln (für Sheet 3)
                p4 = state.step4_preis_steigerer_json
                if p4 and isinstance(p4, dict) and "massnahmen_bewertungen" in p4:
                    massnahmen = p4["massnahmen_bewertungen"]
                    if isinstance(massnahmen, list):
                        for m in massnahmen:
                            m_row = {
                                "artikel_id": unified_row["id"],
                                "artikel_titel": unified_row["titel"]
                            }
                            m_row.update(ExportService.flatten_record(m))
                            all_measures.append(m_row)

        except Exception as e:
            logger.error(f"Fehler bei der Verarbeitung von '{task.item_name}': {e}")

    # Gesamttabelle erstellen
    if all_rows:
        summary_exporter = ExportService(execution_dir)
        summary_export = summary_exporter.export_consolidated_batch(
            items_rows=all_rows,
            measures_rows=all_measures,
            web_research_rows=all_web_research,
            base_filename="consolidated_execution_results"
        )
        logger.info("\n" + "=" * 70)
        logger.info("📊 KONSOLIDIERTE GESAMTTABELLE ALLER ARTIKEL ERSTELLT:")
        logger.info(f"  📗 Excel: {summary_export['excel']}")
        logger.info(f"  📊 CSV:   {summary_export['csv']}")

    # Ausführungs-Manifest speichern
    manifest = {
        "execution_id": execution_dir.name,
        "timestamp": timestamp_str,
        "total_items": len(tasks),
        "success_count": success_count,
        "items": [
            {
                "item_name": t.item_name,
                "video": str(t.video_path.name),
                "images_count": len(t.image_paths)
            }
            for t in tasks
        ]
    }
    with open(execution_dir / "execution_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    logger.info("=" * 70)
    logger.info(f"🎉 AUSFÜHRUNG BEENDET: {success_count}/{len(tasks)} Artikel erfolgreich verarbeitet.")
    logger.info(f"📁 Vollständiger Ausführungs-Ordner: {execution_dir}")
    logger.info("=" * 70)

if __name__ == "__main__":
    main()
