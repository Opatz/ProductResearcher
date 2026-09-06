import os
import configparser
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

# .env laden, falls vorhanden
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config" / "config.ini"

@dataclass
class GoogleSettings:
    api_key: str
    model_name: str
    enable_google_search: bool = False

@dataclass
class PipelineSettings:
    raw_dir: Path
    processed_dir: Path
    artikel_dir: Path
    input_dir: Path
    context_dir: Path
    output_dir: Path
    preview_duration_sec: float
    transcription_language: str

@dataclass
class AppConfig:
    google: GoogleSettings
    pipeline: PipelineSettings
    base_dir: Path


def load_config(config_path: Path = CONFIG_FILE) -> AppConfig:
    """Lädt die Konfiguration aus config.ini und Umgebungsvariablen."""
    parser = configparser.ConfigParser()
    
    if config_path.exists():
        parser.read(config_path, encoding="utf-8")
    
    # API Key: Vorrang Umgebungsvariable > config.ini
    google_api_key = (
        os.getenv("GEMINI_API_KEY") 
        or os.getenv("GOOGLE_API_KEY") 
        or parser.get("GOOGLE", "api_key", fallback="")
    ).strip()
    
    model_name = parser.get("GOOGLE", "model_name", fallback="gemini-3.5-flash-lite").strip()
    enable_google_search = parser.getboolean("GOOGLE", "enable_google_search", fallback=True)
    if os.getenv("ENABLE_GOOGLE_SEARCH"):
        enable_google_search = os.getenv("ENABLE_GOOGLE_SEARCH", "").strip().lower() in {"true", "1", "yes"}
    
    raw_dir_str = parser.get("PIPELINE", "raw_dir", fallback="input/raw").strip()
    raw_dir = (BASE_DIR / raw_dir_str).resolve()
    raw_dir.mkdir(parents=True, exist_ok=True)

    processed_dir_str = parser.get("PIPELINE", "processed_dir", fallback="input/processed").strip()
    processed_dir = (BASE_DIR / processed_dir_str).resolve()
    processed_dir.mkdir(parents=True, exist_ok=True)

    artikel_dir_str = parser.get("PIPELINE", "artikel_dir", fallback="input/artikel").strip()
    artikel_dir = (BASE_DIR / artikel_dir_str).resolve()
    artikel_dir.mkdir(parents=True, exist_ok=True)

    input_dir_str = parser.get("PIPELINE", "input_dir", fallback="input/artikel").strip()
    input_dir = (BASE_DIR / input_dir_str).resolve()
    input_dir.mkdir(parents=True, exist_ok=True)

    context_dir_str = parser.get("PIPELINE", "context_dir", fallback="prompt_context").strip()
    context_dir = (BASE_DIR / context_dir_str).resolve()
    context_dir.mkdir(parents=True, exist_ok=True)

    output_dir_str = parser.get("PIPELINE", "output_dir", fallback="output").strip()
    output_dir = (BASE_DIR / output_dir_str).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    
    preview_duration = parser.getfloat("PIPELINE", "preview_duration_sec", fallback=5.0)
    transcription_language = parser.get("PIPELINE", "transcription_language", fallback="de").strip()
    
    return AppConfig(
        google=GoogleSettings(
            api_key=google_api_key,
            model_name=model_name,
            enable_google_search=enable_google_search
        ),
        pipeline=PipelineSettings(
            raw_dir=raw_dir,
            processed_dir=processed_dir,
            artikel_dir=artikel_dir,
            input_dir=input_dir,
            context_dir=context_dir,
            output_dir=output_dir,
            preview_duration_sec=preview_duration,
            transcription_language=transcription_language
        ),
        base_dir=BASE_DIR
    )
