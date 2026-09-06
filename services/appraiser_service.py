import json
import logging
import re
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pipeline.models import (
    PriceType,
    MatchGenauigkeit,
    RechercheStatus,
    ReferenceListing,
    RetailPriceSynthesis,
)
from services.prompt_manager import PromptManager

logger = logging.getLogger(__name__)


class AppraiserService:
    """
    Chef-Gutachter & Preissynthese-Engine (Stage 3).
    Reconciles disparate platforms, prioritizes Realized Prices over Asking Prices,
    weeds out outliers, applies calibrated condition discounts, and synthesizes
    an authoritative retail valuation while preserving catalog attributes.
    """

    def __init__(
        self,
        gemini_service: Optional[Any] = None,
        prompts_dir: Optional[Path] = None,
        context_dir: Optional[Path] = None,
        prompt_manager: Optional[PromptManager] = None,
    ):
        self.gemini_service = gemini_service
        if prompt_manager:
            self.prompt_manager = prompt_manager
        elif prompts_dir and Path(prompts_dir).exists():
            self.prompt_manager = PromptManager(prompts_dir=Path(prompts_dir), context_dir=context_dir)
        else:
            self.prompt_manager = None

    def calculate_deterministic_baseline(
        self,
        catalog_data: Dict[str, Any],
        reference_listings: List[Union[ReferenceListing, Dict[str, Any]]]
    ) -> RetailPriceSynthesis:
        """
        Berechnet deterministisch die Schlichtung, Ausreißerbereinigung,
        statistischen Median und Mängelabschläge für Mock-Modus und Offline-Fallback.
        """
        # Normalisiere Listings zu ReferenceListing Objekten
        normalized_listings: List[ReferenceListing] = []
        for item in reference_listings:
            if isinstance(item, ReferenceListing):
                normalized_listings.append(item)
            elif isinstance(item, dict):
                try:
                    normalized_listings.append(ReferenceListing(**item))
                except Exception:
                    pass

        # 1. Filtere valide und relevante Listings
        valid_listings: List[ReferenceListing] = []
        excluded_listings: List[Dict[str, Any]] = []
        repro_pattern = re.compile(r"\b(repro|reproduktion|nachbildung|kopie|fake|replica)\b", re.IGNORECASE)

        for listing in normalized_listings:
            # Unbeantwortete / blockierte / unbepreiste Seiten
            if listing.recherche_status != RechercheStatus.ERFOLGREICH or listing.preis_eur is None or listing.preis_eur <= 0:
                excluded_listings.append({
                    "website_name": listing.website_name,
                    "grund": f"Kein valider Preis gefunden (Status: {listing.recherche_status.value})"
                })
                continue

            # Irrelevante Mismatches
            if listing.match_genauigkeit == MatchGenauigkeit.KEIN_TREFFER:
                excluded_listings.append({
                    "website_name": listing.website_name,
                    "preis_eur": listing.preis_eur,
                    "grund": "Kein relevanter Modelltreffer (kein_treffer)"
                })
                continue

            # Ausschluss von Reproduktionen / Nachbildungen
            combined_text = f"{listing.listing_titel or ''} {listing.zustand_referenz or ''}"
            if repro_pattern.search(combined_text):
                excluded_listings.append({
                    "website_name": listing.website_name,
                    "preis_eur": listing.preis_eur,
                    "grund": f"Ausschluss wegen Nachbildung/Reproduktion ('{listing.listing_titel}')"
                })
                continue

            valid_listings.append(listing)

        # Statistische Kennzahlen über alle validen Treffer
        valid_prices = [l.preis_eur for l in valid_listings if l.preis_eur is not None]
        anzahl_gefundene_preise = len(valid_prices)

        if valid_prices:
            median_web_preis = float(statistics.median(valid_prices))
        else:
            # Fallback auf Schätzpreis aus Katalog oder Schritt 1
            fallback_price = float(
                catalog_data.get("geschaetzter_preis")
                or catalog_data.get("aktueller_ist_wert_eur")
                or 300.0
            )
            median_web_preis = fallback_price

        # 2. Plattform-Reconciliation & Ausreißer-Erkennung
        # Gruppierung nach Preistypen
        realized_listings = [l for l in valid_listings if l.preis_typ == PriceType.REALISIERTER_VERKAUFSPREIS]
        asking_listings = [l for l in valid_listings if l.preis_typ == PriceType.ANGEBOTSPREIS]
        bid_listings = [l for l in valid_listings if l.preis_typ == PriceType.AUKTIONSGEBOT]

        outlier_notes: List[str] = []
        adjusted_prices: List[float] = []

        # Prüfe Händler-Plattformen und spekulative Ausreißer (z.B. Pamono, 1stDibs)
        for l in valid_listings:
            p = l.preis_eur or 0.0
            site_low = l.website_name.lower()
            is_dealer_gallery = "pamono" in site_low or "1stdibs" in site_low

            # Wenn es sich um eine Galerie handelt oder der Preis signifikant über/unter dem Median liegt
            if is_dealer_gallery:
                haircut = 0.50
                adjusted_p = round(p * haircut, 2)
                outlier_notes.append(
                    f"{l.website_name}: Händler-Angebotspreis von {p:.2f} € als spekulativer Galeriepreis identifiziert "
                    f"(auf {adjusted_p:.2f} € bereinigt / als Obergrenze gewertet)."
                )
                adjusted_prices.append(adjusted_p)
            elif p > median_web_preis * 2.0:
                adjusted_p = round(median_web_preis * 1.5, 2)
                outlier_notes.append(
                    f"{l.website_name}: Extremer Preisausreißer nach oben ({p:.2f} € vs. Median {median_web_preis:.2f} €) "
                    f"auf {adjusted_p:.2f} € gedeckelt."
                )
                adjusted_prices.append(adjusted_p)
            elif p < median_web_preis * 0.2:
                adjusted_p = round(median_web_preis * 0.5, 2)
                outlier_notes.append(
                    f"{l.website_name}: Extremer Ausreißer nach unten ({p:.2f} € vs. Median {median_web_preis:.2f} €) "
                    f"als Mitnahmepreis/Schnäppchen eingestuft."
                )
                adjusted_prices.append(adjusted_p)
            elif l.preis_typ == PriceType.ANGEBOTSPREIS and p > median_web_preis * 1.5:
                adjusted_p = round(p * 0.70, 2)
                outlier_notes.append(
                    f"{l.website_name}: Angebotspreis von {p:.2f} € als spekulativer Aufschlag identifiziert "
                    f"(auf {adjusted_p:.2f} € bereinigt)."
                )
                adjusted_prices.append(adjusted_p)
            else:
                adjusted_prices.append(p)

        for exc in excluded_listings:
            outlier_notes.append(f"{exc.get('website_name', 'Unbekannt')}: {exc.get('grund', 'Ausgeschlossen')}.")

        # 3. Basispreis aus bereinigten Preisen ermitteln (Priorität auf Realized)
        if realized_listings:
            realized_vals = [l.preis_eur for l in realized_listings if l.preis_eur]
            realized_anchor = float(statistics.median(realized_vals))
            if adjusted_prices:
                # 75% Realized Anchor, 25% restlicher Marktkonsens
                base_market_price = (realized_anchor * 0.75) + (float(statistics.median(adjusted_prices)) * 0.25)
            else:
                base_market_price = realized_anchor
            pricing_rationale_lead = (
                f"Die Wertermittlung basiert primär auf {len(realized_listings)} verifizierten realisierten Verkaufspreisen "
                f"(Anker bei ca. {realized_anchor:.2f} €), die spekulativen Händlerpreisen strikt vorgezogen wurden."
            )
        elif adjusted_prices:
            raw_asking_median = float(statistics.median(adjusted_prices))
            # Reiner Angebotspreis-Markt: Konservativer 15% Sicherheitsabschlag auf den bereinigten Median
            base_market_price = round(raw_asking_median * 0.85, 2)
            pricing_rationale_lead = (
                f"Da keine beendeten Verkäufe vorlagen, wurde der Median der bereinigten Angebotspreise "
                f"({raw_asking_median:.2f} €) mit einem konservativen 15% Sicherheitsabschlag ({base_market_price:.2f} €) als Basis herangezogen."
            )
        else:
            base_market_price = median_web_preis
            pricing_rationale_lead = f"Wertermittlung basiert auf der vorläufigen Objekttaxierung ({base_market_price:.2f} €)."

        # 4. Kalibrierte Zustands- und Mängelabschläge
        zustandsbericht = catalog_data.get("zustandsbericht") or {}
        zustand_str = str(zustandsbericht.get("zustand") or catalog_data.get("zustand") or "gut").lower()
        maengel = zustandsbericht.get("maengel") or catalog_data.get("maengel") or []
        maengel_text = " ".join(str(m) for m in maengel).lower()

        condition_discount_factor = 1.0
        condition_note = "Zustand entspricht weitgehend marktüblichen Referenzen."

        # Prüfe Schweregrad
        if "defekt" in zustand_str or any(w in maengel_text for w in ["abgebrochen", "fehlt", "großer riss", "zertrümmert"]):
            condition_discount_factor = 0.50
            condition_note = "Gravierende Mängel / Defekt führen zu einem kalibrierten Abschlag von 50% gegenüber intakten Vergleichsobjekten."
        elif any(w in maengel_text for w in ["riss", "chip", "abplatzung", "bruch", "beschädigt", "stark bestoßen"]):
            condition_discount_factor = 0.65
            condition_note = "Substanzielle Mängel (Risse, Chips oder Bestoßungen) bedingen einen kalibrierten Mängelabschlag von 35%."
        elif any(w in maengel_text for w in ["kratzer", "fleck", "wasserfleck", "abrieb", "starke gebrauchsspuren"]):
            condition_discount_factor = 0.85
            condition_note = "Sichtbare oberflächliche Gebrauchsspuren / Kratzer führen zu einem kalibrierten Mängelabschlag von 15%."
        elif any(w in maengel_text for w in ["patina", "leichte gebrauchsspuren", "altersgemäß"]):
            condition_discount_factor = 0.95
            condition_note = "Altersübliche Patina und leichte Gebrauchsspuren führen zu einem moderaten Abschlag von 5%."
        elif "sehr gut" in zustand_str or "neuwertig" in zustand_str:
            condition_discount_factor = 1.0
            condition_note = "Überdurchschnittlich guter bzw. neuwertiger Erhaltungszustand ohne werteinschränkende Mängel."


        # Finaler geschätzter Retail-Preis
        geschaetzter_retail_preis = round(base_market_price * condition_discount_factor, 2)
        preisspanne_min = round(geschaetzter_retail_preis * 0.85, 2)
        preisspanne_max = round(geschaetzter_retail_preis * 1.18, 2)

        begruendung = (
            f"{pricing_rationale_lead} {condition_note} "
            f"Empfohlener Retail-Preis: {geschaetzter_retail_preis:.2f} € "
            f"(Plausible Spanne: {preisspanne_min:.2f} € bis {preisspanne_max:.2f} €, Median der Webfunde: {median_web_preis:.2f} €)."
        )

        ausreisser_text = " ".join(outlier_notes) if outlier_notes else "Keine signifikanten Preisausreißer festgestellt."

        return RetailPriceSynthesis(
            geschaetzter_retail_preis_eur=geschaetzter_retail_preis,
            preisspanne_min_eur=preisspanne_min,
            preisspanne_max_eur=preisspanne_max,
            median_web_preis_eur=median_web_preis,
            anzahl_gefundene_preise=anzahl_gefundene_preise,
            begruendung_preisfindung=begruendung,
            ausreisser_bereinigung_notiz=ausreisser_text,
            produktbeschreibung=catalog_data.get("produktbeschreibung") or "",
            physische_merkmale=catalog_data.get("physische_merkmale") or {},
            zustandsbericht=zustandsbericht,
            ausgeschlossene_preise=excluded_listings,
            bereinigte_preise=[{"preis": p} for p in adjusted_prices]
        )

    def synthesize_valuation(
        self,
        catalog_data: Dict[str, Any],
        reference_listings: List[Union[ReferenceListing, Dict[str, Any]]],
        enable_google_search: bool = False
    ) -> RetailPriceSynthesis:
        """
        Führt Stage 3 aus: Appraiser LLM Reconciliation & Synthesis.
        Nutzt Gemini LLM mit strukturiertem Gutachter-Prompt, falls GeminiService aktiv ist,
        und fällt bei Fehlern oder Mock-Modus nahtlos auf die deterministische Schlichtung zurück.
        """
        # Baseline immer vorberechnen
        baseline = self.calculate_deterministic_baseline(catalog_data, reference_listings)

        if not self.gemini_service:
            logger.info("Kein GeminiService aktiv -> verwende deterministische Gutachter-Synthese.")
            return baseline

        # Prompt vorbereiten
        item_id = str(catalog_data.get("id") or "N/A")
        titel = str(catalog_data.get("titel") or "")
        kategorie = str(catalog_data.get("kategorie") or "")
        hersteller = str(catalog_data.get("hersteller_oder_marke") or "")
        epoche = str(catalog_data.get("modell_oder_epoche") or "")
        produktbeschreibung = str(catalog_data.get("produktbeschreibung") or "")
        merkmale_str = json.dumps(catalog_data.get("physische_merkmale") or {}, ensure_ascii=False)
        zustand_str = json.dumps(catalog_data.get("zustandsbericht") or {}, ensure_ascii=False)
        notizen = str(catalog_data.get("notizen_aus_transkript") or "")

        # Referenz-Listings formatieren
        listings_dicts = []
        for l in reference_listings:
            if isinstance(l, ReferenceListing):
                listings_dicts.append(l.model_dump(mode="json"))
            elif isinstance(l, dict):
                listings_dicts.append(l)

        listings_str = json.dumps(listings_dicts, ensure_ascii=False, indent=2)

        stat_summary = (
            f"Valide Preise gefunden: {baseline.anzahl_gefundene_preise}\n"
            f"Statistischer Median: {baseline.median_web_preis_eur:.2f} €\n"
            f"Deterministischer Richtpreis: {baseline.geschaetzter_retail_preis_eur:.2f} €\n"
            f"Bisherige Ausreißer-Notiz: {baseline.ausreisser_bereinigung_notiz}"
        )

        if self.prompt_manager:
            try:
                prompt_text = self.prompt_manager.format_prompt(
                    "prompt_2_appraiser_synthesis.txt",
                    id=item_id,
                    titel=titel,
                    kategorie=kategorie,
                    hersteller=hersteller,
                    epoche=epoche,
                    physische_merkmale=merkmale_str,
                    zustandsbericht=zustand_str,
                    produktbeschreibung=produktbeschreibung,
                    notizen_aus_transkript=notizen,
                    statistische_uebersicht=stat_summary,
                    referenz_listings_json=listings_str
                )
            except Exception as e:
                logger.warning(f"Konnte prompt_2_appraiser_synthesis.txt nicht laden ({e}), nutze Fallback-Prompt.")
                prompt_text = f"Führe Gutachter-Schlichtung durch für {item_id}:\n{listings_str}"
        else:
            prompt_text = f"Führe Gutachter-Schlichtung durch für {item_id}:\n{listings_str}"

        try:
            logger.info(f"Führe Appraiser LLM Synthese für Item '{item_id}' via Gemini aus...")
            resp = self.gemini_service.execute_text_prompt(
                prompt_text=prompt_text,
                images=None,
                expect_json=True,
                enable_google_search=enable_google_search
            )
            parsed = resp.get("parsed_json") or {}

            # Validiere mit Pydantic
            synthesis = RetailPriceSynthesis(
                geschaetzter_retail_preis_eur=parsed.get("geschaetzter_retail_preis_eur") or baseline.geschaetzter_retail_preis_eur,
                preisspanne_min_eur=parsed.get("preisspanne_min_eur") or baseline.preisspanne_min_eur,
                preisspanne_max_eur=parsed.get("preisspanne_max_eur") or baseline.preisspanne_max_eur,
                median_web_preis_eur=parsed.get("median_web_preis_eur") or baseline.median_web_preis_eur,
                anzahl_gefundene_preise=parsed.get("anzahl_gefundene_preise") or baseline.anzahl_gefundene_preise,
                begruendung_preisfindung=str(parsed.get("begruendung_preisfindung") or baseline.begruendung_preisfindung),
                ausreisser_bereinigung_notiz=str(parsed.get("ausreisser_bereinigung_notiz") or baseline.ausreisser_bereinigung_notiz),
                produktbeschreibung=str(parsed.get("produktbeschreibung") or catalog_data.get("produktbeschreibung") or ""),
                physische_merkmale=parsed.get("physische_merkmale") or catalog_data.get("physische_merkmale") or {},
                zustandsbericht=parsed.get("zustandsbericht") or catalog_data.get("zustandsbericht") or {},
                ausgeschlossene_preise=baseline.ausgeschlossene_preise,
                bereinigte_preise=baseline.bereinigte_preise
            )
            logger.info(f"Appraiser LLM Synthese erfolgreich: {synthesis.geschaetzter_retail_preis_eur:.2f} € (Spanne: {synthesis.preisspanne_min_eur:.2f}-{synthesis.preisspanne_max_eur:.2f} €)")
            return synthesis

        except Exception as e:
            logger.warning(f"Fehler bei Appraiser LLM Aufruf ({e}), verwende deterministische Baseline.")
            return baseline
