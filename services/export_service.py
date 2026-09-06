import logging
import json
import re
from pathlib import Path
from typing import Any, List, Dict, Union, Optional
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)


def _format_list_field(val: Any) -> str:
    """Formatiert Listen oder Arrays in einen sauberen, lesbaren String (Semikolon-separiert)."""
    if isinstance(val, (list, tuple)):
        clean_items = [str(x).strip() for x in val if x is not None and str(x).strip()]
        return "; ".join(clean_items)
    elif val is None:
        return ""
    return str(val).strip()


class ExportService:
    """Service zum Konvertieren und Exportieren von Pipeline-Ergebnissen in CSV und Multi-Sheet Excel (.xlsx)."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def flatten_record(record: Dict[str, Any]) -> Dict[str, Any]:
        """Flacht verschachtelte Felder oder Listen in lesbare Tabellenspalten ab."""
        flat_row = {}
        for k, v in record.items():
            if isinstance(v, (list, tuple)):
                flat_row[k] = _format_list_field(v)
            elif isinstance(v, dict):
                for sub_k, sub_v in v.items():
                    if isinstance(sub_v, (list, tuple)):
                        flat_row[f"{k}_{sub_k}"] = _format_list_field(sub_v)
                    elif isinstance(sub_v, dict):
                        flat_row[f"{k}_{sub_k}"] = json.dumps(sub_v, ensure_ascii=False)
                    else:
                        flat_row[f"{k}_{sub_k}"] = sub_v
            else:
                flat_row[k] = v
        return flat_row

    @classmethod
    def build_web_research_rows(
        cls,
        item_id: str,
        listings: List[Union[Dict[str, Any], Any]]
    ) -> List[Dict[str, Any]]:
        """
        Erstellt strukturierte Zeilen für das Sheet 'Marktrecherche_Webpreise' mit klickbaren
        =HYPERLINK(...)-Formeln und Standardspalten.
        """
        rows = []
        for listing in (listings or []):
            if hasattr(listing, "model_dump"):
                listing_dict = listing.model_dump(mode="json")
            elif isinstance(listing, dict):
                listing_dict = listing
            else:
                continue

            site_name = str(listing_dict.get("website_name") or "").strip()
            title = str(listing_dict.get("listing_titel") or "").strip()
            preis = listing_dict.get("preis_eur")
            preis_typ = listing_dict.get("preis_typ")
            if hasattr(preis_typ, "value"):
                preis_typ = preis_typ.value
            match_gen = listing_dict.get("match_genauigkeit")
            if hasattr(match_gen, "value"):
                match_gen = match_gen.value
            zustand = str(listing_dict.get("zustand_referenz") or "").strip()
            status = listing_dict.get("recherche_status") or listing_dict.get("status")
            if hasattr(status, "value"):
                status = status.value

            url = str(listing_dict.get("quell_url") or listing_dict.get("target_url") or "").strip()

            if url.startswith("http://") or url.startswith("https://"):
                friendly_text = title if title else (f"Link ({site_name})" if site_name else "Link öffnen")
                safe_url = url.replace('"', '""')
                safe_friendly = friendly_text.replace('"', '""')
                link_formula = f'=HYPERLINK("{safe_url}", "{safe_friendly}")'
            else:
                link_formula = url or "N/A"

            rows.append({
                "Artikel_ID": str(item_id or "N/A").strip(),
                "Website_Name": site_name,
                "Produkt_Titel": title,
                "Preis_EUR": preis,
                "Preis_Typ": str(preis_typ or "").strip(),
                "Match_Genauigkeit": str(match_gen or "").strip(),
                "Zustand_Referenz": zustand,
                "Status": str(status or "").strip(),
                "Link_URL": link_formula
            })

        return rows

    @classmethod
    def build_unified_item_row_from_state(cls, state: Any) -> Dict[str, Any]:
        """Extrahiert alle Felder aus einem PipelineState-Objekt."""
        return cls.build_unified_item_row(
            step1=getattr(state, "step1_filter_json", None),
            step2=getattr(state, "step2_analysis_json", None),
            step3=getattr(state, "step3_varianten_json", None),
            step4=getattr(state, "step4_preis_steigerer_json", None),
            detected_id=getattr(state, "detected_id", None),
            item_name=getattr(state, "item_name", ""),
            video_filename=state.video_path.name if getattr(state, "video_path", None) else "",
            images_count=len(getattr(state, "image_paths", [])),
            synthesis=getattr(state, "retail_price_synthesis_json", None) or getattr(state, "web_price_summary", None),
            reference_listings=getattr(state, "reference_listings", None) or getattr(state, "discovered_web_sources", None)
        )

    @classmethod
    def build_unified_item_row(
        cls,
        step1: Optional[Dict[str, Any]] = None,
        step2: Optional[Dict[str, Any]] = None,
        step3: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
        step4: Optional[Dict[str, Any]] = None,
        detected_id: Optional[str] = None,
        item_name: str = "",
        video_filename: str = "",
        images_count: int = 0,
        synthesis: Optional[Union[Dict[str, Any], Any]] = None,
        reference_listings: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        """
        Führt sämtliche extrahierten Details (Prompt 1 bis 4) in eine einheitliche,
        vollständige Tabellenzeile zusammen.
        """
        step1 = step1 if isinstance(step1, dict) else {}
        step2 = step2 if isinstance(step2, dict) else {}
        step3_dict = step3 if isinstance(step3, dict) else {}
        step4 = step4 if isinstance(step4, dict) else {}

        synth_dict = {}
        if synthesis is not None:
            if hasattr(synthesis, "model_dump"):
                synth_dict = synthesis.model_dump(mode="json")
            elif isinstance(synthesis, dict):
                synth_dict = synthesis
        synth_merkmale = synth_dict.get("physische_merkmale") if isinstance(synth_dict.get("physische_merkmale"), dict) else {}
        synth_zustand = synth_dict.get("zustandsbericht") if isinstance(synth_dict.get("zustandsbericht"), dict) else {}

        step1_preise = step1.get("preise") if isinstance(step1.get("preise"), dict) else {}
        step2_preise = (step2.get("preise") or step2.get("preisanalyse")) if isinstance(step2.get("preise") or step2.get("preisanalyse"), dict) else {}
        step3_preise = step3_dict.get("preise") if isinstance(step3_dict.get("preise"), dict) else {}
        step2_analyse = (step2.get("zustands_und_marktanalyse") or step2.get("marktrecherche_und_referenzen")) if isinstance(step2.get("zustands_und_marktanalyse") or step2.get("marktrecherche_und_referenzen"), dict) else {}
        step2_merkmale = step2.get("physische_merkmale") if isinstance(step2.get("physische_merkmale"), dict) else {}
        step2_zustand = step2.get("zustandsbericht") if isinstance(step2.get("zustandsbericht"), dict) else {}

        final_rec = step4.get("finale_handlungsempfehlung") if isinstance(step4.get("finale_handlungsempfehlung"), dict) else {}
        artikel_info = step4.get("artikel_uebersicht") if isinstance(step4.get("artikel_uebersicht"), dict) else {}
        export_row = final_rec.get("excel_export_row") if isinstance(final_rec.get("excel_export_row"), dict) else {}

        # 1. ID - Strikte Priorität auf die interne Artikel-ID (keine Verwechslung mit Modell-/Katalognummern)
        folder_match = re.search(r"Artikel_([A-Za-z0-9_]+)", str(item_name))
        folder_id = folder_match.group(1) if folder_match else ""

        if detected_id and str(detected_id).strip().lower() not in {"n/a", "none", "null", ""}:
            item_id = str(detected_id).strip()
        elif folder_id:
            item_id = str(folder_id).strip()
        elif step1.get("interne_artikel_id") and str(step1.get("interne_artikel_id")).strip().lower() not in {"n/a", "none", "null", ""}:
            item_id = str(step1.get("interne_artikel_id")).strip()
        else:
            item_id = str(export_row.get("id") or item_name or "N/A").strip()

        # 2. Titel
        titel = (
            export_row.get("titel")
            or artikel_info.get("titel")
            or step2.get("titel")
            or step1.get("titel")
            or item_name
        )

        # 3. Stammdaten & Attribute
        kategorie = step2.get("kategorie") or step1.get("kategorie") or ""
        hersteller = step2.get("hersteller_oder_marke") or step1.get("hersteller_oder_marke") or ""
        epoche = step2.get("modell_oder_epoche") or step1.get("modell_oder_epoche") or ""
        geschaetztes_jahr = (
            step2.get("geschaetztes_jahr_oder_epoche")
            or step3_dict.get("geschaetztes_jahr_oder_epoche")
            or export_row.get("geschaetztes_jahr_oder_epoche")
            or artikel_info.get("geschaetztes_jahr_oder_epoche")
            or ""
        )

        raw_stempel = (
            step2.get("erkannte_nummern_oder_stempel")
            if step2.get("erkannte_nummern_oder_stempel") is not None
            else step1.get("erkannte_nummern_oder_stempel")
        )
        stempel = _format_list_field(raw_stempel)

        material = step2.get("material") or synth_merkmale.get("material") or step2_merkmale.get("material") or step1.get("material") or ""
        farbe = step2.get("farbe") or synth_merkmale.get("farbe") or step2_merkmale.get("farbe") or step1.get("farbe") or ""
        zustand = step2.get("zustand") or synth_zustand.get("zustand") or step2_zustand.get("zustand") or step1.get("zustand") or ""

        raw_maengel = (
            step2.get("maengel")
            if step2.get("maengel") is not None
            else synth_zustand.get("maengel")
            if synth_zustand.get("maengel") is not None
            else step2_zustand.get("maengel")
            if step2_zustand.get("maengel") is not None
            else step1.get("maengel")
        )
        maengel = _format_list_field(raw_maengel)

        raw_fehlende = (
            step2.get("fehlende_teile")
            if step2.get("fehlende_teile") is not None
            else synth_zustand.get("fehlende_teile")
            if synth_zustand.get("fehlende_teile") is not None
            else step2_zustand.get("fehlende_teile")
            if step2_zustand.get("fehlende_teile") is not None
            else step1.get("fehlende_teile")
        )
        fehlende_teile = _format_list_field(raw_fehlende)

        # 4. Maße & Logistik
        laenge_cm = step2.get("laenge_cm") if step2.get("laenge_cm") is not None else synth_merkmale.get("laenge_cm") if synth_merkmale.get("laenge_cm") is not None else step2_merkmale.get("laenge_cm") if step2_merkmale.get("laenge_cm") is not None else step1.get("laenge_cm")
        breite_cm = step2.get("breite_cm") if step2.get("breite_cm") is not None else synth_merkmale.get("breite_cm") if synth_merkmale.get("breite_cm") is not None else step2_merkmale.get("breite_cm") if step2_merkmale.get("breite_cm") is not None else step1.get("breite_cm")
        hoehe_cm = step2.get("hoehe_cm") if step2.get("hoehe_cm") is not None else synth_merkmale.get("hoehe_cm") if synth_merkmale.get("hoehe_cm") is not None else step2_merkmale.get("hoehe_cm") if step2_merkmale.get("hoehe_cm") is not None else step1.get("hoehe_cm")
        durchmesser_cm = step2.get("durchmesser_cm") if step2.get("durchmesser_cm") is not None else synth_merkmale.get("durchmesser_cm") if synth_merkmale.get("durchmesser_cm") is not None else step2_merkmale.get("durchmesser_cm") if step2_merkmale.get("durchmesser_cm") is not None else step1.get("durchmesser_cm")
        gewicht_kg = step2.get("gewicht_kg") if step2.get("gewicht_kg") is not None else synth_merkmale.get("gewicht_kg") if synth_merkmale.get("gewicht_kg") is not None else step2_merkmale.get("gewicht_kg") if step2_merkmale.get("gewicht_kg") is not None else step1.get("gewicht_kg")
        logistik_kategorie = step2.get("logistik_kategorie") or step1.get("logistik_kategorie") or ""

        # 5. Einkauf & Wunschpreise (aus Transkript/Extraktion)
        einkaufspreis = step1_preise.get("einkaufspreis_eur")
        if einkaufspreis is None:
            einkaufspreis = step2_preise.get("einkaufspreis_eur")

        erwarteter_preis = step1_preise.get("erwarteter_preis_eur")
        if erwarteter_preis is None:
            erwarteter_preis = step2_preise.get("erwarteter_preis_eur")

        mindestpreis = step1_preise.get("gewuenschter_mindestpreis_eur")
        if mindestpreis is None:
            mindestpreis = step2_preise.get("gewuenschter_mindestpreis_eur")

        # 6. Prognose & Marktpreise (Prompt 2 / 3 / Stage 3 Synthese)
        ist_wert = (
            export_row.get("ist_wert")
            or artikel_info.get("aktueller_ist_wert_eur")
            or step2_preise.get("prognostizierter_preis_realistisch_eur")
            or 0.0
        )
        preis_min = step2_preise.get("prognostizierter_preis_min_eur") or step3_preise.get("prognostizierter_preis_min_eur")
        preis_max = step2_preise.get("prognostizierter_preis_max_eur") or step3_preise.get("prognostizierter_preis_max_eur")
        preis_realistisch = step2_preise.get("prognostizierter_preis_realistisch_eur") or step3_preise.get("prognostizierter_preis_realistisch_eur")
        preis_begruendung = step2_preise.get("preis_begruendung") or step3_preise.get("preis_begruendung") or ""

        # Geforderte Bewertungsspalten (Issue 03)
        retail_preis = (
            synth_dict.get("geschaetzter_retail_preis_eur")
            if synth_dict.get("geschaetzter_retail_preis_eur") is not None
            else (step2.get("geschaetzter_retail_preis_eur")
                  if step2.get("geschaetzter_retail_preis_eur") is not None
                  else (step2_preise.get("prognostizierter_preis_realistisch_eur")
                        if step2_preise.get("prognostizierter_preis_realistisch_eur") is not None
                        else (preis_realistisch or ist_wert)))
        )
        preisspanne_min = (
            synth_dict.get("preisspanne_min_eur")
            if synth_dict.get("preisspanne_min_eur") is not None
            else (step2.get("preisspanne_min_eur")
                  if step2.get("preisspanne_min_eur") is not None
                  else (step2_preise.get("prognostizierter_preis_min_eur")
                        if step2_preise.get("prognostizierter_preis_min_eur") is not None
                        else preis_min))
        )
        preisspanne_max = (
            synth_dict.get("preisspanne_max_eur")
            if synth_dict.get("preisspanne_max_eur") is not None
            else (step2.get("preisspanne_max_eur")
                  if step2.get("preisspanne_max_eur") is not None
                  else (step2_preise.get("prognostizierter_preis_max_eur")
                        if step2_preise.get("prognostizierter_preis_max_eur") is not None
                        else preis_max))
        )
        median_web = (
            synth_dict.get("median_web_preis_eur")
            if synth_dict.get("median_web_preis_eur") is not None
            else (step2.get("median_web_preis_eur")
                  if step2.get("median_web_preis_eur") is not None
                  else step2_preise.get("median_web_preis_eur"))
        )
        anzahl_preise = (
            synth_dict.get("anzahl_gefundene_preise")
            if synth_dict.get("anzahl_gefundene_preise") is not None
            else (step2.get("anzahl_gefundene_preise")
                  if step2.get("anzahl_gefundene_preise") is not None
                  else (step2_preise.get("anzahl_gefundene_preise")
                        if step2_preise.get("anzahl_gefundene_preise") is not None
                        else 0))
        )
        begruendung_preise = (
            synth_dict.get("begruendung_preisfindung")
            or step2.get("begruendung_preisfindung")
            or step2_preise.get("preis_begruendung")
            or preis_begruendung
            or ""
        )

        # Top Referenz Links
        top_links = []
        if reference_listings:
            for rl in reference_listings:
                if hasattr(rl, "model_dump"):
                    rd = rl.model_dump(mode="json")
                elif isinstance(rl, dict):
                    rd = rl
                else:
                    continue
                r_url = str(rd.get("quell_url") or rd.get("target_url") or "").strip()
                r_stat = str(rd.get("recherche_status") or rd.get("status") or "").lower()
                if (r_url.startswith("http://") or r_url.startswith("https://")) and (not r_stat or "erfolg" in r_stat):
                    if r_url not in top_links:
                        top_links.append(r_url)
        if top_links:
            top_links_str = "; ".join(top_links[:5])
        else:
            top_links_str = _format_list_field(step2_analyse.get("vergleichbare_referenzobjekte") or step2.get("vergleichbare_referenzobjekte") or "")

        # 7. Zustands- & Marktanalyse
        produktbeschreibung = synth_dict.get("produktbeschreibung") or step2.get("produktbeschreibung") or step2_analyse.get("produktbeschreibung") or ""
        authentizitaet = step2.get("authentizitaet") or step2_analyse.get("authentizitaet") or ""
        marktnachfrage = step2.get("marktnachfrage_level") or step2_analyse.get("marktnachfrage_level") or ""
        zustandsbeschreibung = step2.get("detaillierte_zustandsbeschreibung") or step2_analyse.get("detaillierte_zustandsbeschreibung") or ""
        empfohlene_massnahme = step2_zustand.get("empfohlene_massnahme") or step2.get("empfohlene_massnahme") or ""
        referenzobjekte = _format_list_field(step2_analyse.get("vergleichbare_referenzobjekte") or step2.get("vergleichbare_referenzobjekte"))
        recherche_quellen = step2_analyse.get("recherche_quellen_und_kontext") or step2.get("recherche_quellen_und_kontext") or ""
        altersbestimmung_merkmale = (
            step2_analyse.get("altersbestimmung_und_merkmale")
            or (step3_dict.get("zustands_und_marktanalyse", {}).get("altersbestimmung_und_merkmale") if isinstance(step3_dict.get("zustands_und_marktanalyse"), dict) else "")
            or ""
        )
        ausreisser_notiz = step2_analyse.get("ausreisser_bereinigung_notiz") or ""
        notizen_transkript = step1.get("notizen_aus_transkript") or step2.get("notizen_aus_transkript") or ""

        # 8. Handlungsempfehlung & Arbitrage (Prompt 4)
        details_kurz = export_row.get("artikel_details_kurz") or artikel_info.get("artikel_details_kurz") or ""
        verkaufs_ort = export_row.get("verkaufs_ort") or artikel_info.get("verkaufs_ort") or ""
        preistreiber = export_row.get("preistreiber") or artikel_info.get("preistreiber") or ""
        beste_massnahme = export_row.get("beste_massnahme") or final_rec.get("empfohlene_massnahme") or empfohlene_massnahme or ""
        strategie = final_rec.get("strategie") or export_row.get("strategie") or ""
        handlung = export_row.get("handlung") or ""
        kosten = export_row.get("investitionskosten_eur", 0.0)
        zeit = export_row.get("zeitaufwand_h", 0.0)
        ziel_preis = export_row.get("ziel_verkaufspreis_eur", 0.0)
        netto_profit = export_row.get("netto_profit_eur") if export_row.get("netto_profit_eur") is not None else final_rec.get("erwarteter_endgewinn_eur", 0.0)
        ver_effizienz = export_row.get("ver_effizienz", 0.0)
        anleitung = export_row.get("genaue_anleitung_massnahme") or final_rec.get("genaue_anleitung_massnahme") or ""
        verworfen = export_row.get("verworfen_alternative_massnahmen") or final_rec.get("verworfen_alternative_massnahmen") or ""
        begruendung_gesamt = final_rec.get("begruendung_gesamt") or ""

        return {
            # Stammdaten & Identifikation
            "id": item_id,
            "titel": titel,
            "produktbeschreibung": produktbeschreibung,
            "hersteller_oder_marke": hersteller,
            "modell_oder_epoche": epoche,
            "geschaetztes_jahr_oder_epoche": geschaetztes_jahr,
            "erkannte_nummern_oder_stempel": stempel,
            "material": material,
            "farbe": farbe,
            "zustand": zustand,
            "maengel": maengel,
            "fehlende_teile": fehlende_teile,
            "empfohlene_massnahme_zustand": empfohlene_massnahme,
            # Maße & Logistik
            "laenge_cm": laenge_cm,
            "breite_cm": breite_cm,
            "hoehe_cm": hoehe_cm,
            "durchmesser_cm": durchmesser_cm,
            "gewicht_kg": gewicht_kg,
            "logistik_kategorie": logistik_kategorie,

            # Basis-Preise (Transkript / Extraktion)
            "einkaufspreis_eur": einkaufspreis,
            "erwarteter_preis_eur": erwarteter_preis,
            "gewuenschter_mindestpreis_eur": mindestpreis,

            # Recherche & Marktwertprognose
            "Empfohlener_Retail_Preis_EUR": retail_preis,
            "Preisspanne_Min_EUR": preisspanne_min,
            "Preisspanne_Max_EUR": preisspanne_max,
            "Median_Web_Preis_EUR": median_web,
            "Anzahl_gefundene_Webpreise": anzahl_preise,
            "Top_Referenz_Links": top_links_str,
            "Begruendung_Preisfindung": begruendung_preise,
            "aktueller_ist_wert_eur": ist_wert,
            "prognostizierter_preis_min_eur": preis_min,
            "prognostizierter_preis_max_eur": preis_max,
            "prognostizierter_preis_realistisch_eur": preis_realistisch,
            "preis_begruendung": preis_begruendung,
            "vergleichbare_referenzobjekte": referenzobjekte,
            "authentizitaet": authentizitaet,
            "marktnachfrage_level": marktnachfrage,
            "detaillierte_zustandsbeschreibung": zustandsbeschreibung,
            "ausreisser_bereinigung_notiz": ausreisser_notiz,
            "notizen_aus_transkript": notizen_transkript,

            # Handlungsempfehlung & Arbitrage (Prompt 4)
            "artikel_details_kurz": details_kurz,
            "verkaufs_ort": verkaufs_ort,
            "preistreiber": preistreiber,
            "beste_massnahme": beste_massnahme,
            "strategie": strategie,
            "handlung": handlung,
            "investitionskosten_eur": kosten,
            "zeitaufwand_h": zeit,
            "ziel_verkaufspreis_eur": ziel_preis,
            "netto_profit_eur": netto_profit,
            "ver_effizienz_eur_h": ver_effizienz,
            "genaue_anleitung_massnahme": anleitung,
            "verworfen_alternative_massnahmen": verworfen,
            "begruendung_gesamt": begruendung_gesamt,

            # Prozess- & Dateimetadaten
            "ordner_name": item_name,
            "video_datei": video_filename,
            "anzahl_bilder": images_count
        }

    def _apply_excel_styling(self, workbook: openpyxl.Workbook) -> None:
        """Formatiert alle Sheets mit ansprechenden Spaltenbreiten, Kopfzeilen, Link-Formatierung und Textumbruch."""
        header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        data_font = Font(name="Calibri", size=10)
        link_font = Font(name="Calibri", size=10, color="FF0563C1", underline="single")
        thin_border = Border(
            left=Side(style='thin', color='D9D9D9'),
            right=Side(style='thin', color='D9D9D9'),
            top=Side(style='thin', color='D9D9D9'),
            bottom=Side(style='thin', color='D9D9D9')
        )

        for sheetname in workbook.sheetnames:
            ws = workbook[sheetname]
            ws.freeze_panes = "A2"
            ws.row_dimensions[1].height = 28

            # Header formatieren
            for col_idx in range(1, ws.max_column + 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

            # Datenzeilen formatieren & Spaltenbreiten berechnen
            for col_idx in range(1, ws.max_column + 1):
                col_letter = get_column_letter(col_idx)
                max_len = 0

                header_val = ws.cell(row=1, column=col_idx).value
                if header_val:
                    max_len = max(max_len, len(str(header_val)))

                for row_idx in range(2, ws.max_row + 1):
                    cell = ws.cell(row=row_idx, column=col_idx)
                    cell.border = thin_border

                    val = cell.value
                    if val is not None:
                        val_str = str(val)
                        if val_str.startswith("=HYPERLINK("):
                            cell.font = link_font
                            cell.alignment = Alignment(horizontal="left", vertical="top")
                            m = re.search(r'=HYPERLINK\(".*?",\s*"(.*?)"\)', val_str)
                            display_text = m.group(1) if m else val_str
                            max_len = max(max_len, len(display_text))
                        else:
                            cell.font = data_font
                            # Erste Zeile bei mehrzeiligem Text für Breitenabschätzung
                            first_line = val_str.split("\n")[0] if "\n" in val_str else val_str
                            max_len = max(max_len, len(first_line))

                            if isinstance(val, (int, float)):
                                cell.alignment = Alignment(horizontal="right", vertical="top")
                            else:
                                cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
                    else:
                        cell.font = data_font
                        cell.alignment = Alignment(horizontal="left", vertical="top")

                # Angemessene Spaltenbreite (mindestens 12, maximal 55)
                ws.column_dimensions[col_letter].width = max(12, min(max_len + 3, 55))

    def export_single_item(self, state: Any, base_filename: str = "item_result") -> Dict[str, Path]:
        """
        Exportiert einen einzelnen Artikel mit allen Details in CSV und Multi-Sheet Excel.
        - Sheet 1: Hauptempfehlung (Alle Attribute)
        - Sheet 2: Marktrecherche_Webpreise (10 untersuchte Webseiten & klickbare Links)
        - Sheet 3: Alle_Massnahmen_Details (Maßnahmen aus Prompt 4, falls vorhanden)
        - Sheet 4: Varianten_Prompt3 (Varianten aus Prompt 3, falls vorhanden)
        """
        main_row = self.build_unified_item_row_from_state(state)
        df_main = pd.DataFrame([main_row])

        tracking_cols = ["VerkaufsOrt", "Status", "ErzielterPreis"]
        for col in tracking_cols:
            if col not in df_main.columns:
                if col == "VerkaufsOrt" and "verkaufs_ort" in df_main.columns:
                    df_main[col] = df_main["verkaufs_ort"].fillna("")
                else:
                    df_main[col] = ""
            else:
                df_main[col] = df_main[col].fillna("")
        other_cols = [c for c in df_main.columns if c not in tracking_cols]
        df_main = df_main[other_cols + tracking_cols]

        csv_path = self.output_dir / f"{base_filename}.csv"
        excel_path = self.output_dir / f"{base_filename}.xlsx"

        # CSV-Export mit UTF-8 BOM
        df_main.to_csv(csv_path, index=False, sep=";", encoding="utf-8-sig")
        logger.info(f"CSV exportiert: {csv_path}")

        # Web-Research Listings für Sheet 2 vorbereiten
        ref_listings = (
            getattr(state, "reference_listings", None) 
            or getattr(state, "discovered_web_sources", None)
            or []
        )
        item_id = main_row.get("id") or getattr(state, "detected_id", None) or "N/A"
        web_research_rows = self.build_web_research_rows(item_id, ref_listings)

        # Multi-Sheet Excel-Export
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            # Sheet 1: Hauptempfehlung
            df_main.to_excel(writer, index=False, sheet_name="Hauptempfehlung")

            # Sheet 2: Marktrecherche_Webpreise
            if web_research_rows:
                df_web = pd.DataFrame(web_research_rows)
            else:
                df_web = pd.DataFrame(columns=[
                    "Artikel_ID", "Website_Name", "Produkt_Titel", "Preis_EUR",
                    "Preis_Typ", "Match_Genauigkeit", "Zustand_Referenz", "Status", "Link_URL"
                ])
            df_web.to_excel(writer, index=False, sheet_name="Marktrecherche_Webpreise")

            # Sheet 3: Maßnahmen-Details aus Prompt 4
            p4 = getattr(state, "step4_preis_steigerer_json", None)
            if p4 and isinstance(p4, dict) and "massnahmen_bewertungen" in p4:
                massnahmen = p4["massnahmen_bewertungen"]
                if isinstance(massnahmen, list) and massnahmen:
                    df_massnahmen = pd.DataFrame([self.flatten_record(m) for m in massnahmen])
                    df_massnahmen.to_excel(writer, index=False, sheet_name="Alle_Massnahmen_Details")

            # Sheet 4: Varianten aus Prompt 3
            p3 = getattr(state, "step3_varianten_json", None)
            if p3:
                if isinstance(p3, dict) and "varianten" in p3 and isinstance(p3["varianten"], list) and p3["varianten"]:
                    df_var = pd.DataFrame([self.flatten_record(v) for v in p3["varianten"]])
                    df_var.to_excel(writer, index=False, sheet_name="Varianten_Prompt3")
                elif isinstance(p3, list) and p3:
                    df_var = pd.DataFrame([self.flatten_record(v) for v in p3])
                    df_var.to_excel(writer, index=False, sheet_name="Varianten_Prompt3")

        # Styling nachträglich anwenden
        wb = openpyxl.load_workbook(excel_path)
        self._apply_excel_styling(wb)
        wb.save(excel_path)
        logger.info(f"Excel mit Formatierung exportiert: {excel_path}")

        return {
            "csv": csv_path,
            "excel": excel_path,
            "row_count": 1
        }

    def export_consolidated_batch(
        self,
        items_rows: List[Dict[str, Any]],
        measures_rows: Optional[List[Dict[str, Any]]] = None,
        web_research_rows: Optional[List[Dict[str, Any]]] = None,
        base_filename: str = "consolidated_execution_results"
    ) -> Dict[str, Path]:
        """
        Exportiert die konsolidierte Übersicht aller Artikel in CSV und Multi-Sheet Excel.
        - Sheet 1: Alle_Artikel
        - Sheet 2: Marktrecherche_Webpreise (falls vorhanden)
        - Sheet 3: Alle_Massnahmen_Gesamt (falls vorhanden)
        """
        df_items = pd.DataFrame(items_rows)

        # Automatische Konkatenierung der Tracking-Spalten am Ende der Tabelle
        tracking_cols = ["VerkaufsOrt", "Status", "ErzielterPreis"]
        for col in tracking_cols:
            if col not in df_items.columns:
                if col == "VerkaufsOrt" and "verkaufs_ort" in df_items.columns:
                    df_items[col] = df_items["verkaufs_ort"].fillna("")
                else:
                    df_items[col] = ""
            else:
                df_items[col] = df_items[col].fillna("")

        # Sicherstellen, dass die Tracking-Spalten immer die letzten 3 Spalten sind
        other_cols = [c for c in df_items.columns if c not in tracking_cols]
        df_items = df_items[other_cols + tracking_cols]

        csv_path = self.output_dir / f"{base_filename}.csv"
        excel_path = self.output_dir / f"{base_filename}.xlsx"

        # CSV
        try:
            df_items.to_csv(csv_path, index=False, sep=";", encoding="utf-8-sig")
            logger.info(f"Konsolidierte CSV exportiert: {csv_path}")
        except PermissionError:
            csv_path = self.output_dir / f"{base_filename}_neu.csv"
            df_items.to_csv(csv_path, index=False, sep=";", encoding="utf-8-sig")
            logger.warning(f"Zieldatei war gesperrt. Konsolidierte CSV gespeichert unter: {csv_path}")

        # Excel
        def _write_excel(target_path: Path):
            with pd.ExcelWriter(target_path, engine="openpyxl") as writer:
                df_items.to_excel(writer, index=False, sheet_name="Alle_Artikel")

                if web_research_rows is not None:
                    if web_research_rows:
                        df_web = pd.DataFrame(web_research_rows)
                    else:
                        df_web = pd.DataFrame(columns=[
                            "Artikel_ID", "Website_Name", "Produkt_Titel", "Preis_EUR",
                            "Preis_Typ", "Match_Genauigkeit", "Zustand_Referenz", "Status", "Link_URL"
                        ])
                    df_web.to_excel(writer, index=False, sheet_name="Marktrecherche_Webpreise")

                if measures_rows:
                    df_measures = pd.DataFrame(measures_rows)
                    df_measures.to_excel(writer, index=False, sheet_name="Alle_Massnahmen_Gesamt")

            wb = openpyxl.load_workbook(target_path)
            self._apply_excel_styling(wb)
            wb.save(target_path)

        try:
            _write_excel(excel_path)
            logger.info(f"Konsolidierte Excel exportiert: {excel_path}")
        except PermissionError:
            excel_path = self.output_dir / f"{base_filename}_neu.xlsx"
            _write_excel(excel_path)
            logger.warning(f"Zieldatei war in Excel geöffnet. Konsolidierte Excel gespeichert unter: {excel_path}")

        return {
            "csv": csv_path,
            "excel": excel_path,
            "row_count": len(items_rows)
        }

    def export_data(
        self, 
        data: Union[Dict[str, Any], List[Dict[str, Any]]], 
        base_filename: str = "pipeline_result"
    ) -> Dict[str, Path]:
        """
        Kompatibilitäts-Exportfunktion für bestehende Aufrufe.
        """
        if isinstance(data, list):
            cleaned_records = [self.flatten_record(r) for r in data]
            df_main = pd.DataFrame(cleaned_records)
            measures = None
        elif isinstance(data, dict):
            if "finale_handlungsempfehlung" in data and "excel_export_row" in data["finale_handlungsempfehlung"]:
                row = data["finale_handlungsempfehlung"]["excel_export_row"]
                if "artikel_uebersicht" in data:
                    row["artikel_titel"] = data["artikel_uebersicht"].get("titel", "")
                    row["aktueller_ist_wert_eur"] = data["artikel_uebersicht"].get("aktueller_ist_wert_eur", 0.0)
                records = [row]
            else:
                records = [data]
            df_main = pd.DataFrame([self.flatten_record(r) for r in records])
            measures = [self.flatten_record(m) for m in data.get("massnahmen_bewertungen", [])] if "massnahmen_bewertungen" in data else None
            ref_listings = data.get("reference_listings") or data.get("discovered_web_sources")
            web_rows = self.build_web_research_rows(records[0].get("id", "N/A"), ref_listings) if ref_listings else None
        else:
            raise ValueError(f"Ungültiger Datentyp für Export: {type(data)}")

        csv_path = self.output_dir / f"{base_filename}.csv"
        excel_path = self.output_dir / f"{base_filename}.xlsx"

        df_main.to_csv(csv_path, index=False, sep=";", encoding="utf-8-sig")
        logger.info(f"CSV exportiert: {csv_path}")

        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df_main.to_excel(writer, index=False, sheet_name="Hauptempfehlung")
            if web_rows:
                df_web = pd.DataFrame(web_rows)
                df_web.to_excel(writer, index=False, sheet_name="Marktrecherche_Webpreise")
            if measures:
                df_massnahmen = pd.DataFrame(measures)
                df_massnahmen.to_excel(writer, index=False, sheet_name="Alle_Massnahmen_Details")

        wb = openpyxl.load_workbook(excel_path)
        self._apply_excel_styling(wb)
        wb.save(excel_path)
        logger.info(f"Excel exportiert: {excel_path}")

        return {
            "csv": csv_path,
            "excel": excel_path,
            "row_count": len(df_main)
        }

