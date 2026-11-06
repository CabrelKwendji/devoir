"""Structures de données intermédiaires du scraper."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class RawMatch:
    """Match tel que lu sur OddsPortal, avant filtrage."""

    match_id: str
    url: str | None
    kickoff: datetime | None          # aware, America/Toronto
    league_path: str                   # "england/premier-league"
    country_label: str                 # libellé brut OddsPortal
    league_label: str                  # libellé brut OddsPortal
    home: str
    away: str
    odds_home: float | None = None
    odds_draw: float | None = None
    odds_away: float | None = None
    odds_source: str = "average"

    @property
    def has_odds(self) -> bool:
        return None not in (self.odds_home, self.odds_draw, self.odds_away)
