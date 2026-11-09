from analysis.risk import PROFILE_MID, PROFILE_NA, PROFILE_RISKY, PROFILE_SAFE, risk_profile


def sports(fav_form, out_form, fav_rank=2, out_rank=15, h2h=None):
    return {"fav": {"rank": fav_rank, "points": 20, "played": 10, "form": fav_form},
            "out": {"rank": out_rank, "points": 8, "played": 10, "form": out_form},
            "h2h": h2h}


W, D, L = {"gf": 2, "ga": 0}, {"gf": 1, "ga": 1}, {"gf": 0, "ga": 3}


def test_safe_profile():
    r = risk_profile(1.35, sports([W, W, D], [L, D, L]))
    assert r["profile"] == PROFILE_SAFE and r["signals"] == []


def test_risky_high_odds_and_weak_defence():
    r = risk_profile(1.65, sports([L, L, W], [L, L, L]))  # 6 buts encaissés
    assert r["profile"] == PROFILE_RISKY
    assert any("encaissés" in s for s in r["signals"]) and any("cote" in s for s in r["signals"])


def test_risky_high_odds_and_outsider_in_form():
    r = risk_profile(1.62, sports([W, D, D], [W, W, D]))
    assert r["profile"] == PROFILE_RISKY and any("outsider aussi en forme" in s for s in r["signals"])


def test_intermediate_and_other_signals():
    r = risk_profile(1.45, sports([W, D, D], [W, W, D], fav_rank=7, out_rank=10,
                                  h2h=[{"fg": 0, "og": 1}, {"fg": 1, "og": 2}, {"fg": 1, "og": 1}]))
    assert r["profile"] == PROFILE_MID
    joined = " ".join(r["signals"])
    assert "7e seulement" in joined and "écart de rang de 3" in joined and "2 des 3 derniers H2H" in joined


def test_missing_form_is_na():
    assert risk_profile(1.50, None)["profile"] == PROFILE_NA
