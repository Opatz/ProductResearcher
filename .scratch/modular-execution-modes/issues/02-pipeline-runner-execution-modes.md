# 02 PipelineRunner Modular Execution Methods

Status: ready-for-agent

## Description
Erweitere die `PipelineRunner`-Klasse in `services/ui_server.py`, um die drei Ausführungsmodi isoliert und thread-sicher bereitzustellen:
- `start_sort_only(config)`
- `start_research_only(config)`
- `start_pipeline(config)`

## Acceptance Criteria
- [ ] `start_sort_only` führt nur `run_sorting_process` aus, aktualisiert `created_folders` und setzt Status `COMPLETED`.
- [ ] `start_research_only` überspringt `run_sorting_process` und führt sofort `discover_item_tasks()` und `VideoLLMPipeline.run()` aus.
- [ ] `start_pipeline` führt beide Schritte nacheinander aus (End-to-End).
- [ ] Status, Logs und Progress-Bar arbeiten in allen 3 Modi fehlerfrei.
