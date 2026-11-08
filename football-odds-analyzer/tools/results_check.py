"""Bilan a posteriori : les favoris détectés ont-ils gagné, ou au moins évité la défaite ?

Usage :
    python -m tools.results_check --pred snapshot_A.json [--pred snapshot_B.json ...] \
        [--days 2026-11-06,2026-11-07] --out data/bilan.json

* Les prédictions viennent d'instantanés produits par tools.daily_snapshot AVANT les matchs.
  Pour un même match présent dans plusieurs instantanés, le plus récent (extracted_at) est gardé,
  à condition qu'il soit antérieur au coup d'envoi.
* Les résultats sont lus en ligne sur la page du jour d'OddsPortal (lignes « Finished »).
* Seuls les matchs respectant les seuils (favori < 1.70, outsider > 4.00) sont évalués.
Aucune donnée n'est inventée : un match sans score final est classé « non terminé ».
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import config
from scraper.oddsportal import OddsPortalScraper

log = logging.getLogger(__name__)


def _selected(m: dict, fav_max: float, out_min: float) -> bool:
    o1, o2 = m.get("o1"), m.get("o2")
    return bool(o1 and o2) and min(o1, o2) < fav_max and max(o1, o2) > out_min


def _analysis(m: dict) -> dict:
    """Recalcule score et statut des critères à partir des données de l'instantané."""
    from analysis import criteria as C

    sp = m.get("sports")
    if not sp:
        return {"score": None, "statuses": {}}
    f, o = sp.get("fav") or {}, sp.get("out") or {}
    row = lambda t: C.StandingRow(t.get("rank"), t.get("points"), t.get("played"))  # noqa: E731
    fr = lambda t: None if t.get("form") is None else [C.FixtureResult(x["gf"], x["ga"]) for x in t["form"]]  # noqa: E731
    h2h = None if sp.get("h2h") is None else [
        C.H2HMatch(x.get("date"), "", "", x["fg"], x["og"],
                   "favorite" if x["fg"] > x["og"] else "outsider" if x["og"] > x["fg"] else None)
        for x in sp["h2h"]]
    crit = [C.standings_criterion(row(f), row(o)), C.form_criterion(fr(f), fr(o)), C.h2h_criterion(h2h)]
    return {"score": C.confirmation_score(crit), "statuses": {c.name: c.status for c in crit},
            "low_sample": crit[0].data.get("low_sample")}


def load_predictions(paths: list[str], fav_max: float, out_min: float) -> dict[str, dict]:
    preds: dict[str, dict] = {}
    for p in paths:
        snap = json.loads(Path(p).read_text(encoding="utf-8"))
        snap = snap.get("data", snap)
        stamp = snap.get("extracted_at") or ""
        for m in snap.get("matches", []):
            if not _selected(m, fav_max, out_min):
                continue
            ko = datetime.fromisoformat(m["kickoff"])
            ex = datetime.fromisoformat(stamp).replace(tzinfo=None) if stamp else None
            if ex and ex > ko:
                continue  # extraction postérieure au coup d'envoi : pas une prédiction
            mid = m["id"].removeprefix("op_")
            if mid not in preds or stamp > preds[mid]["_stamp"]:
                preds[mid] = {**m, "_stamp": stamp}
    return preds


def outcome_for_favorite(m: dict, hg: int, ag: int) -> str:
    fav_home = m["o1"] <= m["o2"]
    fg, og = (hg, ag) if fav_home else (ag, hg)
    return "V" if fg > og else "N" if fg == og else "D"


def summarize(rows: list[dict]) -> dict:
    def block(items: list[dict]) -> dict:
        n = len(items)
        w = sum(r["fav_result"] == "V" for r in items)
        d = sum(r["fav_result"] == "N" for r in items)
        profit = sum((r["fav_odds"] - 1) if r["fav_result"] == "V" else -1 for r in items)
        return {
            "n": n, "victoires": w, "nuls": d, "defaites": n - w - d,
            "pct_victoire": round(100 * w / n, 1) if n else None,
            "pct_invaincu": round(100 * (w + d) / n, 1) if n else None,
            "proba_implicite_moy": round(100 * sum(r["implied"] for r in items) / n, 1) if n else None,
            "roi_mise_fixe_pct": round(100 * profit / n, 1) if n else None,
        }

    groups: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        groups["score"][f"{r['score']}/3" if r["score"] is not None else "N/D"].append(r)
        groups["verdict"][r["verdict"]].append(r)
        groups["lieu_favori"]["domicile" if r["fav_home"] else "extérieur"].append(r)
        groups["niveau"][f"N{r['tier']}"].append(r)
        lo = min(int(r["fav_odds"] * 10) / 10, 1.6)
        groups["cote_favori"][f"{lo:.1f}–{lo + 0.1:.1f}" if lo < 1.6 else "1.6–1.69"].append(r)
        for name, st in r["statuses"].items():
            groups[f"critère {name}"][st].append(r)
    return {"global": block(rows), **{g: {k: block(v) for k, v in sorted(sub.items())} for g, sub in groups.items()}}


