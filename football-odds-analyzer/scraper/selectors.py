"""Sélecteurs et motifs OddsPortal — CENTRALISÉS ICI.

OddsPortal modifie régulièrement son HTML. Quand l'extraction ne trouve plus rien,
c'est ce fichier (et uniquement lui) qu'il faut mettre à jour.

Structure observée en novembre 2026 (site Next.js) :
  * page du jour /matches/football/AAAAMMJJ/ : liste « à plat ». Chaque ligue commence par un
    fil d'Ariane  Football / <Pays> / <Ligue>  (liens /football/, /football/<pays>/,
    /football/<pays>/<ligue>/), suivi des lignes de match de cette ligue.
  * ligne de match : <a href="/football/h2h/<equipeA-id>/<equipeB-id>/#<ID match>"> contenant
    des <p> (heure, domicile, extérieur), puis un <ul> frère avec 3 <li><p>cote</p></li>.
    Les cotes de la liste sont les MEILLEURES cotes disponibles, pas la moyenne.
  * page de match (même URL h2h) : <table> dont chaque <tr> = un bookmaker
    (1re cellule : nom ; cellules 2-4 : cotes 1, X, 2).
  * Les bookmakers affichés dépendent du pays de l'adresse IP (ex. : bookmakers américains
    seulement depuis les États-Unis, sans Pinnacle).
"""
from __future__ import annotations

import re

# --- URL ---------------------------------------------------------------------
DAY_LISTING_PATH = "/matches/football/{date}/"   # date = AAAAMMJJ
MATCH_1X2_ANCHOR = ""                            # l'URL h2h#ID ouvre déjà le 1X2 temps réglementaire

# --- Page « matchs du jour » -------------------------------------------------
# Attendre l'apparition d'au moins une ligne de match
LISTING_READY = ["a[href^='/football/h2h/']"]
# Lien de ligue dans le fil d'Ariane : /football/<pays>/<ligue>/
LEAGUE_LINK_RE = re.compile(r"^/football/([a-z0-9-]+)/([a-z0-9-]+)/$")
# Premiers segments d'URL qui ne sont pas des pays
NON_COUNTRY_SEGMENTS = {"h2h", "results", "standings", "outrights"}
# La liste du jour est virtualisée : des lignes disparaissent en défilant. On capture donc le
# HTML à chaque étape de défilement (SCROLL_STEP_PX) et on fusionne les matchs lus.
SCROLL_STEP_PX = 2500
SCROLL_MAX_STEPS = 80
SCROLL_IDLE_STEPS = 4   # arrêt après N étapes sans nouveau match
# Depuis le 7 nov. 2026, la suite de la liste se charge avec un bouton « SHOW MORE »
SHOW_MORE = ["button:text-matches('^\\s*show more\\s*$', 'i')", "text=/^\\s*show more\\s*$/i"]
# Lien de match : /football/h2h/<equipe-id>/<equipe-id>/#<ID>
# (les encarts promotionnels n'ont pas de #ID : ils sont ignorés)
MATCH_LINK_RE = re.compile(r"^/football/h2h/([^/]+)/([^/]+)/#([A-Za-z0-9]{8})$")
# Ancien format d'URL (avant 2026), conservé en repli
LEGACY_MATCH_LINK_RE = re.compile(r"^/football/([a-z0-9-]+)/([a-z0-9-]+)/([^/]+)-([A-Za-z0-9]{8})/?$")
# Textes à l'intérieur du lien de match : heure puis noms des équipes
MATCH_TEXTS = "p"
# Cotes de la ligne (cherchées dans le parent du lien de match)
ROW_ODDS = ["ul li p", "ul li", "[data-testid='odd-container'] p"]

# --- Page d'un match ---------------------------------------------------------
MATCH_READY = ["table tr td a[href*='/bookmakers/']", "table tr"]
BOOKMAKER_ROW = "table tr"
# Lien du bookmaker : /proxy/bookmakers/<slug>/link/ ou /bookmakers/<slug>/
BOOKMAKER_SLUG_RE = re.compile(r"/bookmakers/([a-z0-9-]+)/")
AVERAGE_ROW_LABELS = ["Average", "Moyenne", "Avg"]

# --- Bannière cookies --------------------------------------------------------
COOKIE_ACCEPT = ["#onetrust-accept-btn-handler", "button:has-text('I Accept')", "button:has-text('Accept')"]

# --- Classement d'une ligue (critères Classement et Forme) ---------------------
# /football/<pays>/<ligue>/standings/ : <tr class="... glib-participant-<ID équipe>"> par équipe,
# cellules td.col_rank, td.col_participant_name, td.col_matches_played, td.col_points,
# td.col_form > a[xparam] : « [b]0:1 [/b](Liverpool - Arsenal)\n01.11.2026 » (le plus récent
# en premier ; « Next match » = match à venir, ignoré).
STANDINGS_PATH = "/football/{league_path}/standings/"
STANDINGS_READY = ["tr[class*='glib-participant-']"]
STANDINGS_ROW = "tr[class*='glib-participant-']"
STANDINGS_TEAM_ID_RE = re.compile(r"glib-participant-([A-Za-z0-9]{8})")
STANDINGS_RANK = "td.col_rank"
STANDINGS_NAME = "td.col_participant_name"
STANDINGS_PLAYED = "td.col_matches_played"
STANDINGS_POINTS = "td.col_points"
STANDINGS_FORM_LINKS = "td.col_form a[xparam]"
FORM_XPARAM_RE = re.compile(r"\[b\]\s*(\d+)\s*:\s*(\d+)\s*\[/b\]\s*\((.+?)\s+-\s+(.+?)\)\s*(\d{2}\.\d{2}\.\d{4})", re.S)

# --- Confrontations directes (page du match) ---------------------------------
# Titre « H2H Results », puis blocs : fil d'Ariane de ligue « Premier League 2016/2017 »
# et lignes <a href="/football/h2h/...#ID"> contenant <p>JJ/Mois</p>, <span>score dom.</span>,
# <p>domicile</p>, <p>extérieur</p>, <span>score ext.</span>.
H2H_TITLE_RE = re.compile(r"^\s*H2H Results\s*$")
SEASON_RE = re.compile(r"(\d{4})(?:[/-](\d{4}))?\s*$")
H2H_DATE_RE = re.compile(r"^(\d{1,2})/([A-Za-z]{3})$")
# ID d'équipe dans un lien h2h : /football/h2h/<slug>-<ID>/<slug>-<ID>/
TEAM_IDS_IN_H2H_RE = re.compile(r"/football/h2h/[a-z0-9-]*?-?([A-Za-z0-9]{8})/[a-z0-9-]*?-?([A-Za-z0-9]{8})/")
