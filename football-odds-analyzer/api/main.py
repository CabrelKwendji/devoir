"""Point d'entrée FastAPI : `uvicorn api.main:app --reload`."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import config
from api import scheduler
from api.routes import router
from database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Football Odds Analyzer", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=config.BASE_DIR / "web" / "static"), name="static")
app.include_router(router)
