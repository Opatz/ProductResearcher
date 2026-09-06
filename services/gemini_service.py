import json
import re
import time
import logging
from pathlib import Path
from typing import Any, Optional, Dict, List, Union
from google import genai
from google.genai import types
from google.genai import errors

logger = logging.getLogger(__name__)


class GeminiService:
    """Service zur Kommunikation mit der Google Gemini API (Transkription, Vision, Prompt-Chaining)."""

    def __init__(self, api_key: Optional[str] = None, default_model: str = "gemini-3.5-flash-lite", config: Any = None):
        if config is not None and hasattr(config, "google"):
            api_key = api_key or config.google.api_key
            default_model = getattr(config.google, "model_name", default_model)
        if not api_key:
            raise ValueError(
                "Kein Google API Key angegeben. Bitte in config/config.ini eintragen oder GEMINI_API_KEY setzen."
            )
        self.api_key = api_key
        self.default_model = default_model
        self.fallback_models = ["gemini-2.5-pro", "gemini-3.7-flash", "gemini-2.5-flash"]
        self.client = genai.Client(api_key=self.api_key)
        logger.info(f"GeminiService initialisiert mit Standard-Modell '{self.default_model}'.")

    def _clean_and_parse_json(self, response_text: str) -> Any:
        """Sicheres Parsen von JSON-Antworten aus dem LLM (entfernt Markdown Code-Blöcke)."""
        text = response_text.strip()
        
        # Falls Markdown-Block vorhanden: ```json ... ``` oder ``` ... ```
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if json_match:
            text = json_match.group(1).strip()
        
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"Direktes JSON-Parsen fehlgeschlagen ({e}). Versuche Fallback-Bereinigung...")
            start_curly = text.find("{")
            start_bracket = text.find("[")
            
            if start_curly != -1 and (start_bracket == -1 or start_curly < start_bracket):
                end_curly = text.rfind("}")
                if end_curly != -1:
                    clean_str = text[start_curly:end_curly + 1]
                    return json.loads(clean_str)
            elif start_bracket != -1:
                end_bracket = text.rfind("]")
                if end_bracket != -1:
                    clean_str = text[start_bracket:end_bracket + 1]
                    return json.loads(clean_str)
                    
            logger.error(f"Konnte kein valides JSON aus Text extrahieren: {response_text}")
            raise

    def _generate_with_retry(
        self, 
        contents: Any, 
        config: Optional[types.GenerateContentConfig] = None,
        model_override: Optional[str] = None,
        max_retries: int = 5
    ) -> Any:
        """Führt API-Aufrufe mit intelligentem Retry und Backoff bei Quota-Limits (429/503) durch."""
        models_to_try = [model_override or self.default_model] + [m for m in self.fallback_models if m != (model_override or self.default_model)]
        
        last_error = None
        for model in models_to_try:
            for attempt in range(1, max_retries + 1):
                try:
                    logger.debug(f"Sende Anfrage an Modell '{model}' (Versuch {attempt}/{max_retries})...")
                    response = self.client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=config
                    )
                    # Kurze Pause für Rate-Limit-Schonung
                    time.sleep(2)
                    return response
                except (errors.APIError, errors.ServerError, errors.ClientError, Exception) as e:
                    last_error = e
                    err_msg = str(e)
                    is_transient = "503" in err_msg or "429" in err_msg or "UNAVAILABLE" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "high demand" in err_msg
                    
                    if is_transient and attempt < max_retries:
                        wait_time = max(7, attempt * 5)
                        logger.warning(f"Rate-Limit / Überlastung bei '{model}'. Warte {wait_time}s vor Retry {attempt+1}...")
                        time.sleep(wait_time)
                    else:
                        logger.warning(f"Modell '{model}' nicht verfügbar ({e}). Wechsle zum nächsten Modell...")
                        break
        
        logger.error(f"Alle Modelle und Retries fehlgeschlagen: {last_error}")
        raise last_error

    def transcribe_audio(self, audio_path: Path, language: str = "de", prompt_hint: Optional[str] = None) -> str:
        """
        Lädt die Audiodatei zu Gemini hoch und führt eine vollständige Transkription durch.
        """
        audio_path = Path(audio_path).resolve()
        if not audio_path.exists():
            raise FileNotFoundError(f"Audiodatei nicht gefunden: {audio_path}")

        logger.info(f"Lade Audio '{audio_path.name}' zur Transkription hoch...")
        uploaded_file = self.client.files.upload(file=str(audio_path))
        logger.info(f"Audio hochgeladen (File ID: {uploaded_file.name}). Warte auf Transkription...")

        prompt = (
            prompt_hint or 
            f"Transkribiere das gesprochene Audio vollständig und wortgetreu auf {language}. "
            "Gib ausschließlich das reine Transkript ohne zusätzliche Begrüßung oder Kommentare zurück."
        )

        try:
            response = self._generate_with_retry(
                contents=[uploaded_file, prompt]
            )
            transcription = (response.text or "").strip()
            logger.info("Transkription erfolgreich abgeschlossen.")
            return transcription
        finally:
            try:
                self.client.files.delete(name=uploaded_file.name)
            except Exception as e:
                logger.debug(f"Konnte temporäre Remote-Audiodatei nicht löschen: {e}")

    def extract_id_from_video(self, trimmed_video_path: Path, prompt: str) -> Dict[str, Any]:
        """
        Analysiert den 5-Sekunden-Videoausschnitt visuell und extrahiert sichtbare IDs/Zahlen.
        """
        trimmed_video_path = Path(trimmed_video_path).resolve()
        if not trimmed_video_path.exists():
            raise FileNotFoundError(f"Videoausschnitt nicht gefunden: {trimmed_video_path}")

        logger.info(f"Lade Video-Vorspann '{trimmed_video_path.name}' für ID-Erkennung hoch...")
        uploaded_file = self.client.files.upload(file=str(trimmed_video_path))
        
        time.sleep(2)

        try:
            response = self._generate_with_retry(
                contents=[uploaded_file, prompt]
            )
            raw_text = response.text or ""
            parsed_json = self._clean_and_parse_json(raw_text)
            logger.info(f"Visuelle ID-Erkennung erfolgreich: {parsed_json.get('detected_id') if isinstance(parsed_json, dict) else parsed_json}")
            return {
                "raw_text": raw_text,
                "parsed_json": parsed_json
            }
        finally:
            try:
                self.client.files.delete(name=uploaded_file.name)
            except Exception as e:
                logger.debug(f"Konnte temporäre Remote-Videodatei nicht löschen: {e}")

    def execute_text_prompt(
        self, 
        prompt_text: str, 
        images: Optional[List[Union[str, Path]]] = None,
        expect_json: bool = True, 
        model_override: Optional[str] = None,
        enable_google_search: bool = False
    ) -> Dict[str, Any]:
        """
        Sendet einen Textprompt (optional zusammen mit Bildern) an das LLM mit automatischem Retry
        und optionaler Live-Websuche (Google Search Grounding).
        """
        tools = [{"google_search": {}}] if enable_google_search else None
        
        # Bei aktiviertem Google Search Tool wird response_mime_type weggelassen (JSON wird via Prompt gefordert und durch _clean_and_parse_json geparst)
        config = types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json" if (expect_json and not enable_google_search) else None,
            tools=tools
        )
        
        uploaded_image_files = []
        contents = []

        if images:
            logger.info(f"Lade {len(images)} Bild(er) für multimodalen Prompt hoch...")
            for img in images:
                img_path = Path(img).resolve()
                if img_path.exists():
                    try:
                        up_img = self.client.files.upload(file=str(img_path))
                        uploaded_image_files.append(up_img)
                        contents.append(up_img)
                        logger.debug(f"Bild hochgeladen: {img_path.name}")
                    except Exception as e:
                        logger.warning(f"Konnte Bild '{img_path.name}' nicht hochladen: {e}")

        contents.append(prompt_text)

        try:
            response = self._generate_with_retry(
                contents=contents,
                config=config,
                model_override=model_override
            )
            raw_text = response.text or ""
            parsed = self._clean_and_parse_json(raw_text) if expect_json else raw_text
            return {
                "raw_text": raw_text,
                "parsed_json": parsed
            }
        finally:
            # Temporäre hochgeladene Bilder remote wieder löschen
            for up_f in uploaded_image_files:
                try:
                    self.client.files.delete(name=up_f.name)
                except Exception as e:
                    logger.debug(f"Konnte Remote-Bild {up_f.name} nicht löschen: {e}")
