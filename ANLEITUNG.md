# 📖 Schritt-für-Schritt Anleitung (Item Researcher)
> **Für Anwender & Nicht-Techniker** – Einfache Anleitung ohne Vorkenntnisse.

---

## 🎯 Überblick: Wie funktioniert das System?

Mit diesem System werden Antiquitäten und Sammlerobjekte automatisch durch Künstliche Intelligenz (Gemini) analysiert, recherchiert, mit einem Marktwert versehen und verkaufsfertig für eBay/Excel aufbereitet.

Der gesamte Ablauf besteht aus 3 Schritten:
1. **Dateien ablegen** (in den Eingangs-Ordner auf deinem Desktop)
2. **Doppelklick auf `2_Starte_Analyse`**
3. **Fertige Excel-Tabelle im Ergebnis-Ordner öffnen**

---

## 🛠️ Teil A: Einmalige Einrichtung (Nur beim ersten Mal)

### Schritt 1: GitHub Account & GitHub Desktop
Da das Programm in einem geschützten Bereich liegt, benötigst du einen kostenlosen GitHub-Zugang:

1. **GitHub-Konto erstellen:**
   - Gehe auf [github.com/signup](https://github.com/signup) und erstelle dir ein kostenloses Konto.
   - Gib dem Projektleiter deinen GitHub-Benutzernamen, damit er dich für das Projekt freischaltet.
2. **GitHub Desktop installieren:**
   - Lade dir das Programm **[GitHub Desktop](https://desktop.github.com/)** herunter und installiere es.
   - Öffne GitHub Desktop und melde dich mit deinem GitHub-Konto an.
3. **Projekt auf deinen Computer laden (Klonen):**
   - Klicke in GitHub Desktop auf **File** -> **Clone Repository...**
   - Wähle das Projekt `AsiaWorkflow` / `ProductResearcher` aus.
   - Wähle als Speicherort einen einfachen Pfad (z. B. `C:\Users\DeinName\Dokumente\AsiaWorkflow`).
   - Klicke auf **Clone**.

---

### Schritt 2: Python installieren (Microsoft Store – 1 Klick)
Damit die Skripte ausgeführt werden können, wird Python benötigt:

1. Öffne das Windows-Startmenü (unten links).
2. Tippe **Microsoft Store** ein und öffne die App.
3. Suche oben in der Suchleiste nach **`Python 3.12`** (oder `Python 3.11`).
4. Klicke auf den blauen Button **Installieren** (oder *Abrufen / Kostenlos*).
5. Sobald der Ladebalken durch ist, ist Python einsatzbereit!

---

### Schritt 3: Automatisches Setup starten
1. Öffne den Ordner, in den du das Projekt geklont hast.
2. Mache einen **Doppelklick auf die Datei:**
   ```text
   1_Erstinstallation_Setup.bat
   ```
3. Das Skript richtet alles automatisch ein und erstellt auf deinem Desktop einen aufgeräumten Ordner:
   📁 **`Item Analyse`**
   
   Darin findest du deine 3 zentralen Verknüpfungen:
   - 📁 `1_Item_Scanner_Eingang` (Hier legst du künftig Fotos & Videos rein)
   - ⚡ `2_Starte_Analyse` (Hier machst du künftig den Doppelklick zum Starten)
   - 📊 `3_Item_Scanner_Ergebnisse` (Hier findest du deine fertigen Excel-Dateien)

---

## 📸 Teil B: Die Foto- & Video-Regeln (Wie nehme ich auf?)

Du musst die Dateien nicht mühsam manuell in Unterordner sortieren. Das Programm erkennt automatisch, welche Bilder zu welchem Artikel gehören, wenn du dich an diese **feste Reihenfolge** hältst:

```text
┌────────────────────────────────────────────────────────────────────────┐
│  1. ID-Foto     -> Erstes Bild: Zeigt Zettel / Schild mit Artikel-Nr.  │
│  2. Detailfotos -> 1 bis X Bilder von Vorderseite, Punzen, Schäden etc.│
│  3. Video       -> Schließt diesen Artikel ab                          │
└────────────────────────────────────────────────────────────────────────┘
```

### 💡 Konkretes Beispiel:
Du nimmst 2 Artikel hintereinander mit dem Smartphone oder der Kamera auf:

| Reihenfolge | Dateiname (Beispiel) | Was ist darauf zu sehen? |
| :--- | :--- | :--- |
| **1** | `IMG_0001.JPG` | 📝 **ID-Foto:** Zettel mit großer Zahl **"1"** |
| **2** | `IMG_0002.JPG` | 📸 Detailfoto Vorderseite Buddha |
| **3** | `IMG_0003.JPG` | 📸 Detailfoto Stempel / Bodenmarke |
| **4** | `VID_0004.MP4` | 🎥 **Video:** 15s Rundum-Aufnahme mit Sprachnotiz *(Ende Artikel 1)* |
| **5** | `IMG_0005.JPG` | 📝 **ID-Foto:** Zettel mit großer Zahl **"2"** *(Start Artikel 2)* |
| **6** | `IMG_0006.JPG` | 📸 Detailfoto Silberschale Punze |
| **7** | `VID_0007.MP4` | 🎥 **Video:** Video der Schale *(Ende Artikel 2)* |

> **Wichtig:**
> - Das **ID-Foto** muss gut lesbar sein (gut beleuchtet, deutliche Ziffern).
> - Das **Video** markiert immer das **Ende** des aktuellen Artikels.
> - Danach beginnt der nächste Artikel sofort wieder mit einem neuen ID-Foto.

---

## 🚀 Teil C: Täglicher Ablauf (Auswertung starten)

1. **Dateien rüberkopieren:**
   - Öffne auf deinem Desktop den Ordner **`Item Analyse`** und darin **`1_Item_Scanner_Eingang`**.
   - Kopiere alle Fotos und Videos von deiner Kamera/Handy dort hinein.

2. **Analyse starten:**
   - Mache im Desktop-Ordner **`Item Analyse`** einen Doppelklick auf **`2_Starte_Analyse`**.
   - Es öffnet sich ein schwarzes Fenster, das dir live anzeigt, was die KI gerade tut (Transkription, Webrecherche, Bewertung).
   - Pro Artikel dauert die Analyse ca. 1 bis 2 Minuten.

3. **Ergebnisse ansehen:**
   - Sobald die Analyse fertig ist, öffnet sich **automatisch dein Ergebnis-Ordner** (`output`) im Windows Explorer!
   - Dort findest du:
     - 📗 `consolidated_execution_results.xlsx`: Komplette Excel-Tabelle mit allen analysierten Artikeln, Preisen, Beschreibungen und Szenarien.
     - 📄 `ebay_listings.csv`: Fertige Datei zum direkten Import in das eBay Seller Hub.

---

## 🔄 Updates holen (Wenn es Verbesserungen am Programm gibt)

Wenn der Projektleiter neue Funktionen oder Verbesserungen veröffentlicht hat:
1. Öffne **GitHub Desktop**.
2. Klicke oben rechts auf den Button **Fetch origin** (oder **Pull origin**).
3. Fertig! Dein Programm ist wieder auf dem neuesten Stand.
