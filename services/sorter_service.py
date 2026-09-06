import re
import os
import json
import shutil
import logging
import functools
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime
from PIL import Image

from services.gemini_service import GeminiService

logger = logging.getLogger(__name__)


@dataclass
class SortSummary:
    """Zusammenfassung des Sortier- und Quarantänelaufs."""
    total_media_files: int = 0
    standard_articles: int = 0
    low_confidence_quarantined: int = 0
    missing_id_quarantined: int = 0
    standalone_videos_quarantined: int = 0
    orphan_trailing_quarantined: int = 0
    total_quarantined: int = 0
    total_created: int = 0
    move_files: bool = True
    target_artikel_dir: Optional[Path] = None
    inspect_dir: Optional[Path] = None
    created_folders: List[Path] = field(default_factory=list)


@functools.total_ordering
class MediaSortKey:
    """
    Sortierschlüssel für Mediendateien (Bilder und Videos).
    Unterstützt sowohl WhatsApp-Aufnahmen (Zeitstempel + Subindex)
    als auch Kamera-Aufnahmen (sequentieller numerischer Index) sowie EXIF/mtime Fallbacks.
    """

    def __init__(
        self,
        file_path: Path,
        file_type: str,  # "WHATSAPP", "CAMERA", "FALLBACK"
        timestamp: datetime,
        sub_index: int = 0,
        camera_prefix: str = "",
        numeric_index: Optional[int] = None,
        mtime: Optional[datetime] = None,
    ):
        self.file_path = file_path
        self.filename = file_path.name
        self.file_type = file_type
        self.timestamp = timestamp
        self.sub_index = sub_index
        self.camera_prefix = camera_prefix.upper()
        self.numeric_index = numeric_index
        self.mtime = mtime or timestamp

    def __iter__(self):
        # Ermöglicht weiterhin Entpacken als Tuple: dt, sub_idx, name = key
        effective_idx = self.numeric_index if self.numeric_index is not None else self.sub_index
        return iter((self.timestamp, effective_idx, self.filename))

    def __getitem__(self, idx: int):
        effective_idx = self.numeric_index if self.numeric_index is not None else self.sub_index
        return (self.timestamp, effective_idx, self.filename)[idx]

    def __len__(self):
        return 3

    def __repr__(self):
        return (
            f"MediaSortKey(type={self.file_type}, name='{self.filename}', "
            f"ts={self.timestamp}, num_idx={self.numeric_index}, sub_idx={self.sub_index})"
        )

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, MediaSortKey):
            return False
        return (
            self.file_type == other.file_type
            and self.camera_prefix == other.camera_prefix
            and self.numeric_index == other.numeric_index
            and self.timestamp == other.timestamp
            and self.sub_index == other.sub_index
            and self.filename == other.filename
        )

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, MediaSortKey):
            return NotImplemented

        # 1. Beide sind Kamera-Dateien mit demselben Präfix (z. B. beide IMG_ oder beide DSC_):
        # Primär nach sequentieller Kennzahl sortieren
        if self.file_type == "CAMERA" and other.file_type == "CAMERA" and self.camera_prefix == other.camera_prefix:
            s_idx = self.numeric_index if self.numeric_index is not None else 0
            o_idx = other.numeric_index if other.numeric_index is not None else 0
            if s_idx != o_idx:
                return s_idx < o_idx
            if self.sub_index != other.sub_index:
                return self.sub_index < other.sub_index
            if self.mtime != other.mtime:
                return self.mtime < other.mtime
            return self.filename < other.filename

        # 2. Beide sind WhatsApp-Dateien:
        # Primär nach Datum/Uhrzeit und dann Sub-Index sortieren
        if self.file_type == "WHATSAPP" and other.file_type == "WHATSAPP":
            if self.timestamp != other.timestamp:
                return self.timestamp < other.timestamp
            if self.sub_index != other.sub_index:
                return self.sub_index < other.sub_index
            return self.filename < other.filename

        # 3. Gemischte Batches / unterschiedliche Formate / Fallback:
        # Nach effektivem Zeitstempel vergleichen
        if self.timestamp != other.timestamp:
            return self.timestamp < other.timestamp

        # Bei identischem Zeitstempel:
        if self.file_type != other.file_type:
            return self.file_type < other.file_type

        s_num = self.numeric_index if self.numeric_index is not None else self.sub_index
        o_num = other.numeric_index if other.numeric_index is not None else other.sub_index
        if s_num != o_num:
            return s_num < o_num

        return self.filename < other.filename


