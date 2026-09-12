# 01: Media Drag-and-Drop Ingest and Asynchronous Pipeline Execution (Tab 1)

**What to build:** An intuitive first tab ('Medien hochladen / Vorbereiten') where operators can drag and drop media files (JPG, PNG, HEIC, WEBP, MP4, MOV) into a central dropzone, view an overview grid of staged files with counts, and click a prominent 'Recherche & Beschreibung generieren' button. The backend executes raw sorting and the multimodal AI pipeline in a non-blocking background worker thread, displaying real-time progress percentages and live log console output. Upon completion, the app automatically unlocks and switches to Tab 2.

**Blocked by:** None (can start immediately)

**Status:** ready-for-human

- [x] Interactive HTML5 drag-and-drop dropzone accepting image and video files
- [x] Backend endpoint `/api/upload` processing multipart file uploads into `input/raw/`
- [x] Backend endpoint `/api/staged_media` returning raw file counts and folder lists
- [x] Background pipeline worker thread with `/api/run_pipeline` and `/api/pipeline_status`
- [x] Real-time progress bar, log console, and automatic transition to Tab 2 upon completion
- [x] Automated HTTP unit tests covering staged media, upload, and pipeline status
