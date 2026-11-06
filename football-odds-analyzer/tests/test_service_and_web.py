"""Test de bout en bout hors ligne : API-Football simulée (httpx.MockTransport) + routes web."""
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from analysis.api_football import ApiFootballClient
from analysis.service import analyze_match
from database import Match, RejectedMatch, now_local, session_scope
from tests.conftest import reset_db


def fx(date, home, away, gh, ga):
    return {
        "fixture": {"date": f"{date}T15:00:00+00:00", "status": {"short": "FT"}},
        "teams": {"home": {"id": home[0], "name": home[1], "winner": gh > ga if gh != ga else None},
                  "away": {"id": away[0], "name": away[1], "winner": ga > gh if gh != ga else None}},
        "goals": {"home": gh, "away": ga},
    }


ARS, BUR, X = (42, "Arsenal"), (44, "Burnley"), (1, "Other")
CALLS = []


def handler(request: httpx.Request) -> httpx.Response:
    CALLS.append(str(request.url))
    p, q = request.url.path, dict(request.url.params)
    if p == "/leagues":
        data = [{"league": {"id": 39}, "seasons": [{"year": 2026, "current": True}]}]
    elif p == "/teams":
        data = [{"team": {"id": 42, "name": "Arsenal"}}, {"team": {"id": 44, "name": "Burnley"}}]
    elif p == "/standings":
        data = [{"league": {"standings": [[
            {"rank": 1, "team": {"id": 42}, "points": 27, "all": {"played": 11}},
            {"rank": 19, "team": {"id": 44}, "points": 6, "all": {"played": 11}},
        ]]}}]
    elif p == "/fixtures" and q["team"] == "42":
        data = [fx("2026-11-01", ARS, X, 2, 0), fx("2026-10-25", X, ARS, 1, 1), fx("2026-10-18", ARS, X, 3, 1)]
    elif p == "/fixtures" and q["team"] == "44":
        data = [fx("2026-11-01", BUR, X, 0, 2), fx("2026-10-25", X, BUR, 1, 0), fx("2026-10-18", BUR, X, 1, 1)]
    elif p == "/fixtures/headtohead":
        data = [fx("2025-03-01", ARS, BUR, 3, 0), fx("2024-10-01", BUR, ARS, 1, 1), fx("2024-02-01", BUR, ARS, 0, 2)]
    else:
        return httpx.Response(404)
    return httpx.Response(200, json={"errors": [], "response": data})


@pytest.fixture(scope="module")
def match_id():
    reset_db()
    with session_scope() as s:
        s.add(Match(id="AbCd1234", kickoff=now_local() + timedelta(days=1), country="Angleterre",
                    league="Premier League", league_path="england/premier-league", tier=1,
                    home="Arsenal", away="Burnley", odds_home=1.35, odds_draw=5.2, odds_away=8.5,
                    odds_source="pinnacle", favorite_side="home", favorite="Arsenal", outsider="Burnley",
                    extracted_at=now_local()))
        s.add(Match(id="NoTeam01", kickoff=now_local() + timedelta(days=1), country="Angleterre",
                    league="Premier League", league_path="england/premier-league", tier=1,
                    home="Unknown United", away="Arsenal", odds_home=7.0, odds_draw=4.8, odds_away=1.45,
                    odds_source="average", favorite_side="away", favorite="Arsenal", outsider="Unknown United",
                    extracted_at=now_local()))
    return "AbCd1234"


def test_analysis_3_of_3_and_cache(match_id):
    client = ApiFootballClient(api_key="k", transport=httpx.MockTransport(handler))
    with session_scope() as s:
        a = analyze_match(s.get(Match, match_id), client, s)
        assert a.error is None
        assert a.score == 3 and a.verdict == "Favori confirmé"
        crit = {c["name"]: c for c in a.details["criteria"]}
        assert crit["Classement"]["data"]["rank_gap"] == 18
        assert crit["Forme"]["data"]["favorite"]["sequence"] == "VNV"
        assert crit["Forme"]["data"]["outsider"]["sequence"] == "DDN"
        assert crit["H2H"]["data"]["favorite_wins"] == 2
        assert 0.6 < a.implied_probability < 0.74
    n = len(CALLS)
    with session_scope() as s:  # 2e analyse : tout vient du cache, aucun appel réseau
        analyze_match(s.get(Match, match_id), client, s)
    assert len(CALLS) == n


def test_unmatched_team_logged(match_id):
    client = ApiFootballClient(api_key="k", transport=httpx.MockTransport(handler))
    with session_scope() as s:
        a = analyze_match(s.get(Match, "NoTeam01"), client, s)
        assert a.error and "Unknown United" in a.error and a.verdict == "Analyse impossible"
    with session_scope() as s:
        assert s.query(RejectedMatch).filter_by(match_key="NoTeam01", reason_code="equipe_non_rapprochee").count() == 1


def test_web_pages(match_id):
    from api.main import app

    with TestClient(app) as web:
        r = web.get("/")
        assert r.status_code == 200 and "Arsenal" in r.text and "odd-fav" in r.text
        assert web.get("/?fav_max=1.30").text.count("AbCd1234") == 0  # seuil plus strict
        r = web.get("/analyse")
        assert r.status_code == 200 and "3/3" in r.text and "Favori confirmé" in r.text and "N/D" in r.text
        full = web.get("/analyse?only_full=1").text
        assert "m-AbCd1234" in full and "m-NoTeam01" not in full
        csv = web.get("/analyse/export.csv?only_full=1")
        assert csv.status_code == 200 and "Favori confirmé" in csv.text and "Unknown" not in csv.text
        assert "non rapproch" in web.get("/rejets").text
        assert web.get("/aliases").status_code == 200
        r = web.post("/aliases", data={"oddsportal_name": "Unknown United", "api_team_id": 44,
                                        "api_team_name": "Burnley"}, follow_redirects=True)
        assert "Unknown United" in r.text and "manuel" in r.text
        assert web.get("/api/matches").json()[0]["id"] in {"AbCd1234", "NoTeam01"}
