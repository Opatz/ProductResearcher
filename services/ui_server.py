import os
import re
import io
import json
import time
import shutil
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


def find_item_videos(item_id: str, item_name: str, base_dir: Path) -> List[Path]:
    """Findet alle zugehörigen Videodateien für einen Artikel."""
    videos: List[Path] = []
    video_exts = {".mp4", ".mov", ".mkv", ".avi", ".webm"}

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
                    if f.is_file() and f.suffix.lower() in video_exts:
                        videos.append(f)
                if videos:
                    return videos

    return videos


def parse_multipart_form_data(body: bytes, content_type_header: str) -> List[Tuple[str, bytes]]:
    """
    Parst multipart/form-data ohne veraltetes cgi-Modul (kompatibel mit Python 3.10-3.13+).
    Gibt eine Liste von (filename, content_bytes) zurück.
    """
    files: List[Tuple[str, bytes]] = []
    if "boundary=" not in content_type_header:
        return files

    boundary_token = content_type_header.split("boundary=")[1].split(";")[0].strip().strip('"').strip("'")
    boundary = ("--" + boundary_token).encode("utf-8")

    parts = body.split(boundary)
    for part in parts:
        if not part or part == b"--\r\n" or part == b"--" or part.startswith(b"--"):
            continue

        # Trim leading CRLF from part if present
        if part.startswith(b"\r\n"):
            part = part[2:]
        elif part.startswith(b"\n"):
            part = part[1:]

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
            if "content-disposition:" in line.lower() and "filename=" in line.lower():
                m_quoted = re.search(r'filename="([^"]+)"', line, re.IGNORECASE)
                if m_quoted:
                    raw_fn = m_quoted.group(1)
                    filename = re.split(r'[\\/]', raw_fn)[-1]
                else:
                    m_unquoted = re.search(r'filename=([^;\r\n]+)', line, re.IGNORECASE)
                    if m_unquoted:
                        raw_fn = m_unquoted.group(1).strip().strip('"').strip("'")
                        filename = re.split(r'[\\/]', raw_fn)[-1]

        if filename and content_block is not None:
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
      --warning: #f59e0b;
      --danger: #dc3545;
      --danger-light: #fee2e2;
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
    /* TAB 2: SPLIT SCREEN REVIEW (STUDIO) */
    /* ========================================================= */
    .main-container { display: flex; flex: 1; overflow: hidden; }
    
    /* Left Sidebar */
    .sidebar { width: 330px; min-width: 300px; background: var(--card); border-right: 1px solid var(--border); display: flex; flex-direction: column; }
    .sidebar-header { padding: 12px 16px; border-bottom: 1px solid var(--border); background: #fafbfc; display: flex; flex-direction: column; gap: 10px; }
    .sidebar-search-box { display: flex; align-items: center; position: relative; }
    .sidebar-search-input { width: 100%; padding: 7px 10px 7px 30px; border: 1px solid var(--border); border-radius: 6px; font-size: 12px; background: #fff; }
    .sidebar-search-icon { position: absolute; left: 9px; font-size: 13px; color: var(--text-muted); }
    
    /* Filter Pills */
    .filter-pills { display: flex; gap: 4px; overflow-x: auto; padding-bottom: 2px; }
    .filter-pill {
      padding: 4px 9px; border-radius: 12px; font-size: 11px; font-weight: 600;
      background: #f1f5f9; border: 1px solid var(--border); color: var(--text-muted);
      cursor: pointer; white-space: nowrap; transition: all 0.15s;
    }
    .filter-pill:hover { background: #e2e8f0; color: var(--text); }
    .filter-pill.active { background: var(--primary); color: #fff; border-color: var(--primary); }

    .item-list { flex: 1; overflow-y: auto; list-style: none; }
    
    .item-card {
      padding: 10px 14px; border-bottom: 1px solid var(--border); cursor: pointer;
      display: flex; gap: 10px; align-items: center; transition: all 0.15s ease;
      position: relative;
    }
    .item-card:hover { background: #f0f7ff; }
    .item-card.active { background: #e3f2fd; border-left: 4px solid var(--accent); }
    .item-card.has-warning { border-left: 4px solid var(--danger); background: #fffafa; }
    .item-card.has-warning.active { border-left: 4px solid var(--danger); background: #fee2e2; }

    .item-card-thumb {
      width: 48px; height: 48px; border-radius: 6px; object-fit: cover;
      background: #e2e8f0; flex-shrink: 0; display: flex; align-items: center; justify-content: center;
      font-size: 18px; color: var(--text-muted); border: 1px solid var(--border);
    }
    .item-card-info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
    .item-card-title {
      font-size: 12px; font-weight: 600; white-space: nowrap; overflow: hidden;
      text-overflow: ellipsis; color: var(--text);
    }
    .item-card-meta { font-size: 11px; color: var(--text-muted); display: flex; justify-content: space-between; align-items: center; }
    .item-card-price { font-weight: 700; color: var(--primary); }
    .item-card-price.zero-data { color: var(--danger); font-weight: 800; }
    
    .badge { display: inline-block; padding: 2px 7px; border-radius: 10px; font-size: 10px; font-weight: 700; text-transform: uppercase; }
    .badge-freigegeben { background: #d4edda; color: #155724; }
    .badge-entwurf { background: #fff3cd; color: #856404; }
    .badge-zurückgehalten { background: #e2e8f0; color: #475569; }
    .badge-veröffentlicht { background: #cce5ff; color: #004085; }
    .badge-danger { background: var(--danger-light); color: var(--danger); border: 1px solid rgba(220,53,69,0.3); }

    /* Content Area */
    .content-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
    .toolbar { padding: 10px 24px; background: var(--card); border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
    
    .btn { padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; border: none; transition: background 0.15s; display: inline-flex; align-items: center; gap: 6px; }
    .btn-primary { background: var(--primary); color: #fff; }
    .btn-primary:hover { background: var(--primary-hover); }
    .btn-success { background: var(--success); color: #fff; }
    .btn-success:hover { background: #218838; }
    .btn-outline { background: transparent; border: 1px solid var(--border); color: var(--text); }
    .btn-outline:hover { background: #edf2f7; }

    /* Studio Split Workspace */
    .workspace { flex: 1; display: flex; overflow: hidden; padding: 16px 20px; gap: 18px; }
    .panel { flex: 1.1; background: var(--card); border: 1px solid var(--border); border-radius: 8px; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
    .panel-right { flex: 0.9; }
    .panel-header { padding: 10px 16px; font-size: 13px; font-weight: bold; background: #f8fafc; border-bottom: 1px solid var(--border); color: var(--primary); display: flex; justify-content: space-between; align-items: center; }
    .panel-body { flex: 1; overflow-y: auto; padding: 16px; }

    /* Left Pane Components: AI Valuation Card & Editable Forms */
    .valuation-box {
      background: #eef6fc; border-left: 4px solid var(--accent); padding: 14px 16px; border-radius: 6px; margin-bottom: 16px;
    }
    .valuation-box.zero-data-alert {
      background: #fdf2f2; border-left: 4px solid var(--danger); border: 1px solid #fca5a5;
    }
    .valuation-header { display: flex; justify-content: space-between; align-items: center; }
    .valuation-label { font-size: 11px; font-weight: 800; color: var(--accent); text-transform: uppercase; letter-spacing: 0.5px; }
    .valuation-box.zero-data-alert .valuation-label { color: var(--danger); }
    
    .valuation-price-hero { font-size: 26px; font-weight: 800; color: var(--primary); margin: 4px 0; }
    .valuation-box.zero-data-alert .valuation-price-hero { color: var(--danger); }

    .zero-data-banner {
      background: var(--danger); color: #fff; font-size: 11px; font-weight: 700;
      padding: 4px 8px; border-radius: 4px; margin-top: 6px; display: flex; align-items: center; gap: 6px;
    }
    .valuation-stats { font-size: 12px; color: var(--text-muted); margin-top: 6px; }

    .field-group { margin-bottom: 12px; }
    .field-label { font-size: 11px; font-weight: 700; color: var(--text-muted); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
    .field-input, .field-textarea, .field-select {
      width: 100%; padding: 7px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; color: var(--text); background: #fff;
    }
    .field-textarea { min-height: 80px; resize: vertical; line-height: 1.45; }
    
    .field-input:focus, .field-textarea:focus, .field-select:focus {
      outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(46,117,182,0.15);
    }
    
    .field-input.input-warning {
      border-color: var(--danger) !important;
      box-shadow: 0 0 0 3px rgba(220,53,69,0.15) !important;
      background: #fffafa;
    }

    .form-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .form-grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }

    /* Title Char Count Warning */
    .title-row-info { display: flex; justify-content: space-between; align-items: center; margin-top: 3px; font-size: 11px; }
    .char-counter { color: var(--text-muted); font-weight: 600; }
    .char-counter.warning { color: var(--danger); font-weight: 800; }
    .title-warning-msg { color: var(--danger); font-weight: 700; display: none; }

    /* Right Pane: Gallery & Video Tabs */
    .media-subtabs { display: flex; gap: 6px; background: #e2e8f0; padding: 3px; border-radius: 6px; }
    .media-subtab-btn {
      padding: 4px 12px; border-radius: 4px; font-size: 11px; font-weight: 700; border: none;
      background: transparent; color: var(--text-muted); cursor: pointer; transition: all 0.2s;
    }
    .media-subtab-btn.active { background: #fff; color: var(--primary); box-shadow: 0 1px 3px rgba(0,0,0,0.1); }

    .gallery-view, .video-view { display: none; flex-direction: column; height: 100%; }
    .gallery-view.active, .video-view.active { display: flex; }

    .main-image-wrap {
      flex: 1; background: #0f172a; border-radius: 6px; display: flex; align-items: center;
      justify-content: center; margin-bottom: 10px; overflow: hidden; min-height: 280px; position: relative;
    }
    .main-image { max-width: 100%; max-height: 100%; object-fit: contain; }

    .thumbnail-row {
      display: flex; gap: 8px; overflow-x: auto; padding: 4px 2px; scrollbar-width: thin;
    }
    .thumbnail {
      width: 64px; height: 64px; border-radius: 4px; object-fit: cover; cursor: pointer;
      border: 2px solid transparent; flex-shrink: 0; background: #e2e8f0; transition: border-color 0.15s;
    }
    .thumbnail:hover { border-color: #93c5fd; }
    .thumbnail.active { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(46,117,182,0.3); }

    .video-container {
      flex: 1; background: #0f172a; border-radius: 6px; display: flex; flex-direction: column;
      align-items: center; justify-content: center; overflow: hidden; min-height: 280px; padding: 10px;
    }
    .video-player { width: 100%; height: 100%; max-height: 440px; border-radius: 4px; background: #000; outline: none; }
    .video-empty-state { color: #94a3b8; font-size: 13px; text-align: center; }

    /* Bottom Action Bar */
    .edit-section {
      background: #fafbfc; border-top: 1px solid var(--border); padding: 12px 24px;
      display: grid; grid-template-columns: 1.2fr 1fr 1fr 1.2fr auto; gap: 12px; align-items: end;
    }
    .edit-group { display: flex; flex-direction: column; gap: 3px; }
    .edit-label { font-size: 11px; font-weight: bold; color: var(--text-muted); text-transform: uppercase; }

    #toast {
      position: fixed; bottom: 20px; right: 20px; padding: 12px 20px; border-radius: 6px;
      background: #1e293b; color: #fff; font-size: 13px; display: none; z-index: 1000;
      box-shadow: 0 4px 12px rgba(0,0,0,0.2); border-left: 4px solid var(--accent);
    }
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
          
          <div class="dropzone" id="dropzone" onclick="openFilePicker(event)">
            <div class="dropzone-icon">📁</div>
            <div class="dropzone-text">Fotos & Videos hier hineinziehen</div>
            <div class="dropzone-hint">oder Buttons unten nutzen (JPG, PNG, HEIC, WEBP, MP4, MOV, MKV etc.)</div>
            <div style="display: flex; gap: 10px; margin-top: 10px;" onclick="event.stopPropagation()">
              <button type="button" class="btn btn-primary" style="padding: 8px 16px; font-size: 13px;" onclick="openFilePicker(event)">📂 Dateien auswählen</button>
              <button type="button" class="btn btn-outline" style="padding: 8px 16px; font-size: 13px;" onclick="openFolderPicker(event)">📁 Ordner auswählen</button>
            </div>
          </div>
          <input type="file" id="file-input" multiple style="position: absolute; left: -9999px; opacity: 0; width: 1px; height: 1px;" onchange="handleFileSelect(event)">
          <input type="file" id="folder-input" webkitdirectory directory multiple style="position: absolute; left: -9999px; opacity: 0; width: 1px; height: 1px;" onchange="handleFileSelect(event)">
        </div>

        <!-- Staged Files Grid/List -->
        <div class="card" style="flex: 1;">
          <div class="card-title">
            <span>📋 Bereitgestellte Rohdateien (<span id="staged-list-count">0</span>)</span>
            <button class="btn btn-outline" style="padding: 4px 10px; font-size: 11px;" onclick="loadStagedMedia()">🔄 Aktualisieren</button>
          </div>
          <ul class="staged-list" id="staged-files-ul">
            <li style="padding: 20px; text-align: center; color: var(--text-muted); font-size: 13px;">Keine ungesichteten Rohdateien in input/raw/ vorhanden.</li>
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
      
      <!-- Left Sidebar -->
      <div class="sidebar">
        <div class="sidebar-header">
          <div class="sidebar-search-box">
            <span class="sidebar-search-icon">🔍</span>
            <input type="text" id="sidebar-search-input" class="sidebar-search-input" placeholder="Suchen nach Titel, ID, Marke..." oninput="applySidebarFilters()">
          </div>
          <div class="filter-pills">
            <button class="filter-pill active" id="pill-all" onclick="setFilterStatus('all')">Alle (<span id="count-all">0</span>)</button>
            <button class="filter-pill" id="pill-draft" onclick="setFilterStatus('draft')">Entwürfe (<span id="count-draft">0</span>)</button>
            <button class="filter-pill" id="pill-approved" onclick="setFilterStatus('approved')">Freigegeben (<span id="count-approved">0</span>)</button>
            <button class="filter-pill" id="pill-held" onclick="setFilterStatus('held')">Zurückgehalten (<span id="count-held">0</span>)</button>
          </div>
        </div>
        <ul class="item-list" id="items-ul"></ul>
      </div>

      <!-- Main Workspace -->
      <div class="content-area">
        <div class="toolbar">
          <div>
            <span style="font-weight: 700; font-size: 15px; color: var(--primary);" id="selected-item-title">Kein Artikel ausgewählt</span>
          </div>
          <div style="display: flex; gap: 10px;">
            <button class="btn btn-outline" onclick="loadItems()">🔄 Neu laden</button>
            <button class="btn btn-primary" onclick="exportEbayCsv()">📦 eBay CSV erstellen</button>
            <button class="btn btn-success" onclick="saveCurrentItem(true)">💾 Speichern & Nächster ➔</button>
          </div>
        </div>

        <div class="workspace">
          
          <!-- Left Panel: Metadata & Valuation Editor -->
          <div class="panel">
            <div class="panel-header">
              <span>📊 Recherche & Bewertungsstudio</span>
              <span id="item-id-badge" class="badge badge-entwurf">ID: -</span>
            </div>
            <div class="panel-body" id="details-body">
              
              <!-- Valuation Hero Card -->
              <div class="valuation-box" id="valuation-box">
                <div class="valuation-header">
                  <span class="valuation-label" id="valuation-badge-text">EMPFOHLENE RETRO-BEWERTUNG (KI)</span>
                </div>
                <div class="valuation-price-hero" id="valuation-price-display">0,00 €</div>
                <div id="valuation-zero-data-banner" class="zero-data-banner" style="display: none;">
                  ⚠️ ZERO-DATA: Keine Marktdaten ermittelt (0,00 €) - Bitte Preis manuell festlegen!
                </div>
                <div class="valuation-stats" id="valuation-stats-display">
                  Spanne: 0,00 € - 0,00 € | Web-Median: 0,00 € (0 Quellen)
                </div>
              </div>

              <!-- Editable Form Fields -->
              <div class="field-group">
                <div class="field-label">eBay Titel (Maximal 80 Zeichen)</div>
                <input type="text" id="input-title" class="field-input" oninput="handleTitleChange()">
                <div class="title-row-info">
                  <span class="title-warning-msg" id="title-warning-msg">⚠️ Titel überschreitet 80 Zeichen für eBay!</span>
                  <span class="char-counter" id="char-counter">0 / 80 Zeichen</span>
                </div>
              </div>

              <div class="field-group">
                <div class="field-label">Produktbeschreibung</div>
                <textarea id="input-description" class="field-textarea"></textarea>
              </div>

              <div class="form-grid-2">
                <div class="field-group">
                  <div class="field-label">Hersteller / Marke</div>
                  <input type="text" id="input-manufacturer" class="field-input">
                </div>
                <div class="field-group">
                  <div class="field-label">Modell / Epoche / Jahr</div>
                  <input type="text" id="input-epoch" class="field-input">
                </div>
              </div>

              <div class="form-grid-2">
                <div class="field-group">
                  <div class="field-label">Material</div>
                  <input type="text" id="input-material" class="field-input">
                </div>
                <div class="field-group">
                  <div class="field-label">Farbe</div>
                  <input type="text" id="input-color" class="field-input">
                </div>
              </div>

              <div class="form-grid-3">
                <div class="field-group">
                  <div class="field-label">Länge (cm)</div>
                  <input type="text" id="input-length" class="field-input">
                </div>
                <div class="field-group">
                  <div class="field-label">Breite (cm)</div>
                  <input type="text" id="input-width" class="field-input">
                </div>
                <div class="field-group">
                  <div class="field-label">Höhe (cm)</div>
                  <input type="text" id="input-height" class="field-input">
                </div>
              </div>

              <div class="form-grid-2">
                <div class="field-group">
                  <div class="field-label">Gewicht (kg)</div>
                  <input type="text" id="input-weight" class="field-input">
                </div>
                <div class="field-group">
                  <div class="field-label">Logistik-Kategorie</div>
                  <select id="input-logistics" class="field-select">
                    <option value="Paket">Paket (Standard)</option>
                    <option value="Sperrgut">Sperrgut</option>
                    <option value="Spedition">Spedition / Palette</option>
                    <option value="Selbstabholung">Nur Selbstabholung</option>
                  </select>
                </div>
              </div>

              <div class="form-grid-2">
                <div class="field-group">
                  <div class="field-label">Zustand</div>
                  <input type="text" id="input-condition" class="field-input">
                </div>
                <div class="field-group">
                  <div class="field-label">Mängel & Schäden</div>
                  <input type="text" id="input-defects" class="field-input">
                </div>
              </div>

              <div class="field-group">
                <div class="field-label">Fehlende Teile</div>
                <input type="text" id="input-missing-parts" class="field-input">
              </div>

              <div class="field-group">
                <div class="field-label">Preisfindungs-Begründung</div>
                <div id="valuation-rationale" class="field-textarea" style="background: #f8fafc; font-size: 12px; color: var(--text-muted); border: 1px dashed var(--border); overflow-y: auto;">-</div>
              </div>

            </div>
          </div>

          <!-- Right Panel: High-Res Photo Gallery & Video Player -->
          <div class="panel panel-right">
            <div class="panel-header">
              <div class="media-subtabs">
                <button class="media-subtab-btn active" id="subtab-photos" onclick="switchMediaTab('photos')">
                  📷 Fotos (<span id="photo-count">0</span>)
                </button>
                <button class="media-subtab-btn" id="subtab-videos" onclick="switchMediaTab('videos')">
                  🎥 Video (<span id="video-count">0</span>)
                </button>
              </div>
              <span style="font-size: 11px; color: var(--text-muted);" id="media-zoom-hint">Originalaufnahmen</span>
            </div>

            <div class="panel-body" style="padding: 12px;">
              <!-- Photo Gallery Subtab -->
              <div class="gallery-view active" id="media-gallery-view">
                <div class="main-image-wrap">
                  <img id="main-photo" class="main-image" src="" alt="Kein Bild vorhanden">
                </div>
                <div class="thumbnail-row" id="thumbnail-row"></div>
              </div>

              <!-- Video Player Subtab -->
              <div class="video-view" id="media-video-view">
                <div class="video-container">
                  <video id="main-video-player" class="video-player" controls preload="metadata" style="display: none;"></video>
                  <div id="video-empty-state" class="video-empty-state">
                    🎥 Kein Video für diesen Artikel vorhanden.
                  </div>
                </div>
              </div>
            </div>
          </div>

        </div>

        <!-- Bottom: Edit Bar -->
        <div class="edit-section" id="edit-bar">
          <div class="edit-group">
            <label class="edit-label">Verkaufspreis (€)</label>
            <input type="number" step="0.50" id="input-price" class="field-input" style="font-weight: 700; font-size: 14px;" oninput="handlePriceChange()">
          </div>

          <div class="edit-group">
            <label class="edit-label">Plattform</label>
            <select id="input-platform" class="field-select">
              <option value="eBay">eBay</option>
              <option value="Etsy">Etsy</option>
              <option value="Kleinanzeigen">Kleinanzeigen</option>
              <option value="Shop">Eigenes Webshop</option>
            </select>
          </div>

          <div class="edit-group">
            <label class="edit-label">Format</label>
            <select id="input-format" class="field-select">
              <option value="FixedPrice">Sofort-Kaufen (Festpreis)</option>
              <option value="Auction">Auktion (7 Tage)</option>
            </select>
          </div>

          <div class="edit-group">
            <label class="edit-label">Freigabe-Status</label>
            <select id="input-status" class="field-select">
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
    let filteredIndices = [];
    let selectedIndex = 0;
    let pollInterval = null;
    let currentFilterStatus = "all";

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

    // --- Subtab Navigation in Right Media Panel ---
    function switchMediaTab(tab) {
      const btnPhotos = document.getElementById("subtab-photos");
      const btnVideos = document.getElementById("subtab-videos");
      const viewGallery = document.getElementById("media-gallery-view");
      const viewVideo = document.getElementById("media-video-view");

      if (tab === "photos") {
        btnPhotos.classList.add("active");
        btnVideos.classList.remove("active");
        viewGallery.classList.add("active");
        viewVideo.classList.remove("active");
        const vid = document.getElementById("main-video-player");
        if (vid) vid.pause();
      } else {
        btnVideos.classList.add("active");
        btnPhotos.classList.remove("active");
        viewVideo.classList.add("active");
        viewGallery.classList.remove("active");
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

    function openFilePicker(event) {
      if (event) { event.preventDefault(); event.stopPropagation(); }
      const input = document.getElementById("file-input");
      if (input) input.click();
    }

    function openFolderPicker(event) {
      if (event) { event.preventDefault(); event.stopPropagation(); }
      const input = document.getElementById("folder-input");
      if (input) input.click();
    }

    function handleFileSelect(event) {
      const files = event.target.files;
      if (files && files.length > 0) {
        uploadFiles(files);
      }
      event.target.value = "";
    }

    async function uploadFiles(files) {
      if (!files || files.length === 0) return;
      const dz = document.getElementById("dropzone");
      if (dz) dz.style.opacity = "0.6";

      showToast(`Lade ${files.length} Datei(en) hoch...`);
      const formData = new FormData();
      let validCount = 0;
      for (let i = 0; i < files.length; i++) {
        if (files[i].name) {
          formData.append("files", files[i], files[i].name);
          validCount++;
        }
      }

      if (validCount === 0) {
        showToast("⚠️ Keine gültigen Dateien zum Hochladen gefunden.");
        if (dz) dz.style.opacity = "1.0";
        return;
      }

      try {
        const res = await fetch("/api/upload", {
          method: "POST",
          body: formData
        });
        
        if (!res.ok) {
          const errText = await res.text();
          throw new Error(`HTTP ${res.status}: ${errText}`);
        }

        const data = await res.json();
        if (data.success) {
          showToast(`✅ ${data.count} Datei(en) erfolgreich in input/raw/ gespeichert!`);
          await loadStagedMedia();
        } else {
          showToast("❌ Upload-Fehler: " + (data.error || "Unbekannt"));
          alert("Fehler beim Upload: " + (data.error || "Unbekannt"));
        }
      } catch (err) {
        showToast("❌ Upload fehlgeschlagen: " + err.message);
        alert("Upload fehlgeschlagen: " + err.message);
      } finally {
        if (dz) dz.style.opacity = "1.0";
        const fi = document.getElementById("file-input");
        if (fi) fi.value = "";
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
          terminal.innerText = data.logs.join("\n");
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

    // --- Tab 2: Review Hub Logic & Guardrails ---
    async function loadItems() {
      showToast("Lade Artikeldaten...");
      try {
        const res = await fetch("/api/items");
        const data = await res.json();
        currentItems = data.items || [];
        document.getElementById("status-info").innerText = `Datei: ${data.file_name || 'N/A'} (${currentItems.length} Artikel)`;
        document.getElementById("badge-items-count").innerText = currentItems.length;

        applySidebarFilters();
        if (filteredIndices.length > 0) {
          selectItem(filteredIndices[0]);
        }
      } catch (err) {
        showToast("Fehler beim Laden: " + err.message);
      }
    }

    function setFilterStatus(status) {
      currentFilterStatus = status;
      document.querySelectorAll(".filter-pill").forEach(p => p.classList.remove("active"));
      const targetPill = document.getElementById(`pill-${status}`);
      if (targetPill) targetPill.classList.add("active");
      applySidebarFilters();
    }

    function applySidebarFilters() {
      const query = (document.getElementById("sidebar-search-input").value || "").toLowerCase().trim();
      
      let allCount = currentItems.length;
      let draftCount = 0;
      let approvedCount = 0;
      let heldCount = 0;

      currentItems.forEach(it => {
        const st = (it.Status || "Entwurf").toLowerCase();
        if (st.includes("freigeb")) approvedCount++;
        else if (st.includes("zurück") || st.includes("halt")) heldCount++;
        else draftCount++;
      });

      document.getElementById("count-all").innerText = allCount;
      document.getElementById("count-draft").innerText = draftCount;
      document.getElementById("count-approved").innerText = approvedCount;
      document.getElementById("count-held").innerText = heldCount;

      filteredIndices = [];
      currentItems.forEach((it, idx) => {
        const status = (it.Status || "Entwurf").toLowerCase();
        
        let matchFilter = true;
        if (currentFilterStatus === "draft" && !status.includes("entwurf")) matchFilter = false;
        if (currentFilterStatus === "approved" && !status.includes("freigeb")) matchFilter = false;
        if (currentFilterStatus === "held" && (!status.includes("zurück") && !status.includes("halt"))) matchFilter = false;

        if (!matchFilter) return;

        if (query) {
          const searchable = [
            it.id,
            it.titel,
            it.Produkt_Titel,
            it.hersteller_oder_marke,
            it.modell_oder_epoche,
            it.material,
            it.produktbeschreibung
          ].map(x => String(x || "").toLowerCase()).join(" ");
          
          if (!searchable.includes(query)) return;
        }

        filteredIndices.push(idx);
      });

      renderSidebar();
    }

    function renderSidebar() {
      const ul = document.getElementById("items-ul");
      ul.innerHTML = "";

      if (filteredIndices.length === 0) {
        ul.innerHTML = `<li style="padding: 24px 16px; text-align: center; color: var(--text-muted); font-size: 12px;">Keine passenden Artikel gefunden.</li>`;
        return;
      }

      filteredIndices.forEach(idx => {
        const it = currentItems[idx];
        const li = document.createElement("li");
        
        const price = parseFloat(it.ErzielterPreis || it.Empfohlener_Retail_Preis_EUR || it.Preis_EUR || 0);
        const title = it.titel || it.Produkt_Titel || `Artikel ${it.id || idx+1}`;
        const isZeroData = (price <= 0);
        const isTitleOverflow = (title.length > 80);
        const hasWarning = isZeroData || isTitleOverflow;

        li.className = `item-card ${idx === selectedIndex ? 'active' : ''} ${hasWarning ? 'has-warning' : ''}`;
        li.onclick = () => selectItem(idx);

        const status = (it.Status || "Entwurf").toLowerCase();
        let badgeClass = "badge-entwurf";
        if (status.includes("freigeb")) badgeClass = "badge-freigegeben";
        else if (status.includes("veröff")) badgeClass = "badge-veröffentlicht";
        else if (status.includes("zurück") || status.includes("halt")) badgeClass = "badge-zurückgehalten";

        let warningBadges = "";
        if (isZeroData) {
          warningBadges += `<span class="badge badge-danger">⚠️ 0,00 €</span> `;
        }
        if (isTitleOverflow) {
          warningBadges += `<span class="badge badge-danger">⚠️ >80 Zchn</span>`;
        }

        const thumbHtml = it.thumbnail_url
          ? `<img class="item-card-thumb" src="${it.thumbnail_url}" alt="" onerror="this.outerHTML='<div class=\\'item-card-thumb\\'>📦</div>'">`
          : `<div class="item-card-thumb">📦</div>`;

        li.innerHTML = `
          ${thumbHtml}
          <div class="item-card-info">
            <div class="item-card-title" title="${title}">${title}</div>
            <div class="item-card-meta">
              <span class="item-card-price ${isZeroData ? 'zero-data' : ''}">ID: ${it.id || 'N/A'} | € ${price.toFixed(2)}</span>
              <span class="badge ${badgeClass}">${it.Status || 'Entwurf'}</span>
            </div>
            ${warningBadges ? `<div style="margin-top: 2px;">${warningBadges}</div>` : ''}
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

      const price = parseFloat(it.ErzielterPreis || it.Empfohlener_Retail_Preis_EUR || it.Preis_EUR || 0);
      const isZeroData = (price <= 0);

      document.getElementById("selected-item-title").innerText = it.titel || it.Produkt_Titel || "Artikel " + it.id;
      document.getElementById("item-id-badge").innerText = "ID: " + (it.id || "N/A");

      // AI Valuation Card
      const valBox = document.getElementById("valuation-box");
      const valPriceDisplay = document.getElementById("valuation-price-display");
      const valZeroBanner = document.getElementById("valuation-zero-data-banner");
      const valStats = document.getElementById("valuation-stats-display");
      const valBadge = document.getElementById("valuation-badge-text");

      valPriceDisplay.innerText = `${price.toFixed(2)} €`;
      valStats.innerText = `Spanne: ${(it.Preisspanne_Min_EUR || 0).toFixed(2)} € - ${(it.Preisspanne_Max_EUR || 0).toFixed(2)} € | Web-Median: ${(it.Median_Web_Preis_EUR || 0).toFixed(2)} € (${it.Anzahl_gefundene_Webpreise || 0} Quellen)`;
      document.getElementById("valuation-rationale").innerText = it.Begruendung_Preisfindung || "Keine Begründung angegeben.";

      if (isZeroData) {
        valBox.className = "valuation-box zero-data-alert";
        valZeroBanner.style.display = "flex";
        valBadge.innerText = "⚠️ ACHTUNG: ZERO-DATA / MANUELLE BEWERTUNG ERFORDERLICH";
      } else {
        valBox.className = "valuation-box";
        valZeroBanner.style.display = "none";
        valBadge.innerText = "EMPFOHLENE RETRO-BEWERTUNG (KI)";
      }

      // Populate Editable Form Fields
      document.getElementById("input-title").value = it.titel || it.Produkt_Titel || "";
      document.getElementById("input-description").value = it.produktbeschreibung || "";
      document.getElementById("input-manufacturer").value = it.hersteller_oder_marke || "";
      document.getElementById("input-epoch").value = it.modell_oder_epoche || it.geschaetztes_jahr_oder_epoche || "";
      document.getElementById("input-material").value = it.material || "";
      document.getElementById("input-color").value = it.farbe || "";
      document.getElementById("input-length").value = it.laenge_cm || "";
      document.getElementById("input-width").value = it.breite_cm || "";
      document.getElementById("input-height").value = it.hoehe_cm || "";
      document.getElementById("input-weight").value = it.gewicht_kg || "";
      document.getElementById("input-logistics").value = it.logistik_kategorie || "Paket";
      document.getElementById("input-condition").value = it.zustand || "Gebraucht";
      document.getElementById("input-defects").value = it.maengel || "";
      document.getElementById("input-missing-parts").value = it.fehlende_teile || "";

      // Bottom Bar
      document.getElementById("input-price").value = price;
      document.getElementById("input-platform").value = it.VerkaufsOrt || "eBay";
      document.getElementById("input-format").value = it.AngebotsFormat || "FixedPrice";
      document.getElementById("input-status").value = it.Status || "Freigegeben";

      handleTitleChange();
      handlePriceChange();

      loadMediaForSelected(it);
    }

    function handleTitleChange() {
      const title = document.getElementById("input-title").value || "";
      const countEl = document.getElementById("char-counter");
      const warnMsg = document.getElementById("title-warning-msg");
      const inputEl = document.getElementById("input-title");

      countEl.innerText = `${title.length} / 80 Zeichen`;
      if (title.length > 80) {
        countEl.className = "char-counter warning";
        inputEl.classList.add("input-warning");
        warnMsg.style.display = "inline";
      } else {
        countEl.className = "char-counter";
        inputEl.classList.remove("input-warning");
        warnMsg.style.display = "none";
      }
    }

    function handlePriceChange() {
      const price = parseFloat(document.getElementById("input-price").value) || 0;
      const priceInput = document.getElementById("input-price");
      if (price <= 0) {
        priceInput.classList.add("input-warning");
      } else {
        priceInput.classList.remove("input-warning");
      }
    }

    async function loadMediaForSelected(item) {
      const thumbRow = document.getElementById("thumbnail-row");
      const mainImg = document.getElementById("main-photo");
      const vidPlayer = document.getElementById("main-video-player");
      const vidEmpty = document.getElementById("video-empty-state");

      thumbRow.innerHTML = "";
      document.getElementById("photo-count").innerText = "0";
      document.getElementById("video-count").innerText = "0";

      // 1. Load Images
      try {
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
      } catch (err) {
        console.error("Fehler beim Laden der Bilder:", err);
      }

      // 2. Load Videos
      try {
        const resVid = await fetch(`/api/videos_for_item?id=${encodeURIComponent(item.id || '')}&name=${encodeURIComponent(item.ordner_name || item.titel || '')}`);
        const vidData = await resVid.json();
        const videos = vidData.videos || [];

        document.getElementById("video-count").innerText = videos.length;
        if (videos.length > 0) {
          vidPlayer.src = videos[0].url;
          vidPlayer.style.display = "block";
          vidEmpty.style.display = "none";
        } else {
          vidPlayer.pause();
          vidPlayer.src = "";
          vidPlayer.style.display = "none";
          vidEmpty.style.display = "block";
        }
      } catch (err) {
        console.error("Fehler beim Laden der Videos:", err);
      }
    }

    async function saveCurrentItem(autoAdvance = false) {
      const it = currentItems[selectedIndex];
      if (!it) return;

      const payload = {
        id: it.id,
        titel: document.getElementById("input-title").value,
        produktbeschreibung: document.getElementById("input-description").value,
        hersteller_oder_marke: document.getElementById("input-manufacturer").value,
        modell_oder_epoche: document.getElementById("input-epoch").value,
        material: document.getElementById("input-material").value,
        farbe: document.getElementById("input-color").value,
        laenge_cm: document.getElementById("input-length").value,
        breite_cm: document.getElementById("input-width").value,
        hoehe_cm: document.getElementById("input-height").value,
        gewicht_kg: document.getElementById("input-weight").value,
        logistik_kategorie: document.getElementById("input-logistics").value,
        zustand: document.getElementById("input-condition").value,
        maengel: document.getElementById("input-defects").value,
        fehlende_teile: document.getElementById("input-missing-parts").value,
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
          applySidebarFilters();
          
          if (autoAdvance) {
            const currentFilterPos = filteredIndices.indexOf(selectedIndex);
            if (currentFilterPos >= 0 && currentFilterPos < filteredIndices.length - 1) {
              selectItem(filteredIndices[currentFilterPos + 1]);
            }
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
          alert(`eBay CSV erfolgreich erstellt:\n\nDatei: ${data.csv}\nPayload: ${data.json}\n\nAnzahl Artikel: ${data.count}`);
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

        elif path == "/api/videos_for_item":
            item_id = query.get("id", [""])[0]
            item_name = query.get("name", [""])[0]
            videos = find_item_videos(item_id, item_name, self.config.base_dir)
            vid_list = [{"name": p.name, "url": f"/api/video?path={urllib.parse.quote(str(p))}"} for p in videos]
            self._set_headers("application/json; charset=utf-8")
            self.wfile.write(json.dumps({"videos": vid_list}).encode("utf-8"))

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
                        shutil.copyfileobj(f, self.wfile)
                    return
            self.send_error(404, "Bild nicht gefunden")

        elif path == "/api/video":
            vid_path_str = query.get("path", [""])[0]
            if vid_path_str:
                p = Path(vid_path_str).resolve()
                if p.exists() and p.is_file():
                    mime = "video/mp4"
                    if p.suffix.lower() == ".mov": mime = "video/quicktime"
                    elif p.suffix.lower() == ".webm": mime = "video/webm"
                    elif p.suffix.lower() == ".mkv": mime = "video/x-matroska"
                    elif p.suffix.lower() == ".avi": mime = "video/x-msvideo"
                    
                    file_size = p.stat().st_size
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Length", str(file_size))
                    self.end_headers()
                    with open(p, "rb") as f:
                        shutil.copyfileobj(f, self.wfile)
                    return
            self.send_error(404, "Video nicht gefunden")

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
        try:
            raw_dir = self.config.pipeline.raw_dir
            raw_dir.mkdir(parents=True, exist_ok=True)

            files = parse_multipart_form_data(body, content_type)
            saved_files = []

            if files:
                for fname, data in files:
                    clean_name = re.split(r'[\\/]', fname)[-1].strip()
                    if clean_name:
                        dest = raw_dir / clean_name
                        with open(dest, "wb") as f:
                            f.write(data)
                        saved_files.append(clean_name)
            elif body:
                # Fallback direkte Dateibereitstellung
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                fname = query.get("filename", ["uploaded_file.jpg"])[0]
                clean_name = re.split(r'[\\/]', fname)[-1].strip()
                if clean_name:
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
        except Exception as e:
            logger.error(f"Fehler bei _handle_upload: {e}", exc_info=True)
            self._set_headers("application/json; charset=utf-8", 500)
            self.wfile.write(json.dumps({
                "success": False,
                "error": str(e)
            }).encode("utf-8"))

    def _handle_get_items(self):
        target_file = self.__class__.current_file_path or find_latest_execution_file(self.config.pipeline.output_dir)
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
                    if "id" in clean_r and clean_r["id"] != "":
                        clean_r["id"] = str(clean_r["id"])
                    
                    # Thumbnail ermitteln
                    item_id = str(clean_r.get("id", "")).strip()
                    item_name = str(clean_r.get("ordner_name", "") or clean_r.get("titel", "")).strip()
                    images = find_item_images(item_id, item_name, self.config.base_dir)
                    if images:
                        clean_r["thumbnail_url"] = f"/api/image?path={urllib.parse.quote(str(images[0]))}"
                    else:
                        clean_r["thumbnail_url"] = ""

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
                    if k not in df.columns:
                        df[k] = None
                    df[k] = df[k].astype(object)
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
