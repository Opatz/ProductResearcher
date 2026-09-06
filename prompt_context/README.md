# Prompt Kontext & Zusatzinformationen

In diesem Verzeichnis kannst du beliebige Textdateien (`.txt`, `.md`, `.json`) ablegen, die als zusätzliches Wissen oder Richtlinien vor der Ausführung in die Prompts assembliert (zusammengeführt) werden.

## 📂 Struktur

```
prompt_context/
├── global/                     # Zusatzinfos, die in ALLEN Prompts eingefügt werden
├── prompt_1_filter/            # Spezifische Infos für Schritt 1 (z. B. Abkürzungen, Stempel-Listen)
├── prompt_2_analysis/          # Spezifische Infos für Schritt 2 (z. B. Recherche-Leitfäden, Echtheitsmerkmale)
├── prompt_3_varianten/         # Spezifische Infos für Schritt 3 (z. B. Standard-Aufbereitungsstufen)
└── prompt_4_bewertung/         # Spezifische Infos für Schritt 4 (z. B. Stundensätze, Schwellenwerte)
```

## ⚙️ Funktionsweise
* **Wenn ein Ordner leer ist:** Die Pipeline läuft ganz normal ohne Zusatztext weiter.
* **Wenn Dateien im Ordner liegen:** Alle Textdateien im Ordner werden automatisch eingelesen, sauber zusammengefügt und an der Stelle `{zusatz_kontext}` in den jeweiligen Prompt injiziert.
