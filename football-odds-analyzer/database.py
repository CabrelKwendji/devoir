"""Modèles SQLAlchemy et gestion de la session SQLite."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator
from zoneinfo import ZoneInfo

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.types import TypeDecorator

import config

TZ = ZoneInfo(config.TIMEZONE)


def now_local() -> datetime:
    return datetime.now(TZ)


class TZDateTime(TypeDecorator):
    """Datetime « aware » stocké en ISO 8601 UTC (triable), restitué en America/Toronto.

    SQLite ne conserve pas les fuseaux : on normalise en UTC à l'écriture pour que
    les comparaisons/tri restent corrects (y compris aux changements d'heure).
    """

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=TZ)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return datetime.fromisoformat(value).astimezone(TZ)


class Base(DeclarativeBase):
    pass


class Match(Base):
    """Match retenu (favori net vs outsider) issu d'OddsPortal."""

    __tablename__ = "matches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # identifiant OddsPortal
    kickoff: Mapped[datetime] = mapped_column(TZDateTime, index=True)
    country: Mapped[str] = mapped_column(String(80))
    league: Mapped[str] = mapped_column(String(120))
    league_path: Mapped[str] = mapped_column(String(160))
    tier: Mapped[int] = mapped_column(Integer)
    home: Mapped[str] = mapped_column(String(120))
    away: Mapped[str] = mapped_column(String(120))
    odds_home: Mapped[float | None] = mapped_column(Float, nullable=True)
    odds_draw: Mapped[float | None] = mapped_column(Float, nullable=True)
    odds_away: Mapped[float | None] = mapped_column(Float, nullable=True)
    odds_source: Mapped[str] = mapped_column(String(20))  # "pinnacle" | "average"
    favorite_side: Mapped[str] = mapped_column(String(4))  # "home" | "away"
    favorite: Mapped[str] = mapped_column(String(120))
    outsider: Mapped[str] = mapped_column(String(120))
    url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    extracted_at: Mapped[datetime] = mapped_column(TZDateTime)

    analysis: Mapped["Analysis | None"] = relationship(
        back_populates="match", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def favorite_odds(self) -> float | None:
        return self.odds_home if self.favorite_side == "home" else self.odds_away

    @property
    def outsider_odds(self) -> float | None:
        return self.odds_away if self.favorite_side == "home" else self.odds_home


class RejectedMatch(Base):
    """Journal des matchs rejetés avec leur motif."""

    __tablename__ = "rejected_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    kickoff: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    league: Mapped[str | None] = mapped_column(String(160), nullable=True)
    home: Mapped[str | None] = mapped_column(String(120), nullable=True)
    away: Mapped[str | None] = mapped_column(String(120), nullable=True)
    odds_home: Mapped[float | None] = mapped_column(Float, nullable=True)
    odds_draw: Mapped[float | None] = mapped_column(Float, nullable=True)
    odds_away: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason_code: Mapped[str] = mapped_column(String(30), index=True)
    reason: Mapped[str] = mapped_column(String(300))
    stage: Mapped[str] = mapped_column(String(20), default="extraction")  # extraction | analyse
    logged_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_local)


class TeamAlias(Base):
    """Table d'alias éditable : nom OddsPortal -> équipe API-Football."""

    __tablename__ = "team_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    oddsportal_name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    api_team_id: Mapped[int] = mapped_column(Integer)
    api_team_name: Mapped[str] = mapped_column(String(120))
    is_manual: Mapped[bool] = mapped_column(Boolean, default=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_local, onupdate=now_local)


class ApiCache(Base):
    """Cache des réponses API-Football (respect du quota)."""

    __tablename__ = "api_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(200))
    params: Mapped[dict] = mapped_column(JSON)
    payload: Mapped[dict] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(TZDateTime)


class Analysis(Base):
    """Résultat de l'analyse des 3 critères pour un match."""

    __tablename__ = "analyses"

    match_id: Mapped[str] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True
    )
    computed_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_local)
    score: Mapped[int] = mapped_column(Integer, default=0)
    verdict: Mapped[str] = mapped_column(String(40))
    implied_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    match: Mapped[Match] = relationship(back_populates="analysis")


class ScrapeRun(Base):
    """Historique des extractions."""

    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(TZDateTime, default=now_local)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|ok|error
    found: Mapped[int] = mapped_column(Integer, default=0)
    kept: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if config.DATABASE_URL.startswith("sqlite") else {},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - dépend du pilote
    if config.DATABASE_URL.startswith("sqlite"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Iterator:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator:
    """Dépendance FastAPI."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
