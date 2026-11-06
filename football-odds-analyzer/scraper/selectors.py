"""Sélecteurs CSS OddsPortal — CENTRALISÉS ICI.

OddsPortal modifie régulièrement son HTML. Quand l'extraction ne trouve plus rien,
c'est ce fichier (et uniquement lui) qu'il faut mettre à jour.
Chaque entrée est une liste de sélecteurs essayés dans l'ordre : le premier qui
renvoie un résultat est utilisé.
"""
from __future__ import annotations

# --- URL ---------------------------------------------------------------------
# Page listant tous les matchs de football d'une journée (AAAAMMJJ)
DAY_LISTING_PATH = "/matches/football/{date}/"
# Ancre du marché 1X2 temps réglementaire sur une page de match
MATCH_1X2_ANCHOR = "#1X2;2"

# --- Page « matchs du jour » -------------------------------------------------
# Attendre l'un de ces éléments avant de capturer le HTML
LISTING_READY = ["div.eventRow", "div[class*='eventRow']"]

# Une ligne par match (l'en-tête de ligue n'apparaît que sur la 1re ligne de chaque ligue)
EVENT_ROW = ["div.eventRow", "div[class*='eventRow']"]

# En-tête de ligue (fil d'Ariane pays / ligue) à l'intérieur d'une ligne
LEAGUE_HEADER_LINKS = [
    "div[data-testid='secondary-header'] a[href^='/football/']",
    "a[href^='/football/'][class*='breadcrumb']",
]

# Lien vers la page du match : /football/<pays>/<ligue>/<domicile>-<exterieur>-<ID>/
MATCH_LINK = ["a[href^='/football/'][href*='-']"]

# Heure de coup d'envoi (HH:MM)
KICKOFF_TIME = [
    "[data-testid='time-item'] p",
    "[data-testid='time-item']",
    "div[class*='time'] p",
]

# Noms des équipes (2 éléments : domicile puis extérieur)
PARTICIPANT_NAME = [
    "p.participant-name",
    "[data-testid='event-participants'] p",
    "a[title] p",
]

# Cellules de cotes (3 éléments : 1, X, 2) — cote moyenne affichée par défaut
ODDS_CELL = [
    "[data-testid='odd-container'] p",
    "[data-testid='odd-container-default'] p",
    "[data-testid='odd-container-winning'] p",
    "div[class*='odds-cell'] p",
]

# --- Page d'un match ---------------------------------------------------------
MATCH_READY = ["[data-testid='over-under-expanded-row']", "div[class*='border-black-borders']", "[data-testid='odd-container']"]

# Lignes « bookmaker » du tableau 1X2
BOOKMAKER_ROW = [
    "[data-testid='over-under-expanded-row']",
    "div[class*='border-black-borders'][class*='flex']",
]
# Nom du bookmaker dans une ligne
BOOKMAKER_NAME = [
    "[data-testid='outrights-expanded-bookmaker-name']",
    "a[title]",
    "img[alt]",
    "p",
]
# Ligne « Average » (cote moyenne) en bas du tableau
AVERAGE_ROW_LABELS = ["Average", "Moyenne", "Avg"]

# --- Bannière cookies --------------------------------------------------------
COOKIE_ACCEPT = ["#onetrust-accept-btn-handler", "button:has-text('I Accept')", "button:has-text('Accept')"]
