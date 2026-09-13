from pathlib import Path
from typing import Optional, Dict, Any, Union, List
from pydantic import BaseModel, Field
from datetime import datetime


class PipelineState(BaseModel):
    """Repräsentiert den vollständigen Verarbeitungszustand eines Pipeline-Laufs."""

    run_id: str = Field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))
    item_name: str = ""
    video_path: Path
    image_paths: List[Path] = Field(default_factory=list)
    run_dir: Path
    status: str = "INITIALIZED"

    # Audio & Medien
    audio_path: Optional[Path] = None
    trimmed_video_path: Optional[Path] = None

    # Transkription & ID
    transcription: Optional[str] = None
    id_data: Optional[Dict[str, Any]] = None
    detected_id: Optional[str] = None

    # 3-Stufen Marktbewertung (ADR 0002)
    visual_analysis_json: Optional[Dict[str, Any]] = None
    discovered_web_sources: List[Dict[str, Any]] = Field(default_factory=list)
    reference_listings: List[Dict[str, Any]] = Field(default_factory=list)
    retail_price_synthesis_json: Optional[Dict[str, Any]] = None
    web_price_summary: Optional[Dict[str, Any]] = None

    # Exporte
    export_data: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None
    csv_path: Optional[Path] = None
    excel_path: Optional[Path] = None

    # Metadaten & Fehlermanagement
    source_dir: Optional[Path] = None
    archived_path: Optional[Path] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    class Config:
        arbitrary_types_allowed = True
