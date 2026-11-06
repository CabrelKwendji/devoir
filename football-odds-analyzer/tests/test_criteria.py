import pytest

from analysis import criteria as C


def fr(gf, ga):
    return C.FixtureResult(gf, ga)


# --- Critère 1 : classement ----------------------------------------------------------
def test_standings_favorable():
    r = C.standings_criterion(C.StandingRow(2, 25, 10), C.StandingRow(15, 9, 10))
    assert r.status == C.FAVORABLE
    assert r.data["rank_gap"] == 13 and r.data["points_gap"] == 16
    assert r.note is None


def test_standings_requires_rank_and_points():
    # mieux classé mais moins de points (classement par groupes, matchs en retard...)
    r = C.standings_criterion(C.StandingRow(3, 20, 10), C.StandingRow(5, 21, 11))
    assert r.status == C.UNFAVORABLE


def test_standings_unfavorable():
    r = C.standings_criterion(C.StandingRow(10, 12, 10), C.StandingRow(4, 20, 10))
    assert r.status == C.UNFAVORABLE and r.data["rank_gap"] == -6


def test_standings_low_sample():
    r = C.standings_criterion(C.StandingRow(1, 12, 4), C.StandingRow(18, 1, 4))
    assert r.status == C.FAVORABLE and r.data["low_sample"] and r.note == "échantillon faible"


def test_standings_missing_is_neutral():
    r = C.standings_criterion(None, C.StandingRow(1, 3, 1))
    assert r.status == C.NEUTRAL
    assert r.data["rank_gap"] is None and r.data["favorite_rank"] is None


# --- Critère 2 : forme ---------------------------------------------------------------
def test_form_favorable():
    r = C.form_criterion([fr(2, 0), fr(1, 1), fr(3, 1)], [fr(0, 1), fr(0, 2), fr(1, 1)])
    assert r.status == C.FAVORABLE
    assert r.data["favorite"]["sequence"] == "VNV" and r.data["favorite"]["points"] == 7
    assert r.data["favorite"]["goals_for"] == 6 and r.data["favorite"]["goals_against"] == 2
    assert r.data["outsider"]["sequence"] == "DDN" and r.data["outsider"]["points"] == 1


def test_form_equal_points_is_unfavorable():
    r = C.form_criterion([fr(1, 0), fr(0, 1), fr(1, 1)], [fr(1, 1), fr(2, 0), fr(0, 3)])
    assert r.data["favorite"]["points"] == r.data["outsider"]["points"] == 4
    assert r.status == C.UNFAVORABLE


def test_form_uses_only_last_three():
    r = C.form_criterion([fr(0, 1)] * 3 + [fr(5, 0)] * 5, [fr(1, 0)] * 3)
    assert r.data["favorite"]["count"] == 3 and r.status == C.UNFAVORABLE


def test_form_insufficient_is_neutral():
    r = C.form_criterion([fr(1, 0), fr(2, 0)], [fr(0, 1)] * 3)
    assert r.status == C.NEUTRAL


def test_form_missing_is_neutral():
    r = C.form_criterion(None, None)
    assert r.status == C.NEUTRAL and r.data["favorite"]["sequence"] is None


# --- Critère 3 : H2H -----------------------------------------------------------------
def h(winner):
    return C.H2HMatch("2025-01-01", "A", "B", 1, 0, winner)


def test_h2h_favorable():
    r = C.h2h_criterion([h("favorite"), h("favorite"), h(None), h("outsider"), h("favorite")])
    assert r.status == C.FAVORABLE
    assert (r.data["favorite_wins"], r.data["draws"], r.data["outsider_wins"]) == (3, 1, 1)


def test_h2h_equal_wins_unfavorable():
    assert C.h2h_criterion([h("favorite"), h("outsider"), h(None)]).status == C.UNFAVORABLE


def test_h2h_only_last_five():
    r = C.h2h_criterion([h("outsider")] * 5 + [h("favorite")] * 5)
    assert r.data["count"] == 5 and r.status == C.UNFAVORABLE


def test_h2h_insufficient():
    r = C.h2h_criterion([h("favorite")])
    assert r.status == C.NEUTRAL and r.note == "données insuffisantes"


def test_h2h_missing():
    r = C.h2h_criterion(None)
    assert r.status == C.NEUTRAL and r.data["favorite_wins"] is None


# --- Score, verdict, probabilité ---------------------------------------------------------
@pytest.mark.parametrize("statuses,score,verdict", [
    ([C.FAVORABLE] * 3, 3, C.VERDICT_CONFIRMED),
    ([C.FAVORABLE, C.FAVORABLE, C.NEUTRAL], 2, C.VERDICT_LIKELY),
    ([C.FAVORABLE, C.UNFAVORABLE, C.NEUTRAL], 1, C.VERDICT_FRAGILE),
    ([C.UNFAVORABLE] * 3, 0, C.VERDICT_FRAGILE),
])
def test_score_and_verdict(statuses, score, verdict):
    results = [C.CriterionResult("x", s) for s in statuses]
    assert C.confirmation_score(results) == score
    assert C.verdict(score) == verdict


def test_implied_probability_removes_margin():
    p = C.implied_probability(1.50, 4.20, 6.50)
    inv = [1 / 1.5, 1 / 4.2, 1 / 6.5]
    assert p == pytest.approx(inv[0] / sum(inv))
    assert p < 1 / 1.50  # démarginée : plus faible que 1/cote brute


def test_implied_probability_missing():
    assert C.implied_probability(None, 4.0, 6.0) is None
