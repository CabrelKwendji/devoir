from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scraper.filters import (
    REJECT_CUP, REJECT_ODDS, REJECT_ODDS_MISSING, REJECT_TIER, REJECT_UNLISTED,
    evaluate_match, is_cup_competition, odds_within_thresholds, pick_favorite,
)
from scraper.leagues import LeagueInfo, load_leagues, normalize_path
from scraper.models import RawMatch

TZ = ZoneInfo("America/Toronto")
LEAGUES = {
    "england/premier-league": LeagueInfo("england/premier-league", "Premier League", "Angleterre", 1, 39),
    "england/championship": LeagueInfo("england/championship", "Championship", "Angleterre", 2, 40),
    "england/league-one": LeagueInfo("england/league-one", "League One", "Angleterre", 3),
}


def raw(path="england/premier-league", label="Premier League", country="England", odds=(1.40, 5.0, 8.0)):
    return RawMatch("id1", None, datetime(2026, 11, 7, 15, 0, tzinfo=TZ), path, country, label,
                    "Home FC", "Away FC", *odds)


# --- seuils de cotes -----------------------------------------------------------
@pytest.mark.parametrize("home,away,expected", [
    (1.40, 8.0, True),    # favori à domicile
    (8.0, 1.40, True),    # favori à l'extérieur
    (1.70, 8.0, False),   # 1.70 n'est pas < 1.70
    (1.69, 4.00, False),  # 4.00 n'est pas > 4.00
    (1.69, 4.01, True),
    (2.10, 3.20, False),
])
def test_odds_thresholds(home, away, expected):
    assert odds_within_thresholds(home, away, 1.70, 4.00) is expected


def test_pick_favorite_home_or_away():
    assert pick_favorite(1.5, 6.0) == "home"
    assert pick_favorite(6.0, 1.5) == "away"


# --- coupes ----------------------------------------------------------------------
@pytest.mark.parametrize("path,label,country", [
    ("england/fa-cup", "FA Cup", "England"),
    ("england/league-cup", "League Cup", "England"),
    ("france/coupe-de-france", "Coupe de France", "France"),
    ("germany/dfb-pokal", "DFB Pokal", "Germany"),
    ("spain/copa-del-rey", "Copa del Rey", "Spain"),
    ("italy/coppa-italia", "Coppa Italia", "Italy"),
    ("europe/champions-league", "Champions League", "Europe"),
    ("europe/europa-league", "Europa League", "Europe"),
    ("world/world-cup-2026", "World Cup", "World"),
    ("world/club-friendly", "Club Friendlies", "World"),
    ("england/championship", "Championship - Play Offs", "England"),
    ("netherlands/eredivisie", "Eredivisie - Relegation Play-offs", "Netherlands"),
    ("europe/euro-2028-qualification", "Euro 2028 Qualification", "Europe"),
    ("england/community-shield", "Community Shield", "England"),
])
def test_cups_are_detected(path, label, country):
    assert is_cup_competition(path, label, country)


@pytest.mark.parametrize("path,label", [
    ("england/premier-league", "Premier League"),
    ("england/championship", "Championship"),
    ("scotland/premiership", "Premiership"),
    ("france/ligue-1", "Ligue 1"),
    ("denmark/superliga", "Superliga"),
    ("usa/usl-championship", "USL Championship"),
])
def test_leagues_are_not_cups(path, label):
    assert not is_cup_competition(path, label)


# --- évaluation complète ----------------------------------------------------------
def test_kept_match():
    res = evaluate_match(raw(), LEAGUES)
    assert res.kept and res.favorite_side == "home" and res.league.tier == 1


def test_away_favorite_kept():
    res = evaluate_match(raw(odds=(7.5, 4.8, 1.45)), LEAGUES)
    assert res.kept and res.favorite_side == "away"


def test_cup_rejected_first():
    res = evaluate_match(raw("england/fa-cup", "FA Cup"), LEAGUES)
    assert not res.kept and res.reason_code == REJECT_CUP


def test_unlisted_league_rejected_by_default():
    res = evaluate_match(raw("moldova/super-liga", "Super Liga"), LEAGUES)
    assert res.reason_code == REJECT_UNLISTED


def test_tier_3_rejected():
    res = evaluate_match(raw("england/league-one", "League One"), LEAGUES, max_tier=2)
    assert res.reason_code == REJECT_TIER


def test_tier_2_kept():
    assert evaluate_match(raw("england/championship", "Championship"), LEAGUES).kept


def test_missing_odds_rejected():
    res = evaluate_match(raw(odds=(None, None, None)), LEAGUES)
    assert res.reason_code == REJECT_ODDS_MISSING


def test_odds_out_of_range_rejected():
    res = evaluate_match(raw(odds=(1.90, 3.5, 4.2)), LEAGUES)
    assert res.reason_code == REJECT_ODDS


def test_custom_thresholds():
    assert evaluate_match(raw(odds=(1.90, 3.5, 4.2)), LEAGUES, favorite_max=2.0, outsider_min=4.0).kept


# --- leagues.yaml -------------------------------------------------------------------
def test_normalize_path():
    assert normalize_path("/football/England/Premier-League/") == "england/premier-league"


def test_leagues_yaml_loads_with_aliases():
    idx = load_leagues()
    assert idx["england/premier-league"].tier == 1
    assert idx["spain/primera-division"].name == "LaLiga"  # alias
    assert all(info.tier >= 1 for info in idx.values())
