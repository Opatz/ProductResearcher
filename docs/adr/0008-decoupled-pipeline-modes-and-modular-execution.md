# 0008 Decoupled Pipeline Execution Modes (Sort-Only vs. Research-Only vs. End-to-End)

## Status
Accepted

## Context
In early workflow iterations, raw media sorting and multimodal market valuation were tightly coupled into a single monolithic execution pass. However, real-world auction house and antique dealer operations require distinct operational stages:

1. **Staged Field Ingestion (Sort-Only)**: Field photographers or estate catalogers upload hundreds of high-resolution photos and video clips to `input/raw/`. Operators often want to sort, OCR-identify, and organize these media streams into clean `input/artikel/` folders and quarantine unassigned items *without* immediately triggering expensive multimodal LLM calls and live web scraping.
2. **Targeted Appraisal & Description (Research-Only)**: Once article folders are reviewed or manually curated in `input/artikel/`, operators want to execute the 3-stage valuation pipeline (audio transcription, Gemini Vision analysis, 10-portal parallel web research, Appraiser LLM synthesis, and master table export) without re-scanning or modifying the raw ingest directories.
3. **Automated Non-Technical Flow (End-to-End Pipeline)**: Operators processing single batches or automated studio sessions still require the seamless, 1-click end-to-end execution that automatically sorts incoming raw media and immediately runs AI research, description generation, and valuation in one uninterrupted sequence.

Without explicitly decoupled execution modes, operators are forced to re-run sorting unnecessarily, or cannot run AI analysis on manually prepared article folders without placing dummy files in the raw ingest folder.

## Decision
We establish three first-class, modular execution modes supported across the CLI, the Background Pipeline Runner, and the Web Studio UI:

### 1. The Three Canonical Execution Modes

| Modus | Name (Deutsch) | Scope & Verhalten | CLI Trigger | UI Studio Endpunkt & Aktion |
|---|---|---|---|---|
| **Mode 1: Sort-Only** | *Nur Sortierung* | Liest `input/raw/` & `input/processed/`, führt chronologische/numerische Sequenzierung durch, erkennt IDs via Vision OCR (`prompt_id.txt`), baut `input/artikel/Artikel_<ID>/` auf und isoliert Fehler nach `output/to_inspect/`. Stoppt danach ohne LLM-Recherche. | `python main.py --sort-only`<br>`python main.py --sort-raw` | `POST /api/pipeline/sort-only`<br>Button: *„📦 Nur Rohmedien sortieren“* |
| **Mode 2: Research-Only** | *Nur Recherche & Beschreibung* | Überspringt Rohdaten-Sortierung, liest direkt aus `input/artikel/` (oder `--batch-dir`), führt Transkription, visuelle Detailanalyse, 10-Site Webrecherche, Appraiser LLM Preissynthese und Master-Export (Excel/CSV/eBay) durch. | `python main.py --no-sort`<br>`python main.py --batch-dir <path>` | `POST /api/pipeline/research-only`<br>Button: *„🔍 Nur Recherche & Beschreibung starten“* |
| **Mode 3: End-to-End Pipeline** | *Komplette Pipeline* | Führt vollautomatisch **Mode 1** direkt gefolgt von **Mode 2** in einem ununterbrochenen Gesamtlauf aus. Bietet den vollständigen Studio-Komfort für End-to-End-Verarbeitungen. | `python main.py` (Standard) | `POST /api/pipeline/start`<br>Button: *„🚀 Komplette Pipeline ausführen“* |

### 2. UI Studio Integration (Tab 1: Vorbereiten & Starten)
Tab 1 des Human-in-the-Loop Review Hubs stellt alle drei Betriebsmodi über dedizierte, visuell unterscheidbare Steuerelemente bereit:
- **Button A (Sekundär / Indigo)**: *„📦 Nur Rohmedien sortieren“* – strukturiert neu hochgeladene Dateien vor, aktualisiert die Artikelanzahl im Dashboard und wechselt nicht in die teure KI-Phase.
- **Button B (Sekundär / Blau)**: *„🔍 Nur Recherche & Beschreibung starten“* – startet die KI-Bewertung für alle bereits in `input/artikel/` vorhandenen Artikelordner.
- **Button C (Primär / Grün & Prominent)**: *„🚀 Komplette Pipeline ausführen (Sortierung + Recherche + Beschreibung)“* – vollautomatisierter Gesamtlauf mit Live-Fortschrittsbalken und Log-Streaming.

### 3. PipelineRunner Threading & Status Management
Der thread-sichere `PipelineRunner` im UI-Server unterstützt getrennte Steuerungsroutinen:
- `start_sort_only(config: AppConfig)`: Führt `run_sorting_process()` aus, aktualisiert `created_folders` und schließt mit Status `COMPLETED` ab.
- `start_research_only(config: AppConfig, search_dir: Optional[Path])`: Führt `discover_item_tasks()` und den `VideoLLMPipeline`-Lauf für alle erfassten Artikel aus.
- `start_pipeline(config: AppConfig)`: Führt beide Schritte sequentiell nacheinander aus.

## Consequences
- **Positiv**:
  - Maximale Flexibilität: Große Fotobestände können vorab sortiert und geprüft werden, bevor Token-Kosten für die Webrecherche anfallen.
  - Fehlerbehebung: Manuell korrigierte oder nachbearbeitete Artikel in `input/artikel/` können isoliert analysiert werden, ohne den Ingest-Ordner zu manipulieren.
  - Nahtlose Benutzerfreundlichkeit: Benutzer, die den vollautomatischen 1-Klick-Ablauf bevorzugen, behalten die gewohnte Komplettausführung bei.
- **Negativ**:
  - Zusätzliche API-Endpunkte und Status-States im UI-Server.
