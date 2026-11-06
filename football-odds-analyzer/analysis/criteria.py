"""Les 3 critères de confirmation du favori (fonctions pures, testées unitairement).

Aucune donnée n'est inventée : une donnée manquante est représentée par None et
affichée « N/D » ; un critère sans données suffisantes est « neutre ».
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import config

FAVORABLE = "favorable"      # ✅
UNFAVORABLE = "defavorable"  # ❌
NEUTRAL = "neutre"           # ⚪

ICONS = {FAVORABLE: "✅", UNFAVORABLE: "❌", NEUTRAL: "⚪"}

VERDICT_CONFIRMED = "Favori confirmé"
VERDICT_LIKELY = "Plutôt confirmé"
VERDICT_FRAGILE = "Favori fragile"


@dataclass
class CriterionResult:
    name: str
    status: str
    note: str | None = None
    data: dict = field(default_factory=dict)

    @property
    def icon(self) -> str:
        return ICONS[self.status]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["icon"] = self.icon
        return d


# --- Données d'entrée ----------------------------------------------------------
@dataclass
class StandingRow:
    rank: int | None
    points: int | None
    played: int | None


@dataclass
class FixtureResult:
    """Un match passé vu du côté d'une équipe donnée."""

    goals_for: int
    goals_against: int

    @property
    def outcome(self) -> str:
        if self.goals_for > self.goals_against:
            return "V"
        if self.goals_for == self.goals_against:
            return "N"
        return "D"

    @property
    def points(self) -> int:
        return {"V": 3, "N": 1, "D": 0}[self.outcome]


# --- Critère 1 : classement ------------------------------------------------------
def standings_criterion(fav: StandingRow | None, out: StandingRow | None) -> CriterionResult:
    """Favorable si le favori est mieux classé ET a plus de points."""
    data = {
        "favorite_rank": fav.rank if fav else None,
        "favorite_points": fav.points if fav else None,
        "favorite_played": fav.played if fav else None,
        "outsider_rank": out.rank if out else None,
        "outsider_points": out.points if out else None,
        "outsider_played": out.played if out else None,
        "rank_gap": None,
        "points_gap": None,
        "low_sample": False,
    }
    if not fav or not out or None in (fav.rank, fav.points, out.rank, out.points):
        return CriterionResult("Classement", NEUTRAL, "Classement N/D", data)

    data["rank_gap"] = out.rank - fav.rank       # > 0 : favori mieux classé
    data["points_gap"] = fav.points - out.points  # > 0 : favori a plus de points
    note = None
    played = [p for p in (fav.played, out.played) if p is not None]
    if not played or min(played) < config.MIN_ROUNDS_PLAYED:
        data["low_sample"] = True
        note = "échantillon faible"

    better = fav.rank < out.rank and fav.points > out.points
    return CriterionResult("Classement", FAVORABLE if better else UNFAVORABLE, note, data)


# --- Critère 2 : forme -------------------------------------------------------------
def _form_summary(results: list[FixtureResult] | None) -> dict:
    if results is None:
        return {"sequence": None, "points": None, "goals_for": None, "goals_against": None, "count": 0}
    last = results[: config.FORM_MATCHES]
    return {
        "sequence": "".join(r.outcome for r in last) or None,
        "points": sum(r.points for r in last) if last else None,
        "goals_for": sum(r.goals_for for r in last) if last else None,
        "goals_against": sum(r.goals_against for r in last) if last else None,
        "count": len(last),
    }


def form_criterion(fav_results: list[FixtureResult] | None, out_results: list[FixtureResult] | None) -> CriterionResult:
    """Points sur les 3 derniers matchs de championnat (les plus récents en premier).

    Favorable si points du favori > points de l'outsider.
    """
    fav = _form_summary(fav_results)
    out = _form_summary(out_results)
    data = {"favorite": fav, "outsider": out}
    n = config.FORM_MATCHES
    if fav["count"] < n or out["count"] < n:
        return CriterionResult("Forme", NEUTRAL, f"Moins de {n} matchs disponibles", data)
    status = FAVORABLE if fav["points"] > out["points"] else UNFAVORABLE
    return CriterionResult("Forme", status, None, data)


# --- Critère 3 : confrontations directes ------------------------------------------
@dataclass
class H2HMatch:
    date: str | None
    home: str
    away: str
    home_goals: int
    away_goals: int
    winner: str | None  # "favorite" | "outsider" | None (nul)


def h2h_criterion(matches: list[H2HMatch] | None) -> CriterionResult:
    """5 dernières confrontations : favorable si victoires favori > victoires outsider."""
    last = (matches or [])[: config.H2H_MATCHES]
    fav_w = sum(1 for m in last if m.winner == "favorite")
    out_w = sum(1 for m in last if m.winner == "outsider")
    draws = len(last) - fav_w - out_w
    data = {
        "count": len(last),
        "favorite_wins": fav_w if matches is not None else None,
        "outsider_wins": out_w if matches is not None else None,
        "draws": draws if matches is not None else None,
        "matches": [asdict(m) for m in last],
    }
    if matches is None:
        return CriterionResult("H2H", NEUTRAL, "H2H N/D", data)
    if len(last) < config.MIN_H2H_MATCHES:
        return CriterionResult("H2H", NEUTRAL, "données insuffisantes", data)
    return CriterionResult("H2H", FAVORABLE if fav_w > out_w else UNFAVORABLE, None, data)


# --- Score, verdict, probabilité -------------------------------------------------
def confirmation_score(results: list[CriterionResult]) -> int:
    return sum(1 for r in results if r.status == FAVORABLE)


def verdict(score: int) -> str:
    if score >= 3:
        return VERDICT_CONFIRMED
    if score == 2:
        return VERDICT_LIKELY
    return VERDICT_FRAGILE


def implied_probability(odds_favorite: float | None, odds_draw: float | None, odds_other: float | None) -> float | None:
    """Probabilité implicite démarginée : (1/cote) / somme(1/cote des 3 issues)."""
    if None in (odds_favorite, odds_draw, odds_other) or min(odds_favorite, odds_draw, odds_other) <= 1.0:
        return None
    inv = [1 / odds_favorite, 1 / odds_draw, 1 / odds_other]
    return inv[0] / sum(inv)
