"""Analyse du HTML rendu d'OddsPortal (après exécution JavaScript par Playwright).

Le parsing est séparé de la navigation pour pouvoir être testé hors ligne
sur des fixtures HTML (tests/fixtures/).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from fractions import Fraction
from statistics import mean
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

import config
from scraper import selectors as S
from scraper.models import RawMatch

log = logging.getLogger(__name__)
TZ = ZoneInfo(config.TIMEZONE)
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


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


def _text(tag: Tag) -> str:
    return " ".join(tag.get_text(" ", strip=True).split())


def _row_odds(container: Tag | None) -> list[float]:
    if container is None:
        return []
    for sel in S.ROW_ODDS:
        values = [parse_odds(_text(el)) for el in container.select(sel)]
        if len(values) >= 3:
            return [v for v in values[:3]] if all(v is not None for v in values[:3]) else []
    return []


def _league_header(a: Tag) -> tuple[str, str, str] | None:
    """Reconnaît le lien de ligue d'un fil d'Ariane « Football / Pays / Ligue »."""
    m = S.LEAGUE_LINK_RE.match(a["href"])
    if not m or a.parent is None or m.group(1) in S.NON_COUNTRY_SEGMENTS:
        return None
    prev = a.parent.find_previous_sibling()
    if prev is None or prev.find("a", href=f"/football/{m.group(1)}/") is None:
        return None  # lien de menu / barre latérale, pas un en-tête de liste
    country = _text(prev).strip(" /")
    return f"{m.group(1)}/{m.group(2)}", country, _text(a)


def parse_listing(html: str, day: date) -> list[RawMatch]:
    """Extrait les matchs d'une page /matches/football/AAAAMMJJ/ (ordre du document)."""
    soup = BeautifulSoup(html, "lxml")
    results: list[RawMatch] = []
    seen: set[str] = set()
    current: tuple[str, str, str] | None = None

    for a in soup.find_all("a", href=True):
        header = _league_header(a)
        if header:
            current = header
            continue

        href = a["href"]
        m = S.MATCH_LINK_RE.match(href)
        legacy = None if m else S.LEGACY_MATCH_LINK_RE.match(href)
        if legacy and legacy.group(1) in S.NON_COUNTRY_SEGMENTS:
            legacy = None  # encart promotionnel /football/h2h/... sans identifiant de match
        if not m and not legacy:
            continue
        match_id = m.group(3) if m else legacy.group(4)
        if match_id in seen:
            continue
        if m:
            if current is None:
                continue  # ligne sans en-tête de ligue identifiable
            league_path, country_label, league_label = current
        else:
            league_path = f"{legacy.group(1)}/{legacy.group(2)}"
            country_label = current[1] if current and current[0] == league_path else legacy.group(1).replace("-", " ").title()
            league_label = current[2] if current and current[0] == league_path else legacy.group(2).replace("-", " ").title()

        texts = [_text(p) for p in a.find_all(S.MATCH_TEXTS)]
        texts = [t for t in texts if t and t != "-"]
        clock = next((TIME_RE.match(t) for t in texts if TIME_RE.match(t)), None)
        names = [t for t in texts if not TIME_RE.match(t)]
        if clock is None:
            continue  # match en cours / terminé / reporté : pas d'heure future exploitable
        if len(names) < 2:
            log.debug("Ligne ignorée (équipes introuvables) : %s", href)
            continue

        odds = _row_odds(a.parent)
        seen.add(match_id)
        results.append(RawMatch(
            match_id=match_id,
            url=config.ODDSPORTAL_BASE_URL + href,
            kickoff=datetime.combine(day, time(int(clock.group(1)), int(clock.group(2))), tzinfo=TZ),
            league_path=league_path,
            country_label=country_label,
            league_label=league_label,
            home=names[0],
            away=names[1],
            odds_home=odds[0] if odds else None,
            odds_draw=odds[1] if odds else None,
            odds_away=odds[2] if odds else None,
            odds_source="meilleure",  # la liste affiche la meilleure cote du marché
        ))
    return results


@dataclass
class BookmakerOdds:
    name: str
    slug: str | None
    odds: list[float]


def parse_bookmaker_rows(html: str) -> list[BookmakerOdds]:
    """Lignes du tableau 1X2 d'une page de match (une ligne = un bookmaker)."""
    soup = BeautifulSoup(html, "lxml")
    rows: list[BookmakerOdds] = []
    for tr in soup.select(S.BOOKMAKER_ROW):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 4:
            continue
        odds = [parse_odds(_text(c)) for c in cells[1:4]]
        if any(o is None for o in odds):
            continue
        name_el = cells[0].find("p") or cells[0]
        link = cells[0].find("a", href=S.BOOKMAKER_SLUG_RE)
        slug = S.BOOKMAKER_SLUG_RE.search(link["href"]).group(1) if link else None
        rows.append(BookmakerOdds(_text(name_el), slug, odds))
    return rows


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def parse_bookmaker_odds(html: str, bookmaker: str = config.PINNACLE_BOOKMAKER_NAME) -> list[float] | None:
    """Cotes 1/X/2 d'un bookmaker donné sur la page d'un match, ou None s'il est absent."""
    target = _norm(bookmaker)
    for row in parse_bookmaker_rows(html):
        if _norm(row.name).startswith(target) or (row.slug and _norm(row.slug).startswith(target)):
            return row.odds
    return None


def parse_average_odds(html: str) -> tuple[list[float], int] | None:
    """Cote moyenne 1/X/2 : ligne « Average » si présente, sinon moyenne des bookmakers.

    Retourne (cotes, nombre de bookmakers) — 0 si la ligne « Average » du site est utilisée.
    """
    rows = parse_bookmaker_rows(html)
    labels = {_norm(lbl) for lbl in S.AVERAGE_ROW_LABELS}
    for row in rows:
        if _norm(row.name) in labels:
            return row.odds, 0
    books = [r for r in rows if _norm(r.name) not in labels]
    if not books:
        return None
    avg = [round(mean(r.odds[i] for r in books), 2) for i in range(3)]
    return avg, len(books)
