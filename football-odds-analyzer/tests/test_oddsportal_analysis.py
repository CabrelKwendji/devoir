"""Analyse à partir d'OddsPortal : classement, forme (page standings) et H2H (page du match)."""
from datetime import date

from analysis.oddsportal_source import build_analysis
from scraper.parsers import parse_h2h, parse_standings, team_ids_from_url
from tests.conftest import FIXTURES

URL = "https://www.oddsportal.com/football/h2h/arsenal-hA1Zm19f/burnley-S66R0t75/#AbCd1234"


def standings():
    return parse_standings((FIXTURES / "standings.html").read_text())


def h2h():
    return parse_h2h((FIXTURES / "match.html").read_text(), today=date(2026, 11, 6))


def test_parse_standings():
    t = standings()
    ars = t["hA1Zm19f"]
    assert (ars.name, ars.rank, ars.played, ars.points) == ("Arsenal", 1, 9, 24)
    assert len(ars.form) == 4  # « Next match » ignoré
    assert ars.form[0].date == "2026-11-01" and (ars.form[0].home, ars.form[0].away_goals) == ("Liverpool", 1)


def test_parse_h2h_with_season_years():
    rows = h2h()
    assert [(r.date, r.home, r.home_goals, r.away_goals) for r in rows] == [
        ("2025-02-11", "Arsenal", 2, 0), ("2024-09-17", "Burnley", 1, 1), ("2024-03-08", "Burnley", 0, 4)]
    assert rows[2].competition == "FA Cup 2023/2024"


def test_team_ids_from_url():
    assert team_ids_from_url(URL) == ("hA1Zm19f", "S66R0t75")


def test_build_analysis_3_of_3():
    a = build_analysis(home="Arsenal", away="Burnley", favorite_side="home", url=URL,
                       odds=(1.35, 5.2, 8.5), standings=standings(), h2h=h2h())
    crit = {c["name"]: c for c in a["details"]["criteria"]}
    assert crit["Classement"]["status"] == "favorable" and crit["Classement"]["data"]["rank_gap"] == 16
    assert crit["Forme"]["data"]["favorite"]["sequence"] == "VVN"  # 0:1 à Liverpool, 2:0, 1:1
    assert crit["Forme"]["data"]["outsider"]["sequence"] == "DND"
    assert crit["H2H"]["data"]["favorite_wins"] == 2 and crit["H2H"]["data"]["draws"] == 1
    assert a["score"] == 3 and a["verdict"] == "Favori confirmé" and a["details"]["source"] == "OddsPortal"


def test_build_analysis_away_favorite_and_missing_data():
    # favori à l'extérieur, classement absent, H2H non lu : tout reste N/D / neutre
    a = build_analysis(home="Burnley", away="Arsenal", favorite_side="away", url=None,
                       odds=(8.5, 5.2, 1.35), standings=None, h2h=None)
    assert a["score"] == 0
    assert all(c["status"] == "neutre" for c in a["details"]["criteria"])
    assert a["details"]["notes"]
    assert a["implied_probability"] is not None
