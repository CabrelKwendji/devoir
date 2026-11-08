"""Lecture des résultats : lignes « Finished » de la page du jour et score final d'une page de match."""
from scraper.parsers import match_ids, parse_final_result, parse_results

ROW = """<div><a href="/football/h2h/arsenal-hA1Zm19f/hull-city-S66R0t75/#Eyc1EfPH"><div><p>
<span class="max-md:hidden">Finished</span><span class="min-md:hidden">FIN</span></p></div>
<div><span>1</span><div><img alt=""><p>Arsenal</p></div><span>-</span><div><img alt=""><p>Hull</p></div><span>0</span></div></a>
<ul><li><p>1.17</p></li><li><p>9.00</p></li><li><p>21.00</p></li></ul></div>
<div><a href="/football/h2h/a-aaaaaaaa/b-bbbbbbbb/#Zz9Zz9Zz"><div><p>18:30</p></div>
<div><p>Alpha</p><span>-</span><p>Beta</p></div></a></div>"""


def test_parse_results_finished_and_upcoming():
    res = parse_results(ROW)
    ars = res["Eyc1EfPH"]
    assert (ars.status, ars.home, ars.away, ars.home_goals, ars.away_goals) == ("Finished", "Arsenal", "Hull", 1, 0)
    assert ars.finished
    assert not res["Zz9Zz9Zz"].finished and res["Zz9Zz9Zz"].home_goals is None
    assert match_ids(ROW) == {"Eyc1EfPH", "Zz9Zz9Zz"}


def test_parse_final_result():
    html = "<div><p>Club Brugge KV</p> 1 - <p>Anderlecht</p> 1 Today, 08 Nov 2026, 07:30 Final&nbsp;result&nbsp; 1:1 &nbsp;(1:0,&nbsp;0:1)</div>"
    assert parse_final_result(html) == (1, 1)
    assert parse_final_result("<p>Tomorrow, 07 Nov 2026, 10:00</p>") is None
