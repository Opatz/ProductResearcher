import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class PromptManager:
    """Verwaltet das Laden, Assemblieren von Zusatz-Kontexten und dynamische Befüllen von Prompt-Dateien."""

    def __init__(self, prompts_dir: Path, context_dir: Optional[Path] = None):
        self.prompts_dir = Path(prompts_dir)
        if not self.prompts_dir.exists():
            raise FileNotFoundError(f"Prompt-Verzeichnis existiert nicht: {self.prompts_dir}")
        
        self.context_dir = Path(context_dir) if context_dir else None
        if self.context_dir and not self.context_dir.exists():
            self.context_dir.mkdir(parents=True, exist_ok=True)

    def load_prompt(self, filename: str) -> str:
        """Lädt den Rohinhalt einer Prompt-Datei."""
        file_path = self.prompts_dir / filename
        if not file_path.exists():
            raise FileNotFoundError(f"Prompt-Datei nicht gefunden: {file_path}")
        
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    def get_assembled_context(self, prompt_key: str) -> str:
        """
        Assembliert alle Textdateien aus dem globalen Kontext und dem spezifischen Prompt-Unterordner.
        Ignoriert .gitkeep und leere Dateien.
        Gibt einen leeren String zurück, falls nichts hinterlegt ist.
        """
        if not self.context_dir or not self.context_dir.exists():
            return ""

        context_parts: List[str] = []
        valid_extensions = {".txt", ".md", ".json", ".csv"}

        # 1. Globaler Kontext (gilt für alle Prompts)
        global_dir = self.context_dir / "global"
        if global_dir.exists() and global_dir.is_dir():
            for file_path in sorted(global_dir.iterdir()):
                if file_path.is_file() and file_path.suffix.lower() in valid_extensions and not file_path.name.startswith("."):
                    content = file_path.read_text(encoding="utf-8").strip()
                    if content:
                        context_parts.append(f"--- [Globaler Kontext: {file_path.name}] ---\n{content}")

        # 2. Spezifischer Kontext für diesen Prompt
        prompt_context_dir = self.context_dir / prompt_key
        if prompt_context_dir.exists() and prompt_context_dir.is_dir():
            for file_path in sorted(prompt_context_dir.iterdir()):
                if file_path.is_file() and file_path.suffix.lower() in valid_extensions and not file_path.name.startswith("."):
                    content = file_path.read_text(encoding="utf-8").strip()
                    if content:
                        context_parts.append(f"--- [Zusatzinfo: {file_path.name}] ---\n{content}")

        if not context_parts:
            return ""

        assembled = (
            "ZUSÄTZLICHE HINTERGRUND- UND KONTEXT-INFORMATIONEN:\n"
            + "\n\n".join(context_parts)
            + "\n"
        )
        logger.info(f"Zusatz-Kontext für '{prompt_key}' assembliert ({len(context_parts)} Dokument(e)).")
        return assembled

    def format_prompt(self, filename: str, **kwargs: Any) -> str:
        """
        Lädt ein Prompt-Template und ersetzt gezielt bekannte Platzhalter wie {transcription}, {id}, {zusatz_kontext} etc.
        """
        template = self.load_prompt(filename)
        
        # Synchronisiere id und video_id für maximale Kompatibilität
        if "id" in kwargs and "video_id" not in kwargs:
            kwargs["video_id"] = kwargs["id"]
        elif "video_id" in kwargs and "id" not in kwargs:
            kwargs["id"] = kwargs["video_id"]

        # Ersetze alle übergebenen Schlüsselwörter
        for key, value in kwargs.items():
            placeholder = f"{{{key}}}"
            val_str = str(value) if value is not None else ""
            template = template.replace(placeholder, val_str)
        
        # Falls {zusatz_kontext} nicht explizit übergeben wurde, bereinigen
        if "{zusatz_kontext}" in template:
            template = template.replace("{zusatz_kontext}", "")

        return template
