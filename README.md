## 📂 Eingabe-Struktur (Unterordner mit Video + Bildern)

Du kannst deine Artikel in [`input_videos/`](file:///c:/Users/MarioOpatz/OneDrive%20-%20Roboyo%20Global/Desktop/ML_Training/AsiaWorkflow/src/input_videos) wie folgt anlegen:

```
input_videos/
├── Artikel_1_Buddha/
│   ├── video.mp4            # Video (für Audio-Extraktion, 5s-Schnitt & Prompt 1)
│   ├── foto_vorne.jpg       # Fotos (werden automatisch an Prompt 2 übergeben)
│   ├── foto_stempel.jpg
│   └── foto_rueckseite.png
│
└── Artikel_2_Silberschalen/
    ├── video.mp4
    ├── foto_punze.jpg
    └── foto_muster.jpg
```

---

## 📌 Pipeline-Ablauf (9 Schritte)

1. **Audio-Extraktion**: Trennt die Audiospur aus dem Video (`.mp3`).
2. **Audio-Transkription**: Transkribiert das Audio wortgetreu mit Gemini (`gemini-3.7-flash` / `gemini-3.5-flash-lite`).
3. **Video-Schnitt (5s)**: Schneidet die ersten 5 Sekunden des Videos heraus.
4. **Visuelle ID-/Zahlenerkennung**: Gemini Vision analysiert das 5s-Intro und extrahiert eingeblendete IDs oder Nummern.
5. **Prompt 1 (Extraktion)**: Extrahiert alle relevanten Artikeldetails (Maße, Material, Zustand, Mängel) in ein strukturiertes JSON.
6. **Prompt 2 (Recherche & Bildabgleich)**: Erhält das JSON aus Schritt 1 **plus alle Bilder des Artikels**, führt Webrecherche & Zustandsanalyse durch und schätzt den Ist-Marktwert.
7. **Prompt 3 (Varianten & Szenarien)**: Erhält JSON 1 & 2 und generiert bis zu 5 realistische Szenarien zur Wertsteigerung.
8. **Prompt 4 (PreisSteigererBewerter)**: Berechnet die Arbitrage, den VER-Stundenlohn, die beste wirtschaftliche Maßnahme und die Excel-Zeile.
9. **Export**: Exportiert das Gesamtergebnis automatisch als **CSV** und als **Multi-Sheet Excel-Arbeitsmappe (`.xlsx`)** (inkl. Hauptempfehlung & Detailvergleich).

---

## 📂 Ordnerstruktur

```
src/
├── input/                   # 🎬 Artikel-Unterordner (Video + Bilder pro Artikel)
│   ├── Artikel_1/
│   │   ├── video.mp4
│   │   ├── foto_1.png
│   │   └── foto_2.png
│   └── Artikel_2/
│       └── ...
├── prompt_context/          # 📚 HIER Zusatzinformationen & Richtlinien ablegen
│   ├── global/              # Gilt für ALLE Prompts
│   ├── prompt_1_filter/     # Spezifisch für Schritt 1 (Extraktion)
│   ├── prompt_2_analysis/   # Spezifisch für Schritt 2 (Recherche & Zustand)
│   ├── prompt_3_varianten/  # Spezifisch für Schritt 3 (Szenarien)
│   └── prompt_4_bewertung/  # Spezifisch für Schritt 4 (PreisSteigerer / VER)
├── config/
│   ├── config.ini           # Google API Key, Modellname, Speicherpfade
│   └── settings.py          # Konfigurations-Loader
├── prompts/
│   ├── prompt_id.txt        # Prompt für die visuelle ID-Erkennung (5s-Intro)
│   ├── prompt_1_filter.txt  # Prompt 1: Extraktions-Modul (JSON)
│   ├── prompt_2_analysis.txt# Prompt 2: Recherche- & Bildabgleich (JSON)
│   ├── prompt_3_varianten.txt # Prompt 3: Varianten & Szenarien (JSON)
│   └── prompt_4_PreisSteigererBewerter.txt # Prompt 4: Arbitrage & VER-Bewertung
├── services/
│   ├── video_service.py     # Audio-Extraktion & 5s-Video-Schnitt (FFmpeg / MoviePy)
│   ├── gemini_service.py    # Gemini API Anbindung (Audio, Vision, Multimodal)
│   ├── prompt_manager.py    # Template- & Kontext-Assemblierungs-Manager
│   └── export_service.py    # CSV- und Multi-Sheet Excel-Generierung
├── pipeline/
│   ├── state.py             # Pydantic PipelineState Modell
│   └── orchestrator.py      # Haupt-Orchestrator mit Zwischenspeicherung
├── output/                  # Automatisches Verzeichnis für alle Ergebnisse & Zwischenstände
├── main.py                  # Einstiegspunkt (CLI & Batch-Verarbeitung)
└── requirements.txt         # Python-Abhängigkeiten
```

---

## ⚙️ Installation & Einrichtung

### 1. Abhängigkeiten installieren
```bash
pip install -r requirements.txt
```

### 2. Google API Key konfigurieren
Öffne `config/config.ini` und trage deinen Key ein:
```ini
[GOOGLE]
api_key = DEIN_GOOGLE_API_KEY_HIER
model_name = gemini-3.7-flash
```
*Alternativ kann auch eine Umgebungsvariable `GEMINI_API_KEY` gesetzt werden.*

---

## 🚀 Ausführung

### Einzelnes Video verarbeiten:
```bash
python main.py --video "pfad/zu/deinem_video.mp4"
```

### Mehrere Videos im Batch verarbeiten:
```bash
python main.py --batch-dir "pfad/zu/video_ordner"
```

### Testlauf / Mock-Modus (ohne API-Kosten):
```bash
python main.py --video "pfad/zu/deinem_video.mp4" --mock
```

---

## 📊 Ergebnisse & Zwischenspeicherung

Nach jedem Durchlauf werden die Ergebnisse im `output/`-Ordner gespeichert:
- `output/<Zeitstempel>_<Videoname>/`:
  - `02_transcription.txt` (Vollständiges Transkript)
  - `04_detected_id.json` (Erkannte ID/Zahl aus dem Intro)
  - `05_filter_result.json` (Gefilterte Kernaussagen)
  - `06_analysis_result.json` (Vertiefte LLM-Analyse)
  - `07_synthesis_result.json` (Konsolidierte Daten)
  - `result.csv` & `result.xlsx` (Exportierte Tabelle)
  - `pipeline_state.json` (Kompletter Laufstatus)
- `output/<Videoname>_result.csv` & `.xlsx` im Haupt-Outputverzeichnis.
# ProductResearcher
