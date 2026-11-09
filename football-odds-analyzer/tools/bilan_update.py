"""Mise à jour quotidienne du bilan cumulé (document `oddsportal/bilan` de l'artefact).

Usage :
    python -m tools.bilan_update --prev ancien_latest.json [--bilan bilan_actuel.json] --out nouveau_bilan.json

* `--prev` : l'instantané de la veille (document `oddsportal/latest` lu AVANT d'être remplacé) :
  ce sont les prédictions faites avant les matchs.
* Les matchs de ces prédictions dont la date est antérieure à aujourd'hui (heure de Toronto) et
  qui ne figurent pas déjà dans le bilan sont évalués : résultat lu en ligne sur OddsPortal.
* Le résumé (taux de victoire / d'invincibilité par score, profil de risque, critère, cote...)
  est recalculé sur l'ensemble des matchs du bilan.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import config
from tools.results_check import evaluate, fetch_results, load_predictions, summarize

log = logging.getLogger(__name__)
MAX_ROWS = 2500  # limite de taille du document (environ 1 Mio)
KEEP = ("id", "kickoff", "country", "league", "tier", "home", "away", "favorite", "fav_home", "fav_odds",
        "odds", "implied", "score", "verdict", "statuses", "risk", "risk_signals", "final", "fav_result")


def _compact(r: dict) -> dict:
    out = {k: r.get(k) for k in KEEP}
    if out["implied"] is not None:
        out["implied"] = round(out["implied"], 4)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prev", action="append", required=True, help="instantané(s) de prédictions")
    ap.add_argument("--bilan", help="bilan cumulé existant (JSON du document oddsportal/bilan)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--before", help="évaluer les matchs antérieurs à cette date AAAA-MM-JJ (défaut : aujourd'hui à Toronto)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")

    old = {}
    if args.bilan and Path(args.bilan).exists():
        old = json.loads(Path(args.bilan).read_text(encoding="utf-8"))
        old = old.get("data", old)
    rows = {r["id"]: r for r in old.get("matches", [])}

    today = date.fromisoformat(args.before) if args.before else datetime.now(ZoneInfo(config.TIMEZONE)).date()
    preds = load_predictions(args.prev, config.FAVORITE_MAX_ODDS, config.OUTSIDER_MIN_ODDS)
    preds = {k: v for k, v in preds.items()
             if k not in rows and date.fromisoformat(v["kickoff"][:10]) < today}
    days = sorted({date.fromisoformat(v["kickoff"][:10]) for v in preds.values()})
    log.info("%d match(s) à évaluer sur %s", len(preds), [d.isoformat() for d in days])

    added, pending = [], []
    if preds:
        results = asyncio.run(fetch_results(days, preds))
        added, pending = evaluate(preds, results)
    for r in added:
        rows[r["id"]] = _compact(r)

    ordered = sorted(rows.values(), key=lambda r: r["kickoff"], reverse=True)[:MAX_ROWS]
    report = {
        "updated_at": datetime.now(ZoneInfo(config.TIMEZONE)).isoformat(timespec="seconds"),
        "first_day": ordered[-1]["kickoff"][:10] if ordered else None,
        "last_day": ordered[0]["kickoff"][:10] if ordered else None,
        "evaluated": len(ordered),
        "thresholds": {"favorite_max": config.FAVORITE_MAX_ODDS, "outsider_min": config.OUTSIDER_MIN_ODDS},
        "last_run": {"days": [d.isoformat() for d in days], "added": len(added),
                     "not_found": [{"id": p["id"], "match": f"{p['home']} - {p['away']}", "status": p["status"]}
                                   for p in pending]},
        "summary": summarize(ordered) if ordered else {},
        "matches": ordered,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    g = report["summary"].get("global", {})
    print(f"Bilan : {len(added)} ajouté(s), {len(pending)} sans score, {len(ordered)} au total ; "
          f"victoire {g.get('pct_victoire')} %, invaincu {g.get('pct_invaincu')} % -> {args.out}")


if __name__ == "__main__":
    main()
