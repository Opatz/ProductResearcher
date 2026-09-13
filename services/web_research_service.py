import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pipeline.models import (
    PriceType,
    MatchGenauigkeit,
    RechercheStatus,
    TargetWebsiteSuggestion,
    ReferenceListing,
    VisualAnalysisResult,
    RetailPriceSynthesis
)
from services.prompt_manager import PromptManager
from services.appraiser_service import AppraiserService

logger = logging.getLogger(__name__)

# Standard-Empfehlungen für Zielplattformen nach Kategorien
DEFAULT_TARGET_SITES: List[Dict[str, str]] = [
    {
        "website_name": "eBay (Beendete Angebote)",
        "target_url": "https://www.ebay.de/sch/i.html?LH_Sold=1&LH_Complete=1",
        "suchbegriff": "{titel}",
        "plattform_typ": "marktplatz",
        "begruendung": "Primär beendete Verkäufe (LH_Sold=1); Fallback auf aktive Angebote bei 0 Treffern"
    },
    {
        "website_name": "Kleinanzeigen",
        "target_url": "https://www.kleinanzeigen.de",
        "suchbegriff": "{titel}",
        "plattform_typ": "kleinanzeigen",
        "begruendung": "Lokale Gebrauchtpreise und Privatangebote"
    },
    {
        "website_name": "Pamono",
        "target_url": "https://www.pamono.de",
        "suchbegriff": "{hersteller} {titel}",
        "plattform_typ": "haendlerplattform",
        "begruendung": "Internationaler Vintage- und Designermöbel-Handel (Asking Prices)"
    },
    {
        "website_name": "1stDibs",
        "target_url": "https://www.1stdibs.com",
        "suchbegriff": "{hersteller} {titel}",
        "plattform_typ": "haendlerplattform",
        "begruendung": "Gehobener Galerie- und Antiquitätenmarkt"
    },
    {
        "website_name": "Catawiki",
        "target_url": "https://www.catawiki.com",
        "suchbegriff": "{titel}",
        "plattform_typ": "auktionshaus",
        "begruendung": "Europäische Kuratierte Online-Auktionen mit Bieterhistorie"
    },
    {
        "website_name": "Etsy",
        "target_url": "https://www.etsy.com",
        "suchbegriff": "{titel} vintage",
        "plattform_typ": "marktplatz",
        "begruendung": "Vintage- und Handwerks-Angebote mit Festpreisen"
    },
    {
        "website_name": "LiveAuctioneers",
        "target_url": "https://www.liveauctioneers.com",
        "suchbegriff": "{hersteller} {titel}",
        "plattform_typ": "auktionshaus",
        "begruendung": "Historische Auktionszuschläge und Hammerpreise"
    },
    {
        "website_name": "Dorotheum",
        "target_url": "https://www.dorotheum.com",
        "suchbegriff": "{titel}",
        "plattform_typ": "auktionshaus",
        "begruendung": "Führendes mitteleuropäisches Auktionshaus für Kunst & Antiquitäten"
    },
    {
        "website_name": "Invaluable",
        "target_url": "https://www.invaluable.com",
        "suchbegriff": "{titel}",
        "plattform_typ": "auktionsarchiv",
        "begruendung": "Archiv weltweiter Auktionsergebnisse und Preisdatenbank"
    },
    {
        "website_name": "Barnebys",
        "target_url": "https://www.barnebys.de",
        "suchbegriff": "{titel}",
        "plattform_typ": "meta_suchmaschine",
        "begruendung": "Meta-Suchmaschine für Auktionshäuser und Galerien"
    }
]


