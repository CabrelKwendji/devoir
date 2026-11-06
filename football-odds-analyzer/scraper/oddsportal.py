"""Navigation OddsPortal avec Playwright (Chromium headless).

OddsPortal est rendu en JavaScript : on laisse Chromium exécuter la page,
puis on capture le HTML rendu (mis en cache) et on le confie à scraper.parsers.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import date, timedelta

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout

import config
from scraper import parsers
from scraper import selectors as S
from scraper.cache import HtmlCache
from scraper.models import RawMatch

log = logging.getLogger(__name__)


class ScrapeError(RuntimeError):
    pass


class OddsPortalScraper:
    def __init__(self, cache: HtmlCache | None = None, headless: bool = config.SCRAPE_HEADLESS):
        self.cache = cache or HtmlCache()
        self.headless = headless
        self._pw = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._last_request_at: float | None = None

    # --- cycle de vie --------------------------------------------------------
    async def __aenter__(self) -> "OddsPortalScraper":
        self._pw = await async_playwright().start()
        launch_kwargs = {"headless": self.headless}
        if config.CHROMIUM_EXECUTABLE:
            launch_kwargs["executable_path"] = config.CHROMIUM_EXECUTABLE
        self._browser = await self._pw.chromium.launch(**launch_kwargs)
        self._context = await self._browser.new_context(
            user_agent=config.USER_AGENT,
            locale="en-US",
            timezone_id=config.TIMEZONE,  # les heures affichées sont alors en heure de Toronto
            viewport={"width": 1366, "height": 900},
        )
        # Les images / polices ne sont pas nécessaires
        await self._context.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in {"image", "media", "font"}
            else route.continue_(),
        )
        return self

    async def __aexit__(self, *exc) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer:
                    await closer.close()
            except PlaywrightError:
                pass
        if self._pw:
            await self._pw.stop()

    # --- utilitaires -----------------------------------------------------------
    async def _polite_delay(self) -> None:
        """Délai aléatoire de 3 à 8 s entre deux pages réellement téléchargées."""
        if self._last_request_at is not None:
            await asyncio.sleep(random.uniform(config.SCRAPE_DELAY_MIN, config.SCRAPE_DELAY_MAX))
        self._last_request_at = asyncio.get_running_loop().time()

    async def _accept_cookies(self, page: Page) -> None:
        for sel in S.COOKIE_ACCEPT:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1500):
                    await btn.click()
                    return
            except PlaywrightError:
                continue

    async def _wait_any(self, page: Page, selectors: list[str], timeout_ms: int) -> bool:
        for sel in selectors:
            try:
                await page.wait_for_selector(sel, timeout=timeout_ms, state="attached")
                return True
            except PlaywrightTimeout:
                continue
        return False

    async def fetch(self, url: str, ready: list[str], scroll: bool = False, retries: int = 2) -> str:
        """Retourne le HTML rendu de l'URL (cache local d'abord)."""
        cached = self.cache.get(url)
        if cached is not None:
            log.debug("Cache HTML : %s", url)
            return cached

        last_exc: Exception | None = None
        for attempt in range(1, retries + 2):
            await self._polite_delay()
            page = await self._context.new_page()
            try:
                resp = await page.goto(url, timeout=config.SCRAPE_TIMEOUT_MS, wait_until="domcontentloaded")
                if resp is not None and resp.status >= 400:
                    raise ScrapeError(f"HTTP {resp.status} sur {url}")
                await self._accept_cookies(page)
                if not await self._wait_any(page, ready, config.SCRAPE_TIMEOUT_MS // max(len(ready), 1)):
                    log.warning("Aucun élément attendu trouvé sur %s (sélecteurs à vérifier ?)", url)
                if scroll:
                    # La liste du jour se charge par défilement (lazy loading)
                    previous = -1
                    for _ in range(40):
                        height = await page.evaluate("document.body.scrollHeight")
                        if height == previous:
                            break
                        previous = height
                        await page.mouse.wheel(0, 4000)
                        await page.wait_for_timeout(random.randint(600, 1200))
                else:
                    await page.wait_for_timeout(1500)
                html = await page.content()
                self.cache.set(url, html)
                return html
            except (PlaywrightError, ScrapeError) as exc:
                last_exc = exc
                log.warning("Échec %s (tentative %d) : %s", url, attempt, exc)
            finally:
                await page.close()
        raise ScrapeError(f"Impossible de charger {url} : {last_exc}")

    # --- extraction ------------------------------------------------------------
    async def list_day(self, day: date) -> list[RawMatch]:
        url = config.ODDSPORTAL_BASE_URL + S.DAY_LISTING_PATH.format(date=day.strftime("%Y%m%d"))
        html = await self.fetch(url, S.LISTING_READY, scroll=True)
        matches = parsers.parse_listing(html, day)
        log.info("%s : %d matchs lus", day.isoformat(), len(matches))
        return matches

    async def list_upcoming(self, days_ahead: int = config.DAYS_AHEAD, start: date | None = None) -> list[RawMatch]:
        from database import now_local

        start = start or now_local().date()
        out: list[RawMatch] = []
        errors: list[str] = []
        for i in range(days_ahead + 1):
            day = start + timedelta(days=i)
            try:
                out.extend(await self.list_day(day))
            except ScrapeError as exc:
                log.error("Journée %s ignorée : %s", day, exc)
                errors.append(str(exc))
        if errors and len(errors) == days_ahead + 1:
            raise ScrapeError("Aucune journée chargée : " + errors[0])
        return out

    async def enrich_with_pinnacle(self, match: RawMatch) -> RawMatch:
        """Remplace les cotes moyennes par celles de Pinnacle si disponibles."""
        if not match.url:
            return match
        try:
            html = await self.fetch(match.url + S.MATCH_1X2_ANCHOR, S.MATCH_READY)
        except ScrapeError as exc:
            log.warning("Page du match indisponible (%s) : cotes moyennes conservées", exc)
            return match
        odds = parsers.parse_bookmaker_odds(html, config.PINNACLE_BOOKMAKER_NAME)
        if odds:
            match.odds_home, match.odds_draw, match.odds_away = odds
            match.odds_source = "pinnacle"
        elif not match.has_odds:
            avg = parsers.parse_average_odds(html)
            if avg:
                match.odds_home, match.odds_draw, match.odds_away = avg
                match.odds_source = "average"
        return match
