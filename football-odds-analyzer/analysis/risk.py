"""Profil de risque d'un favori, à partir des données connues AVANT le match.

Signaux observés sur le bilan du 6 au 8 novembre 2026 (108 matchs, 14 défaites du favori).
Ce sont des hypothèses à confirmer avec le bilan quotidien, pas des règles établies :

  * cote du favori >= 1.60 ;
  * favori ayant encaissé >= 5 buts sur ses 3 derniers matchs de championnat ;
  * outsider avec au moins autant de points que le favori sur les 3 derniers matchs ;
  * outsider vainqueur d'au moins 2 des 5 dernières confrontations ;
  * favori hors du top 5 ;
  * écart de rang <= 5 places.

Profil :
  « à risque » : cote >= 1.60 ET (défense du favori fragile OU outsider au moins aussi en forme)
  « sûr »      : cote < 1.60 ET aucun de ces deux signaux de forme
  « intermédiaire » : le reste ; « N/D » si la forme n'est pas connue.
"""
from __future__ import annotations

RISK_ODDS = 1.60
RISK_CONCEDED = 5
RISK_H2H_OUT_WINS = 2
RISK_TOP = 5
RISK_RANK_GAP = 5

PROFILE_RISKY = "à risque"
PROFILE_SAFE = "sûr"
PROFILE_MID = "intermédiaire"
PROFILE_NA = "N/D"


def _form_points(form: list[dict] | None) -> int | None:
    if not form:
        return None
    last = form[:3]
    return sum(3 if x["gf"] > x["ga"] else 1 if x["gf"] == x["ga"] else 0 for x in last)


def _conceded(form: list[dict] | None) -> int | None:
    return None if not form else sum(x["ga"] for x in form[:3])


def risk_profile(fav_odds: float | None, sports: dict | None) -> dict:
    """`sports` au format de l'instantané : {fav:{rank,points,played,form:[{gf,ga}]}, out:{...}, h2h:[{fg,og}]}."""
    sp = sports or {}
    f, o = sp.get("fav") or {}, sp.get("out") or {}
    signals: list[str] = []

    if fav_odds is not None and fav_odds >= RISK_ODDS:
        signals.append(f"cote du favori ≥ {RISK_ODDS:.2f}")
    conceded = _conceded(f.get("form"))
    weak_defence = conceded is not None and conceded >= RISK_CONCEDED
    if weak_defence:
        signals.append(f"favori : {conceded} buts encaissés sur 3 matchs")
    fp, op = _form_points(f.get("form")), _form_points(o.get("form"))
    out_in_form = fp is not None and op is not None and op >= fp
    if out_in_form:
        signals.append(f"outsider aussi en forme ({op} pts contre {fp})")
    h2h = sp.get("h2h")
    if h2h:
        out_wins = sum(1 for x in h2h[:5] if x["og"] > x["fg"])
        if out_wins >= RISK_H2H_OUT_WINS:
            signals.append(f"outsider vainqueur de {out_wins} des {min(len(h2h), 5)} derniers H2H")
    fr, orr = f.get("rank"), o.get("rank")
    if fr is not None and fr > RISK_TOP:
        signals.append(f"favori {fr}e seulement")
    if fr is not None and orr is not None and orr - fr <= RISK_RANK_GAP:
        signals.append(f"écart de rang de {orr - fr} place(s)")

    if fp is None or op is None or fav_odds is None:
        profile = PROFILE_NA
    elif fav_odds >= RISK_ODDS and (weak_defence or out_in_form):
        profile = PROFILE_RISKY
    elif fav_odds < RISK_ODDS and not weak_defence and not out_in_form:
        profile = PROFILE_SAFE
    else:
        profile = PROFILE_MID
    return {"profile": profile, "signals": signals}
