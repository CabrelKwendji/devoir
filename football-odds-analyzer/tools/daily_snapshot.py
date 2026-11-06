"""Extraction quotidienne OddsPortal + instantané JSON pour l'artefact « Favori Confirmé ».

Usage :
    python -m tools.daily_snapshot --out data/snapshot.json [--days 3] [--no-scrape]

Le fichier produit est le document `oddsportal/latest` de la base de l'artefact :
  * matches : tous les matchs de championnat éligibles (niveau <= MAX_LEAGUE_TIER) avec cotes,
    pour que la page puisse appliquer ses propres seuils ;
  * rejects : matchs exclus à l'extraction (coupe, non référencé, niveau, cotes N/D) ;
  * analyses (classement, forme, H2H) lues sur OddsPortal, ou API-Football si ANALYSIS_SOURCE=api-football.
Aucune valeur n'est inventée : une donnée absente reste null.
"""
from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path

from sqlalchemy import select

import config
from database import Match, RejectedMatch, ScrapeRun, init_db, now_local, session_scope

MAX_REJECTS = 400
EXTRACTION_REJECT_CODES = {"coupe", "non_reference", "niveau", "cotes_nd"}


def _sports_from_analysis(m: Match) -> dict | None:
    a = m.analysis
    if not a or a.error or not (a.details or {}).get("criteria"):
        return None
    by = {c["name"]: c.get("data") or {} for c in a.details["criteria"]}
    cl, fo, hh = by.get("Classement", {}), by.get("Forme", {}), by.get("H2H")

    def form(side: dict | None):
        rows = (side or {}).get("matches") or []
        out = []
        for x in rows:
            try:
                gf, ga = (int(v) for v in str(x["score"]).split("-"))
                out.append({"gf": gf, "ga": ga})
            except (KeyError, ValueError):
                continue
        return out or None

    h2h = None
    if hh is not None and isinstance(hh.get("matches"), list):
        h2h = []
        for x in hh["matches"]:
            fav_home = (x.get("winner") == "favorite" and x["home_goals"] > x["away_goals"]) or \
                       (x.get("winner") == "outsider" and x["home_goals"] < x["away_goals"]) or \
                       (x.get("winner") is None and x.get("home") == (a.details.get("teams", {}).get("favorite", {}).get("name")))
            h2h.append({"date": x.get("date"),
                        "fg": x["home_goals"] if fav_home else x["away_goals"],
                        "og": x["away_goals"] if fav_home else x["home_goals"]})
    return {
        "fav": {"rank": cl.get("favorite_rank"), "points": cl.get("favorite_points"),
                "played": cl.get("favorite_played"), "form": form(fo.get("favorite"))},
        "out": {"rank": cl.get("outsider_rank"), "points": cl.get("outsider_points"),
                "played": cl.get("outsider_played"), "form": form(fo.get("outsider"))},
        "h2h": h2h,
        "origin": (a.details or {}).get("source") or "API-Football",
        "notes": (a.details or {}).get("notes") or [],
    }


def build_snapshot() -> dict:
    with session_scope() as s:
        run = s.scalar(select(ScrapeRun).where(ScrapeRun.status == "ok").order_by(ScrapeRun.id.desc()))
        start = now_local().replace(hour=0, minute=0, second=0, microsecond=0)
        matches = []
        for m in s.scalars(select(Match).where(Match.kickoff >= start).order_by(Match.kickoff)):
            matches.append({
                "id": "op_" + m.id, "kickoff": m.kickoff.strftime("%Y-%m-%dT%H:%M"),
                "country": m.country, "league": m.league, "tier": m.tier,
                "home": m.home, "away": m.away,
                "o1": m.odds_home, "ox": m.odds_draw, "o2": m.odds_away,
                "source": m.odds_source, "url": m.url,
                "sports": _sports_from_analysis(m),
                "analysis_error": m.analysis.error if m.analysis else None,
            })
        since = run.started_at if run else start
        rej = s.scalars(select(RejectedMatch).where(RejectedMatch.logged_at >= since,
                                                    RejectedMatch.reason_code.in_(EXTRACTION_REJECT_CODES))
                        .order_by(RejectedMatch.kickoff)).all()
        counts = Counter(r.reason_code for r in rej)
        # priorité aux rejets les plus parlants (coupes, niveau) avant les « non référencés »
        order = {"coupe": 0, "niveau": 1, "cotes_nd": 2, "non_reference": 3}
        rej_sorted = sorted(rej, key=lambda r: (order.get(r.reason_code, 9), r.kickoff or start))[:MAX_REJECTS]
        rejects = [{
            "kickoff": r.kickoff.strftime("%Y-%m-%dT%H:%M") if r.kickoff else None,
            "country": r.country, "league": r.league, "home": r.home, "away": r.away,
            "o1": r.odds_home, "ox": r.odds_draw, "o2": r.odds_away,
            "code": r.reason_code, "reason": r.reason,
        } for r in rej_sorted]
        return {
            "extracted_at": run.finished_at.isoformat() if run and run.finished_at else None,
            "found": run.found if run else 0,
            "days_ahead": config.DAYS_AHEAD,
            "odds_source_mode": config.ODDS_SOURCE,
            "max_tier": config.MAX_LEAGUE_TIER,
            "analysis_source": config.ANALYSIS_SOURCE,
            "matches": matches,
            "rejects": rejects,
            "reject_counts": dict(counts),
            "rejects_truncated": max(0, len(rej) - len(rejects)),
        }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(config.DATA_DIR / "snapshot.json"))
    ap.add_argument("--days", type=int, default=config.DAYS_AHEAD)
    ap.add_argument("--no-scrape", action="store_true", help="exporter la base sans nouvelle extraction")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    init_db()
    if not args.no_scrape:
        from scraper.pipeline import run_extraction
        summary = run_extraction(days_ahead=args.days)
        print(json.dumps(summary, ensure_ascii=False))
        if summary.get("status") != "ok":
            raise SystemExit(f"Extraction en échec : {summary}")
    snap = build_snapshot()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    size = Path(args.out).stat().st_size
    print(f"Instantané : {len(snap['matches'])} matchs, {len(snap['rejects'])} rejets, {size // 1024} Kio -> {args.out}")


if __name__ == "__main__":
    main()
