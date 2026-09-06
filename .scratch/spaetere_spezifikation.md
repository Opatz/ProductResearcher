# Spezifikations- und Optimierungsplan: Stage 3 Appraiser LLM & Preissynthese

Dieses Dokument enthält die abgestimmten fachlichen Korrekturen und Schärfungen für das **Appraiser LLM (Stage 3: Reconciliation & Preissynthese)**, basierend auf der Zwei-Achsen-Code-Review für Issue 02.

---

## 1. Strikte Priorisierung realisierter Verkaufspreise (Realized vs. Asking Prices)

* **Status Quo (Problem):**  
  Liegen beendete Verkäufe vor, wurde der Basispreis zu 75% aus den realisierten Preisen und zu 25% aus den (oft spekulativ überhöhten) Angebotspreisen gemischt (`(realized_anchor * 0.75) + (asking_median * 0.25)`). Das zog den Richtpreis künstlich nach oben.
* **Soll-Verhalten:**  
  - Liegt mindestens ein verifizierter **`realisierter_verkaufspreis`** (z. B. eBay beendete Angebote, Dorotheum/Catawiki Auktionszuschläge) vor, bildet dieser zu **100% den unbeeinflussten Markt-Anker** (`base_market_price = realized_anchor`).
  - **`angebotspreis`** (z. B. Pamono, 1stDibs, Kleinanzeigen) dient **ausschließlich als spekulative Obergrenze (Ceiling)** bzw. Plausibilitätscheck und wird *nicht* in den Basispreis eingerechnet.
  - **Fallback:** Nur wenn *keine* realisierten Verkäufe existieren, wird der Median der bereinigten Angebotspreise herangezogen – dann jedoch mit einem verbindlichen **15%-Sicherheitsabschlag**.

---

## 2. Echtes Aussortieren von Preisausreißern (Weeding Out statt Clamping)

* **Status Quo (Problem):**  
  Preise mit extremer Abweichung (`> 2.0x Median` oder `< 0.2x Median`) wurden lediglich auf 1.5x bzw. 0.5x gekappt, blieben aber weiterhin im Berechnungspool.
* **Soll-Verhalten:**  
  - Echte statistische Ausreißer sowie Duplikate/Replikate (`repro`, `nachbildung`, `fake`) werden **vollständig aus der Preisberechnung ausgeschlossen** (`excluded_listings`).
  - Jeder Ausschluss wird zwingend in `ausreisser_bereinigung_notiz` dokumentiert (z. B. *„Pamono: Angebotspreis von 1.200 € als extremer Händleraufschlag (> 2x Median) aus der Berechnung ausgeschlossen.“*).
  - Der bereinigte Pool enthält nur noch plausible, vergleichbare Marktpreise.

---

## 3. Deaktivierung von Google Search Grounding in Stage 3 (Kritisch)

* **Status Quo (Problem):**  
  In `AppraiserService.synthesize_valuation()` wurde `enable_google_search=True` an Gemini übergeben.
* **Soll-Verhalten:**  
  - In Stage 3 wird `enable_google_search=False` fest vorgegeben.
  - **Begründung:** Stage 3 ist eine reine **Gutachter- und Schlichtungsphase**. Sie soll ausschließlich die in Stage 2 (den 10 separaten Recherche-Sessions) ermittelten `ReferenceListing`-Daten synthetisieren. Eine erneute Websuche in Stage 3 verursacht unnötige Latenz, Token-Kosten und birgt das Risiko von Halluzinationen oder unstrukturierten Drittquellen. Live-Websuche gehört exklusiv in Stage 1 & 2.

---

## 4. Präzise Median-Definition (Prompt & Modell)

* **Status Quo (Problem):**  
  Im Prompt `prompt_2_appraiser_synthesis.txt` stand missverständlich „Median aller validen, bereinigten Webpreise“.
* **Soll-Verhalten:**  
  - `median_web_preis_eur` ist laut Spezifikation der **mathematische Median aller rohen, validen Webpreise** vor jeder Händler- oder Ausreißer-Bereinigung.
  - Er dient als objektiver statistischer Benchmark des Rohmarktes, während `geschaetzter_retail_preis_eur` den bereinigten, zustandskalibrierten Richtpreis darstellt.

---

## 5. Standard-Bereinigungen & Code-Hygiene (Clean Code)

* **Entfernung redundanter State-Aliase:**  
  In `pipeline/state.py` und `pipeline/orchestrator.py` werden `discovered_web_sources` und `web_price_summary` entfernt. Es gelten ausschließlich die kanonischen Begriffe gemäß `CONTEXT.md`:
  - `state.reference_listings` (für die 10 Plattform-Listings)
  - `state.retail_price_synthesis_json` (für das Stage-3-Gutachten)
* **Beseitigung des Middle-Man-Forwarders:**  
  In `services/web_research_service.py` kann die reine Delegationsmethode `synthesize_retail_valuation()` entfallen, da der Orchestrator `AppraiserService` bereits direkt instanziiert und nutzt.

---

## Checkliste für die spätere Implementierung:

- [ ] **`services/appraiser_service.py`**:
  - `base_market_price = realized_anchor` (100% Anker bei vorhandenen Realized Prices).
  - Asking Prices rein als Obergrenzen-Prüfung behandeln.
  - Extreme Ausreißer (`> 2.0x` / `< 0.2x` Median) komplett nach `excluded_listings` verschieben.
  - `enable_google_search=False` im Gemini-Aufruf fixieren.
- [ ] **`prompts/prompt_2_appraiser_synthesis.txt`**:
  - Definition von `median_web_preis_eur` auf den unbereinigten Rohmedian schärfen.
- [ ] **`pipeline/state.py` & `pipeline/orchestrator.py`**:
  - Redundante State-Aliase (`discovered_web_sources`, `web_price_summary`) entfernen.
- [ ] **`tests/test_appraiser_service.py`**:
  - Tests für 100% Realized Anchor, vollständiges Weeding-Out und `enable_google_search=False` anpassen.
- [ ] **Testsuite verifizieren**:
  - Ausführen mit `python -m unittest discover tests`.
