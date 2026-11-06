"""Orchestration d'une extraction : OddsPortal -> filtres -> SQLite (+ journal des rejets)."""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import timedelta

from sqlalchemy import delete, select

import config
from database import Match, RejectedMatch, ScrapeRun, now_local, session_scope
from scraper.filters import REJECT_ODDS, REJECT_ODDS_MISSING, evaluate_match, odds_within_thresholds
from scraper.leagues import default_leagues
from scraper.models import RawMatch
from scraper.oddsportal import OddsPortalScraper

log = logging.getLogger(__name__)
_lock = threading.Lock()

# Marge appliquée sur les cotes moyennes avant d'ouvrir la page du match (cote Pinnacle)
PREFILTER_FAV_MARGIN = 0.20
PREFILTER_OUT_MARGIN = 1.00


def _log_reject(session, raw: RawMatch, code: str, reason: str, stage: str = "extraction") -> None:
    existing = session.scalar(
        select(RejectedMatch).where(RejectedMatch.match_key == raw.match_id, RejectedMatch.reason_code == code)
    )
    if existing:
        existing.reason = reason
        existing.logged_at = now_local()
        existing.odds_home, existing.odds_draw, existing.odds_away = raw.odds_home, raw.odds_draw, raw.odds_away
        return
    session.add(
        RejectedMatch(
            match_key=raw.match_id,
            kickoff=raw.kickoff,
            country=raw.country_label,
            league=f"{raw.league_label} ({raw.league_path})",
            home=raw.home,
            away=raw.away,
            odds_home=raw.odds_home,
            odds_draw=raw.odds_draw,
            odds_away=raw.odds_away,
            reason_code=code,
            reason=reason,
            stage=stage,
        )
    )


def _upsert_match(session, raw: RawMatch, league, favorite_side: str, extracted_at) -> Match:
    m = session.get(Match, raw.match_id) or Match(id=raw.match_id)
    m.kickoff = raw.kickoff
    m.country = league.country
    m.league = league.name
    m.league_path = league.path
    m.tier = league.tier
    m.home, m.away = raw.home, raw.away
    m.odds_home, m.odds_draw, m.odds_away = raw.odds_home, raw.odds_draw, raw.odds_away
    m.odds_source = raw.odds_source
    m.favorite_side = favorite_side
    m.favorite = raw.home if favorite_side == "home" else raw.away
    m.outsider = raw.away if favorite_side == "home" else raw.home
    m.url = raw.url
    m.extracted_at = extracted_at
    session.add(m)
    return m


async def _scrape(days_ahead: int) -> tuple[list[RawMatch], dict[str, tuple]]:
    """Lit les matchs puis ouvre la page des candidats plausibles pour la cote de référence."""
    leagues = default_leagues()
    decisions: dict[str, tuple] = {}
    async with OddsPortalScraper() as scraper:
        raws = await scraper.list_upcoming(days_ahead)
        loose_fav = config.FAVORITE_MAX_ODDS + PREFILTER_FAV_MARGIN
        loose_out = max(1.01, config.OUTSIDER_MIN_ODDS - PREFILTER_OUT_MARGIN)
        pages = 0
        for raw in raws:
            pre = evaluate_match(raw, leagues, favorite_max=loose_fav, outsider_min=loose_out)
            structural_reject = not pre.kept and pre.reason_code not in (REJECT_ODDS, REJECT_ODDS_MISSING)
            if structural_reject:
                decisions[raw.match_id] = (pre.reason_code, pre.reason)
                continue
            if config.ODDS_SOURCE in ("pinnacle", "average") and pre.reason_code != REJECT_ODDS:
                if pages < config.SCRAPE_MAX_MATCH_PAGES:
                    await scraper.enrich_odds(raw)
                    pages += 1
                else:
                    log.info("Plafond de pages de match atteint : meilleure cote de la liste conservée pour %s", raw.match_id)
    return raws, decisions


def run_extraction(days_ahead: int = config.DAYS_AHEAD) -> dict:
    """Extraction complète (bloquante). Retourne un résumé."""
    if not _lock.acquire(blocking=False):
        return {"status": "busy", "message": "Une extraction est déjà en cours."}
    try:
        with session_scope() as s:
            run = ScrapeRun(started_at=now_local())
            s.add(run)
            s.flush()
            run_id = run.id
        try:
            raws, decisions = asyncio.run(_scrape(days_ahead))
        except Exception as exc:  # Playwright absent, réseau, etc.
            log.exception("Extraction échouée")
            with session_scope() as s:
                run = s.get(ScrapeRun, run_id)
                run.status, run.finished_at, run.message = "error", now_local(), str(exc)[:2000]
            return {"status": "error", "message": str(exc)}

        leagues = default_leagues()
        extracted_at = now_local()
        kept = rejected = 0
        kept_ids: set[str] = set()
        with session_scope() as s:
            for raw in raws:
                if raw.match_id in decisions:
                    code, reason = decisions[raw.match_id]
                    _log_reject(s, raw, code, reason)
                    rejected += 1
                    continue
                res = evaluate_match(raw, leagues)
                if res.league is None or not raw.has_odds:
                    _log_reject(s, raw, res.reason_code, res.reason)
                    rejected += 1
                    continue
                # Les matchs de championnat éligibles avec cotes sont stockés : cela permet
                # d'élargir les seuils depuis l'interface. Seuls ceux qui respectent les
                # seuils par défaut sont considérés « retenus ».
                fav_side = res.favorite_side or ("home" if raw.odds_home <= raw.odds_away else "away")
                _upsert_match(s, raw, res.league, fav_side, extracted_at)
                kept_ids.add(raw.match_id)
                if res.kept:
                    kept += 1
                else:
                    _log_reject(s, raw, res.reason_code, res.reason)
                    rejected += 1

            # Nettoyage : matchs de la fenêtre qui ne sont plus proposés / matchs passés
            if raws:
                window_end = now_local() + timedelta(days=days_ahead + 1)
                stale = s.scalars(select(Match).where(Match.kickoff <= window_end)).all()
                for m in stale:
                    if m.id not in kept_ids:
                        s.delete(m)
            s.execute(delete(RejectedMatch).where(RejectedMatch.logged_at < now_local() - timedelta(days=14)))

            run = s.get(ScrapeRun, run_id)
            run.status = "ok"
            run.finished_at = now_local()
            run.found, run.kept, run.rejected = len(raws), kept, rejected
            if not raws:
                run.message = "Aucun match lu : vérifier les sélecteurs (scraper/selectors.py) ou la connexion."
        summary = {"status": "ok", "found": len(raws), "kept": kept, "rejected": rejected}
        log.info("Extraction terminée : %s", summary)

        if config.ANALYZE_AFTER_SCRAPE and kept:
            from analysis.service import analyze_pending

            try:
                summary["analysed"] = analyze_pending()
            except Exception as exc:
                log.exception("Analyse automatique échouée")
                summary["analysis_error"] = str(exc)
        return summary
    finally:
        _lock.release()


def meets_thresholds(m: Match, favorite_max: float, outsider_min: float) -> bool:
    if m.odds_home is None or m.odds_away is None:
        return False
    return odds_within_thresholds(m.odds_home, m.odds_away, favorite_max, outsider_min)
