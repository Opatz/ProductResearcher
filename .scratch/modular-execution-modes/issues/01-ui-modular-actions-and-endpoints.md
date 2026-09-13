# 01 UI Modular Actions and REST Endpoints

Status: ready-for-agent

## Description
Ermögliche im Item Research Studio (UI Server) den getrennten Aufruf von:
1. `POST /api/pipeline/sort-only` für reine Rohmedien-Sortierung.
2. `POST /api/pipeline/research-only` für reine Recherche & Beschreibung auf Basis bestehender Artikelordner.
3. `POST /api/pipeline/start` für den vollständigen End-to-End-Lauf.

## Acceptance Criteria
- [ ] In Tab 1 des UI werden 3 Aktionsbuttons angezeigt:
  - *„📦 Nur Rohmedien sortieren“*
  - *„🔍 Nur Recherche & Beschreibung starten“*
  - *„🚀 Komplette Pipeline ausführen“*
- [ ] Entsprechende Endpunkte rufen die dedizierten Methoden im `PipelineRunner` auf.
- [ ] Live-Fortschritt und Logs spiegeln den jeweils gewählten Modus präzise wider.
