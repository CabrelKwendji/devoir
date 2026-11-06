"""Routes HTML (Jinja2 + HTMX) et JSON."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

import config
from analysis.criteria import ICONS, implied_probability
from analysis.service import analyze_ids, analyze_pending
from api import scheduler
from database import Analysis, Match, RejectedMatch, ScrapeRun, TeamAlias, get_session, now_local
from scraper.filters import REJECT_LABELS
from scraper.pipeline import _lock as scrape_lock
from scraper.pipeline import meets_thresholds

router = APIRouter()
templates = Jinja2Templates(directory=str(config.BASE_DIR / "web" / "templates"))
NA = config.NA


# --- filtres Jinja -------------------------------------------------------------
def fmt_odds(v) -> str:
    return NA if v is None else f"{v:.2f}"


def fmt_pct(v) -> str:
    return NA if v is None else f"{v * 100:.1f} %"


_JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def fmt_dt(v: datetime | None, pattern: str = "%Y-%m-%d %H:%M") -> str:
    if v is None:
        return NA
    return v.strftime(pattern.replace("%a", _JOURS[v.weekday()]))


def nd(v) -> str:
    return NA if v is None or v == "" else str(v)


def signed(v) -> str:
    return NA if v is None else f"{v:+d}"


templates.env.filters.update(odds=fmt_odds, pct=fmt_pct, dt=fmt_dt, nd=nd, signed=signed)
templates.env.globals.update(
    ICONS=ICONS, NA=NA, REJECT_LABELS=REJECT_LABELS,
    implied=lambda m: implied_probability(m.favorite_odds, m.odds_draw, m.outsider_odds),
)


def _float(value: str | None, default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


def _status_context(session: Session) -> dict:
    last_ok = session.scalar(select(ScrapeRun).where(ScrapeRun.status == "ok").order_by(desc(ScrapeRun.id)))
    last = session.scalar(select(ScrapeRun).order_by(desc(ScrapeRun.id)))
    return {"last_ok": last_ok, "last_run": last, "running": scrape_lock.locked()}


# --- Page 1 : matchs détectés ----------------------------------------------------
def _filtered_matches(session: Session, day: str | None, country: str | None, league: str | None,
                      fav_max: float, out_min: float) -> list[Match]:
    q = select(Match).where(Match.kickoff >= now_local().replace(hour=0, minute=0, second=0, microsecond=0))
    q = q.order_by(Match.kickoff)
    rows = session.scalars(q).all()
    out = []
    for m in rows:
        if day and m.kickoff.date().isoformat() != day:
            continue
        if country and m.country != country:
            continue
        if league and m.league != league:
            continue
        if not meets_thresholds(m, fav_max, out_min):
            continue
        out.append(m)
    return out


@router.get("/", response_class=HTMLResponse)
def index(request: Request, country: str | None = None, league: str | None = None,
          fav_max: str | None = None, out_min: str | None = None, session: Session = Depends(get_session)):
    day = request.query_params.get("date") or None
    fmax = _float(fav_max, config.FAVORITE_MAX_ODDS)
    omin = _float(out_min, config.OUTSIDER_MIN_ODDS)
    matches = _filtered_matches(session, day, country or None, league or None, fmax, omin)
    all_matches = session.scalars(select(Match)).all()
    ctx = {
        "request": request,
        "matches": matches,
        "filters": {"date": day or "", "country": country or "", "league": league or "",
                    "fav_max": fmax, "out_min": omin},
        "countries": sorted({m.country for m in all_matches}),
        "leagues": sorted({m.league for m in all_matches if not country or m.country == country}),
        "dates": sorted({m.kickoff.date().isoformat() for m in all_matches}),
        "config": config,
        **_status_context(session),
    }
    template = "partials/matches_table.html" if request.headers.get("HX-Request") and \
        request.headers.get("HX-Target") == "matches" else "index.html"
    return templates.TemplateResponse(request, template, ctx)


@router.post("/refresh", response_class=HTMLResponse)
def refresh(request: Request, session: Session = Depends(get_session)):
    if not scrape_lock.locked():
        scheduler.trigger_refresh_now()
    ctx = {"request": request, **_status_context(session), "running": True}
    return templates.TemplateResponse(request, "partials/status.html", ctx)


@router.get("/status", response_class=HTMLResponse)
def status(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "partials/status.html", {"request": request, **_status_context(session)})


# --- Analyse --------------------------------------------------------------------
@router.post("/analyse/{match_id}", response_class=HTMLResponse)
def analyse_one(match_id: str, request: Request, session: Session = Depends(get_session)):
    if session.get(Match, match_id) is None:
        raise HTTPException(404, "Match inconnu")
    analyze_ids([match_id])
    session.expire_all()
    m = session.get(Match, match_id)
    return templates.TemplateResponse(request, "partials/analyse_button.html", {"request": request, "m": m})


@router.post("/analyse-all")
def analyse_all():
    analyze_pending()
    return RedirectResponse("/analyse", status_code=303)


def _analyses(session: Session, only_full: bool, sort: str) -> list[Match]:
    rows = session.scalars(
        select(Match).join(Analysis).where(Match.kickoff >= now_local().replace(hour=0, minute=0, second=0))
    ).all()
    if only_full:
        rows = [m for m in rows if m.analysis.score == 3]
    if sort == "date":
        rows.sort(key=lambda m: m.kickoff)
    else:
        rows.sort(key=lambda m: (-m.analysis.score, m.kickoff))
    return rows


@router.get("/analyse", response_class=HTMLResponse)
def analyse_page(request: Request, only_full: str | None = None, sort: str = "score",
                 session: Session = Depends(get_session)):
    full = only_full in ("1", "on", "true")
    ctx = {"request": request, "matches": _analyses(session, full, sort),
           "only_full": full, "sort": sort, **_status_context(session)}
    template = "partials/analysis_cards.html" if request.headers.get("HX-Target") == "cards" else "analyse.html"
    return templates.TemplateResponse(request, template, ctx)


def _crit(m: Match, name: str) -> dict:
    for c in (m.analysis.details or {}).get("criteria", []):
        if c["name"] == name:
            return c
    return {}


@router.get("/analyse/export.csv")
def export_csv(only_full: str | None = None, sort: str = "score", session: Session = Depends(get_session)):
    rows = _analyses(session, only_full in ("1", "on", "true"), sort)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["date", "pays", "ligue", "niveau", "domicile", "exterieur", "cote_1", "cote_X", "cote_2",
                "source_cotes", "favori", "outsider", "proba_implicite_favori", "classement", "forme", "h2h",
                "score", "verdict", "remarque"])
    for m in rows:
        a = m.analysis
        w.writerow([
            fmt_dt(m.kickoff), m.country, m.league, m.tier, m.home, m.away,
            fmt_odds(m.odds_home), fmt_odds(m.odds_draw), fmt_odds(m.odds_away), m.odds_source,
            m.favorite, m.outsider, fmt_pct(a.implied_probability),
            *[_crit(m, n).get("status", NA) for n in ("Classement", "Forme", "H2H")],
            f"{a.score}/3", a.verdict, a.error or "",
        ])
    data = "﻿" + buf.getvalue()  # BOM pour Excel
    filename = f"analyse_{date.today().isoformat()}.csv"
    return StreamingResponse(iter([data]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# --- Journal des rejets ----------------------------------------------------------
@router.get("/rejets", response_class=HTMLResponse)
def rejects(request: Request, reason: str | None = None, session: Session = Depends(get_session)):
    q = select(RejectedMatch).order_by(desc(RejectedMatch.logged_at)).limit(1000)
    if reason:
        q = q.where(RejectedMatch.reason_code == reason)
    rows = session.scalars(q).all()
    return templates.TemplateResponse(request, "rejets.html",
                                      {"request": request, "rows": rows, "reason": reason or "", **_status_context(session)})


# --- Table d'alias ---------------------------------------------------------------
@router.get("/aliases", response_class=HTMLResponse)
def aliases(request: Request, session: Session = Depends(get_session)):
    rows = session.scalars(select(TeamAlias).order_by(TeamAlias.oddsportal_name)).all()
    return templates.TemplateResponse(request, "aliases.html", {"request": request, "rows": rows, **_status_context(session)})


@router.post("/aliases")
def save_alias(oddsportal_name: str = Form(...), api_team_id: int = Form(...), api_team_name: str = Form(...),
               session: Session = Depends(get_session)):
    row = session.scalar(select(TeamAlias).where(TeamAlias.oddsportal_name == oddsportal_name.strip()))
    row = row or TeamAlias(oddsportal_name=oddsportal_name.strip())
    row.api_team_id, row.api_team_name, row.is_manual, row.score = api_team_id, api_team_name.strip(), True, None
    session.add(row)
    session.commit()
    return RedirectResponse("/aliases", status_code=303)


@router.post("/aliases/{alias_id}/delete")
def delete_alias(alias_id: int, session: Session = Depends(get_session)):
    row = session.get(TeamAlias, alias_id)
    if row:
        session.delete(row)
        session.commit()
    return RedirectResponse("/aliases", status_code=303)


# --- JSON -------------------------------------------------------------------------
@router.get("/api/matches")
def api_matches(session: Session = Depends(get_session)):
    out = []
    for m in session.scalars(select(Match).order_by(Match.kickoff)).all():
        out.append({
            "id": m.id, "kickoff": m.kickoff.isoformat(), "country": m.country, "league": m.league,
            "tier": m.tier, "home": m.home, "away": m.away, "odds": [m.odds_home, m.odds_draw, m.odds_away],
            "odds_source": m.odds_source, "favorite": m.favorite, "outsider": m.outsider,
            "extracted_at": m.extracted_at.isoformat(),
            "analysis": None if not m.analysis else {
                "score": m.analysis.score, "verdict": m.analysis.verdict,
                "implied_probability": m.analysis.implied_probability, "error": m.analysis.error,
                "details": m.analysis.details,
            },
        })
    return out
