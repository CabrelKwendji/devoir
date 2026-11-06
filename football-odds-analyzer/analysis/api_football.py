"""Client API-Football (api-sports.io v3) avec cache SQLite pour respecter le quota."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta

import httpx

import config
from database import ApiCache, now_local, session_scope

log = logging.getLogger(__name__)

FINISHED = {"FT", "AET", "PEN"}


class ApiFootballError(RuntimeError):
    pass


def _cache_key(endpoint: str, params: dict) -> str:
    raw = endpoint + "?" + json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


class ApiFootballClient:
    def __init__(
        self,
        api_key: str = config.API_FOOTBALL_KEY,
        base_url: str = config.API_FOOTBALL_BASE_URL,
        ttl_hours: int = config.API_CACHE_TTL_HOURS,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key
        self.ttl = timedelta(hours=ttl_hours)
        self._http = httpx.Client(
            base_url=base_url,
            headers={"x-apisports-key": api_key},
            timeout=config.API_TIMEOUT_S,
            transport=transport,
        )
        self.remaining: str | None = None

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- appel générique avec cache -----------------------------------------------
    def get(self, endpoint: str, ttl: timedelta | None = None, **params) -> list:
        params = {k: v for k, v in params.items() if v is not None}
        key = _cache_key(endpoint, params)
        ttl = ttl or self.ttl
        with session_scope() as s:
            cached = s.get(ApiCache, key)
            if cached and now_local() - cached.fetched_at < ttl:
                return cached.payload.get("response", [])

        if not self.api_key:
            raise ApiFootballError("API_FOOTBALL_KEY absente : renseignez-la dans le fichier .env")
        try:
            resp = self._http.get(endpoint, params=params)
        except httpx.HTTPError as exc:
            raise ApiFootballError(f"Erreur réseau API-Football : {exc}") from exc
        self.remaining = resp.headers.get("x-ratelimit-requests-remaining")
        if resp.status_code != 200:
            raise ApiFootballError(f"API-Football HTTP {resp.status_code} sur {endpoint}")
        payload = resp.json()
        errors = payload.get("errors")
        if errors:  # ex. quota atteint, clé invalide, paramètre incorrect
            raise ApiFootballError(f"API-Football : {errors}")

        with session_scope() as s:
            row = s.get(ApiCache, key) or ApiCache(key=key)
            row.endpoint, row.params, row.payload, row.fetched_at = endpoint, params, payload, now_local()
            s.add(row)
        return payload.get("response", [])

    # --- endpoints utilisés ---------------------------------------------------------
    def current_season(self, league_id: int) -> int | None:
        data = self.get("/leagues", ttl=timedelta(days=7), id=league_id, current="true")
        for item in data:
            for season in item.get("seasons", []):
                if season.get("current"):
                    return int(season["year"])
        return None

    def find_league(self, country: str, name: str) -> int | None:
        """Recherche l'id d'une ligue par pays (nom anglais API) et nom (approché)."""
        from rapidfuzz import fuzz, process

        data = self.get("/leagues", ttl=timedelta(days=30), country=country, type="league")
        choices = {item["league"]["id"]: item["league"]["name"] for item in data if item.get("league")}
        if not choices:
            return None
        best = process.extractOne(name, choices, scorer=fuzz.WRatio)
        return best[2] if best and best[1] >= 85 else None

    def teams(self, league_id: int, season: int) -> list[tuple[int, str]]:
        data = self.get("/teams", ttl=timedelta(days=7), league=league_id, season=season)
        return [(t["team"]["id"], t["team"]["name"]) for t in data if t.get("team")]

    def standings(self, league_id: int, season: int) -> dict[int, dict]:
        """{team_id: {rank, points, played, group}} (toutes poules confondues)."""
        data = self.get("/standings", league=league_id, season=season)
        table: dict[int, dict] = {}
        for item in data:
            for group in item.get("league", {}).get("standings", []):
                for row in group:
                    tid = row.get("team", {}).get("id")
                    if tid is None or tid in table:
                        continue
                    table[tid] = {
                        "rank": row.get("rank"),
                        "points": row.get("points"),
                        "played": (row.get("all") or {}).get("played"),
                        "group": row.get("group"),
                    }
        return table

    def league_fixtures(self, team_id: int, league_id: int, season: int) -> list[dict]:
        """Matchs terminés d'une équipe dans le championnat, du plus récent au plus ancien."""
        data = self.get("/fixtures", team=team_id, league=league_id, season=season)
        done = [f for f in data if f.get("fixture", {}).get("status", {}).get("short") in FINISHED]
        return sorted(done, key=lambda f: f["fixture"]["date"], reverse=True)

    def head_to_head(self, team_a: int, team_b: int, last: int = config.H2H_MATCHES) -> list[dict]:
        data = self.get("/fixtures/headtohead", h2h=f"{team_a}-{team_b}", last=last + 5)
        done = [f for f in data if f.get("fixture", {}).get("status", {}).get("short") in FINISHED]
        return sorted(done, key=lambda f: f["fixture"]["date"], reverse=True)[:last]


# Conversion du chemin OddsPortal en nom de pays API-Football
_COUNTRY_OVERRIDES = {"usa": "USA", "south-korea": "South-Korea", "czech-republic": "Czech-Republic",
                      "saudi-arabia": "Saudi-Arabia"}


def api_country_from_path(league_path: str) -> str:
    slug = league_path.split("/")[0]
    return _COUNTRY_OVERRIDES.get(slug, "-".join(p.capitalize() for p in slug.split("-")))