class MediaSorterService:
    """
    Automatischer Sorter für rohe / vorverarbeitete Aufnahmen:
    - Sortiert alle Bilder und Videos aufsteigend chronologisch nach Aufnahmezeitpunkt & Index.
    - Erkennt Sequenzen: Erstes Bild = ID/Nummer -> Folge-Bilder -> bis einschließlich Video.
    - Extrahiert die ID vom ersten Bild via Gemini Vision unter Verwendung von 'prompt_id.txt'.
    - Erstellt den Zielordner 'Artikel_<ID>' (bei Duplikaten 'Artikel_<ID>_1', 'Artikel_<ID>_2'...).
    - Verschiebt alle zusammengehörigen Medien in den entsprechenden Artikel-Ordner in input/artikel/.
    """

    def __init__(
        self, 
        gemini_service: Optional[GeminiService] = None, 
        prompts_dir: Optional[Path] = None
    ):
        self.gemini_service = gemini_service
        self.prompts_dir = Path(prompts_dir) if prompts_dir else (Path(__file__).resolve().parent.parent / "prompts")
        self.image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic"}
        self.video_extensions = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
        self.last_summary: Optional[SortSummary] = None

    def _extract_exif_datetime(self, file_path: Path) -> Optional[datetime]:
        """Liest DateTimeOriginal / DateTimeDigitized / DateTime aus dem EXIF-Header aus."""
        suffix = file_path.suffix.lower()
        if suffix in self.image_extensions:
            try:
                with Image.open(file_path) as img:
                    exif_data = img._getexif()
                    if exif_data:
                        # 36867: DateTimeOriginal, 36868: DateTimeDigitized, 306: DateTime
                        for tag_id in (36867, 36868, 306):
                            if tag_id in exif_data:
                                date_str = str(exif_data[tag_id]).strip()
                                for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                                    try:
                                        return datetime.strptime(date_str, fmt)
                                    except ValueError:
                                        pass
            except Exception:
                pass
        return None

    def _get_chronological_key(self, file_path: Path) -> MediaSortKey:
        """
        Ermittelt einen präzisen Sortierschlüssel (Aufnahmezeitpunkt, Index, Dateiname).
        Erkennt:
        1. WhatsApp-Dateinamen: 'WhatsApp Image YYYY-MM-DD at HH.MM.SS (n)'
        2. Screenshot-Muster: 'Screenshot YYYY-MM-DD HHMMSS'
        3. Kamera-/Telefon-Muster: 'IMG_4793.mp4', 'DSC_0012.JPG', '4793.mp4'
        4. EXIF-Datum bei Bildern mit mtime-Fallback
        """
        name = file_path.name
        stem = file_path.stem

        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
        except Exception:
            mtime = datetime.now()

        # 1. Spezielles WhatsApp-/Datumsmuster mit optionalem Index: 'YYYY-MM-DD at HH.MM.SS (n)'
        m_wa = re.search(r"(\d{4})-(\d{2})-(\d{2})\s+at\s+(\d{2})\.(\d{2})\.(\d{2})(?:\s*\((\d+)\))?", name)
        if m_wa:
            try:
                y, m, d, h, mi, s = map(int, m_wa.groups()[:6])
                sub_idx = int(m_wa.group(7)) if m_wa.group(7) is not None else 0
                return MediaSortKey(
                    file_path=file_path,
                    file_type="WHATSAPP",
                    timestamp=datetime(y, m, d, h, mi, s),
                    sub_index=sub_idx,
                    mtime=mtime
                )
            except Exception:
                pass

        # 2. Screenshot-Muster: 'Screenshot YYYY-MM-DD HHMMSS'
        m_ss = re.search(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2})(\d{2})(\d{2})", name)
        if m_ss:
            try:
                y, m, d, h, mi, s = map(int, m_ss.groups())
                return MediaSortKey(
                    file_path=file_path,
                    file_type="WHATSAPP",
                    timestamp=datetime(y, m, d, h, mi, s),
                    sub_index=0,
                    mtime=mtime
                )
            except Exception:
                pass

        # 3. Kamera-/Telefon-Sequenzmuster: 'IMG_4793', 'DSC_0012', 'VID_4795', 'PIC_4796'
        m_cam = re.match(r"^(IMG|DSC|VID|PIC)[_-]?(\d+)(?:[_\s(-]+(\d+)\)?)?$", stem, re.IGNORECASE)
        if m_cam:
            prefix = m_cam.group(1).upper()
            numeric_idx = int(m_cam.group(2))
            sub_idx = int(m_cam.group(3)) if m_cam.group(3) is not None else 0
            exif_dt = self._extract_exif_datetime(file_path)
            return MediaSortKey(
                file_path=file_path,
                file_type="CAMERA",
                timestamp=exif_dt or mtime,
                camera_prefix=prefix,
                numeric_index=numeric_idx,
                sub_index=sub_idx,
                mtime=mtime
            )

        # Standalone Zahl (z. B. bereits bereinigt '4793.mp4', '0012.jpg')
        m_digits = re.match(r"^(\d+)(?:[_\s(-]+(\d+)\)?)?$", stem)
        if m_digits:
            numeric_idx = int(m_digits.group(1))
            sub_idx = int(m_digits.group(2)) if m_digits.group(2) is not None else 0
            exif_dt = self._extract_exif_datetime(file_path)
            return MediaSortKey(
                file_path=file_path,
                file_type="CAMERA",
                timestamp=exif_dt or mtime,
                camera_prefix="",
                numeric_index=numeric_idx,
                sub_index=sub_idx,
                mtime=mtime
            )

        # 4. Fallback: EXIF-Datum oder Datei-Änderungszeitpunkt (mtime)
        exif_dt = self._extract_exif_datetime(file_path)
        return MediaSortKey(
            file_path=file_path,
            file_type="FALLBACK",
            timestamp=exif_dt or mtime,
            sub_index=0,
            mtime=mtime
        )

    def _load_id_prompt(self) -> str:
        """Lädt das ID-Prompt aus prompt_id.txt oder verwendet einen Standard-Fallback."""
        prompt_file = self.prompts_dir / "prompt_id.txt"
        if prompt_file.exists():
            try:
                return prompt_file.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Konnte prompt_id.txt nicht laden ({e}). Verwende Fallback-Prompt.")

        return (
            "Du bist ein hochpräziser visueller OCR- und Erkennungs-Assistent für Artikel-IDs und Kennnummern.\n"
            "Analysiere das übergebene Bild.\n"
            "AUFGABE:\n"
            "1. Suche nach sichtbaren Zahlen, Kennnummern, Codes oder Identifikationsnummern (ID).\n"
            "2. Extrahiere den genauen Wert (z. B. '1', '2', '3', 'ARTIKEL-1').\n"
            "3. Falls keine ID zu sehen ist, antworte mit 'N/A'.\n\n"
            "FORMAT: Reines JSON:\n"
            "{\n"
            '  "detected_id": "string",\n'
            '  "confidence": "high|medium|low",\n'
            '  "visual_description": "string"\n'
            "}"
        )

    def _clean_detected_id(self, raw_id: str, fallback_idx: int) -> str:
        """Bereinigt die erkannte ID (entfernt Sonderzeichen/Präfixe, normalisiert Ziffern)."""
        if not raw_id:
            return str(fallback_idx)

        val = str(raw_id).strip()
        if val.lower() in {"n/a", "null", "none", "unbekannt", "unknown", ""}:
            return str(fallback_idx)

        # Entferne gängige Präfixe wie "Artikel", "ID", "Item", "Nr.", "No.", "#"
        clean = re.sub(r"^(?:(?:artikel|id|item|nr\.?|no\.?|#|kennnummer)\s*[:\-\s#]*)+", "", val, flags=re.IGNORECASE).strip()
        
        # Falls eine Ziffernfolge durch Leerzeichen oder Bindestriche getrennt ist (z. B. "2 1 2" oder "2-1-2")
        condensed_digits = re.sub(r"[\s\-_]+", "", clean)
        if condensed_digits.isdigit():
            clean = condensed_digits

        # Falls eine führende Null vorhanden ist (z. B. "01" -> "1", "042" -> "42")
        if clean.isdigit():
            clean = str(int(clean))
        elif not clean:
            clean = str(fallback_idx)

        # Sonderzeichen für Ordnernamen bereinigen
        clean = re.sub(r'[\\/*?:"<>|]', '_', clean).strip()
        return clean or str(fallback_idx)

    def detect_id_from_image(
        self, 
        image_path: Optional[Path], 
        fallback_idx: int = 1
    ) -> Dict[str, Any]:
        """
        Analysiert das erste Bild via Gemini Vision und liefert strukturierte Erkennungsdetails:
        - detected_id: Bereinigte Artikel-ID
        - confidence: 'high' | 'medium' | 'low'
        - visual_description: Bildbeschreibung
        - raw_id: Rohwert vor Bereinigung
        - is_valid: Ob eine valide ID erkannt wurde
        - gemini_response: Vollständiges JSON von Gemini
        """
        if not image_path or not Path(image_path).exists():
            logger.info(f"Kein gültiges Bild vorhanden; verwende Fallback-ID '{fallback_idx}'.")
            return {
                "detected_id": str(fallback_idx),
                "confidence": "low",
                "visual_description": "No image provided",
                "raw_id": "",
                "is_valid": False,
                "gemini_response": {}
            }

        image_path = Path(image_path)

        if not self.gemini_service:
            logger.info(f"Kein GeminiService aktiv; verwende Fallback-ID '{fallback_idx}' mit Standard-Konfidenz.")
            return {
                "detected_id": str(fallback_idx),
                "confidence": "medium",
                "visual_description": "Fallback (kein GeminiService)",
                "raw_id": str(fallback_idx),
                "is_valid": True,
                "gemini_response": {"detected_id": str(fallback_idx), "confidence": "medium"}
            }

        prompt = self._load_id_prompt()

        try:
            logger.info(f"🔍 Scanne erstes Bild '{image_path.name}' nach Artikel-ID...")
            result = self.gemini_service.execute_text_prompt(
                prompt_text=prompt,
                images=[image_path],
                expect_json=True
            )
            parsed = result.get("parsed_json", {}) if isinstance(result, dict) else {}
            raw_id = str(parsed.get("detected_id", "") or "").strip()
            raw_conf = str(parsed.get("confidence", "") or "").strip().lower()
            desc = str(parsed.get("visual_description", "") or "").strip()

            is_valid = bool(raw_id and raw_id.lower() not in {"n/a", "null", "none", "unbekannt", "unknown", ""})
            cleaned_id = self._clean_detected_id(raw_id, fallback_idx)

            if raw_conf in {"high", "medium", "low"}:
                confidence = raw_conf
            else:
                confidence = "medium" if is_valid else "low"

            if not is_valid and confidence != "low":
                confidence = "low"

            logger.info(
                f"🎯 Erkannte ID für '{image_path.name}': '{cleaned_id}' "
                f"(Rohwert: '{raw_id}', Konfidenz: '{confidence}')"
            )
            return {
                "detected_id": cleaned_id,
                "confidence": confidence,
                "visual_description": desc,
                "raw_id": raw_id,
                "is_valid": is_valid,
                "gemini_response": parsed
            }
        except Exception as e:
            logger.warning(f"Konnte ID aus Bild '{image_path.name}' nicht extrahieren ({e}). Verwende Fallback '{fallback_idx}'.")
            return {
                "detected_id": str(fallback_idx),
                "confidence": "low",
                "visual_description": f"Error: {e}",
                "raw_id": "",
                "is_valid": False,
                "gemini_response": {"error": str(e)}
            }

    def extract_id_from_image(self, image_path: Path, fallback_idx: int = 1) -> str:
        """Kompatibilitätsmethode: liefert die bereinigte ID als String."""
        res = self.detect_id_from_image(image_path, fallback_idx=fallback_idx)
        return res["detected_id"]

    def resolve_target_folder_name(
        self, 
        target_dir: Path, 
        article_id: str, 
        suffix: str = ""
    ) -> str:
        """
        Ermittelt den finalen Ordnernamen nach dem Schema:
        - Artikel_<ID><suffix> (z. B. Artikel_1 oder Artikel_1_low_confidence)
        - Bei Duplikaten: Artikel_<ID><suffix>_1, Artikel_<ID><suffix>_2 etc.
        """
        base_name = f"Artikel_{article_id}{suffix}"
        
        if not (target_dir / base_name).exists():
            return base_name

        # Duplikat-Index hochzählen: Artikel_1_1, Artikel_1_2, ...
        dup_idx = 1
        while (target_dir / f"{base_name}_{dup_idx}").exists():
            dup_idx += 1

        chosen_name = f"{base_name}_{dup_idx}"
        logger.info(f"⚠️ Ordner '{base_name}' existiert bereits. Verwende Duplikat-Namen: '{chosen_name}'")
        return chosen_name

    def resolve_unassigned_seq_folder_name(
        self, 
        inspect_dir: Path, 
        reserved: Optional[set] = None
    ) -> str:
        """
        Ermittelt den nächsten fortlaufenden Ordnernamen für unidentifizierte Sequenzen:
        unassigned_seq_01, unassigned_seq_02, etc.
        """
        idx = 1
        while (inspect_dir / f"unassigned_seq_{idx:02d}").exists() or (reserved and f"unassigned_seq_{idx:02d}" in reserved):
            idx += 1
        name = f"unassigned_seq_{idx:02d}"
        if reserved is not None:
            reserved.add(name)
        return name

    def resolve_orphan_media_folder_name(
        self, 
        inspect_dir: Path, 
        reserved: Optional[set] = None
    ) -> str:
        """
        Ermittelt den Zielordnernamen für unvollständige Sequenzen ohne abschließendes Video:
        orphan_trailing_media, orphan_trailing_media_1, etc.
        """
        base_name = "orphan_trailing_media"
        if not (inspect_dir / base_name).exists() and not (reserved and base_name in reserved):
            if reserved is not None:
                reserved.add(base_name)
            return base_name

        idx = 1
        while (inspect_dir / f"{base_name}_{idx}").exists() or (reserved and f"{base_name}_{idx}" in reserved):
            idx += 1
        name = f"{base_name}_{idx}"
        if reserved is not None:
            reserved.add(name)
        return name

    def _clean_target_filename(self, filename: str) -> str:
        """
        Normalisiert Zieldateinamen:
        1. Entfernt WhatsApp-Präfixe wie 'WhatsApp Image ', 'WhatsApp Video ', 'WhatsApp Unknown ' etc.
        2. Entfernt Kamera-/Telefon-Präfixe wie 'IMG_', 'DSC_', 'VID_', 'PIC_' (z. B. 'IMG_4793.mp4' -> '4793.mp4').
        """
        # 1. WhatsApp-Präfixe entfernen
        clean = re.sub(r"^WhatsApp\s+[A-Za-z]+\s+", "", filename, flags=re.IGNORECASE)
        # 2. Kamera-Präfixe (IMG_, DSC_, VID_, PIC_) entfernen, falls gefolgt von einer Zahl
        clean = re.sub(r"^(?:IMG|DSC|VID|PIC)[_-]?(?=\d)", "", clean, flags=re.IGNORECASE)
        return clean

    def sort_media_files(
        self,
        source_dir: Union[str, Path, List[Union[str, Path]]],
        target_artikel_dir: Union[str, Path],
        inspect_dir: Optional[Union[str, Path]] = None,
        move_files: bool = True
    ) -> List[Path]:
        """
        Liest alle Mediendateien aus den Quellordnern ein, sortiert sie chronologisch/numerisch aufsteigend,
        bildet Sequenzen (1. Bild mit ID bis einschließlich Video) und speichert sie in target_artikel_dir/Artikel_<ID>
        (bzw. bei niedriger Konfidenz in inspect_dir/Artikel_<ID>_low_confidence).
        """
        # Falls inspect_dir als bool übergeben wurde (z. B. altes Positionsargument move_files)
        if isinstance(inspect_dir, bool):
            move_files = inspect_dir
            inspect_dir = None

        target_artikel_dir = Path(target_artikel_dir).resolve()
        target_artikel_dir.mkdir(parents=True, exist_ok=True)

        if inspect_dir:
            inspect_dir = Path(inspect_dir).resolve()
        else:
            inspect_dir = (target_artikel_dir.parent.parent / "output" / "to_inspect").resolve()

        # Quellordner auflösen
        source_dirs_list = [source_dir] if isinstance(source_dir, (str, Path)) else list(source_dir)
        source_paths = [Path(d).resolve() for d in source_dirs_list if Path(d).exists()]

        if not source_paths:
            logger.info("Keine gültigen Quellverzeichnisse zur Sortierung gefunden.")
            self.last_summary = SortSummary(
                total_media_files=0,
                move_files=move_files,
                target_artikel_dir=target_artikel_dir,
                inspect_dir=inspect_dir
            )
            return []

        # Alle Mediendateien aus allen Quellordnern sammeln
        media_files: List[Tuple[Path, MediaSortKey, str]] = []
        for src in source_paths:
            for f in src.iterdir():
                if f.is_file() and not f.name.startswith("."):
                    ext = f.suffix.lower()
                    if ext in self.image_extensions:
                        sort_key = self._get_chronological_key(f)
                        media_files.append((f, sort_key, "IMAGE"))
                    elif ext in self.video_extensions:
                        sort_key = self._get_chronological_key(f)
                        media_files.append((f, sort_key, "VIDEO"))

        if not media_files:
            logger.info("Keine Bilder oder Videos in den Quellverzeichnissen gefunden.")
            self.last_summary = SortSummary(
                total_media_files=0,
                move_files=move_files,
                target_artikel_dir=target_artikel_dir,
                inspect_dir=inspect_dir
            )
            return []

        # Deterministisch nach MediaSortKey sortieren
        media_files.sort(key=lambda x: x[1])

        summary = SortSummary(
            total_media_files=len(media_files),
            move_files=move_files,
            target_artikel_dir=target_artikel_dir,
            inspect_dir=inspect_dir
        )

        logger.info("=" * 65)
        logger.info(f"📦 MEDIA-SORTER: {len(media_files)} Mediendateien chronologisch/numerisch sortiert.")
        logger.info("=" * 65)

        # In Artikel-Blöcke aufteilen (Start = Erstes Bild, Ende = Video)
        chunks: List[Dict[str, Any]] = []
        current_images: List[Path] = []

        for f, sort_key, kind in media_files:
            if kind == "IMAGE":
                current_images.append(f)
            elif kind == "VIDEO":
                chunks.append({
                    "first_image": current_images[0] if current_images else None,
                    "images": list(current_images),
                    "video": f
                })
                current_images.clear()

        # Bilder am Ende ohne abschließendes Video (z. B. Nachzügler)
        if current_images:
            logger.warning(f"⚠️ {len(current_images)} Bild(er) am Ende ohne folgendes Video gefunden.")

        logger.info(f"Gefundene Artikel-Sequenzen: {len(chunks)}")

        created_folders: List[Path] = []
        reserved_folder_names: set = set()

        for seq_idx, chunk in enumerate(chunks, 1):
            video_file: Path = chunk["video"]
            images: List[Path] = chunk["images"]
            first_img: Optional[Path] = chunk["first_image"]

            clean_vid_name = self._clean_target_filename(video_file.name)
            clean_first_img = self._clean_target_filename(first_img.name) if first_img else None

            # Fall A: Standalone Video (keine vorangegangenen Bilder)
            if not images:
                summary.standalone_videos_quarantined += 1
                inspect_dir.mkdir(parents=True, exist_ok=True)
                folder_name = self.resolve_unassigned_seq_folder_name(inspect_dir, reserved_folder_names)
                article_dir = inspect_dir / folder_name
                quarantine_reason = "video_without_images"
                is_quarantine = True
                is_low_confidence = False
                detected_id = None
                confidence = "low"
                id_info = {"gemini_response": {}}
                logger.info(
                    f"⚠️ [{seq_idx}/{len(chunks)}] Standalone Video '{video_file.name}' ohne vorangegangene Bilder. "
                    f"Quarantänisiere nach '{inspect_dir.name}/{folder_name}'..."
                )
            else:
                # 1. ID und Konfidenz vom ersten Bild analysieren
                id_info = self.detect_id_from_image(first_img, fallback_idx=seq_idx)
                detected_id = id_info["detected_id"]
                confidence = id_info["confidence"]
                is_valid = id_info.get("is_valid", False)

                # 2. Routing: Missing ID -> unassigned_seq_XX, Low -> Artikel_<ID>_low_confidence, High/Medium -> Artikel_<ID>
                if not is_valid:
                    summary.missing_id_quarantined += 1
                    inspect_dir.mkdir(parents=True, exist_ok=True)
                    folder_name = self.resolve_unassigned_seq_folder_name(inspect_dir, reserved_folder_names)
                    article_dir = inspect_dir / folder_name
                    quarantine_reason = "missing_or_unrecognized_id"
                    is_quarantine = True
                    is_low_confidence = False
                    logger.info(
                        f"⚠️ [{seq_idx}/{len(chunks)}] Keine gültige ID im Bild '{first_img.name}' erkannt. "
                        f"Quarantänisiere nach '{inspect_dir.name}/{folder_name}'..."
                    )
                elif confidence == "low":
                    summary.low_confidence_quarantined += 1
                    inspect_dir.mkdir(parents=True, exist_ok=True)
                    folder_name = self.resolve_target_folder_name(
                        inspect_dir, detected_id, suffix="_low_confidence"
                    )
                    article_dir = inspect_dir / folder_name
                    quarantine_reason = "low_confidence_id"
                    is_quarantine = True
                    is_low_confidence = True
                    logger.info(
                        f"⚠️ [{seq_idx}/{len(chunks)}] Niedrige Konfidenz ({confidence}) für ID '{detected_id}'. "
                        f"Isoliere nach '{inspect_dir.name}/{folder_name}'..."
                    )
                else:
                    summary.standard_articles += 1
                    folder_name = self.resolve_target_folder_name(target_artikel_dir, detected_id)
                    article_dir = target_artikel_dir / folder_name
                    quarantine_reason = None
                    is_quarantine = False
                    is_low_confidence = False
                    logger.info(
                        f"📁 [{seq_idx}/{len(chunks)}] Erstelle '{folder_name}' (ID: '{detected_id}', "
                        f"Konfidenz: '{confidence}') mit {len(images)} Bild(ern)..."
                    )

            article_dir.mkdir(parents=True, exist_ok=True)
            reserved_folder_names.add(folder_name)

            # 3. Dateien übertragen (verschieben oder kopieren) mit bereinigten Namen ohne Präfix
            op = shutil.move if move_files else shutil.copy2
            transferred_images = []

            # Bilder übertragen (beginnend mit dem ID-Bild)
            for img in images:
                clean_img_name = self._clean_target_filename(img.name)
                target_img_path = article_dir / clean_img_name
                # Kollision im selben Ordner vermeiden
                if target_img_path.exists() and (move_files or str(img.resolve()) != str(target_img_path.resolve())):
                    stem = target_img_path.stem
                    suffix = target_img_path.suffix
                    c = 1
                    while (article_dir / f"{stem}_{c}{suffix}").exists():
                        c += 1
                    clean_img_name = f"{stem}_{c}{suffix}"
                    target_img_path = article_dir / clean_img_name
                op(str(img), str(target_img_path))
                transferred_images.append(clean_img_name)

            # Video übertragen (schließt den Artikel ab)
            target_vid_path = article_dir / clean_vid_name
            if target_vid_path.exists() and (move_files or str(video_file.resolve()) != str(target_vid_path.resolve())):
                stem = target_vid_path.stem
                suffix = target_vid_path.suffix
                c = 1
                while (article_dir / f"{stem}_{c}{suffix}").exists():
                    c += 1
                clean_vid_name = f"{stem}_{c}{suffix}"
                target_vid_path = article_dir / clean_vid_name
            op(str(video_file), str(target_vid_path))

            # 4. Metadaten-Datei ablegen
            manifest = {
                "folder_name": folder_name,
                "detected_id": detected_id if (not is_quarantine or is_low_confidence) else None,
                "confidence": confidence,
                "sequence_nr": seq_idx,
                "first_image_id": clean_first_img,
                "video": clean_vid_name,
                "images": transferred_images,
                "sorted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(article_dir / "sort_info.json", "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)

            # Falls Quarantäne: inspection_reason.json schreiben
            if is_quarantine:
                inspection_data = {
                    "folder_name": folder_name,
                    "quarantine_reason": quarantine_reason,
                    "proposed_id": detected_id if is_low_confidence else None,
                    "confidence": confidence,
                    "sequence_nr": seq_idx,
                    "detected_first_image": clean_first_img,
                    "video": clean_vid_name,
                    "media_files": transferred_images + [clean_vid_name],
                    "gemini_response": id_info.get("gemini_response", {}),
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                with open(article_dir / "inspection_reason.json", "w", encoding="utf-8") as f:
                    json.dump(inspection_data, f, ensure_ascii=False, indent=2)

            created_folders.append(article_dir)

        # 5. Bilder am Ende ohne abschließendes Video (Trailing Orphan Media)
        if current_images:
            inspect_dir.mkdir(parents=True, exist_ok=True)
            orphan_folder_name = self.resolve_orphan_media_folder_name(inspect_dir, reserved_folder_names)
            orphan_dir = inspect_dir / orphan_folder_name
            orphan_dir.mkdir(parents=True, exist_ok=True)
            reserved_folder_names.add(orphan_folder_name)
            logger.warning(
                f"⚠️ {len(current_images)} Bild(er) am Ende ohne folgendes Video gefunden. "
                f"Quarantänisiere nach '{inspect_dir.name}/{orphan_folder_name}'..."
            )

            op = shutil.move if move_files else shutil.copy2
            transferred_orphan_images = []
            for img in current_images:
                clean_img_name = self._clean_target_filename(img.name)
                target_img_path = orphan_dir / clean_img_name
                if target_img_path.exists() and (move_files or str(img.resolve()) != str(target_img_path.resolve())):
                    stem = target_img_path.stem
                    suffix = target_img_path.suffix
                    c = 1
                    while (orphan_dir / f"{stem}_{c}{suffix}").exists():
                        c += 1
                    clean_img_name = f"{stem}_{c}{suffix}"
                    target_img_path = orphan_dir / clean_img_name
                op(str(img), str(target_img_path))
                transferred_orphan_images.append(clean_img_name)

            clean_first_orphan_img = self._clean_target_filename(current_images[0].name)

            orphan_sort_info = {
                "folder_name": orphan_folder_name,
                "detected_id": None,
                "confidence": "low",
                "sequence_nr": None,
                "first_image_id": clean_first_orphan_img,
                "video": None,
                "images": transferred_orphan_images,
                "sorted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(orphan_dir / "sort_info.json", "w", encoding="utf-8") as f:
                json.dump(orphan_sort_info, f, ensure_ascii=False, indent=2)

            orphan_inspection_reason = {
                "folder_name": orphan_folder_name,
                "quarantine_reason": "unclosed_sequence_no_video",
                "proposed_id": None,
                "confidence": "low",
                "sequence_nr": None,
                "detected_first_image": clean_first_orphan_img,
                "video": None,
                "media_files": transferred_orphan_images,
                "gemini_response": {},
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(orphan_dir / "inspection_reason.json", "w", encoding="utf-8") as f:
                json.dump(orphan_inspection_reason, f, ensure_ascii=False, indent=2)

            summary.orphan_trailing_quarantined += 1
            created_folders.append(orphan_dir)

        summary.total_quarantined = (
            summary.low_confidence_quarantined
            + summary.missing_id_quarantined
            + summary.standalone_videos_quarantined
            + summary.orphan_trailing_quarantined
        )
        summary.total_created = len(created_folders)
        summary.created_folders = list(created_folders)
        self.last_summary = summary

        op_str = "VERSCHOBEN (Move)" if move_files else "KOPIERT (Copy)"
        logger.info("=" * 70)
        logger.info("📊 RAW INGEST SORTIERUNG ZUSAMMENFASSUNG")
        logger.info("=" * 70)
        logger.info(f"  📦 Verarbeitete Mediendateien:   {summary.total_media_files}")
        logger.info(f"  📂 Standard Artikel-Ordner:      {summary.standard_articles}")
        logger.info(f"  🚨 Quarantänisierte Ordner:      {summary.total_quarantined}")
        if summary.low_confidence_quarantined:
            logger.info(f"     • Niedrige Konfidenz:         {summary.low_confidence_quarantined}")
        if summary.missing_id_quarantined:
            logger.info(f"     • Fehlende / Unbekannte ID:   {summary.missing_id_quarantined}")
        if summary.standalone_videos_quarantined:
            logger.info(f"     • Standalone-Videos:          {summary.standalone_videos_quarantined}")
        if summary.orphan_trailing_quarantined:
            logger.info(f"     • Verwaiste Bilder (Trailing):{summary.orphan_trailing_quarantined}")
        logger.info(f"  🔄 Datei-Operation:              {op_str}")
        logger.info(f"  📁 Zielverzeichnis:              {target_artikel_dir}")
        logger.info(f"  🔍 Quarantäneverzeichnis:        {inspect_dir}")
        logger.info(f"✅ SORTIERUNG ERFOLGREICH: {len(created_folders)} Ordner insgesamt erstellt.")
        logger.info("=" * 70)

        return created_folders


