"""Pipeline d'extraction hors ligne : le scraping Playwright est remplacé par la fixture HTML."""
from datetime import timedelta

from database import Match, RejectedMatch, ScrapeRun, now_local, session_scope
from scraper import pipeline
from scraper.parsers import parse_listing
from tests.conftest import FIXTURES, reset_db


def test_run_extraction_stores_kept_and_logs_rejects(monkeypatch):
    reset_db()
    day = (now_local() + timedelta(days=1)).date()
    raws = parse_listing((FIXTURES / "listing.html").read_text(), day)

    async def fake_scrape(days_ahead):
        decisions = {}
        for r in raws:
            res = pipeline.evaluate_match(r, pipeline.default_leagues())
            if not res.kept and res.reason_code not in (pipeline.REJECT_ODDS, pipeline.REJECT_ODDS_MISSING):
                decisions[r.match_id] = (res.reason_code, res.reason)
        return raws, decisions

    monkeypatch.setattr(pipeline, "_scrape", fake_scrape)
    summary = pipeline.run_extraction(days_ahead=1)
    assert summary["status"] == "ok" and summary["found"] == 3 and summary["kept"] == 2

    with session_scope() as s:
        ars = s.get(Match, "AbCd1234")
        assert ars.favorite == "Arsenal" and ars.outsider == "Burnley" and ars.tier == 1
        assert ars.country == "Angleterre" and ars.kickoff.tzinfo is not None
        eve = s.get(Match, "ZyXw9876")
        assert eve.favorite_side == "away" and eve.favorite == "Liverpool"
        assert s.get(Match, "QqQq1111") is None  # FA Cup
        rej = s.query(RejectedMatch).filter_by(match_key="QqQq1111").one()
        assert rej.reason_code == "coupe"
        assert s.query(ScrapeRun).order_by(ScrapeRun.id.desc()).first().status == "ok"
