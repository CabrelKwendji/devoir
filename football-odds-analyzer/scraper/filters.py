"""Filtres de sélection des matchs (fonctions pures, testées unitairement).

Règles :
  * cote du favori < FAVORITE_MAX_ODDS (1.70) et cote de l'outsider > OUTSIDER_MIN_ODDS (4.00)
  * le favori peut jouer à domicile ou à l'extérieur
  * toute coupe / compétition internationale / amical / barrage / qualification est exclue
  * seuls les championnats présents dans leagues.yaml avec tier <= MAX_LEAGUE_TIER sont gardés
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import config
from scraper.leagues import LeagueInfo, normalize_path
from scraper.models import RawMatch

# Codes de motif de rejet (journal)
REJECT_CUP = "coupe"
REJECT_UNLISTED = "non_reference"
REJECT_TIER = "niveau"
REJECT_ODDS_MISSING = "cotes_nd"
REJECT_ODDS = "cotes_hors_seuils"
REJECT_TEAM = "equipe_non_rapprochee"

REJECT_LABELS = {
    REJECT_CUP: "Coupe / compétition hors championnat",
    REJECT_UNLISTED: "Championnat absent de leagues.yaml",
    REJECT_TIER: "Niveau de division trop bas",
    REJECT_ODDS_MISSING: "Cotes 1X2 indisponibles",
    REJECT_ODDS: "Cotes hors seuils",
    REJECT_TEAM: "Équipe non rapprochée (API-Football)",
}

# Pays « virtuels » d'OddsPortal regroupant des compétitions internationales
INTERNATIONAL_COUNTRIES = {
    "world", "europe", "south-america", "north-central-america", "asia", "africa",
    "oceania", "international",
}

# Mots isolés signalant une coupe ou une compétition hors championnat
CUP_TOKENS = {
    "cup", "cups", "coupe", "copa", "coppa", "pokal", "taca", "beker", "kupa", "cupa",
    "puchar", "pohar", "kubok", "kupasi", "trophy", "trophee", "shield", "supercup",
    "supercopa", "supercoppa", "superpokal", "supercoupe", "friendly", "friendlies",
    "playoff", "playoffs", "qualification", "qualifying", "qualifiers", "qualifier",
    "libertadores", "sudamericana", "concacaf", "uefa", "fifa", "afc", "caf", "ofc",
    "conmebol", "olympic", "olympics", "euro", "liguilla", "relegation",
    "barrage", "barrages", "knockout", "carabao",
}
# Expressions (après normalisation en tirets)
CUP_PHRASES = (
    "play-off", "play-offs", "champions-league", "europa-league", "conference-league",
    "nations-league", "world-cup", "club-friendly", "league-cup", "fa-cup", "super-cup",
    "copa-del-rey", "dfb-pokal", "coupe-de-france", "coppa-italia", "gold-cup",
    "asian-cup", "africa-cup", "leagues-cup", "community-shield", "fa-trophy",
)


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def is_cup_competition(league_path: str, league_label: str = "", country_label: str = "") -> bool:
    """Vrai si la compétition n'est pas un championnat national."""
    path = normalize_path(league_path)
    country = path.split("/")[0] if path else _slug(country_label)
    if country in INTERNATIONAL_COUNTRIES or _slug(country_label) in INTERNATIONAL_COUNTRIES:
        return True
    haystack = "-".join(s for s in (_slug(path.replace("/", "-")), _slug(league_label)) if s)
    tokens = set(haystack.split("-"))
    if tokens & CUP_TOKENS:
        return True
    padded = f"-{haystack}-"
    return any(f"-{phrase}-" in padded for phrase in CUP_PHRASES)


def pick_favorite(odds_home: float, odds_away: float) -> str:
    """Retourne 'home' ou 'away' : l'équipe à la cote la plus basse."""
    return "home" if odds_home <= odds_away else "away"


def odds_within_thresholds(
    odds_home: float,
    odds_away: float,
    favorite_max: float = config.FAVORITE_MAX_ODDS,
    outsider_min: float = config.OUTSIDER_MIN_ODDS,
) -> bool:
    """Favori net (< favorite_max) contre outsider (> outsider_min), à domicile ou à l'extérieur."""
    fav = min(odds_home, odds_away)
    out = max(odds_home, odds_away)
    return fav < favorite_max and out > outsider_min


@dataclass
class FilterResult:
    kept: bool
    reason_code: str | None = None
    reason: str | None = None
    league: LeagueInfo | None = None
    favorite_side: str | None = None


def evaluate_match(
    raw: RawMatch,
    leagues: dict[str, LeagueInfo],
    max_tier: int = config.MAX_LEAGUE_TIER,
    favorite_max: float = config.FAVORITE_MAX_ODDS,
    outsider_min: float = config.OUTSIDER_MIN_ODDS,
) -> FilterResult:
    """Applique toutes les règles dans l'ordre et renvoie le premier motif de rejet."""
    if is_cup_competition(raw.league_path, raw.league_label, raw.country_label):
        return FilterResult(False, REJECT_CUP, f"Coupe/hors championnat : {raw.league_label or raw.league_path}")

    league = leagues.get(normalize_path(raw.league_path))
    if league is None:
        return FilterResult(False, REJECT_UNLISTED, f"Championnat non référencé : {raw.league_path}")

    if league.tier > max_tier:
        return FilterResult(
            False, REJECT_TIER, f"Niveau {league.tier} > {max_tier} ({league.name})", league
        )

    if not raw.has_odds:
        return FilterResult(False, REJECT_ODDS_MISSING, "Cotes 1X2 N/D", league)

    if not odds_within_thresholds(raw.odds_home, raw.odds_away, favorite_max, outsider_min):
        fav = min(raw.odds_home, raw.odds_away)
        out = max(raw.odds_home, raw.odds_away)
        return FilterResult(
            False,
            REJECT_ODDS,
            f"Cotes hors seuils : favori {fav:.2f} (seuil < {favorite_max:.2f}), "
            f"outsider {out:.2f} (seuil > {outsider_min:.2f})",
            league,
        )

    return FilterResult(True, league=league, favorite_side=pick_favorite(raw.odds_home, raw.odds_away))
