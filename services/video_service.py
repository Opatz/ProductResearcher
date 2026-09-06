import logging
import subprocess
from pathlib import Path
from typing import Optional
import imageio_ffmpeg

logger = logging.getLogger(__name__)


class VideoService:
    """Service zur Audio-Extraktion, Video-Schnitt und Medienverarbeitung."""

    def __init__(self):
        self.ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        logger.info(f"VideoService initialisiert mit FFmpeg Executable: {self.ffmpeg_exe}")

    def extract_audio(self, video_path: Path, output_audio_path: Path) -> Path:
        """
        Extrahiert die Audiospur aus einem Video (z.B. als MP3/WAV).
        Nutzt FFmpeg direkt über imageio_ffmpeg für höchste Geschwindigkeit und Stabilität.
        """
        video_path = Path(video_path).resolve()
        output_audio_path = Path(output_audio_path).resolve()
        output_audio_path.parent.mkdir(parents=True, exist_ok=True)

        if not video_path.exists():
            raise FileNotFoundError(f"Video-Datei nicht gefunden: {video_path}")

        logger.info(f"Extrahiere Audio von '{video_path.name}' -> '{output_audio_path.name}'...")

        # FFmpeg Befehl zum Extrahieren der Audiospur
        cmd = [
            self.ffmpeg_exe,
            "-y",                     # Vorhandene Datei überschreiben
            "-i", str(video_path),    # Input
            "-vn",                    # Kein Video
            "-acodec", "libmp3lame" if output_audio_path.suffix.lower() == ".mp3" else "pcm_s16le",
            "-q:a", "2",              # Gute Audioqualität
            str(output_audio_path)
        ]

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logger.error(f"FFmpeg Audio-Extraktion fehlgeschlagen: {result.stderr}")
            raise RuntimeError(f"Fehler bei der Audio-Extraktion: {result.stderr}")

        logger.info(f"Audiospur erfolgreich exportiert: {output_audio_path}")
        return output_audio_path

    def trim_video(self, video_path: Path, output_video_path: Path, duration_sec: float = 5.0) -> Path:
        """
        Schneidet die ersten N Sekunden eines Videos heraus.
        """
        video_path = Path(video_path).resolve()
        output_video_path = Path(output_video_path).resolve()
        output_video_path.parent.mkdir(parents=True, exist_ok=True)

        if not video_path.exists():
            raise FileNotFoundError(f"Video-Datei nicht gefunden: {video_path}")

        logger.info(f"Schneide erste {duration_sec}s von '{video_path.name}' -> '{output_video_path.name}'...")

        cmd = [
            self.ffmpeg_exe,
            "-y",
            "-ss", "00:00:00",
            "-i", str(video_path),
            "-t", str(duration_sec),
            "-c", "copy",             # Schnelles Schneiden ohne Neukodierung
            str(output_video_path)
        ]

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        # Falls Stream-Copy fehlschlägt (z.B. wegen Keyframe-Versatz), mit Re-Encoding versuchen:
        if result.returncode != 0:
            logger.warning("Schneller Stream-Copy fehlgeschlagen, versuche Re-Encoding...")
            cmd_reencode = [
                self.ffmpeg_exe,
                "-y",
                "-ss", "00:00:00",
                "-i", str(video_path),
                "-t", str(duration_sec),
                "-c:v", "libx264",
                "-c:a", "aac",
                str(output_video_path)
            ]
            result_re = subprocess.run(cmd_reencode, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result_re.returncode != 0:
                logger.error(f"FFmpeg Schnitt fehlgeschlagen: {result_re.stderr}")
                raise RuntimeError(f"Fehler beim Video-Schnitt: {result_re.stderr}")

        logger.info(f"Video-Schnitt erfolgreich erstellt: {output_video_path}")
        return output_video_path