class WebResearchService:
    """
    Entkoppelte Zwei-Phasen-Recherche-Engine für visuelle Objektanalyse und Webpreise.
    
    Phase 1: Visuelle Objektanalyse & Ableitung von 10 Ziel-Webseiten.
    Phase 2: 10 unabhängige, parallele Plattform-Recherche-Aufrufe mit ThreadPoolExecutor.
    """

    def __init__(
        self,
        gemini_service: Optional[Any] = None,
        prompts_dir: Optional[Path] = None,
        context_dir: Optional[Path] = None,
        prompt_manager: Optional[PromptManager] = None,
        max_workers: int = 5,
        timeout_sec: float = 30.0
    ):
        self.gemini_service = gemini_service
        self.max_workers = max_workers
        self.timeout_sec = timeout_sec

        if prompt_manager:
            self.prompt_manager = prompt_manager
        elif prompts_dir and Path(prompts_dir).exists():
            self.prompt_manager = PromptManager(prompts_dir=Path(prompts_dir), context_dir=context_dir)
        else:
            self.prompt_manager = None

        self.appraiser_service = AppraiserService(
            gemini_service=self.gemini_service,
            prompts_dir=prompts_dir,
            context_dir=context_dir,
            prompt_manager=self.prompt_manager
        )

    def synthesize_retail_valuation(
        self,
        catalog_data: Dict[str, Any],
        reference_listings: List[Union[ReferenceListing, Dict[str, Any]]],
        enable_google_search: bool = False
    ) -> RetailPriceSynthesis:
        """
        Führt Stage 3 aus: Appraiser LLM Reconciliation & Valuation Synthesis.
        Delegiert an den dedizierten AppraiserService.
        """
        return self.appraiser_service.synthesize_valuation(
            catalog_data=catalog_data,
            reference_listings=reference_listings,
            enable_google_search=enable_google_search
        )


    # =========================================================================
    # Phase 1: Visuelle Analyse & Ziel-Webseiten
    # =========================================================================

    def parse_visual_analysis_payload(self, data: Dict[str, Any], ensure_ten: bool = False) -> VisualAnalysisResult:
        """Parst und validiert das JSON-Payload aus Phase 1 in ein VisualAnalysisResult."""
        if not isinstance(data, dict):
            data = {}

        raw_targets = data.get("ziel_webseiten", [])
        parsed_targets: List[TargetWebsiteSuggestion] = []

        if isinstance(raw_targets, list):
            for t in raw_targets:
                if isinstance(t, dict) and t.get("website_name"):
                    parsed_targets.append(
                        TargetWebsiteSuggestion(
                            website_name=str(t.get("website_name", "")).strip(),
                            target_url=t.get("target_url"),
                            suchbegriff=t.get("suchbegriff"),
                            plattform_typ=t.get("plattform_typ"),
                            begruendung=t.get("begruendung")
                        )
                    )
                elif isinstance(t, str) and t.strip():
                    parsed_targets.append(
                        TargetWebsiteSuggestion(
                            website_name=t.strip(),
                            suchbegriff=data.get("titel", "")
                        )
                    )

        if ensure_ten:
            # Bei Bedarf mit bewährten Defaults auf genau 10 Zielseiten auffüllen
            item_title = str(data.get("titel", "") or "Antiquität").strip()
            maker = str(data.get("hersteller_oder_marke", "") or "").strip()

            existing_names = {t.website_name.lower() for t in parsed_targets}
            for default_spec in DEFAULT_TARGET_SITES:
                if len(parsed_targets) >= 10:
                    break
                d_name = default_spec["website_name"]
                base_site = d_name.split()[0].lower()
                if any(base_site in name for name in existing_names):
                    continue
                
                suchbegriff = default_spec["suchbegriff"].format(
                    titel=item_title,
                    hersteller=maker or item_title
                ).strip()

                parsed_targets.append(
                    TargetWebsiteSuggestion(
                        website_name=d_name,
                        target_url=default_spec["target_url"],
                        suchbegriff=suchbegriff,
                        plattform_typ=default_spec["plattform_typ"],
                        begruendung=default_spec["begruendung"]
                    )
                )
                existing_names.add(d_name.lower())

        return VisualAnalysisResult(
            id=str(data.get("id", "")) or None,
            titel=str(data.get("titel", "")),
            kategorie=str(data.get("kategorie", "")),
            produktbeschreibung=str(data.get("produktbeschreibung", "")),
            hersteller_oder_marke=data.get("hersteller_oder_marke"),
            modell_oder_epoche=str(data.get("modell_oder_epoche", "")),
            geschaetztes_jahr_oder_epoche=str(data.get("geschaetztes_jahr_oder_epoche", "")),
            authentizitaet=str(data.get("authentizitaet", "unklar")),
            erkannte_nummern_oder_stempel=data.get("erkannte_nummern_oder_stempel") or [],
            physische_merkmale=data.get("physische_merkmale") or {},
            zustandsbericht=data.get("zustandsbericht") or {},
            ziel_webseiten=parsed_targets[:10] if ensure_ten else parsed_targets
        )

    def analyze_visual_and_suggest_targets(
        self,
        video_filename: str,
        item_id: str,
        image_paths: List[Path],
        step1_json: Optional[Dict[str, Any]] = None,
        zusatz_kontext: str = "",
        enable_google_search: bool = True
    ) -> VisualAnalysisResult:
        """
        Führt Phase 1 aus: Visuelle Inspektion aller Objektbilder, Maße, Schäden,
        Verkaufsbeschreibung und Ermittlung von 10 Ziel-Webseiten.
        """
        logger.info(f"Starte Phase 1 (Visuelle Analyse & 10 Ziel-Webseiten) für Item '{item_id}'...")

        if not self.gemini_service:
            logger.info("Kein GeminiService vorhanden -> Generiere Mock-Ergebnis für Phase 1.")
            return self.generate_mock_visual_analysis(item_id=item_id, video_filename=video_filename, step1_json=step1_json)

        # Prompt formatieren
        step1_str = json.dumps(step1_json or {}, ensure_ascii=False, indent=2)
        if self.prompt_manager:
            try:
                prompt_text = self.prompt_manager.format_prompt(
                    "prompt_2_visual_analysis.txt",
                    id=item_id,
                    video_filename=video_filename,
                    step1_json=step1_str,
                    zusatz_kontext=zusatz_kontext
                )
            except Exception as e:
                logger.warning(f"Konnte prompt_2_visual_analysis.txt nicht laden ({e}), nutze Fallback-Prompt.")
                prompt_text = f"Analysiere die Bilder für Artikel {item_id}:\n{step1_str}"
        else:
            prompt_text = f"Analysiere die Bilder für Artikel {item_id}:\n{step1_str}"

        try:
            result = self.gemini_service.execute_text_prompt(
                prompt_text=prompt_text,
                images=image_paths,
                expect_json=True,
                enable_google_search=enable_google_search
            )
            parsed_json = result.get("parsed_json") or {}
            visual_result = self.parse_visual_analysis_payload(parsed_json, ensure_ten=True)
            visual_result.id = item_id
            logger.info(f"Phase 1 erfolgreich abgeschlossen: '{visual_result.titel}', {len(visual_result.ziel_webseiten)} Zielseiten ermittelt.")
            return visual_result
        except Exception as e:
            logger.error(f"Fehler in Phase 1 bei visueller Analyse: {e}")
            return self.generate_mock_visual_analysis(item_id=item_id, video_filename=video_filename, step1_json=step1_json)

    # =========================================================================
    # Phase 2: 10 Unabhängige Plattform-Recherche-Prompts
    # =========================================================================

    def research_single_site(
        self,
        target: Union[Dict[str, Any], TargetWebsiteSuggestion],
        object_summary: Dict[str, Any],
        enable_google_search: bool = True
    ) -> ReferenceListing:
        """
        Führt EINE dedizierte, unabhängige Recherche-Abfrage für eine einzelne Ziel-Webseite durch.
        Fängt alle Fehler (Netzwerk, HTTP 403/Block, Timeout, Parsing) ab und liefert
        immer ein valides ReferenceListing mit passendem RechercheStatus.
        """
        if isinstance(target, TargetWebsiteSuggestion):
            site_name = target.website_name
            target_url = target.target_url or ""
            suchbegriff = target.suchbegriff or ""
        elif isinstance(target, dict):
            site_name = str(target.get("website_name", "")).strip() or "Unbekannte Seite"
            target_url = str(target.get("target_url", "") or "").strip()
            suchbegriff = str(target.get("suchbegriff", "") or "").strip()
        else:
            site_name = "Unbekannte Seite"
            target_url = ""
            suchbegriff = ""

        # Vorbelegung für Fallback/Fehlerfall
        fallback_listing = ReferenceListing(
            website_name=site_name,
            listing_titel="",
            preis_eur=None,
            urspruengliche_waehrung="EUR",
            preis_typ=PriceType.UNBEKANNT,
            match_genauigkeit=MatchGenauigkeit.KEIN_TREFFER,
            zustand_referenz="",
            quell_url=target_url,
            recherche_status=RechercheStatus.NICHT_VERFUEGBAR
        )

        if not self.gemini_service:
            # Mock-Modus
            return self._create_mock_single_listing(site_name, target_url, object_summary)

        # Prompt zusammenstellen
        obj_titel = str(object_summary.get("titel", "") or "Antiquität").strip()
        maker = str(object_summary.get("hersteller_oder_marke", "") or "").strip()
        epoche = str(object_summary.get("modell_oder_epoche", "") or "").strip()
        kategorie = str(object_summary.get("kategorie", "") or "").strip()
        material = str(object_summary.get("material", "") or "").strip()
        stempel = str(object_summary.get("erkannte_nummern_oder_stempel", "") or "").strip()
        zustand = str(object_summary.get("zustand", "") or "").strip()

        if not suchbegriff:
            suchbegriff = f"{maker} {obj_titel}".strip()

        if self.prompt_manager:
            try:
                prompt_text = self.prompt_manager.format_prompt(
                    "prompt_2_site_research.txt",
                    target_site_name=site_name,
                    target_url=target_url,
                    suchbegriff=suchbegriff,
                    object_titel=obj_titel,
                    kategorie=kategorie,
                    hersteller=maker,
                    epoche=epoche,
                    stempel=stempel,
                    material=material,
                    zustand=zustand,
                    page_content=""
                )
            except Exception as e:
                logger.debug(f"Konnte prompt_2_site_research.txt nicht laden: {e}")
                prompt_text = (
                    f"Recherchiere auf {site_name} (URL: {target_url}) nach: {suchbegriff}.\n"
                    f"Objekt: {obj_titel}, {kategorie}, {maker}, {epoche}. Gib JSON mit ReferenceListing zurück."
                )
        else:
            prompt_text = (
                f"Recherchiere auf {site_name} (URL: {target_url}) nach: {suchbegriff}.\n"
                f"Objekt: {obj_titel}, {kategorie}, {maker}, {epoche}. Gib JSON mit ReferenceListing zurück."
            )

        try:
            resp = self.gemini_service.execute_text_prompt(
                prompt_text=prompt_text,
                images=None,
                expect_json=True,
                enable_google_search=enable_google_search
            )
            parsed = resp.get("parsed_json") or {}
            if not isinstance(parsed, dict):
                return fallback_listing

            # Status ermitteln
            raw_status = parsed.get("recherche_status")
            status = RechercheStatus.from_string(raw_status)
            if not raw_status:
                if parsed.get("preis_eur") is not None:
                    status = RechercheStatus.ERFOLGREICH
                else:
                    status = RechercheStatus.KEIN_PREIS_GEFUNDEN

            # Preis parsen
            price_val = parsed.get("preis_eur")
            price_type = PriceType.from_string(parsed.get("preis_typ"))
            match_acc = MatchGenauigkeit.from_string(parsed.get("match_genauigkeit"))
            
            return ReferenceListing(
                website_name=str(parsed.get("website_name") or site_name).strip(),
                listing_titel=str(parsed.get("listing_titel", "")).strip(),
                preis_eur=price_val,
                urspruengliche_waehrung=str(parsed.get("urspruengliche_waehrung", "EUR")).strip() or "EUR",
                preis_typ=price_type,
                match_genauigkeit=match_acc,
                zustand_referenz=str(parsed.get("zustand_referenz", "")).strip(),
                quell_url=str(parsed.get("quell_url") or target_url).strip(),
                recherche_status=status,
                raw_details=parsed
            )

        except Exception as e:
            err_msg = str(e).lower()
            logger.warning(f"Fehler bei Einzelrecherche für '{site_name}': {e}")
            if "403" in err_msg or "block" in err_msg or "captcha" in err_msg or "forbidden" in err_msg:
                fallback_listing.recherche_status = RechercheStatus.ZUGRIFF_BLOCKIERT
            else:
                fallback_listing.recherche_status = RechercheStatus.NICHT_VERFUEGBAR
            return fallback_listing

    def research_all_sites_parallel(
        self,
        targets: List[Union[Dict[str, Any], TargetWebsiteSuggestion]],
        object_summary: Dict[str, Any],
        max_workers: Optional[int] = None,
        timeout: Optional[float] = None
    ) -> List[ReferenceListing]:
        """
        Führt alle 10 unabhängigen Plattform-Recherche-Prompts nebenläufig über einen ThreadPool aus.
        Gewährleistet konfigurierbare Timeouts und liefert alle ReferenceListing-Ergebnisse zurück.
        """
        workers = max_workers or self.max_workers
        effective_timeout = timeout or self.timeout_sec

        logger.info(f"Starte parallele Webrecherche für {len(targets)} Zielplattformen (Workers: {workers}, Timeout: {effective_timeout}s)...")
        results: List[ReferenceListing] = []

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_target = {
                executor.submit(self.research_single_site, t, object_summary): t
                for t in targets
            }

            for future in future_to_target:
                t = future_to_target[future]
                site_name = t.website_name if isinstance(t, TargetWebsiteSuggestion) else str(t.get("website_name", "Unbekannt"))
                target_url = t.target_url if isinstance(t, TargetWebsiteSuggestion) else str(t.get("target_url", "") or "")
                try:
                    listing = future.result(timeout=effective_timeout)
                    results.append(listing)
                except FuturesTimeoutError:
                    logger.warning(f"Timeout ({effective_timeout}s) für Plattform '{site_name}' überschritten.")
                    results.append(
                        ReferenceListing(
                            website_name=site_name,
                            listing_titel="Recherche-Timeout",
                            preis_eur=None,
                            urspruengliche_waehrung="EUR",
                            preis_typ=PriceType.UNBEKANNT,
                            match_genauigkeit=MatchGenauigkeit.KEIN_TREFFER,
                            zustand_referenz="",
                            quell_url=target_url,
                            recherche_status=RechercheStatus.NICHT_VERFUEGBAR
                        )
                    )
                except Exception as e:
                    logger.warning(f"Unerwarteter Fehler bei Plattform '{site_name}': {e}")
                    results.append(
                        ReferenceListing(
                            website_name=site_name,
                            listing_titel="",
                            preis_eur=None,
                            urspruengliche_waehrung="EUR",
                            preis_typ=PriceType.UNBEKANNT,
                            match_genauigkeit=MatchGenauigkeit.KEIN_TREFFER,
                            zustand_referenz="",
                            quell_url=target_url,
                            recherche_status=RechercheStatus.NICHT_VERFUEGBAR
                        )
                    )

        logger.info(f"Parallele Webrecherche abgeschlossen: {len(results)}/{len(targets)} Plattformen ausgewertet.")
        return results

    # =========================================================================
    # Mock- und Test-Generatoren
    # =========================================================================

    def _create_mock_single_listing(
        self,
        site_name: str,
        target_url: str,
        object_summary: Dict[str, Any]
    ) -> ReferenceListing:
        """Erzeugt ein einzelnes konsistentes Mock-Listing für eine Zielseite."""
        base_price = float(object_summary.get("geschaetzter_preis") or object_summary.get("aktueller_ist_wert_eur") or 300.0)
        s_lower = site_name.lower()

        if "ebay" in s_lower:
            return ReferenceListing(
                website_name=site_name,
                listing_titel=f"{object_summary.get('titel', 'Artikel')} - Verkauft",
                preis_eur=round(base_price * 0.95, 2),
                urspruengliche_waehrung="EUR",
                preis_typ=PriceType.REALISIERTER_VERKAUFSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                zustand_referenz="Gebraucht mit typischen Altersspuren",
                quell_url="https://www.ebay.de/itm/1122334455",
                recherche_status=RechercheStatus.ERFOLGREICH
            )
        elif "kleinanzeigen" in s_lower:
            return ReferenceListing(
                website_name=site_name,
                listing_titel=f"{object_summary.get('titel', 'Artikel')} Vintage",
                preis_eur=round(base_price * 0.85, 2),
                urspruengliche_waehrung="EUR",
                preis_typ=PriceType.ANGEBOTSPREIS,
                match_genauigkeit=MatchGenauigkeit.MODELLVARIANTE,
                zustand_referenz="Gut erhalten, Selbstabholung",
                quell_url="https://www.kleinanzeigen.de/s-anzeige/123456",
                recherche_status=RechercheStatus.ERFOLGREICH
            )
        elif "pamono" in s_lower or "1stdibs" in s_lower:
            return ReferenceListing(
                website_name=site_name,
                listing_titel=f"{object_summary.get('titel', 'Artikel')} Galerie-Zustand",
                preis_eur=round(base_price * 2.2, 2),
                urspruengliche_waehrung="EUR",
                preis_typ=PriceType.ANGEBOTSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                zustand_referenz="Hervorragend restauriert",
                quell_url="https://www.pamono.de/items/998877",
                recherche_status=RechercheStatus.ERFOLGREICH
            )
        elif "catawiki" in s_lower:
            return ReferenceListing(
                website_name=site_name,
                listing_titel=f"{object_summary.get('titel', 'Artikel')} Auktionslos",
                preis_eur=round(base_price * 1.05, 2),
                urspruengliche_waehrung="EUR",
                preis_typ=PriceType.AUKTIONSGEBOT,
                match_genauigkeit=MatchGenauigkeit.MODELLVARIANTE,
                zustand_referenz="Altersgemäße Patina",
                quell_url="https://www.catawiki.com/l/556677",
                recherche_status=RechercheStatus.ERFOLGREICH
            )
        elif "dorotheum" in s_lower or "liveauctioneers" in s_lower:
            return ReferenceListing(
                website_name=site_name,
                listing_titel=f"{object_summary.get('titel', 'Artikel')} Hammerpreis",
                preis_eur=round(base_price * 1.1, 2),
                urspruengliche_waehrung="EUR",
                preis_typ=PriceType.REALISIERTER_VERKAUFSPREIS,
                match_genauigkeit=MatchGenauigkeit.EXAKTER_TREFFER,
                zustand_referenz="Guter Originalzustand",
                quell_url="https://www.dorotheum.com/lot/123",
                recherche_status=RechercheStatus.ERFOLGREICH
            )
        elif "invaluable" in s_lower or "barnebys" in s_lower:
            return ReferenceListing(
                website_name=site_name,
                listing_titel=f"{object_summary.get('titel', 'Artikel')}",
                preis_eur=None,
                urspruengliche_waehrung="EUR",
                preis_typ=PriceType.UNBEKANNT,
                match_genauigkeit=MatchGenauigkeit.KEIN_TREFFER,
                zustand_referenz="",
                quell_url=target_url or "https://www.invaluable.com",
                recherche_status=RechercheStatus.KEIN_PREIS_GEFUNDEN
            )
        else:
            return ReferenceListing(
                website_name=site_name,
                listing_titel="",
                preis_eur=None,
                urspruengliche_waehrung="EUR",
                preis_typ=PriceType.UNBEKANNT,
                match_genauigkeit=MatchGenauigkeit.KEIN_TREFFER,
                zustand_referenz="",
                quell_url=target_url,
                recherche_status=RechercheStatus.ZUGRIFF_BLOCKIERT
            )

    def generate_mock_visual_analysis(
        self,
        item_id: str,
        video_filename: str,
        step1_json: Optional[Dict[str, Any]] = None
    ) -> VisualAnalysisResult:
        """Erzeugt ein realistisches Mock-Ergebnis für Phase 1."""
        step1 = step1_json or {}
        title = step1.get("titel") or "Vintage-Designertisch Mid-Century Teak"
        maker = step1.get("hersteller_oder_marke") or "Dänisches Manufakturdesign"
        era = step1.get("modell_oder_epoche") or "Mid-Century 1960er"
        stamps = step1.get("erkannte_nummern_oder_stempel") or [item_id or "ARTIKEL-01", "Made in Denmark"]

        description = (
            f"Authentischer {title} ({era}), zugeschrieben {maker}. "
            "Massive Ausführung in Teakholz mit zeittypischer organischer Linienführung. "
            "Sichtbare oberflächliche Gebrauchsspuren und leichte Kratzer auf der Oberseite, "
            "Konstruktion stabil und standfest. Ideal für Liebhaber skandinavischen Mid-Century-Designs."
        )

        mock_payload = {
            "id": item_id,
            "titel": title,
            "kategorie": step1.get("kategorie") or "Möbel",
            "produktbeschreibung": description,
            "hersteller_oder_marke": maker,
            "modell_oder_epoche": era,
            "geschaetztes_jahr_oder_epoche": "ca. 1962–1965",
            "authentizitaet": "original",
            "erkannte_nummern_oder_stempel": stamps,
            "physische_merkmale": {
                "material": step1.get("material") or "Massivholz Teak",
                "farbe": step1.get("farbe") or "Braun / Teak Natur",
                "laenge_cm": step1.get("laenge_cm", 120.0),
                "breite_cm": step1.get("breite_cm", 80.0),
                "hoehe_cm": step1.get("hoehe_cm", 75.0),
                "durchmesser_cm": step1.get("durchmesser_cm"),
                "gewicht_kg": step1.get("gewicht_kg", 22.0),
                "logistik_kategorie": "sperrgut"
            },
            "zustandsbericht": {
                "zustand": "gebraucht",
                "maengel": step1.get("maengel") or [
                    "Kratzer auf der Oberseite ca. 5 cm",
                    "Leichte Wasserflecken am Rand"
                ],
                "fehlende_teile": [],
                "empfohlene_massnahme": "Oberflächenpolitur und Teaköl-Pflege"
            },
            "ziel_webseiten": DEFAULT_TARGET_SITES
        }
        return self.parse_visual_analysis_payload(mock_payload, ensure_ten=True)

    def generate_mock_research(
        self,
        targets: Optional[List[Dict[str, Any]]] = None,
        object_summary: Optional[Dict[str, Any]] = None
    ) -> List[ReferenceListing]:
        """
        Erzeugt genau 10 vielfältige, realitätsnahe Mock-Referenz-Listings für Tests
        und den Pipeline-Mock-Modus.
        """
        summary = object_summary or {"titel": "Vintage Teak Tisch", "geschaetzter_preis": 300.0}
        site_targets = targets or DEFAULT_TARGET_SITES

        listings: List[ReferenceListing] = []
        for t in site_targets[:10]:
            name = t.get("website_name") if isinstance(t, dict) else getattr(t, "website_name", "")
            url = t.get("target_url") if isinstance(t, dict) else getattr(t, "target_url", "")
            listings.append(self._create_mock_single_listing(name, url or "", summary))

        return listings
