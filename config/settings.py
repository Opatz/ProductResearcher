import os
import configparser
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
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
    completed_dir: Optional[Path] = None

    def __post_init__(self):
        if self.completed_dir is None:
            self.completed_dir = (self.input_dir.parent / "completed").resolve()
            self.completed_dir.mkdir(parents=True, exist_ok=True)

@dataclass
class EbaySettings:
    site_id: str = "Germany"
    country: str = "DE"
    currency: str = "EUR"
    postal_code: str = "10115"
    listing_duration: str = "GTC"
    listing_type: str = "FixedPrice"
    default_dispatch_days: int = 2
    default_shipping_cost: float = 6.99
    default_bulky_shipping_cost: float = 19.99
    default_freight_shipping_cost: float = 69.99
    image_base_url: str = ""

@dataclass
class AppConfig:
    google: GoogleSettings
    pipeline: PipelineSettings
    ebay: EbaySettings = field(default_factory=EbaySettings)
    base_dir: Path = BASE_DIR


def load_config(config_path: Path = CONFIG_FILE) -> AppConfig:
    """Lädt die Konfiguration aus config.ini und Umgebungsvariablen."""
    parser = configparser.ConfigParser()
    
    if config_path.exists():
        parser.read(config_path, encoding="utf-8")
    
    # API Key: Vorrang Umgebungsvariable (auch wenn leer) > config.ini
    env_api_key = os.getenv("GEMINI_API_KEY")
    if env_api_key is None:
        env_api_key = os.getenv("GOOGLE_API_KEY")
    
    if env_api_key is not None:
        google_api_key = env_api_key.strip()
    else:
        google_api_key = parser.get("GOOGLE", "api_key", fallback="").strip()
    
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

    completed_dir_str = parser.get("PIPELINE", "completed_dir", fallback="input/completed").strip()
    completed_dir = (BASE_DIR / completed_dir_str).resolve()
    completed_dir.mkdir(parents=True, exist_ok=True)

    output_dir_str = parser.get("PIPELINE", "output_dir", fallback="output").strip()
    output_dir = (BASE_DIR / output_dir_str).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    
    preview_duration = parser.getfloat("PIPELINE", "preview_duration_sec", fallback=5.0)
    transcription_language = parser.get("PIPELINE", "transcription_language", fallback="de").strip()

    # eBay Settings
    ebay_site_id = parser.get("EBAY", "site_id", fallback="Germany").strip()
    ebay_country = parser.get("EBAY", "country", fallback="DE").strip()
    ebay_currency = parser.get("EBAY", "currency", fallback="EUR").strip()
    ebay_postal_code = parser.get("EBAY", "postal_code", fallback="10115").strip()
    ebay_duration = parser.get("EBAY", "listing_duration", fallback="GTC").strip()
    ebay_type = parser.get("EBAY", "listing_type", fallback="FixedPrice").strip()
    ebay_dispatch = parser.getint("EBAY", "default_dispatch_days", fallback=2)
    ebay_shipping = parser.getfloat("EBAY", "default_shipping_cost", fallback=6.99)
    ebay_bulky_shipping = parser.getfloat("EBAY", "default_bulky_shipping_cost", fallback=19.99)
    ebay_freight_shipping = parser.getfloat("EBAY", "default_freight_shipping_cost", fallback=69.99)
    ebay_image_base = os.getenv("EBAY_IMAGE_BASE_URL", parser.get("EBAY", "image_base_url", fallback="")).strip()
    
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
            transcription_language=transcription_language,
            completed_dir=completed_dir
        ),
        ebay=EbaySettings(
            site_id=ebay_site_id,
            country=ebay_country,
            currency=ebay_currency,
            postal_code=ebay_postal_code,
            listing_duration=ebay_duration,
            listing_type=ebay_type,
            default_dispatch_days=ebay_dispatch,
            default_shipping_cost=ebay_shipping,
            default_bulky_shipping_cost=ebay_bulky_shipping,
            default_freight_shipping_cost=ebay_freight_shipping,
            image_base_url=ebay_image_base
        ),
        base_dir=BASE_DIR
    )
