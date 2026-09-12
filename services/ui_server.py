import os
import re
import io
import json
import time
import logging
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from collections import deque
import pandas as pd

from config.settings import load_config, BASE_DIR, AppConfig
from services.ebay_service import EbayService
from main import run_sorting_process, discover_item_tasks, ItemTask
from pipeline.orchestrator import VideoLLMPipeline
from services.export_service import ExportService

logger = logging.getLogger(__name__)


def find_latest_execution_file(output_dir: Path) -> Optional[Path]:
    """Findet die aktuellste konsolidierte Excel- oder CSV-Datei."""
    output_dir = Path(output_dir).resolve()
    if not output_dir.exists():
        return None

    candidates = list(output_dir.glob("consolidated_execution_results*.xlsx"))
    if not candidates:
        candidates = list(output_dir.glob("execution_*/consolidated_execution_results*.xlsx"))

    if not candidates:
        candidates = list(output_dir.glob("*.xlsx"))

    if not candidates:
        return None

    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def find_item_images(item_id: str, item_name: str, base_dir: Path) -> List[Path]:
    """Findet alle zugehörigen Bilddateien für einen Artikel."""
    images: List[Path] = []
    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic"}

    search_dirs = [
        base_dir / "input" / "completed",
        base_dir / "input" / "artikel",
        base_dir / "input" / "processed",
        base_dir / "input" / "raw",
        base_dir / "output"
    ]

    target_names = {
        item_id.strip().lower(),
        f"artikel_{item_id}".lower(),
        item_name.strip().lower(),
        f"artikel_{item_name}".lower()
    }

    for root_dir in search_dirs:
        if not root_dir.exists():
            continue
        for sub in root_dir.iterdir():
            if sub.is_dir() and sub.name.lower() in target_names:
                for f in sorted(sub.iterdir(), key=lambda x: x.name):
                    if f.is_file() and f.suffix.lower() in image_exts:
                        images.append(f)
                if images:
                    return images

    return images


def parse_multipart_form_data(body: bytes, content_type_header: str) -> List[Tuple[str, bytes]]:
    """
    Parst multipart/form-data ohne veraltetes cgi-Modul (kompatibel mit Python 3.10-3.13+).
    Gibt eine Liste von (filename, content_bytes) zurück.
    """
    files: List[Tuple[str, bytes]] = []
    if "boundary=" not in content_type_header:
        return files

    boundary_token = content_type_header.split("boundary=")[1].split(";")[0].strip().strip('"')
    boundary = ("--" + boundary_token).encode("utf-8")
    delimiter = boundary

    parts = body.split(delimiter)
    for part in parts:
        if not part or part == b"--\r\n" or part == b"--" or part.startswith(b"--"):
            continue

        # Header und Content trennen
        if b"\r\n\r\n" in part:
            header_block, content_block = part.split(b"\r\n\r\n", 1)
        elif b"\n\n" in part:
            header_block, content_block = part.split(b"\n\n", 1)
        else:
            continue

        # Letzte Newline vor nächstem Boundary entfernen
        if content_block.endswith(b"\r\n"):
            content_block = content_block[:-2]
        elif content_block.endswith(b"\n"):
            content_block = content_block[:-1]

        header_text = header_block.decode("utf-8", errors="replace")
        filename = None
        for line in header_text.splitlines():
            if "Content-Disposition:" in line and "filename=" in line:
                match = re.search(r'filename="?([^";\r\n]+)"?', line)
                if match:
                    filename = Path(match.group(1)).name

        if filename and content_block:
            files.append((filename, content_block))

    return files


def get_staged_media_info(config: AppConfig) -> Dict[str, Any]:
    """Sammelt Übersicht über ungesichtete Rohmedien und vorbereitete Artikel-Ordner."""
    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic"}
    video_exts = {".mp4", ".mov", ".mkv", ".avi", ".webm"}

    raw_files: List[Dict[str, Any]] = []
    raw_images_count = 0
    raw_videos_count = 0

    # 1. Rohdateien aus raw_dir & processed_dir
    check_dirs = [config.pipeline.raw_dir]
    if config.pipeline.processed_dir.exists() and config.pipeline.processed_dir != config.pipeline.raw_dir:
        check_dirs.append(config.pipeline.processed_dir)

    for d in check_dirs:
        if not d.exists():
            continue
        for f in sorted(d.iterdir(), key=lambda x: x.name):
            if f.is_file() and not f.name.startswith("."):
                ext = f.suffix.lower()
                media_type = "image" if ext in image_exts else ("video" if ext in video_exts else "other")
                if media_type == "image":
                    raw_images_count += 1
                elif media_type == "video":
                    raw_videos_count += 1

                raw_files.append({
                    "name": f.name,
                    "path": str(f),
                    "size_kb": round(f.stat().st_size / 1024, 1),
                    "ext": ext,
                    "type": media_type,
                    "modified": f.stat().st_mtime
                })

    # 2. Bereits sortierte Artikel-Ordner
    artikel_folders: List[Dict[str, Any]] = []
    if config.pipeline.artikel_dir.exists():
        for sub in sorted(config.pipeline.artikel_dir.iterdir(), key=lambda x: x.name):
            if sub.is_dir() and not sub.name.startswith("."):
                files = [f for f in sub.iterdir() if f.is_file() and not f.name.startswith(".")]
                artikel_folders.append({
                    "name": sub.name,
                    "files_count": len(files)
                })

    # 3. Quarantäne-Ordner
    inspect_count = 0
    inspect_dir = config.pipeline.output_dir / "to_inspect"
    if inspect_dir.exists():
        inspect_count = len([f for f in inspect_dir.iterdir() if not f.name.startswith(".")])

    return {
        "raw_count": len(raw_files),
        "raw_images": raw_images_count,
        "raw_videos": raw_videos_count,
        "raw_files": raw_files,
        "artikel_count": len(artikel_folders),
        "artikel_folders": artikel_folders,
        "inspect_count": inspect_count
    }


class PipelineStatusLogHandler(logging.Handler):
    """Logging-Handler zum Echtzeit-Streaming von Logs in den PipelineRunner."""
    def __init__(self, runner: "PipelineRunner"):
        super().__init__()
        self.runner = runner

    def emit(self, record):
        try:
            msg = self.format(record)
            self.runner.add_log(msg)
        except Exception:
            pass


