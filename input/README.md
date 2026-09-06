# 📂 Eingabeverzeichnis (`input/`)

Das Eingabeverzeichnis gliedert sich in zwei Bereiche:

```
input/
├── raw/                 # 📥 HIER Rohaufnahmen unsortiert nach Aufnahmezeit ablegen
└── artikel/             # 📁 Hier liegen die fertig sortierten Artikel (Artikel_1, Artikel_2...)
```

---

## ⚡ 1. Rohaufnahmen in `input/raw/` ablegen (Automatische Sortierung)

Lege deine aufgenommenen Bilder und Videos einfach unsortiert in `input/raw/`.

**Sequenz-Regel:**
1. Das **erste Bild** zeigt die Kennnummer / ID (Zettel, Schild oder Bildschirm).
2. Alle **darauffolgenden Bilder** zeigen Details/Zustand des Artikels.
3. Das **Video** schließt diesen Artikel ab.
4. Danach beginnt der nächste Artikel wieder mit einem ID-Foto.

**Beispiel in `input/raw/`:**
```
input/raw/
├── foto_01_id_1.jpg          <-- Erstes Bild: Zeigt ID / Zahl "1"
├── foto_02_vorne.jpg         <-- Gehört zu Artikel 1
├── foto_03_stempel.jpg       <-- Gehört zu Artikel 1
├── video_04_buddha.mp4       <-- Schließt Artikel 1 ab
├── foto_05_id_2.jpg          <-- Erstes Bild für Artikel 2: Zeigt ID / Zahl "2"
├── foto_06_muster.jpg        <-- Gehört zu Artikel 2
└── video_07_silberschale.mp4 <-- Schließt Artikel 2 ab
```

Wenn du `python main.py` ausführst, werden diese Dateien vollautomatisch:
- Nach Aufnahmezeitpunkt geordnet
- Das erste Bild per Gemini Vision analysiert und die ID extrahiert
- Automatisch in `input/artikel/Artikel_1/`, `input/artikel/Artikel_2/` etc. einsortiert und verarbeitet!

---

## 📁 2. Direkt sortierte Artikel in `input/artikel/`

Du kannst auch direkt eigene Artikel-Ordner in `input/artikel/` pflegen:
```
input/artikel/
├── Artikel_1/
│   ├── video.mp4
│   ├── foto_vorne.jpg
│   └── foto_stempel.jpg
└── Artikel_2/
    ├── video.mp4
    └── foto_muster.jpg
```
