"""Analyse du HTML rendu d'OddsPortal (après exécution JavaScript par Playwright).

Le parsing est séparé de la navigation pour pouvoir être testé hors ligne
sur des fixtures HTML (tests/fixtures/).
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time
from fractions import Fraction
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

import config
from scraper import selectors as S
from scraper.models import RawMatch

log = logging.getLogger(__name__)
TZ = ZoneInfo(config.TIMEZONE)

MATCH_HREF_RE = re.compile(r"^/football/([^/]+)/([^/]+)/([^/]+)-([A-Za-z0-9]{8})/?(?:[#?].*)?$")
TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def parse_odds(text: str | None) -> float | None:
    """Convertit une cote affichée (décimale, américaine ou fractionnaire) en cote décimale."""
    if text is None:
        return None
    t = text.strip().replace(",", ".")
    if not t or t in {"-", "–", "—"} or "%" in t:
        return None
    try:
        if re.fullmatch(r"[+-]\d{3,5}", t):  # américaine
            v = int(t)
            return round(1 + (v / 100 if v > 0 else 100 / abs(v)), 3)
        if re.fullmatch(r"\d+/\d+", t):  # fractionnaire
            return round(1 + float(Fraction(t)), 3)
        if re.fullmatch(r"\d+(\.\d+)?", t):
            v = float(t)
            return v if v >= 1.01 else None
    except (ValueError, ZeroDivisionError):
        return None
    return None


def _select_first(node: Tag, selectors: list[str]) -> list[Tag]:
    for sel in selectors:
        try:
            found = node.select(sel)
        except Exception:  # sélecteur non supporté par soupsieve
            continue
        if found:
            return found
    return []


def _text(tag: Tag) -> str:
    return " ".join(tag.get_text(" ", strip=True).split())


def _odds_in(node: Tag) -> list[float]:
    cells = _select_first(node, S.ODDS_CELL)
    values = [parse_odds(_text(c)) for c in cells]
    values = [v for v in values if v is not None]
    if len(values) >= 3:
        return values[:3]
    # Repli : tout <p> dont le texte ressemble à une cote
    values = [parse_odds(_text(p)) for p in node.find_all("p")]
    values = [v for v in values if v is not None]
    return values[:3] if len(values) >= 3 else []


def parse_listing(html: str, day: date) -> list[RawMatch]:
    """Extrait les matchs d'une page /matches/football/AAAAMMJJ/."""
    soup = BeautifulSoup(html, "lxml")
    rows = _select_first(soup, S.EVENT_ROW)
    results: list[RawMatch] = []
    seen: set[str] = set()
    current_country, current_league = "", ""

    for row in rows:
        header = _select_first(row, S.LEAGUE_HEADER_LINKS)
        if header:
            labels = [_text(a) for a in header if _text(a)]
            if len(labels) >= 2:
                current_country, current_league = labels[-2], labels[-1]
            elif labels:
                current_league = labels[-1]

        link = None
        for a in row.find_all("a", href=True):
            if MATCH_HREF_RE.match(a["href"]):
                link = a
                break
        if link is None:
            continue
        m = MATCH_HREF_RE.match(link["href"])
        country_slug, league_slug, _teams_slug, match_id = m.groups()
        if match_id in seen:
            continue

        names = [_text(p) for p in _select_first(row, S.PARTICIPANT_NAME) if _text(p)]
        if len(names) < 2:
            names = [a.get("title", "").strip() for a in row.find_all("a", title=True)]
            names = [n for n in names if n]
        if len(names) < 2:
            log.debug("Ligne ignorée (équipes introuvables) : %s", link["href"])
            continue

        kickoff = None
        for el in _select_first(row, S.KICKOFF_TIME) or [row]:
            tm = TIME_RE.search(_text(el))
            if tm:
                kickoff = datetime.combine(day, time(int(tm.group(1)), int(tm.group(2))), tzinfo=TZ)
                break
        if kickoff is None:
            # Match en cours / terminé / reporté : pas d'heure future exploitable
            continue

        odds = _odds_in(row)
        seen.add(match_id)
        results.append(
            RawMatch(
                match_id=match_id,
                url=config.ODDSPORTAL_BASE_URL + link["href"].split("#")[0],
                kickoff=kickoff,
                league_path=f"{country_slug}/{league_slug}",
                country_label=current_country or country_slug.replace("-", " ").title(),
                league_label=current_league or league_slug.replace("-", " ").title(),
                home=names[0],
                away=names[1],
                odds_home=odds[0] if odds else None,
                odds_draw=odds[1] if odds else None,
                odds_away=odds[2] if odds else None,
                odds_source="average",
            )
        )
    return results


def _bookmaker_names(row: Tag) -> list[str]:
    names = []
    for img in row.find_all("img", alt=True):
        names.append(img["alt"])
    for a in row.find_all("a", title=True):
        names.append(a["title"])
    for el in _select_first(row, S.BOOKMAKER_NAME):
        names.append(_text(el))
    return [n.strip().lower() for n in names if n and n.strip()]


def parse_bookmaker_odds(html: str, bookmaker: str = config.PINNACLE_BOOKMAKER_NAME) -> list[float] | None:
    """Cotes 1/X/2 d'un bookmaker donné sur la page d'un match, ou None."""
    soup = BeautifulSoup(html, "lxml")
    target = bookmaker.strip().lower()
    for row in _select_first(soup, S.BOOKMAKER_ROW):
        if any(n == target or n.startswith(target + " ") for n in _bookmaker_names(row)):
            odds = _odds_in(row)
            if len(odds) == 3:
                return odds
    # Repli : on remonte depuis le logo / le lien du bookmaker
    for el in soup.find_all(lambda t: (t.get("alt") or t.get("title") or "").strip().lower() == target):
        node = el
        for _ in range(8):
            node = node.parent
            if node is None:
                break
            odds = _odds_in(node)
            if len(odds) == 3:
                return odds
    return None


def parse_average_odds(html: str) -> list[float] | None:
    """Ligne « Average » de la page d'un match, ou None."""
    soup = BeautifulSoup(html, "lxml")
    labels = {lbl.lower() for lbl in S.AVERAGE_ROW_LABELS}
    for el in soup.find_all(string=True):
        if el.strip().lower() in labels:
            node = el.parent
            for _ in range(6):
                if node is None:
                    break
                odds = _odds_in(node)
                if len(odds) == 3:
                    return odds
                node = node.parent
    return None
