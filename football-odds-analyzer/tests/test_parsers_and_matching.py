from datetime import date

from analysis.team_matching import match_team, normalize_team
from scraper.parsers import parse_average_odds, parse_bookmaker_odds, parse_listing, parse_odds
from tests.conftest import FIXTURES


def test_parse_odds_formats():
    assert parse_odds("1.65") == 1.65
    assert parse_odds("+150") == 2.5
    assert parse_odds("-200") == 1.5
    assert parse_odds("5/2") == 3.5
    assert parse_odds("-") is None
    assert parse_odds("95.1%") is None


def test_parse_listing_fixture():
    matches = parse_listing((FIXTURES / "listing.html").read_text(), date(2026, 11, 7))
    ids = [m.match_id for m in matches]
    assert ids == ["AbCd1234", "ZyXw9876", "QqQq1111"]  # le match terminé (FT) est ignoré
    ars = matches[0]
    assert (ars.home, ars.away) == ("Arsenal", "Burnley")
    assert (ars.odds_home, ars.odds_draw, ars.odds_away) == (1.35, 5.20, 8.50)
    assert ars.league_path == "england/premier-league" and ars.league_label == "Premier League"
    assert ars.kickoff.hour == 15 and str(ars.kickoff.tzinfo) == "America/Toronto"
    # l'en-tête de ligue est propagé aux lignes suivantes
    assert matches[1].league_label == "Premier League" and matches[1].odds_away == 1.55
    assert matches[2].league_path == "england/fa-cup"


def test_parse_pinnacle_and_average():
    html = (FIXTURES / "match.html").read_text()
    assert parse_bookmaker_odds(html, "Pinnacle") == [1.38, 5.40, 9.20]
    assert parse_bookmaker_odds(html, "Unibet") is None
    assert parse_average_odds(html) == [1.35, 5.20, 8.70]


# --- rapprochement des noms ----------------------------------------------------------------
CANDIDATES = [(33, "Manchester United"), (50, "Manchester City"), (47, "Tottenham"),
              (157, "Bayern München"), (85, "Paris Saint Germain"), (529, "Barcelona"),
              (541, "Real Madrid"), (530, "Atletico Madrid")]


def test_normalize_team():
    assert normalize_team("Man Utd") == "manchester united"
    assert normalize_team("FC Barcelona") == "barcelona"


def test_match_team_variants():
    assert match_team("Manchester Utd", CANDIDATES).team_id == 33
    assert match_team("Man City", CANDIDATES).team_id == 50
    assert match_team("Bayern Munich", CANDIDATES).team_id == 157
    assert match_team("PSG", CANDIDATES).team_id == 85
    assert match_team("Atl. Madrid", CANDIDATES).team_id == 530
    assert match_team("Real Madrid", CANDIDATES).team_id == 541


def test_match_team_unknown_or_ambiguous():
    assert match_team("Leeds", CANDIDATES) is None
    assert match_team("Manchester", CANDIDATES) is None  # ambigu


def test_alias_has_priority():
    m = match_team("Spurs FC", CANDIDATES, aliases={"Spurs FC": (47, "Tottenham")})
    assert m.team_id == 47 and m.via_alias
