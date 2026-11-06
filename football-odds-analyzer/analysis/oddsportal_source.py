"""Analyse des 3 critères à partir des données d'OddsPortal (sans API externe).

* Classement + Forme : page /football/<pays>/<ligue>/standings/ (rang, matchs joués, points,
  derniers résultats de championnat avec score et date).
* H2H : section « H2H Results » de la page du match (déjà ouverte pour les cotes).

Les équipes sont reconnues par leur identifiant OddsPortal (présent dans l'URL du match et dans
le classement) : aucun rapprochement approximatif n'est nécessaire dans le cas normal.
"""
from __future__ import annotations

from dataclasses import asdict

from rapidfuzz import fuzz

import config
from analysis import criteria as C
from analysis.team_matching import normalize_team
from scraper.parsers import H2HResult, StandingEntry, team_ids_from_url

SOURCE = "OddsPortal"


def _same(a: str, b: str) -> bool:
    return normalize_team(a) == normalize_team(b) or fuzz.WRatio(normalize_team(a), normalize_team(b)) >= 92


def _assign_entries(url: str | None, home: str, away: str,
                    standings: dict[str, StandingEntry]) -> tuple[StandingEntry | None, StandingEntry | None]:
    """Retourne (entrée domicile, entrée extérieur) du classement."""
    ids = team_ids_from_url(url)
    found = [standings.get(i) for i in ids] if ids else []
    found = [e for e in found if e is not None]
    h = next((e for e in found if _same(e.name, home)), None)
    a = next((e for e in found if e is not h and _same(e.name, away)), None)
    if len(found) == 2 and (h is None) != (a is None):  # un seul nom reconnu : l'autre est l'autre
        h = h or next(e for e in found if e is not a)
        a = a or next(e for e in found if e is not h)
    if h is None or a is None:  # repli sur les noms (URL sans ID, équipe absente...)
        by_name = list(standings.values())
        h = h or next((e for e in by_name if _same(e.name, home)), None)
        a = a or next((e for e in by_name if e is not h and _same(e.name, away)), None)
    return h, a


def _form(entry: StandingEntry | None) -> tuple[list[C.FixtureResult] | None, list[dict]]:
    if entry is None:
        return None, []
    results, display = [], []
    for fm in entry.form[: config.FORM_MATCHES]:
        is_home = _same(fm.home, entry.name) if not _same(fm.away, entry.name) else False
        gf, ga = (fm.home_goals, fm.away_goals) if is_home else (fm.away_goals, fm.home_goals)
        r = C.FixtureResult(gf, ga)
        results.append(r)
        display.append({"date": fm.date, "opponent": fm.away if is_home else fm.home,
                        "venue": "D" if is_home else "E", "score": f"{gf}-{ga}", "outcome": r.outcome})
    return results, display


def _h2h(results: list[H2HResult] | None, favorite: str, outsider: str) -> list[C.H2HMatch] | None:
    if results is None:
        return None
    out = []
    for r in results[: config.H2H_MATCHES]:
        fav_home = _same(r.home, favorite) or (not _same(r.away, favorite) and _same(r.away, outsider))
        fg, og = (r.home_goals, r.away_goals) if fav_home else (r.away_goals, r.home_goals)
        winner = "favorite" if fg > og else "outsider" if og > fg else None
        out.append(C.H2HMatch(date=r.date, home=r.home, away=r.away,
                              home_goals=r.home_goals, away_goals=r.away_goals, winner=winner))
    return out


def build_analysis(*, home: str, away: str, favorite_side: str, url: str | None,
                   odds: tuple[float | None, float | None, float | None],
                   standings: dict[str, StandingEntry] | None,
                   h2h: list[H2HResult] | None) -> dict:
    """Calcule score, verdict, probabilité implicite et détails (même format que l'analyse API-Football)."""
    favorite, outsider = (home, away) if favorite_side == "home" else (away, home)
    o1, ox, o2 = odds
    fav_odds, out_odds = (o1, o2) if favorite_side == "home" else (o2, o1)
    implied = C.implied_probability(fav_odds, ox, out_odds)

    notes = []
    h_entry = a_entry = None
    if standings:
        h_entry, a_entry = _assign_entries(url, home, away, standings)
        if h_entry is None or a_entry is None:
            notes.append("équipe absente du classement OddsPortal")
    else:
        notes.append("classement OddsPortal N/D")
    fav_e, out_e = (h_entry, a_entry) if favorite_side == "home" else (a_entry, h_entry)

    row = lambda e: C.StandingRow(e.rank, e.points, e.played) if e else None  # noqa: E731
    c1 = C.standings_criterion(row(fav_e), row(out_e))
    fav_res, fav_disp = _form(fav_e)
    out_res, out_disp = _form(out_e)
    c2 = C.form_criterion(fav_res, out_res)
    c2.data["favorite"]["matches"] = fav_disp
    c2.data["outsider"]["matches"] = out_disp
    c3 = C.h2h_criterion(_h2h(h2h, favorite, outsider))
    if h2h is None:
        notes.append("page du match non lue (H2H N/D)")

    results = [c1, c2, c3]
    score = C.confirmation_score(results)
    return {
        "score": score,
        "verdict": C.verdict(score),
        "implied_probability": implied,
        "error": None,
        "details": {
            "source": SOURCE,
            "notes": notes,
            "teams": {"favorite": {"id": (fav_e.team_id if fav_e else None), "name": favorite},
                      "outsider": {"id": (out_e.team_id if out_e else None), "name": outsider}},
            "criteria": [r.to_dict() for r in results],
        },
    }


__all__ = ["build_analysis", "SOURCE", "asdict"]
