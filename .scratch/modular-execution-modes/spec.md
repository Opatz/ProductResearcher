# Spec: Modulare Pipeline-Ausführungsmodi (Getrennte Sortierung vs. Recherche & Beschreibung vs. End-to-End)

## 1. Problemstellung & Motivation
In der bisherigen Betriebs- und UI-Praxis wurden Ingest-Sortierung und KI-Marktrecherche teils gebündelt ausgeführt. Im realen Auktions- und Antiquitäten-Alltag entstehen jedoch verschiedene Arbeitsmuster:
1. **Fotografen / Ingest-Phase:** Hunderte Fotos/Videos von mehreren Smartphones/Kameras werden in `input/raw/` abgelegt. Diese sollen vorab rein chronologisch sortiert, IDs via Vision-OCR erkannt und Artikel-Ordner in `input/artikel/` sowie Quarantäne-Fälle in `output/to_inspect/` angelegt werden, **ohne** sofort teure LLM-Recherche-Aufrufe zu starten.
2. **Kuratoren / Analyse-Phase:** Bereits vorbereitete, geprüfte oder manuell ergänzte Artikelordner in `input/artikel/` sollen analysiert, transkribiert, mit Webrecherche versehen und bewertet werden, **ohne** dass der Sortierer erneut über Rohordner laufen muss.
3. **Studio-Autopilot / 1-Klick-Workflow:** Für Standarddurchläufe soll weiterhin die Option bestehen, die **gesamte Pipeline** (Sortierung + Recherche + Beschreibung + Bewertung + Export) vollautomatisch in einem einzigen Schritt durchzuführen.

---

## 2. Architektonische Spezifikation der 3 Ausführungsmodi

### Modus 1: Sort-Only Execution (`Nur Sortierung`)
- **Ziel**: Vorverarbeitung und Strukturierung des Rohmedien-Streams.
- **Eingabe**: `input/raw/` und/oder `input/processed/` (oder `--source`).
- **Ablauf**:
  1. `MediaSorterService` liest alle Bild- und Videodateien ein.
  2. Deterministische chronologische/numerische Sortierung über `MediaSortKey`.
  3. Sequenzschnitt `[ID-Bild] -> [Detailbilder] -> [Objekt-Video]`.
  4. ID-Extraktion des ersten Bildes via Gemini Vision OCR (`prompts/prompt_id.txt`).
  5. Verschieben/Kopieren in `input/artikel/Artikel_<ID>/` (inkl. `sort_info.json`) bzw. Quarantäne nach `output/to_inspect/` (inkl. `inspection_reason.json`).
- **Ende**: Stoppt nach erfolgreicher Strukturierung. Keine Transkription, keine 10-Site Webrecherche, keine Appraiser-Synthese.
- **CLI**: `python main.py --sort-only` (oder `python main.py --sort-raw`)
- **UI API**: `POST /api/pipeline/sort-only`
- **UI Element**: Button *„📦 Nur Rohmedien sortieren“*

### Modus 2: Research-Only Execution (`Nur Recherche & Beschreibung`)
- **Ziel**: Multimodale Analyse, Webrecherche und Preissynthese für bereits vorhandene Artikelordner.
- **Eingabe**: Alle Unterordner in `input/artikel/` (oder `--batch-dir`, `--item <ID>`).
- **Ablauf**:
  1. `discover_item_tasks()` scannt `input/artikel/`.
  2. Für jeden Artikel:
     - Audio-Extraktion & Transkription via Gemini.
     - Multimodale visuelle Analyse (Phase 1).
     - Parallele Webrecherche auf bis zu 10 Vergleichsportalen (Phase 2).
     - Appraiser LLM Reconciliation & Preissynthese (Phase 3).
     - Einzel-Export & automatische Archivierung nach `input/completed/Artikel_<ID>/`.
  3. Konsolidierung der Master-Tabelle (`consolidated_execution_results.xlsx`) und eBay-Payloads.
- **Rohmedien**: Unberührt; keine Neusortierung von `input/raw/`.
- **CLI**: `python main.py --no-sort`
- **UI API**: `POST /api/pipeline/research-only`
- **UI Element**: Button *„🔍 Nur Recherche & Beschreibung starten“*

### Modus 3: End-to-End Pipeline Execution (`Komplette Pipeline`)
- **Ziel**: Vollautomatische Gesamtausführung in einem Schritt.
- **Ablauf**:
  1. Automatischer Start von **Modus 1** (Sortierung aller in `input/raw/` wartenden Medien).
  2. Unmittelbarer Übergang zu **Modus 2** für alle neu entstandenen sowie bereits bestehenden Artikel in `input/artikel/`.
  3. Konsolidierter Export & Bereitstellung der Ergebnisse im Review Hub.
- **CLI**: `python main.py` (Standardaufruf)
- **UI API**: `POST /api/pipeline/start`
- **UI Element**: Button *„🚀 Komplette Pipeline ausführen (Sortierung + Recherche + Beschreibung)“*

---

## 3. UI Studio Layout & Interaktion (Tab 1: Medien vorbereiten & Pipeline)

In Tab 1 (*„Medien hochladen / Vorbereiten“*) werden drei klar beschriftete, visuell hierarchische Aktions-Buttons bereitgestellt:

```
+-----------------------------------------------------------------------------------------------+
|  STUFE 1: VORBEREITUNG & AUSFÜHRUNG                                                           |
|                                                                                               |
|  [ 📤 Dateien hierher ziehen oder durchsuchen (Drag & Drop) ]                                 |
|                                                                                               |
|  Status: 24 Rohdateien in input/raw/  |  3 Artikelordner in input/artikel/ ready              |
|                                                                                               |
|  Aktionen:                                                                                    |
|  +------------------------------+  +--------------------------------+                         |
|  | 📦 Nur Rohmedien sortieren   |  | 🔍 Nur Recherche & Beschreibung|                         |
|  | (Erstellt Artikel-Ordner)    |  | (Analysiert Artikel-Ordner)    |                         |
|  +------------------------------+  +--------------------------------+                         |
|                                                                                               |
|  +-----------------------------------------------------------------------------------------+  |
|  | 🚀 Komplette Pipeline ausführen (Sortierung + Recherche + Beschreibung + Bewertung)      |  |
|  +-----------------------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------------------+
```

---

## 4. PipelineRunner Backend Schnittstelle

```python
class PipelineRunner:
    def start_sort_only(self, config: AppConfig) -> bool:
        """Startet ausschließlich die Sortierung von Rohmedien."""
        ...

    def start_research_only(self, config: AppConfig) -> bool:
        """Startet ausschließlich Recherche & Beschreibung für vorhandene Artikel-Ordner."""
        ...

    def start_pipeline(self, config: AppConfig) -> bool:
        """Startet die vollständige End-to-End Pipeline (Sortierung + Recherche)."""
        ...
```

---

## 5. Abgrenzung zu bestehenden ADRs & Spezifikationen
- Ergänzt und präzisiert **ADR-0001 (Sequence Parsing & Quarantine)** und **ADR-0007 (Studio Workflow)**.
- Dokumentiert in **ADR-0008 (Decoupled Pipeline Execution Modes)**.
- Begriffe verankert in **`CONTEXT.md`**.
