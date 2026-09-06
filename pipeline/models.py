from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator


class PriceType(str, Enum):
    """Klassifizierung der ermittelten Preisart."""
    REALISIERTER_VERKAUFSPREIS = "realisierter_verkaufspreis"
    ANGEBOTSPREIS = "angebotspreis"
    AUKTIONSGEBOT = "auktionsgebot"
    SCHAETZPREIS = "schaetzpreis"
    UNBEKANNT = "unbekannt"

    @classmethod
    def from_string(cls, val: Any) -> "PriceType":
        if not val:
            return cls.UNBEKANNT
        s = str(val).strip().lower()
        for member in cls:
            if member.value == s:
                return member
        if "realisiert" in s or "sold" in s or "verkauft" in s or "hammer" in s:
            return cls.REALISIERTER_VERKAUFSPREIS
        if "angebot" in s or "asking" in s or "list" in s:
            return cls.ANGEBOTSPREIS
        if "gebot" in s or "bid" in s:
            return cls.AUKTIONSGEBOT
        if "schaetz" in s or "estimate" in s:
            return cls.SCHAETZPREIS
        return cls.UNBEKANNT


class MatchGenauigkeit(str, Enum):
    """Genauigkeit der Übereinstimmung zwischen Referenzobjekt und gescanntem Artikel."""
    EXAKTER_TREFFER = "exakter_treffer"
    MODELLVARIANTE = "modellvariante"
    AEHNLICHES_OBJEKT = "aehnliches_objekt"
    KEIN_TREFFER = "kein_treffer"

    @classmethod
    def from_string(cls, val: Any) -> "MatchGenauigkeit":
        if not val:
            return cls.KEIN_TREFFER
        s = str(val).strip().lower()
        if "exakt" in s or "exact" in s or "identisch" in s:
            return cls.EXAKTER_TREFFER
        if "variante" in s or "variant" in s:
            return cls.MODELLVARIANTE
        if "aehnlich" in s or "ähnlich" in s or "similar" in s:
            return cls.AEHNLICHES_OBJEKT
        for member in cls:
            if member.value == s:
                return member
        return cls.KEIN_TREFFER


class RechercheStatus(str, Enum):
    """Status des einzelnen Website-Recherche-Aufrufs."""
    ERFOLGREICH = "erfolgreich"
    KEIN_PREIS_GEFUNDEN = "kein_preis_gefunden"
    ZUGRIFF_BLOCKIERT = "zugriff_blockiert"
    NICHT_VERFUEGBAR = "nicht_verfuegbar"

    @classmethod
    def from_string(cls, val: Any) -> "RechercheStatus":
        if not val:
            return cls.NICHT_VERFUEGBAR
        s = str(val).strip().lower()
        if "erfolg" in s or "success" in s:
            return cls.ERFOLGREICH
        if "kein_preis" in s or "no_price" in s:
            return cls.KEIN_PREIS_GEFUNDEN
        if "block" in s or "forbidden" in s or "403" in s or "captcha" in s:
            return cls.ZUGRIFF_BLOCKIERT
        for member in cls:
            if member.value == s:
                return member
        return cls.NICHT_VERFUEGBAR


class TargetWebsiteSuggestion(BaseModel):
    """Vorschlag einer Ziel-Webseite für die vertiefte Recherche aus Phase 1."""
    website_name: str
    target_url: Optional[str] = None
    suchbegriff: Optional[str] = None
    plattform_typ: Optional[str] = None
    begruendung: Optional[str] = None


def parse_currency_float(v: Any) -> Optional[float]:
    """Konvertiert Währungsstrings oder Zahlen einheitlich in float."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        s = str(v).replace("€", "").replace("EUR", "").replace("$", "").replace("USD", "").replace("£", "").strip()
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".")
        elif "," in s:
            s = s.replace(",", ".")
        return float(s)
    except (ValueError, TypeError):
        return None


class ReferenceListing(BaseModel):
    """
    Strukturierte Referenz-Listung (Reference Listing) aus der Webrecherche (Phase 2).
    Entspricht strikt den Vorgaben in CONTEXT.md und ADR 0002.
    """
    website_name: str
    listing_titel: str = ""
    preis_eur: Optional[float] = None
    urspruengliche_waehrung: str = "EUR"
    preis_typ: PriceType = PriceType.UNBEKANNT
    match_genauigkeit: MatchGenauigkeit = MatchGenauigkeit.KEIN_TREFFER
    zustand_referenz: str = ""
    quell_url: str = ""
    recherche_status: RechercheStatus = RechercheStatus.NICHT_VERFUEGBAR
    raw_details: Optional[Dict[str, Any]] = None

    @field_validator("preis_eur", mode="before")
    @classmethod
    def parse_preis(cls, v: Any) -> Optional[float]:
        return parse_currency_float(v)


class VisualAnalysisResult(BaseModel):
    """
    Ergebnis der multimodalen visuellen Objektanalyse & 10 Ziel-Webseiten (Phase 1).
    """
    id: Optional[str] = None
    titel: str = ""
    kategorie: str = ""
    produktbeschreibung: str = ""
    hersteller_oder_marke: Optional[str] = None
    modell_oder_epoche: str = ""
    geschaetztes_jahr_oder_epoche: str = ""
    authentizitaet: str = "unklar"
    erkannte_nummern_oder_stempel: List[str] = Field(default_factory=list)
    physische_merkmale: Dict[str, Any] = Field(default_factory=dict)
    zustandsbericht: Dict[str, Any] = Field(default_factory=dict)
    ziel_webseiten: List[TargetWebsiteSuggestion] = Field(default_factory=list)


class RetailPriceSynthesis(BaseModel):
    """
    Synthetisierte Einzelhandelsbewertung aus der Appraiser LLM Reconciliation & Synthesis (Stage 3).
    Entspricht strikt den Vorgaben in Issue 02, CONTEXT.md und ADR 0002.
    """
    geschaetzter_retail_preis_eur: float
    preisspanne_min_eur: float
    preisspanne_max_eur: float
    median_web_preis_eur: float
    anzahl_gefundene_preise: int
    begruendung_preisfindung: str
    ausreisser_bereinigung_notiz: str
    produktbeschreibung: Optional[str] = None
    physische_merkmale: Dict[str, Any] = Field(default_factory=dict)
    zustandsbericht: Dict[str, Any] = Field(default_factory=dict)
    ausgeschlossene_preise: List[Dict[str, Any]] = Field(default_factory=list)
    bereinigte_preise: List[Dict[str, Any]] = Field(default_factory=list)

    @field_validator(
        "geschaetzter_retail_preis_eur",
        "preisspanne_min_eur",
        "preisspanne_max_eur",
        "median_web_preis_eur",
        mode="before"
    )
    @classmethod
    def parse_float_field(cls, v: Any) -> float:
        parsed = parse_currency_float(v)
        return parsed if parsed is not None else 0.0

    @field_validator("anzahl_gefundene_preise", mode="before")
    @classmethod
    def parse_int_field(cls, v: Any) -> int:
        if v is None or v == "":
            return 0
        try:
            return int(float(str(v).strip()))
        except (ValueError, TypeError):
            return 0