async def fetch_results(days: list[date], preds: dict[str, dict]) -> dict:
    """Résultats des pages du jour, puis page du match pour ceux qui manquent (liste incomplète)."""
    from scraper import parsers
    from scraper import selectors as S
    from scraper.oddsportal import ScrapeError

    res: dict = {}
    async with OddsPortalScraper() as sc:
        for d in days:
            for mid, r in (await sc.results_day(d)).items():
                if mid not in res or (r.finished and not res[mid].finished):
                    res[mid] = r
        now = datetime.now()
        for mid, m in preds.items():
            if (mid in res and res[mid].finished) or not m.get("url"):
                continue
            if datetime.fromisoformat(m["kickoff"]) > now:
                continue
            try:
                html = await sc.fetch(m["url"], S.MATCH_READY)
            except ScrapeError as exc:
                log.warning("Page du match %s illisible : %s", mid, exc)
                continue
            score = parsers.parse_final_result(html)
            if score:
                res[mid] = parsers.MatchResult(mid, "Finished", m["home"], m["away"], score[0], score[1])
                log.info("Résultat lu sur la page du match %s : %d-%d", mid, *score)
    return res


def main() -> None:
    from analysis.criteria import implied_probability, verdict

    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", action="append", required=True)
    ap.add_argument("--days", help="AAAA-MM-JJ séparés par des virgules (défaut : jours des prédictions, jusqu'à aujourd'hui)")
    ap.add_argument("--out", default=str(config.DATA_DIR / "bilan.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")

    preds = load_predictions(args.pred, config.FAVORITE_MAX_ODDS, config.OUTSIDER_MIN_ODDS)
    today = date.today()
    days = sorted({date.fromisoformat(x) for x in args.days.split(",")}) if args.days else \
        sorted({date.fromisoformat(m["kickoff"][:10]) for m in preds.values()} & {d for d in
               (date.fromisoformat(m["kickoff"][:10]) for m in preds.values()) if d <= today})
    preds = {k: v for k, v in preds.items() if date.fromisoformat(v["kickoff"][:10]) in days}
    results = asyncio.run(fetch_results(days, preds))

    rows, pending = [], []
    for mid, m in sorted(preds.items(), key=lambda kv: kv[1]["kickoff"]):
        r = results.get(mid)
        fav_home = m["o1"] <= m["o2"]
        fav_odds, out_odds = (m["o1"], m["o2"]) if fav_home else (m["o2"], m["o1"])
        a = _analysis(m)
        base = {"id": mid, "kickoff": m["kickoff"], "country": m["country"], "league": m["league"],
                "tier": m["tier"], "home": m["home"], "away": m["away"], "fav_home": fav_home,
                "favorite": m["home"] if fav_home else m["away"], "fav_odds": fav_odds,
                "odds": [m["o1"], m["ox"], m["o2"]], "source": m["source"],
                "implied": implied_probability(fav_odds, m["ox"], out_odds),
                "score": a["score"], "verdict": verdict(a["score"]) if a["score"] is not None else "N/D",
                "statuses": a["statuses"], "prediction_at": m["_stamp"]}
        if r is None or not r.finished:
            pending.append({**base, "status": r.status if r else "introuvable"})
            continue
        rows.append({**base, "final": f"{r.home_goals}-{r.away_goals}", "status": r.status,
                     "fav_result": outcome_for_favorite(m, r.home_goals, r.away_goals)})

    report = {"generated_at": datetime.now().isoformat(timespec="seconds"), "days": [d.isoformat() for d in days],
              "evaluated": len(rows), "not_finished": len(pending), "summary": summarize(rows) if rows else {},
              "matches": rows, "pending": pending}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report["summary"].get("global", {}), ensure_ascii=False))
    print(f"{len(rows)} matchs évalués, {len(pending)} non terminés -> {args.out}")


if __name__ == "__main__":
    main()