class PipelineRunner:
    """Thread-sicherer Singleton zur asynchronen Ausführung der Sortier- und Analyse-Pipeline."""
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self.status: str = "IDLE"  # IDLE, RUNNING, COMPLETED, FAILED
        self.progress: int = 0
        self.current_step: str = "Bereit"
        self.total_items: int = 0
        self.completed_items: int = 0
        self.logs: deque = deque(maxlen=400)
        self.error: Optional[str] = None
        self.execution_dir: Optional[str] = None
        self.created_folders: List[str] = []
        self.worker_thread: Optional[threading.Thread] = None

    @classmethod
    def get_instance(cls) -> "PipelineRunner":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def add_log(self, msg: str):
        with self._lock:
            ts = datetime.now().strftime("%H:%M:%S")
            self.logs.append(f"[{ts}] {msg}")

    def reset(self):
        with self._lock:
            self.status = "IDLE"
            self.progress = 0
            self.current_step = "Bereit"
            self.total_items = 0
            self.completed_items = 0
            self.logs.clear()
            self.error = None
            self.created_folders = []
            self.worker_thread = None

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "status": self.status,
                "progress": self.progress,
                "current_step": self.current_step,
                "total_items": self.total_items,
                "completed_items": self.completed_items,
                "logs": list(self.logs),
                "error": self.error,
                "created_folders": self.created_folders,
                "execution_dir": self.execution_dir
            }

    def start_pipeline(self, config: AppConfig) -> bool:
        with self._lock:
            if self.status == "RUNNING":
                return False

            self.status = "RUNNING"
            self.progress = 5
            self.current_step = "Initialisiere Pipeline..."
            self.logs.clear()
            self.error = None
            self.created_folders = []

            self.worker_thread = threading.Thread(
                target=self._run_worker,
                args=(config,),
                daemon=True,
                name="PipelineWorker"
            )
            self.worker_thread.start()
            return True

    def _run_worker(self, config: AppConfig):
        log_handler = PipelineStatusLogHandler(self)
        formatter = logging.Formatter("%(levelname)s [%(name)s] %(message)s")
        log_handler.setFormatter(formatter)
        root_logger = logging.getLogger()
        root_logger.addHandler(log_handler)

        try:
            self.add_log("🚀 Starte multimodale Pipeline im Hintergrund...")

            # 1. Raw Ingest Sortierung
            self.current_step = "Sortiere Rohmedien (Raw Ingest)..."
            self.progress = 15
            self.add_log("▶ Prüfe Rohmedien und führe automatische Sortierung aus...")

            class MockArgs:
                source = None
                target = None
                inspect = None
                copy = False

            created_folders = run_sorting_process(
                args=MockArgs(),
                config=config,
                logger=logger
            )
            self.created_folders = [f.name for f in created_folders]
            self.add_log(f"✅ Sortierung abgeschlossen: {len(created_folders)} Artikel-Ordner bereitgestellt.")

            # 2. Aufgaben ermitteln
            self.progress = 25
            self.current_step = "Erfasse verarbeitbare Artikel..."
            search_dir = config.pipeline.artikel_dir
            if not search_dir.exists() or not any(search_dir.iterdir()):
                search_dir = config.pipeline.input_dir

            tasks = discover_item_tasks(search_dir)
            self.total_items = len(tasks)
            self.completed_items = 0

            if not tasks:
                self.add_log("ℹ️ Keine verarbeitbaren Artikel gefunden.")
                self.status = "COMPLETED"
                self.progress = 100
                self.current_step = "Keine Artikel zur Verarbeitung vorhanden."
                return

            self.add_log(f"📦 Gefundene Artikel zur KI-Analyse: {len(tasks)}")

            # 3. Pipeline initialisieren
            timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            execution_dir = (config.pipeline.output_dir / f"execution_{timestamp_str}").resolve()
            execution_dir.mkdir(parents=True, exist_ok=True)
            self.execution_dir = str(execution_dir)

            pipeline = VideoLLMPipeline(config=config, execution_dir=execution_dir)

            all_rows: List[Dict[str, Any]] = []
            all_web_research: List[Dict[str, Any]] = []

            for idx, task in enumerate(tasks, 1):
                self.current_step = f"Analysiere Artikel {idx}/{len(tasks)}: '{task.item_name}'..."
                progress_step = int(30 + (idx - 1) / len(tasks) * 50)
                self.progress = progress_step
                self.add_log(f"▶ [{idx}/{len(tasks)}] Verarbeite '{task.item_name}' (Video + Bilder)...")

                try:
                    state = pipeline.run(
                        video_path=task.video_path,
                        image_paths=task.image_paths,
                        item_name=task.item_name
                    )
                    if state.status == "SUCCESS":
                        unified_row = ExportService.build_unified_item_row_from_state(state)
                        all_rows.append(unified_row)

                        ref_listings = (
                            getattr(state, "reference_listings", None)
                            or getattr(state, "discovered_web_sources", None)
                            or []
                        )
                        if ref_listings:
                            web_rows = ExportService.build_web_research_rows(unified_row["id"], ref_listings)
                            all_web_research.extend(web_rows)

                        self.add_log(f"  ✅ '{task.item_name}' erfolgreich bewertet (ID: {state.detected_id})")
                    else:
                        self.add_log(f"  ⚠️ '{task.item_name}' mit Status '{state.status}' beendet.")
                except Exception as e:
                    self.add_log(f"  ❌ Fehler bei '{task.item_name}': {e}")

                self.completed_items = idx

            # 4. Konsolidierung & Export
            self.progress = 85
            self.current_step = "Erstelle konsolidierte Master-Tabelle & eBay-Exporte..."
            self.add_log("▶ Konsolidiere Gesamtergebnisse und erstelle Excel-Dateien...")

            if all_rows:
                summary_exporter = ExportService(execution_dir)
                summary_export = summary_exporter.export_consolidated_batch(
                    items_rows=all_rows,
                    web_research_rows=all_web_research,
                    base_filename="consolidated_execution_results"
                )
                self.add_log(f"📊 Excel erstellt: {summary_export['excel'].name}")

                try:
                    ebay_svc = EbayService(settings=config.ebay, output_dir=execution_dir)
                    ebay_res = ebay_svc.export_ebay_batch(
                        items=all_rows,
                        output_dir=execution_dir,
                        filename_prefix="ebay_listings"
                    )
                    self.add_log(f"🏛️ eBay Vorbereitung: {ebay_res['count']} Artikel exportiert.")
                except Exception as ex:
                    self.add_log(f"⚠️ eBay-Export Hinweis: {ex}")

            self.progress = 100
            self.status = "COMPLETED"
            self.current_step = "Recherche & Analyse erfolgreich abgeschlossen!"
            self.add_log("🎉 Gesamter Pipeline-Lauf erfolgreich beendet!")

        except Exception as e:
            logger.error(f"Pipeline Fehler: {e}", exc_info=True)
            self.status = "FAILED"
            self.error = str(e)
            self.current_step = f"Fehler aufgetreten: {e}"
            self.add_log(f"❌ KRITISCHER FEHLER: {e}\n{traceback.format_exc()}")
        finally:
            root_logger.removeHandler(log_handler)


HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Item Research & Marketplace Studio</title>
  <style>
    :root {
      --primary: #1f4e79;
      --primary-hover: #163857;
      --accent: #2e75b6;
      --accent-light: #eef6fc;
      --success: #28a745;
      --warning: #ffc107;
      --danger: #dc3545;
      --bg: #f4f6f9;
      --card: #ffffff;
      --border: #e2e8f0;
      --text: #2d3748;
      --text-muted: #718096;
      --terminal-bg: #1a202c;
      --terminal-text: #e2e8f0;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
    body { background-color: var(--bg); color: var(--text); height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

    header {
      background: linear-gradient(135deg, #1f4e79 0%, #0d233a 100%);
      color: #fff; padding: 10px 24px; display: flex; align-items: center; justify-content: space-between;
      box-shadow: 0 2px 8px rgba(0,0,0,0.15); z-index: 10;
    }
    header h1 { font-size: 18px; font-weight: 700; display: flex; align-items: center; gap: 10px; }
    
    /* Top Tab Navigation */
    .tab-nav {
      display: flex; gap: 6px; background: rgba(255,255,255,0.1); padding: 4px; border-radius: 8px;
    }
    .tab-btn {
      padding: 6px 14px; border-radius: 6px; font-size: 13px; font-weight: 600; color: #e2e8f0;
      background: transparent; border: none; cursor: pointer; transition: all 0.2s; display: flex; align-items: center; gap: 6px;
    }
    .tab-btn:hover { background: rgba(255,255,255,0.2); color: #fff; }
    .tab-btn.active { background: #fff; color: var(--primary); box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    .tab-btn .tab-badge { background: var(--accent); color: #fff; font-size: 10px; padding: 2px 6px; border-radius: 10px; font-weight: bold; }

    .status-bar { font-size: 12px; opacity: 0.9; }

    .main-view { flex: 1; display: none; overflow: hidden; }
    .main-view.active { display: flex; }

    /* ========================================================= */
    /* TAB 1: MEDIA INGEST & PIPELINE TRIGGER */
    /* ========================================================= */
    .ingest-container { flex: 1; display: flex; gap: 20px; padding: 20px 28px; overflow-y: auto; }
    .ingest-left { flex: 1.2; display: flex; flex-direction: column; gap: 18px; }
    .ingest-right { flex: 1; display: flex; flex-direction: column; gap: 18px; }

    .card {
      background: var(--card); border: 1px solid var(--border); border-radius: 10px;
      padding: 18px 22px; box-shadow: 0 2px 6px rgba(0,0,0,0.03); display: flex; flex-direction: column;
    }
    .card-title { font-size: 15px; font-weight: 700; color: var(--primary); margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; }

    .metrics-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
    .metric-box {
      background: #f8fafc; border: 1px solid var(--border); border-radius: 8px; padding: 12px; text-align: center;
    }
    .metric-value { font-size: 22px; font-weight: 800; color: var(--primary); }
    .metric-label { font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; margin-top: 2px; }

    /* Drag & Drop Zone */
    .dropzone {
      border: 2px dashed #93c5fd; border-radius: 10px; background: #f0f7ff; padding: 36px 20px;
      text-align: center; cursor: pointer; transition: all 0.2s ease; display: flex; flex-direction: column;
      align-items: center; justify-content: center; gap: 10px;
    }
    .dropzone:hover, .dropzone.dragover {
      border-color: var(--accent); background: #e0f2fe; transform: translateY(-2px);
    }
    .dropzone-icon { font-size: 42px; color: var(--accent); line-height: 1; }
    .dropzone-text { font-size: 15px; font-weight: 600; color: var(--primary); }
    .dropzone-hint { font-size: 12px; color: var(--text-muted); }

    /* Staged Media List */
    .staged-list {
      max-height: 220px; overflow-y: auto; border: 1px solid var(--border); border-radius: 6px;
      list-style: none; background: #fafbfc;
    }
    .staged-item {
      padding: 8px 12px; border-bottom: 1px solid var(--border); display: flex;
      align-items: center; justify-content: space-between; font-size: 12px;
    }
    .staged-item:last-child { border-bottom: none; }
    .staged-item-name { font-weight: 600; color: var(--text); display: flex; align-items: center; gap: 8px; }

    /* Action Trigger Button */
    .btn-large-action {
      background: linear-gradient(135deg, #1f4e79 0%, #2e75b6 100%);
      color: #fff; font-size: 16px; font-weight: 700; padding: 14px 24px; border-radius: 8px;
      border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 10px;
      box-shadow: 0 4px 12px rgba(31, 78, 121, 0.25); transition: all 0.2s;
    }
    .btn-large-action:hover { background: linear-gradient(135deg, #163857 0%, #1f4e79 100%); transform: translateY(-1px); }
    .btn-large-action:disabled { background: #cbd5e1; cursor: not-allowed; box-shadow: none; }

    /* Progress & Live Console */
    .progress-wrap { margin-top: 10px; }
    .progress-bar-bg { height: 12px; background: #e2e8f0; border-radius: 6px; overflow: hidden; }
    .progress-bar-fill {
      height: 100%; width: 0%; background: linear-gradient(90deg, #2e75b6, #28a745);
      border-radius: 6px; transition: width 0.3s ease;
    }
    .progress-status-text {
      display: flex; justify-content: space-between; font-size: 12px; font-weight: 600;
      color: var(--text-muted); margin-top: 6px;
    }

    .terminal-console {
      background: var(--terminal-bg); color: var(--terminal-text); border-radius: 8px;
      padding: 12px 16px; font-family: "Cascadia Code", Consolas, Monaco, monospace;
      font-size: 12px; line-height: 1.45; flex: 1; min-height: 260px; max-height: 380px;
      overflow-y: auto; white-space: pre-wrap; word-break: break-all;
    }

    /* ========================================================= */
    /* TAB 2: SPLIT SCREEN REVIEW (EXISTING WORKSPACE) */
    /* ========================================================= */
    .main-container { display: flex; flex: 1; overflow: hidden; }
    .sidebar { width: 300px; background: var(--card); border-right: 1px solid var(--border); display: flex; flex-direction: column; }
    .sidebar-header { padding: 14px 16px; border-bottom: 1px solid var(--border); font-size: 14px; font-weight: bold; background: #fafbfc; }
    .item-list { flex: 1; overflow-y: auto; list-style: none; }
    .item-card { padding: 12px 16px; border-bottom: 1px solid var(--border); cursor: pointer; transition: all 0.15s ease; }
    .item-card:hover { background: #f0f7ff; }
    .item-card.active { background: #e3f2fd; border-left: 4px solid var(--accent); }
    .item-card-title { font-size: 13px; font-weight: 600; margin-bottom: 4px; line-height: 1.3; }
    .item-card-meta { font-size: 11px; color: var(--text-muted); display: flex; justify-content: space-between; }
    .badge { display: inline-block; padding: 2px 7px; border-radius: 12px; font-size: 10px; font-weight: 700; text-transform: uppercase; }
    .badge-freigegeben { background: #d4edda; color: #155724; }
    .badge-entwurf { background: #fff3cd; color: #856404; }
    .badge-veröffentlicht { background: #cce5ff; color: #004085; }

    .content-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
    .toolbar { padding: 10px 24px; background: var(--card); border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
    .btn { padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; border: none; transition: background 0.15s; display: inline-flex; align-items: center; gap: 6px; }
    .btn-primary { background: var(--primary); color: #fff; }
    .btn-primary:hover { background: var(--primary-hover); }
    .btn-success { background: var(--success); color: #fff; }
    .btn-success:hover { background: #218838; }
    .btn-outline { background: transparent; border: 1px solid var(--border); color: var(--text); }
    .btn-outline:hover { background: #edf2f7; }

    .workspace { flex: 1; display: flex; overflow: hidden; padding: 16px 24px; gap: 20px; }
    .panel { flex: 1; background: var(--card); border: 1px solid var(--border); border-radius: 8px; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
    .panel-header { padding: 12px 18px; font-size: 14px; font-weight: bold; background: #f8fafc; border-bottom: 1px solid var(--border); color: var(--primary); display: flex; justify-content: space-between; align-items: center; }
    .panel-body { flex: 1; overflow-y: auto; padding: 18px; }

    .field-group { margin-bottom: 14px; }
    .field-label { font-size: 12px; font-weight: 700; color: var(--text-muted); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
    .field-value { font-size: 14px; line-height: 1.5; color: var(--text); }
    .price-box { background: #eef6fc; border-left: 4px solid var(--accent); padding: 12px; border-radius: 4px; margin-bottom: 16px; }
    .price-highlight { font-size: 20px; font-weight: bold; color: var(--primary); }

    .gallery-container { display: flex; flex-direction: column; height: 100%; }
    .main-image-wrap { flex: 1; background: #000; border-radius: 6px; display: flex; align-items: center; justify-content: center; margin-bottom: 12px; overflow: hidden; min-height: 250px; }
    .main-image { max-width: 100%; max-height: 100%; object-fit: contain; }
    .thumbnail-row { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 6px; }
    .thumbnail { width: 64px; height: 64px; border-radius: 4px; object-fit: cover; cursor: pointer; border: 2px solid transparent; }
    .thumbnail.active { border-color: var(--accent); }

    .edit-section { background: #fafbfc; border-top: 1px solid var(--border); padding: 16px 24px; display: grid; grid-template-columns: 2fr 1fr 1fr 1fr 1.2fr auto; gap: 14px; align-items: end; }
    .form-group { display: flex; flex-direction: column; gap: 4px; }
    .form-label { font-size: 11px; font-weight: bold; color: var(--text-muted); }
    .form-input, .form-select { padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; background: #fff; }
    .char-count { font-size: 11px; color: var(--text-muted); text-align: right; }
    .char-count.warning { color: var(--danger); font-weight: bold; }

    #toast { position: fixed; bottom: 20px; right: 20px; padding: 12px 20px; border-radius: 6px; background: #333; color: #fff; font-size: 13px; display: none; z-index: 1000; box-shadow: 0 4px 12px rgba(0,0,0,0.2); }
  </style>
</head>
<body>

  <header>
    <h1>🏛️ Item Research & Marketplace Studio</h1>
    
    <!-- Tab Switcher -->
    <div class="tab-nav">
      <button class="tab-btn active" id="btn-tab-ingest" onclick="switchTab('tab-ingest')">
        📥 1. Medien & Pipeline <span class="tab-badge" id="badge-raw-count">0</span>
      </button>
      <button class="tab-btn" id="btn-tab-review" onclick="switchTab('tab-review')">
        🔍 2. Artikel prüfen & Freigeben <span class="tab-badge" id="badge-items-count">0</span>
      </button>
      <button class="tab-btn" id="btn-tab-export" onclick="switchTab('tab-export')">
        📦 3. eBay Upload & Export
      </button>
    </div>

    <div class="status-bar" id="status-info">Bereit</div>
  </header>

  <!-- ========================================================= -->
  <!-- TAB 1: MEDIEN HOCHLADEN & PIPELINE AUSFÜHREN -->
  <!-- ========================================================= -->
  <div class="main-view active" id="tab-ingest">
    <div class="ingest-container">
      
      <!-- Left Column: Upload & Staged Files -->
      <div class="ingest-left">
        
        <!-- Metrics -->
        <div class="metrics-row">
          <div class="metric-box">
            <div class="metric-value" id="metric-raw-total">0</div>
            <div class="metric-label">Rohdateien</div>
          </div>
          <div class="metric-box">
            <div class="metric-value" id="metric-raw-images">0</div>
            <div class="metric-label">Fotos (JPG/PNG)</div>
          </div>
          <div class="metric-box">
            <div class="metric-value" id="metric-raw-videos">0</div>
            <div class="metric-label">Videos (MP4/MOV)</div>
          </div>
          <div class="metric-box">
            <div class="metric-value" id="metric-artikel-folders">0</div>
            <div class="metric-label">Artikel-Ordner</div>
          </div>
        </div>

        <!-- Drag & Drop Dropzone -->
        <div class="card">
          <div class="card-title">
            <span>📥 Medien per Drag & Drop bereitstellen</span>
            <span style="font-size: 12px; font-weight: normal; color: var(--text-muted);">Ziel: input/raw/</span>
          </div>
          
          <div class="dropzone" id="dropzone" onclick="document.getElementById('file-input').click()">
            <div class="dropzone-icon">📁</div>
            <div class="dropzone-text">Fotos & Videos hier hineinziehen</div>
            <div class="dropzone-hint">oder klicken zum Auswählen (JPG, PNG, HEIC, WEBP, MP4, MOV, MKV)</div>
            <input type="file" id="file-input" multiple accept="image/*,video/*,.heic,.mov,.mkv,.avi,.mp4,.jpg,.jpeg,.png,.webp" style="display: none;" onchange="handleFileSelect(event)">
          </div>
        </div>

        <!-- Staged Files Grid/List -->
        <div class="card" style="flex: 1;">
          <div class="card-title">
            <span>📋 Bereitgestellte Rohdateien (<span id="staged-list-count">0</span>)</span>
            <button class="btn btn-outline" style="padding: 4px 10px; font-size: 11px;" onclick="loadStagedMedia()">🔄 Aktualisieren</button>
          </div>
          <ul class="staged-list" id="staged-files-ul">
            <li style="padding: 20px; text-align: center; color: var(--text-muted); font-size: 13px;">Keine ungesichteten Rohdateien in input/raw vorhanden.</li>
          </ul>
        </div>

      </div>

      <!-- Right Column: Trigger & Realtime Console -->
      <div class="ingest-right">
        
        <!-- Pipeline Trigger Card -->
        <div class="card">
          <div class="card-title">
            <span>🤖 KI-Recherche & Marktbewertung</span>
          </div>
          <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 16px; line-height: 1.4;">
            Startet die automatische Sortierung (1. Bild = ID -> Detailfotos -> Video) und führt die multimodale Gemini KI-Extraktion und empirische Web-Marktrecherche im Hintergrund durch.
          </p>

          <button class="btn-large-action" id="btn-run-pipeline" onclick="triggerPipeline()">
            <span>🚀 Recherche & Beschreibung generieren</span>
          </button>

          <div class="progress-wrap" id="progress-container" style="display: none;">
            <div class="progress-bar-bg">
              <div class="progress-bar-fill" id="progress-fill"></div>
            </div>
            <div class="progress-status-text">
              <span id="progress-step-text">Bereite Ausführung vor...</span>
              <span id="progress-percent-text">0%</span>
            </div>
          </div>
        </div>

        <!-- Live Terminal Log Stream -->
        <div class="card" style="flex: 1;">
          <div class="card-title">
            <span>🖥️ Live-Ausführungsprotokoll</span>
            <span class="badge badge-entwurf" id="pipeline-status-badge">Bereit</span>
          </div>
          <div class="terminal-console" id="terminal-logs">Warte auf Pipeline-Start...</div>
        </div>

      </div>

    </div>
  </div>

  <!-- ========================================================= -->
  <!-- TAB 2: ARTIKEL PRÜFEN & FREIGEBEN (REVIEW HUB) -->
  <!-- ========================================================= -->
  <div class="main-view" id="tab-review">
    <div class="main-container">
      <!-- Sidebar -->
      <div class="sidebar">
        <div class="sidebar-header">
          Gefundene Artikel (<span id="item-count">0</span>)
        </div>
        <ul class="item-list" id="items-ul"></ul>
      </div>

      <!-- Main Workspace -->
      <div class="content-area">
        <div class="toolbar">
          <div>
            <span style="font-weight: 600; font-size: 14px;" id="selected-item-title">Kein Artikel ausgewählt</span>
          </div>
          <div style="display: flex; gap: 10px;">
            <button class="btn btn-outline" onclick="loadItems()">🔄 Neu laden</button>
            <button class="btn btn-primary" onclick="exportEbayCsv()">📦 eBay CSV erstellen</button>
            <button class="btn btn-success" onclick="saveCurrentItem(true)">💾 Speichern & Nächster</button>
          </div>
        </div>

        <div class="workspace">
          <!-- Left Panel: Data & Research -->
          <div class="panel">
            <div class="panel-header">
              <span>📊 Recherche & Bewertungsdaten</span>
              <span id="item-id-badge" class="badge badge-entwurf">ID: -</span>
            </div>
            <div class="panel-body" id="details-body">
              <div style="color: var(--text-muted); text-align: center; margin-top: 40px;">Wähle einen Artikel aus der linken Liste.</div>
            </div>
          </div>

          <!-- Right Panel: Images -->
          <div class="panel">
            <div class="panel-header">
              <span>📷 Original-Bildmaterial (<span id="photo-count">0</span>)</span>
            </div>
            <div class="panel-body" style="padding: 12px;">
              <div class="gallery-container">
                <div class="main-image-wrap">
                  <img id="main-photo" class="main-image" src="" alt="Kein Bild vorhanden">
                </div>
                <div class="thumbnail-row" id="thumbnail-row"></div>
              </div>
            </div>
          </div>
        </div>

        <!-- Bottom: Edit Bar -->
        <div class="edit-section" id="edit-bar">
          <div class="form-group">
            <label class="form-label">eBay Titel (Max 80 Zeichen)</label>
            <input type="text" id="input-title" class="form-input" oninput="updateCharCount()">
            <div class="char-count" id="char-count">0 / 80</div>
          </div>

          <div class="form-group">
            <label class="form-label">Verkaufspreis (€)</label>
            <input type="number" step="0.50" id="input-price" class="form-input">
          </div>

          <div class="form-group">
            <label class="form-label">Plattform</label>
            <select id="input-platform" class="form-select">
              <option value="eBay">eBay</option>
              <option value="Etsy">Etsy</option>
              <option value="Kleinanzeigen">Kleinanzeigen</option>
              <option value="Shop">Eigenes Webshop</option>
            </select>
          </div>

          <div class="form-group">
            <label class="form-label">Format</label>
            <select id="input-format" class="form-select">
              <option value="FixedPrice">Sofort-Kaufen (Festpreis)</option>
              <option value="Auction">Auktion (7 Tage)</option>
            </select>
          </div>

          <div class="form-group">
            <label class="form-label">Freigabe-Status</label>
            <select id="input-status" class="form-select">
              <option value="Freigegeben">✅ Freigegeben</option>
              <option value="Entwurf">📝 Entwurf</option>
              <option value="Zurückgehalten">⏸️ Zurückgehalten</option>
              <option value="Veröffentlicht">🚀 Veröffentlicht</option>
            </select>
          </div>

          <button class="btn btn-success" onclick="saveCurrentItem(false)">💾 Speichern</button>
        </div>
      </div>
    </div>
  </div>

  <!-- ========================================================= -->
  <!-- TAB 3: EBAY EXPORT & PUBLISH (PLACEHOLDER) -->
  <!-- ========================================================= -->
  <div class="main-view" id="tab-export">
    <div style="flex: 1; padding: 40px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 20px;">
      <div class="card" style="max-width: 600px; width: 100%; text-align: center;">
        <div class="card-title" style="justify-content: center;">📦 eBay Seller Hub & REST API Export</div>
        <p style="font-size: 14px; color: var(--text-muted); margin-bottom: 24px;">
          Exportiere alle geprüften und freigegebenen Artikel für das eBay Seller Hub (CSV File Exchange) oder veröffentliche direkt live über die eBay REST API.
        </p>
        <div style="display: flex; justify-content: center; gap: 14px;">
          <button class="btn btn-primary" style="padding: 12px 24px; font-size: 14px;" onclick="exportEbayCsv()">📦 eBay CSV Datei erstellen</button>
        </div>
      </div>
    </div>
  </div>

  <div id="toast">Meldung</div>

  <script>
    let currentItems = [];
    let selectedIndex = 0;
    let pollInterval = null;

    // --- Tab Navigation ---
    function switchTab(tabId) {
      document.querySelectorAll(".main-view").forEach(el => el.classList.remove("active"));
      document.querySelectorAll(".tab-btn").forEach(el => el.classList.remove("active"));

      const targetView = document.getElementById(tabId);
      if (targetView) targetView.classList.add("active");

      if (tabId === "tab-ingest") {
        document.getElementById("btn-tab-ingest").classList.add("active");
        loadStagedMedia();
      } else if (tabId === "tab-review") {
        document.getElementById("btn-tab-review").classList.add("active");
        loadItems();
      } else if (tabId === "tab-export") {
        document.getElementById("btn-tab-export").classList.add("active");
      }
    }

    // --- Tab 1: Drag and Drop & Staged Media ---
    const dropzone = document.getElementById("dropzone");
    ['dragenter', 'dragover'].forEach(eventName => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.add("dragover");
      }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.remove("dragover");
      }, false);
    });

    dropzone.addEventListener('drop', (e) => {
      const dt = e.dataTransfer;
      const files = dt.files;
      if (files.length > 0) {
        uploadFiles(files);
      }
    });

    function handleFileSelect(event) {
      const files = event.target.files;
      if (files.length > 0) {
        uploadFiles(files);
      }
    }

    async function uploadFiles(files) {
      showToast(`Lade ${files.length} Datei(en) hoch...`);
      const formData = new FormData();
      for (let i = 0; i < files.length; i++) {
        formData.append("files", files[i]);
      }

      try {
        const res = await fetch("/api/upload", {
          method: "POST",
          body: formData
        });
        const data = await res.json();
        if (data.success) {
          showToast(`✅ ${data.count} Datei(en) erfolgreich in input/raw/ gespeichert!`);
          loadStagedMedia();
        } else {
          showToast("❌ Upload-Fehler: " + (data.error || "Unbekannt"));
        }
      } catch (err) {
        showToast("❌ Upload fehlgeschlagen: " + err.message);
      }
    }

    async function loadStagedMedia() {
      try {
        const res = await fetch("/api/staged_media");
        const data = await res.json();

        document.getElementById("metric-raw-total").innerText = data.raw_count || 0;
        document.getElementById("metric-raw-images").innerText = data.raw_images || 0;
        document.getElementById("metric-raw-videos").innerText = data.raw_videos || 0;
        document.getElementById("metric-artikel-folders").innerText = data.artikel_count || 0;
        document.getElementById("badge-raw-count").innerText = data.raw_count || 0;
        document.getElementById("staged-list-count").innerText = data.raw_count || 0;

        const ul = document.getElementById("staged-files-ul");
        ul.innerHTML = "";

        if (!data.raw_files || data.raw_files.length === 0) {
          ul.innerHTML = `<li style="padding: 20px; text-align: center; color: var(--text-muted); font-size: 13px;">Keine ungesichteten Rohdateien in input/raw/ vorhanden.</li>`;
        } else {
          data.raw_files.forEach(f => {
            const li = document.createElement("li");
            li.className = "staged-item";
            const icon = f.type === "video" ? "🎥" : (f.type === "image" ? "📷" : "📄");
            li.innerHTML = `
              <span class="staged-item-name">${icon} ${f.name}</span>
              <span style="color: var(--text-muted); font-size: 11px;">${f.size_kb} KB</span>
            `;
            ul.appendChild(li);
          });
        }
      } catch (err) {
        console.error("Fehler beim Laden der Staged Media:", err);
      }
    }

    // --- Tab 1: Pipeline Execution & Status Polling ---
    async function triggerPipeline() {
      const btn = document.getElementById("btn-run-pipeline");
      btn.disabled = true;
      document.getElementById("progress-container").style.display = "block";
      showToast("🚀 Starte Pipeline im Hintergrund...");

      try {
        const res = await fetch("/api/run_pipeline", { method: "POST" });
        const data = await res.json();
        if (data.success) {
          startStatusPolling();
        } else {
          showToast("❌ Start fehlgeschlagen: " + data.error);
          btn.disabled = false;
        }
      } catch (err) {
        showToast("❌ Fehler beim Aufruf: " + err.message);
        btn.disabled = false;
      }
    }

    function startStatusPolling() {
      if (pollInterval) clearInterval(pollInterval);
      pollInterval = setInterval(checkPipelineStatus, 800);
      checkPipelineStatus();
    }

    async function checkPipelineStatus() {
      try {
        const res = await fetch("/api/pipeline_status");
        const data = await res.json();

        const badge = document.getElementById("pipeline-status-badge");
        const btn = document.getElementById("btn-run-pipeline");
        const fill = document.getElementById("progress-fill");
        const stepText = document.getElementById("progress-step-text");
        const percentText = document.getElementById("progress-percent-text");
        const terminal = document.getElementById("terminal-logs");

        fill.style.width = (data.progress || 0) + "%";
        percentText.innerText = (data.progress || 0) + "%";
        stepText.innerText = data.current_step || "Warte...";

        if (data.logs && data.logs.length > 0) {
          terminal.innerText = data.logs.join("\\n");
          terminal.scrollTop = terminal.scrollHeight;
        }

        if (data.status === "RUNNING") {
          badge.className = "badge badge-entwurf";
          badge.innerText = "Ausführung läuft...";
          btn.disabled = true;
          document.getElementById("progress-container").style.display = "block";
        } else if (data.status === "COMPLETED") {
          badge.className = "badge badge-freigegeben";
          badge.innerText = "Abgeschlossen";
          btn.disabled = false;
          clearInterval(pollInterval);
          pollInterval = null;
          showToast("🎉 Pipeline erfolgreich abgeschlossen! Wechsle zu Tab 2...");
          
          // Automatische Umschaltung auf Tab 2
          setTimeout(() => {
            switchTab("tab-review");
          }, 1200);
        } else if (data.status === "FAILED") {
          badge.className = "badge badge-veröffentlicht";
          badge.style.background = "#f8d7da";
          badge.style.color = "#721c24";
          badge.innerText = "Fehlgeschlagen";
          btn.disabled = false;
          clearInterval(pollInterval);
          pollInterval = null;
          showToast("❌ Pipeline-Fehler: " + (data.error || "Details im Protokoll"));
        } else {
          badge.className = "badge badge-entwurf";
          badge.innerText = "Bereit";
          btn.disabled = false;
        }
      } catch (err) {
        console.error("Status polling error:", err);
      }
    }

    // --- Tab 2: Review Hub Logic ---
    async function loadItems() {
      showToast("Lade Artikeldaten...");
      try {
        const res = await fetch("/api/items");
        const data = await res.json();
        currentItems = data.items || [];
        document.getElementById("status-info").innerText = `Datei: ${data.file_name || 'N/A'} (${currentItems.length} Artikel)`;
        document.getElementById("item-count").innerText = currentItems.length;
        document.getElementById("badge-items-count").innerText = currentItems.length;

        renderSidebar();
        if (currentItems.length > 0) {
          selectItem(0);
        }
      } catch (err) {
        showToast("Fehler beim Laden: " + err.message);
      }
    }

    function renderSidebar() {
      const ul = document.getElementById("items-ul");
      ul.innerHTML = "";
      currentItems.forEach((it, idx) => {
        const li = document.createElement("li");
        li.className = `item-card ${idx === selectedIndex ? 'active' : ''}`;
        li.onclick = () => selectItem(idx);

        const status = (it.Status || "Entwurf").toLowerCase();
        const badgeClass = status.includes("freigeb") ? "badge-freigegeben" : (status.includes("veröff") ? "badge-veröffentlicht" : "badge-entwurf");

        li.innerHTML = `
          <div class="item-card-title">${it.titel || it.Produkt_Titel || 'Artikel ' + (it.id || idx+1)}</div>
          <div class="item-card-meta">
            <span>ID: ${it.id || 'N/A'} | € ${(it.ErzielterPreis || it.Empfohlener_Retail_Preis_EUR || it.Preis_EUR || 0)}</span>
            <span class="badge ${badgeClass}">${it.Status || 'Entwurf'}</span>
          </div>
        `;
        ul.appendChild(li);
      });
    }

    function selectItem(idx) {
      selectedIndex = idx;
      renderSidebar();
      const it = currentItems[idx];
      if (!it) return;

      document.getElementById("selected-item-title").innerText = it.titel || "Artikel " + it.id;
      document.getElementById("item-id-badge").innerText = "ID: " + (it.id || "N/A");

      const details = document.getElementById("details-body");
      details.innerHTML = `
        <div class="price-box">
          <div style="font-size: 12px; color: var(--accent); font-weight: bold; margin-bottom: 2px;">EMPFOHLENE RETRO-BEWERTUNG (LLM)</div>
          <div class="price-highlight">€ ${(it.Empfohlener_Retail_Preis_EUR || it.Preis_EUR || 0).toFixed(2)}</div>
          <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
            Spanne: € ${(it.Preisspanne_Min_EUR || 0).toFixed(2)} - € ${(it.Preisspanne_Max_EUR || 0).toFixed(2)} | Web-Median: € ${(it.Median_Web_Preis_EUR || 0).toFixed(2)} (${it.Anzahl_gefundene_Webpreise || 0} Quellen)
          </div>
        </div>

        <div class="field-group">
          <div class="field-label">Produktbeschreibung</div>
          <div class="field-value">${(it.produktbeschreibung || 'Keine Beschreibung vorhanden.').replace(/\\n/g, '<br>')}</div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 14px;">
          <div class="field-group">
            <div class="field-label">Hersteller / Epoche</div>
            <div class="field-value">${it.hersteller_oder_marke || 'Unbekannt'} / ${it.modell_oder_epoche || it.geschaetztes_jahr_oder_epoche || 'Vintage'}</div>
          </div>
          <div class="field-group">
            <div class="field-label">Material & Farbe</div>
            <div class="field-value">${it.material || 'Unbekannt'} (${it.farbe || '-'})</div>
          </div>
        </div>

        <div class="field-group">
          <div class="field-label">Abmessungen & Logistik</div>
          <div class="field-value">L: ${it.laenge_cm || '-'} cm, B: ${it.breite_cm || '-'} cm, H: ${it.hoehe_cm || '-'} cm, Gewicht: ${it.gewicht_kg || '-'} kg | <strong>${it.logistik_kategorie || 'Paket'}</strong></div>
        </div>

        <div class="field-group">
          <div class="field-label">Zustand & Mängel</div>
          <div class="field-value"><strong>${it.zustand || 'Gebraucht'}</strong>: ${it.maengel || 'Keine besonderen Mängel'}${it.fehlende_teile ? ' | Fehlend: ' + it.fehlende_teile : ''}</div>
        </div>

        <div class="field-group">
          <div class="field-label">Preisfindungs-Begründung</div>
          <div class="field-value" style="font-size: 13px; color: var(--text-muted);">${it.Begruendung_Preisfindung || '-'}</div>
        </div>
      `;

      document.getElementById("input-title").value = it.titel || it.Produkt_Titel || "";
      document.getElementById("input-price").value = it.ErzielterPreis || it.Empfohlener_Retail_Preis_EUR || it.Preis_EUR || "";
      document.getElementById("input-platform").value = it.VerkaufsOrt || "eBay";
      document.getElementById("input-format").value = it.AngebotsFormat || "FixedPrice";
      document.getElementById("input-status").value = it.Status || "Freigegeben";
      updateCharCount();

      loadImagesForSelected(it);
    }

    function updateCharCount() {
      const title = document.getElementById("input-title").value;
      const countEl = document.getElementById("char-count");
      countEl.innerText = `${title.length} / 80 Zeichen`;
      if (title.length > 80) {
        countEl.className = "char-count warning";
      } else {
        countEl.className = "char-count";
      }
    }

    async function loadImagesForSelected(item) {
      const thumbRow = document.getElementById("thumbnail-row");
      const mainImg = document.getElementById("main-photo");
      thumbRow.innerHTML = "";
      document.getElementById("photo-count").innerText = "0";

      const res = await fetch(`/api/images_for_item?id=${encodeURIComponent(item.id || '')}&name=${encodeURIComponent(item.ordner_name || item.titel || '')}`);
      const data = await res.json();
      const images = data.images || [];

      document.getElementById("photo-count").innerText = images.length;
      if (images.length > 0) {
        mainImg.src = images[0].url;
        images.forEach((img, idx) => {
          const t = document.createElement("img");
          t.src = img.url;
          t.className = `thumbnail ${idx === 0 ? 'active' : ''}`;
          t.onclick = () => {
            mainImg.src = img.url;
            document.querySelectorAll(".thumbnail").forEach(el => el.classList.remove("active"));
            t.classList.add("active");
          };
          thumbRow.appendChild(t);
        });
      } else {
        mainImg.src = "";
      }
    }

    async function saveCurrentItem(autoAdvance = false) {
      const it = currentItems[selectedIndex];
      if (!it) return;

      const payload = {
        id: it.id,
        titel: document.getElementById("input-title").value,
        ErzielterPreis: parseFloat(document.getElementById("input-price").value) || it.Empfohlener_Retail_Preis_EUR,
        VerkaufsOrt: document.getElementById("input-platform").value,
        AngebotsFormat: document.getElementById("input-format").value,
        Status: document.getElementById("input-status").value
      };

      try {
        const res = await fetch("/api/save_item", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const resp = await res.json();
        if (resp.success) {
          showToast("✅ Artikel erfolgreich gespeichert & synchronisiert!");
          Object.assign(it, payload);
          renderSidebar();
          if (autoAdvance && selectedIndex < currentItems.length - 1) {
            selectItem(selectedIndex + 1);
          }
        }
      } catch (err) {
        showToast("❌ Fehler beim Speichern: " + err.message);
      }
    }

    async function exportEbayCsv() {
      showToast("Erstelle eBay File Exchange CSV...");
      try {
        const res = await fetch("/api/export_ebay", { method: "POST" });
        const data = await res.json();
        if (data.success) {
          showToast(`🚀 eBay Export erfolgreich! (${data.count} Artikel exportiert)`);
          alert(`eBay CSV erfolgreich erstellt:\\n\\nDatei: ${data.csv}\\nPayload: ${data.json}\\n\\nAnzahl Artikel: ${data.count}`);
        } else {
          showToast("❌ Export fehlgeschlagen: " + data.error);
        }
      } catch (err) {
        showToast("Fehler beim Export: " + err.message);
      }
    }

    function showToast(msg) {
      const t = document.getElementById("toast");
      t.innerText = msg;
      t.style.display = "block";
      setTimeout(() => { t.style.display = "none"; }, 3500);
    }

    window.onload = () => {
      loadStagedMedia();
      loadItems();
      checkPipelineStatus();
    };
  </script>
</body>
</html>
"""


class StudioHTTPRequestHandler(BaseHTTPRequestHandler):
    config = load_config()
    current_file_path: Optional[Path] = None

    def _set_headers(self, content_type: str = "text/html; charset=utf-8", status_code: int = 200):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)

        if path == "/" or path == "/index.html":
            self._set_headers("text/html; charset=utf-8")
            self.wfile.write(HTML_DASHBOARD.encode("utf-8"))

        elif path == "/api/staged_media":
            info = get_staged_media_info(self.config)
            self._set_headers("application/json; charset=utf-8")
            self.wfile.write(json.dumps(info, ensure_ascii=False).encode("utf-8"))

        elif path == "/api/pipeline_status":
            status = PipelineRunner.get_instance().get_status()
            self._set_headers("application/json; charset=utf-8")
            self.wfile.write(json.dumps(status, ensure_ascii=False).encode("utf-8"))

        elif path == "/api/items":
            self._handle_get_items()

        elif path == "/api/images_for_item":
            item_id = query.get("id", [""])[0]
            item_name = query.get("name", [""])[0]
            images = find_item_images(item_id, item_name, self.config.base_dir)
            img_list = [{"name": p.name, "url": f"/api/image?path={urllib.parse.quote(str(p))}"} for p in images]
            self._set_headers("application/json; charset=utf-8")
            self.wfile.write(json.dumps({"images": img_list}).encode("utf-8"))

        elif path == "/api/image":
            img_path_str = query.get("path", [""])[0]
            if img_path_str:
                p = Path(img_path_str).resolve()
                if p.exists() and p.is_file():
                    mime = "image/jpeg"
                    if p.suffix.lower() == ".png": mime = "image/png"
                    elif p.suffix.lower() == ".webp": mime = "image/webp"
                    
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Cache-Control", "max-age=3600")
                    self.end_headers()
                    with open(p, "rb") as f:
                        self.wfile.write(f.read())
                    return
            self.send_error(404, "Bild nicht gefunden")

        else:
            self.send_error(404, "Endpunkt nicht gefunden")

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        length = int(self.headers.get("Content-Length", 0))
        content_type = self.headers.get("Content-Type", "")

        if path == "/api/upload":
            body = self.rfile.read(length) if length > 0 else b""
            self._handle_upload(body, content_type)

        elif path == "/api/run_pipeline":
            runner = PipelineRunner.get_instance()
            started = runner.start_pipeline(self.config)
            if started:
                self._set_headers("application/json; charset=utf-8")
                self.wfile.write(json.dumps({"success": True, "message": "Pipeline gestartet"}).encode("utf-8"))
            else:
                self._set_headers("application/json; charset=utf-8", 409)
                self.wfile.write(json.dumps({"success": False, "error": "Pipeline läuft bereits"}).encode("utf-8"))

        elif path == "/api/pipeline_reset":
            PipelineRunner.get_instance().reset()
            self._set_headers("application/json; charset=utf-8")
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))

        else:
            body = self.rfile.read(length) if length > 0 else b""
            payload = json.loads(body.decode("utf-8")) if body else {}

            if path == "/api/save_item":
                self._handle_save_item(payload)
            elif path == "/api/export_ebay":
                self._handle_export_ebay()
            else:
                self.send_error(404, "Endpunkt nicht gefunden")

    def _handle_upload(self, body: bytes, content_type: str):
        """Speichert hochgeladene Dateien sicher in raw_dir."""
        raw_dir = self.config.pipeline.raw_dir
        raw_dir.mkdir(parents=True, exist_ok=True)

        files = parse_multipart_form_data(body, content_type)
        saved_files = []

        if files:
            for fname, data in files:
                clean_name = Path(fname).name
                dest = raw_dir / clean_name
                with open(dest, "wb") as f:
                    f.write(data)
                saved_files.append(clean_name)
        elif body:
            # Fallback direkte Dateibereitstellung
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            fname = query.get("filename", ["uploaded_file.jpg"])[0]
            clean_name = Path(fname).name
            dest = raw_dir / clean_name
            with open(dest, "wb") as f:
                f.write(body)
            saved_files.append(clean_name)

        self._set_headers("application/json; charset=utf-8")
        self.wfile.write(json.dumps({
            "success": True,
            "count": len(saved_files),
            "files": saved_files
        }).encode("utf-8"))

    def _handle_get_items(self):
        target_file = find_latest_execution_file(self.config.pipeline.output_dir)
        self.__class__.current_file_path = target_file

        items = []
        file_name = ""
        if target_file and target_file.exists():
            file_name = target_file.name
            try:
                xl = pd.ExcelFile(target_file)
                sheet_name = "Alle_Artikel" if "Alle_Artikel" in xl.sheet_names else ("Hauptempfehlung" if "Hauptempfehlung" in xl.sheet_names else xl.sheet_names[0])
                df = pd.read_excel(target_file, sheet_name=sheet_name)
                for r in df.to_dict(orient="records"):
                    clean_r = {str(k).strip(): (v if pd.notna(v) else "") for k, v in r.items()}
                    items.append(clean_r)
            except Exception as e:
                logger.error(f"Fehler beim Lesen der Excel: {e}")

        self._set_headers("application/json; charset=utf-8")
        self.wfile.write(json.dumps({"file_name": file_name, "items": items}, ensure_ascii=False).encode("utf-8"))

    def _handle_save_item(self, payload: Dict[str, Any]):
        target_file = self.__class__.current_file_path or find_latest_execution_file(self.config.pipeline.output_dir)
        item_id = str(payload.get("id", "")).strip()

        if target_file and target_file.exists() and target_file.suffix.lower() in [".xlsx", ".xls"]:
            try:
                xl = pd.ExcelFile(target_file)
                sheet_name = "Alle_Artikel" if "Alle_Artikel" in xl.sheet_names else ("Hauptempfehlung" if "Hauptempfehlung" in xl.sheet_names else xl.sheet_names[0])
                df = pd.read_excel(target_file, sheet_name=sheet_name)

                # Aktualisiere Datensatz
                mask = df["id"].astype(str).str.strip() == item_id
                if not mask.any():
                    mask = df.index == 0

                for k, v in payload.items():
                    if k in df.columns:
                        df.loc[mask, k] = v

                # Schreibe zurück
                with pd.ExcelWriter(target_file, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
                    df.to_excel(writer, index=False, sheet_name=sheet_name)

                logger.info(f"Artikel '{item_id}' in '{target_file.name}' aktualisiert.")
            except Exception as e:
                logger.warning(f"Excel Update gescheitert: {e}")

        # Audit History sichern
        audit_file = self.config.pipeline.output_dir / "reviewed_listings.json"
        history = []
        if audit_file.exists():
            try:
                with open(audit_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                history = []
        
        history.append(payload)
        with open(audit_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

        self._set_headers("application/json; charset=utf-8")
        self.wfile.write(json.dumps({"success": True}).encode("utf-8"))

    def _handle_export_ebay(self):
        target_file = self.__class__.current_file_path or find_latest_execution_file(self.config.pipeline.output_dir)
        if not target_file or not target_file.exists():
            self._set_headers("application/json; charset=utf-8", 400)
            self.wfile.write(json.dumps({"success": False, "error": "Keine Datendatei gefunden"}).encode("utf-8"))
            return

        ebay_svc = EbayService(settings=self.config.ebay, output_dir=self.config.pipeline.output_dir)
        items = ebay_svc.load_items_from_source(
            source_path=target_file,
            status_filter="Freigegeben",
            platform_filter="ebay"
        )

        res = ebay_svc.export_ebay_batch(
            items=items,
            output_dir=self.config.pipeline.output_dir,
            filename_prefix="ebay_listings"
        )

        self._set_headers("application/json; charset=utf-8")
        self.wfile.write(json.dumps({
            "success": True,
            "csv": str(res["csv"]),
            "json": str(res["json"]),
            "count": res["count"]
        }).encode("utf-8"))


def start_ui_server(port: int = 8501, auto_open: bool = True):
    """Startet den eingebetteten Review Hub HTTP-Server."""
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, StudioHTTPRequestHandler)
    url = f"http://127.0.0.1:{port}"
    print("=" * 70)
    print(f"🏛️ ITEM RESEARCH & MARKETPLACE STUDIO GESTARTET")
    print(f"🌐 Öffne im Webbrowser: {url}")
    print("=" * 70)

    if auto_open:
        webbrowser.open(url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStudio beendet.")
        httpd.server_close()
