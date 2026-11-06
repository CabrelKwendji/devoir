"""Cache local (fichiers) du HTML rendu, pour éviter de recharger OddsPortal inutilement."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import config


class HtmlCache:
    def __init__(self, directory: Path = config.SCRAPE_CACHE_DIR, ttl_minutes: int = config.SCRAPE_CACHE_TTL_MIN):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_minutes * 60

    def _path(self, url: str) -> Path:
        return self.directory / (hashlib.sha256(url.encode()).hexdigest()[:32] + ".html")

    def get(self, url: str) -> str | None:
        p = self._path(url)
        if not p.exists() or time.time() - p.stat().st_mtime > self.ttl_seconds:
            return None
        return p.read_text(encoding="utf-8")

    def set(self, url: str, html: str) -> None:
        self._path(url).write_text(html, encoding="utf-8")

    def purge_expired(self) -> int:
        n = 0
        for p in self.directory.glob("*.html"):
            if time.time() - p.stat().st_mtime > self.ttl_seconds:
                p.unlink(missing_ok=True)
                n += 1
        return n
