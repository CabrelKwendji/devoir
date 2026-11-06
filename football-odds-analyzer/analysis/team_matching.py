"""Rapprochement des noms d'équipes OddsPortal <-> API-Football (rapidfuzz + table d'alias)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz, process

import config

# Mots sans valeur discriminante
STOPWORDS = {
    "fc", "cf", "afc", "sc", "ac", "as", "ss", "ssc", "sv", "vfl", "vfb", "fk", "nk", "sk", "if",
    "bk", "cd", "ud", "sd", "rc", "club", "de", "calcio", "1", "ca", "cp", "the", "football",
    "futbol", "fussball", "spor", "sad", "us", "aj", "ogc",
}
# Remplacement d'abréviations courantes (appliqué mot à mot après normalisation)
SYNONYMS = {
    "utd": "united",
    "atl": "atletico",
    "man": "manchester",
    "st": "saint",
    "nottm": "nottingham",
    "wolves": "wolverhampton",
    "psg": "paris saint germain",
    "spurs": "tottenham",
    "munich": "munchen",
    "gladbach": "monchengladbach",
    "m": "",
}


def normalize_team(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    words = []
    for w in text.split():
        w = SYNONYMS.get(w, w)
        words.extend(w.split())
    core = [w for w in words if w not in STOPWORDS]
    return " ".join(core or words)


@dataclass
class TeamMatch:
    team_id: int
    team_name: str
    score: float
    via_alias: bool = False


def match_team(
    name: str,
    candidates: list[tuple[int, str]],
    aliases: dict[str, tuple[int, str]] | None = None,
    min_score: float = config.TEAM_MATCH_MIN_SCORE,
    ambiguity_margin: float = 3.0,
) -> TeamMatch | None:
    """Retourne l'équipe API-Football correspondant à `name`, ou None si non rapprochée.

    1. table d'alias (prioritaire, éditable dans l'interface)
    2. égalité des noms normalisés
    3. rapidfuzz (WRatio) avec seuil minimum et rejet des cas ambigus
    """
    aliases = aliases or {}
    if name in aliases:
        tid, tname = aliases[name]
        return TeamMatch(tid, tname, 100.0, via_alias=True)
    if not candidates:
        return None

    target = normalize_team(name)
    normalized = {tid: normalize_team(tname) for tid, tname in candidates}
    names = dict(candidates)
    exact = [tid for tid, n in normalized.items() if n == target]
    if len(exact) == 1:
        return TeamMatch(exact[0], names[exact[0]], 100.0)

    results = process.extract(target, normalized, scorer=fuzz.WRatio, limit=2)
    if not results:
        return None
    _, best_score, best_id = results[0]
    if best_score < min_score:
        return None
    if len(results) > 1:
        _, second_score, second_id = results[1]
        if second_id != best_id and best_score - second_score < ambiguity_margin:
            return None  # ambigu (ex. « Manchester » seul) : on préfère ne pas deviner
    return TeamMatch(best_id, names[best_id], float(best_score))
