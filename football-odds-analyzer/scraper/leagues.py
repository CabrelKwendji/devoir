"""Chargement du référentiel leagues.yaml (ligue -> pays -> niveau)."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

import config


@dataclass(frozen=True)
class LeagueInfo:
    path: str            # "england/premier-league"
    name: str
    country: str
    tier: int
    api_football_id: int | None = None


def normalize_path(path: str) -> str:
    """'/football/England/Premier-League/' -> 'england/premier-league'."""
    p = path.strip().strip("/").lower()
    if p.startswith("football/"):
        p = p[len("football/"):]
    parts = [x for x in p.split("/") if x]
    return "/".join(parts[:2])


def load_leagues(path: Path | None = None) -> dict[str, LeagueInfo]:
    """Retourne un index {chemin OddsPortal normalisé: LeagueInfo} (alias compris)."""
    path = path or config.LEAGUES_FILE
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    index: dict[str, LeagueInfo] = {}
    for entry in data.get("leagues", []):
        info = LeagueInfo(
            path=normalize_path(entry["oddsportal"]),
            name=str(entry["name"]),
            country=str(entry["country"]),
            tier=int(entry["tier"]),
            api_football_id=entry.get("api_football_id"),
        )
        for p in [entry["oddsportal"], *(entry.get("aliases") or [])]:
            index[normalize_path(p)] = info
    return index


@lru_cache(maxsize=1)
def default_leagues() -> dict[str, LeagueInfo]:
    return load_leagues()
