"""Planification APScheduler : rafraîchissement automatique toutes les 2 h."""
from __future__ import annotations

import logging
import threading

from apscheduler.schedulers.background import BackgroundScheduler

import config
from database import TZ

log = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone=TZ)


def _job() -> None:
    from scraper.pipeline import run_extraction

    log.info("Rafraîchissement planifié")
    run_extraction()


def trigger_refresh_now() -> None:
    """Lance une extraction dans un thread (n'attend pas la fin)."""
    threading.Thread(target=_job, name="refresh", daemon=True).start()


def start() -> None:
    if not config.SCHEDULER_ENABLED or scheduler.running:
        return
    scheduler.add_job(_job, "interval", hours=config.REFRESH_INTERVAL_HOURS, id="refresh",
                      max_instances=1, coalesce=True, replace_existing=True)
    scheduler.start()
    log.info("Planificateur démarré (toutes les %d h)", config.REFRESH_INTERVAL_HOURS)


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
