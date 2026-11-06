"""Configuration centrale de l'application.

Toutes les valeurs peuvent être surchargées par des variables d'environnement
(fichier .env chargé automatiquement).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "oui"}


# --- Seuils de sélection -----------------------------------------------------
FAVORITE_MAX_ODDS: float = _env_float("FAVORITE_MAX_ODDS", 1.70)   # cote favori < 1.70
OUTSIDER_MIN_ODDS: float = _env_float("OUTSIDER_MIN_ODDS", 4.00)   # cote outsider > 4.00
MAX_LEAGUE_TIER: int = _env_int("MAX_LEAGUE_TIER", 2)

# --- Extraction OddsPortal ---------------------------------------------------
DAYS_AHEAD: int = _env_int("DAYS_AHEAD", 3)                # J à J+3
# "pinnacle" (repli : moyenne des bookmakers) | "average" (moyenne) | "listing" (meilleure cote de la liste, sans ouvrir les matchs)
ODDS_SOURCE: str = _env("ODDS_SOURCE", "pinnacle").lower()
PINNACLE_BOOKMAKER_NAME: str = _env("PINNACLE_BOOKMAKER_NAME", "Pinnacle")
ODDSPORTAL_BASE_URL: str = _env("ODDSPORTAL_BASE_URL", "https://www.oddsportal.com")
SCRAPE_DELAY_MIN: float = _env_float("SCRAPE_DELAY_MIN", 3.0)
SCRAPE_DELAY_MAX: float = _env_float("SCRAPE_DELAY_MAX", 8.0)
SCRAPE_TIMEOUT_MS: int = _env_int("SCRAPE_TIMEOUT_MS", 45_000)
SCRAPE_HEADLESS: bool = _env_bool("SCRAPE_HEADLESS", True)
SCRAPE_CACHE_TTL_MIN: int = _env_int("SCRAPE_CACHE_TTL_MIN", 90)
# Nombre max. de pages de match ouvertes par extraction (cote Pinnacle)
SCRAPE_MAX_MATCH_PAGES: int = _env_int("SCRAPE_MAX_MATCH_PAGES", 200)
CHROMIUM_EXECUTABLE: str | None = os.getenv("CHROMIUM_EXECUTABLE") or None
USER_AGENT: str = _env(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
)

# --- Fuseau horaire ----------------------------------------------------------
TIMEZONE: str = _env("TIMEZONE", "America/Toronto")

# --- API-Football ------------------------------------------------------------
API_FOOTBALL_KEY: str = _env("API_FOOTBALL_KEY", "")
API_FOOTBALL_BASE_URL: str = _env("API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io")
API_CACHE_TTL_HOURS: int = _env_int("API_CACHE_TTL_HOURS", 12)
API_TIMEOUT_S: float = _env_float("API_TIMEOUT_S", 20.0)

# --- Analyse -----------------------------------------------------------------
FORM_MATCHES: int = 3
H2H_MATCHES: int = 5
MIN_ROUNDS_PLAYED: int = 5   # en dessous : « échantillon faible »
MIN_H2H_MATCHES: int = 2     # en dessous : « données insuffisantes »
TEAM_MATCH_MIN_SCORE: float = _env_float("TEAM_MATCH_MIN_SCORE", 85.0)

# --- Planification -----------------------------------------------------------
REFRESH_INTERVAL_HOURS: int = _env_int("REFRESH_INTERVAL_HOURS", 2)
SCHEDULER_ENABLED: bool = _env_bool("SCHEDULER_ENABLED", True)
ANALYZE_AFTER_SCRAPE: bool = _env_bool("ANALYZE_AFTER_SCRAPE", True)

# --- Fichiers ----------------------------------------------------------------
DATA_DIR: Path = Path(_env("DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL: str = _env("DATABASE_URL", f"sqlite:///{DATA_DIR / 'app.db'}")
SCRAPE_CACHE_DIR: Path = DATA_DIR / "cache" / "oddsportal"
LEAGUES_FILE: Path = Path(_env("LEAGUES_FILE", str(BASE_DIR / "leagues.yaml")))

NA = "N/D"  # affichage de toute donnée manquante
