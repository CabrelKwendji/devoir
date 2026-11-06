"""Analyse d'un match : récupère les données API-Football et applique les 3 critères."""
from __future__ import annotations

import logging

from sqlalchemy import select

import config
from analysis import criteria as C
from analysis.api_football import ApiFootballClient, ApiFootballError, api_country_from_path
from analysis.team_matching import match_team
from database import Analysis, Match, RejectedMatch, TeamAlias, now_local, session_scope
from scraper.filters import REJECT_TEAM, odds_within_thresholds
from scraper.leagues import default_leagues

log = logging.getLogger(__name__)

VERDICT_UNAVAILABLE = "Analyse impossible"


def _aliases(session) -> dict[str, tuple[int, str]]:
    return {a.oddsportal_name: (a.api_team_id, a.api_team_name) for a in session.scalars(select(TeamAlias))}


def _remember_alias(session, op_name: str, team_id: int, team_name: str, score: float) -> None:
    if session.scalar(select(TeamAlias).where(TeamAlias.oddsportal_name == op_name)):
        return
    session.add(TeamAlias(oddsportal_name=op_name, api_team_id=team_id, api_team_name=team_name,
                          is_manual=False, score=score))


def _log_unmatched(session, match: Match, names: list[str]) -> None:
    reason = "Équipe non rapprochée : " + ", ".join(names)
    row = session.scalar(
        select(RejectedMatch).where(RejectedMatch.match_key == match.id, RejectedMatch.reason_code == REJECT_TEAM)
    )
    if row:
        row.reason, row.logged_at = reason, now_local()
        return
    session.add(RejectedMatch(
        match_key=match.id, kickoff=match.kickoff, country=match.country, league=match.league,
        home=match.home, away=match.away, odds_home=match.odds_home, odds_draw=match.odds_draw,
        odds_away=match.odds_away, reason_code=REJECT_TEAM, reason=reason, stage="analyse",
    ))


def _team_results(fixtures: list[dict], team_id: int) -> tuple[list[C.FixtureResult], list[dict]]:
    results, display = [], []
    for f in fixtures[: config.FORM_MATCHES]:
        home, away = f["teams"]["home"], f["teams"]["away"]
        gh, ga = f["goals"]["home"], f["goals"]["away"]
        if gh is None or ga is None:
            continue
        is_home = home["id"] == team_id
        r = C.FixtureResult(goals_for=gh if is_home else ga, goals_against=ga if is_home else gh)
        results.append(r)
        display.append({
            "date": f["fixture"]["date"][:10],
            "opponent": away["name"] if is_home else home["name"],
            "venue": "D" if is_home else "E",
            "score": f"{r.goals_for}-{r.goals_against}",
            "outcome": r.outcome,
        })
    return results, display


def _h2h(fixtures: list[dict], fav_id: int, out_id: int) -> list[C.H2HMatch]:
    out = []
    for f in fixtures:
        home, away = f["teams"]["home"], f["teams"]["away"]
        gh, ga = f["goals"]["home"], f["goals"]["away"]
        if gh is None or ga is None:
            continue
        winner = None
        if home.get("winner") is True:
            winner = home["id"]
        elif away.get("winner") is True:
            winner = away["id"]
        out.append(C.H2HMatch(
            date=f["fixture"]["date"][:10], home=home["name"], away=away["name"],
            home_goals=gh, away_goals=ga,
            winner="favorite" if winner == fav_id else "outsider" if winner == out_id else None,
        ))
    return out


def analyze_match(match: Match, client: ApiFootballClient, session) -> Analysis:
    analysis = session.get(Analysis, match.id) or Analysis(match_id=match.id)
    fav_odds = match.favorite_odds
    out_odds = match.outsider_odds
    analysis.implied_probability = C.implied_probability(fav_odds, match.odds_draw, out_odds)
    analysis.computed_at = now_local()
    details: dict = {"criteria": [], "teams": {}}

    def fail(message: str) -> Analysis:
        analysis.score, analysis.verdict, analysis.error = 0, VERDICT_UNAVAILABLE, message
        analysis.details = details
        session.add(analysis)
        return analysis

    league = default_leagues().get(match.league_path)
    try:
        league_id = (league.api_football_id if league else None) or client.find_league(
            api_country_from_path(match.league_path), match.league
        )
        if not league_id:
            return fail(f"Ligue introuvable chez API-Football ({match.league}) : renseigner api_football_id dans leagues.yaml")
        season = client.current_season(league_id)
        if season is None:
            return fail("Saison en cours N/D chez API-Football")
        details.update({"league_id": league_id, "season": season})

        candidates = client.teams(league_id, season)
        aliases = _aliases(session)
        fav_m = match_team(match.favorite, candidates, aliases)
        out_m = match_team(match.outsider, candidates, aliases)
        unmatched = [n for n, m in ((match.favorite, fav_m), (match.outsider, out_m)) if m is None]
        if unmatched:
            _log_unmatched(session, match, unmatched)
            return fail("Équipe non rapprochée : " + ", ".join(unmatched) + " (ajouter un alias dans /aliases)")
        details["teams"] = {
            "favorite": {"id": fav_m.team_id, "name": fav_m.team_name},
            "outsider": {"id": out_m.team_id, "name": out_m.team_name},
        }

        table = client.standings(league_id, season)
        def row(tid):
            r = table.get(tid)
            return C.StandingRow(r["rank"], r["points"], r["played"]) if r else None
        c1 = C.standings_criterion(row(fav_m.team_id), row(out_m.team_id))

        fav_fx = client.league_fixtures(fav_m.team_id, league_id, season)
        out_fx = client.league_fixtures(out_m.team_id, league_id, season)
        fav_res, fav_disp = _team_results(fav_fx, fav_m.team_id)
        out_res, out_disp = _team_results(out_fx, out_m.team_id)
        c2 = C.form_criterion(fav_res, out_res)
        c2.data["favorite"]["matches"] = fav_disp
        c2.data["outsider"]["matches"] = out_disp

        c3 = C.h2h_criterion(_h2h(client.head_to_head(fav_m.team_id, out_m.team_id), fav_m.team_id, out_m.team_id))
    except ApiFootballError as exc:
        return fail(str(exc))

    # Écritures en base seulement après les appels API (SQLite : un seul écrivain à la fois,
    # et le cache API écrit dans sa propre session).
    for name, m in ((match.favorite, fav_m), (match.outsider, out_m)):
        if not m.via_alias:
            _remember_alias(session, name, m.team_id, m.team_name, m.score)

    results = [c1, c2, c3]
    analysis.score = C.confirmation_score(results)
    analysis.verdict = C.verdict(analysis.score)
    analysis.error = None
    details["criteria"] = [r.to_dict() for r in results]
    analysis.details = details
    session.add(analysis)
    return analysis


def analyze_ids(match_ids: list[str]) -> int:
    n = 0
    with ApiFootballClient() as client:
        for mid in match_ids:
            with session_scope() as s:
                m = s.get(Match, mid)
                if m is None:
                    continue
                analyze_match(m, client, s)
                n += 1
    return n


def analyze_pending(favorite_max: float = config.FAVORITE_MAX_ODDS,
                    outsider_min: float = config.OUTSIDER_MIN_ODDS) -> int:
    """Analyse tous les matchs à venir qui respectent les seuils (le cache API limite les appels)."""
    with session_scope() as s:
        ids = [
            m.id for m in s.scalars(select(Match).where(Match.kickoff >= now_local())).all()
            if m.odds_home and m.odds_away and odds_within_thresholds(m.odds_home, m.odds_away, favorite_max, outsider_min)
        ]
    return analyze_ids(ids)
