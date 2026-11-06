# ⚽ Football Odds Analyzer

Application web qui **détecte les matchs de football où un favori net affronte un outsider**
(cotes 1X2 OddsPortal), puis **vérifie si les indicateurs sportifs confirment le statut de favori**
(classement, forme, confrontations directes via API-Football).

> Outil d'analyse de données. Ce n'est pas un conseil de pari.

---

## 1. Fonctionnement

```
OddsPortal (Playwright, rendu JS) ──► filtres ──► SQLite ──► analyse (API-Football, cache) ──► pages web
                                         │
                                         └──► journal des rejets (motif)
```

### Module 1 : extraction OddsPortal (`scraper/`)
- Pages `/matches/football/AAAAMMJJ/` de **J à J+`DAYS_AHEAD`** (3 par défaut), marché 1X2.
- Chromium headless est lancé avec le fuseau `America/Toronto`, donc les heures affichées par OddsPortal sont déjà dans ce fuseau.
- **Cote de référence** (`ODDS_SOURCE`) :
  - `pinnacle` (défaut) : ouvre la page du match et lit la ligne Pinnacle ; si Pinnacle est absent, calcule la **moyenne des bookmakers affichés** ; si la page est illisible, garde la cote de la liste.
  - `average` : moyenne des bookmakers de la page du match.
  - `listing` : cote de la liste du jour, sans ouvrir les matchs. **Attention : OddsPortal y affiche la meilleure cote du marché, pas la moyenne.**
  - Seuls les matchs déjà proches des seuils sont ouverts, dans la limite de `SCRAPE_MAX_MATCH_PAGES`. La source réellement utilisée est enregistrée pour chaque match (`pinnacle`, `moyenne (N bookm.)`, `meilleure`).
  - Les bookmakers affichés dépendent du pays de l'adresse IP. Depuis les États-Unis, OddsPortal ne montre que des bookmakers américains, sans Pinnacle : la cote retenue est alors la moyenne.
- **Liste virtualisée** : la page du jour retire des lignes en défilant. Le scraper capture donc le HTML à chaque étape de défilement et fusionne les matchs (environ 700 matchs pour un samedi chargé).
- **Sélection** (seuils dans `config.py`) : cote du favori `< 1.70`, cote de l'outsider `> 4.00`. Le favori peut jouer à domicile ou à l'extérieur.
- **Exclusions** :
  - Coupes nationales et coupes de la ligue, compétitions européennes et internationales, amicaux, barrages (play-offs), qualifications, supercoupes. Le contrôle porte sur les mots-clés du nom et de l'URL, et sur les « pays » virtuels `world`, `europe`, etc.
  - Championnat absent de `leagues.yaml` : **exclu par défaut**.
  - Niveau > `MAX_LEAGUE_TIER` (2).
- **Bonne conduite** : délai aléatoire de 3 à 8 s entre les pages téléchargées, user-agent réaliste, cache HTML local (`data/cache/oddsportal`, TTL 90 min), 2 nouvelles tentatives en cas d'erreur, images et polices non chargées.
- **Tous les sélecteurs CSS sont dans `scraper/selectors.py`.** Si OddsPortal change son HTML, c'est le seul fichier à modifier.
- Données stockées : id, date/heure (America/Toronto), pays, ligue, niveau, domicile, extérieur, cotes 1/X/2, source des cotes, favori, outsider, horodatage d'extraction.

### Module 2 : analyse (`analysis/`)
| Critère | Règle | Cas neutre ⚪ |
|---|---|---|
| **Classement** | ✅ si le favori est **mieux classé ET a plus de points**. Affiche les rangs, les points, l'écart de rang et l'écart de points. | Classement N/D. Mention « échantillon faible » si moins de 5 journées jouées |
| **Forme** (3 derniers matchs de championnat) | Points V=3, N=1, D=0. ✅ si points du favori > points de l'outsider. Affiche la séquence V/N/D et les buts pour/contre. | Moins de 3 matchs disponibles |
| **H2H** (5 dernières confrontations) | ✅ si victoires du favori > victoires de l'outsider | Moins de 2 confrontations : « données insuffisantes » |

- **Score** = nombre de ✅ (0 à 3). **Verdict** : 3/3 « Favori confirmé », 2/3 « Plutôt confirmé », 0–1/3 « Favori fragile ».
- **Probabilité implicite démarginée** du favori = `(1/cote_fav) / (1/c1 + 1/cX + 1/c2)`.
- Si l'analyse est impossible (équipe non rapprochée, quota atteint, clé absente…), la carte affiche « Analyse impossible », un score « N/D » et la cause. Aucune valeur n'est inventée.

### Rapprochement des noms (`analysis/team_matching.py`)
1. **Table d'alias** (page `/aliases`), toujours prioritaire et éditable.
2. Égalité des noms normalisés (accents, `FC`, `AFC`, abréviations `Utd` → `United`, `Man` → `Manchester`…).
3. `rapidfuzz` (WRatio) avec un seuil `TEAM_MATCH_MIN_SCORE` (85). Un cas **ambigu** (deux candidats proches) est refusé plutôt que deviné.

Les rapprochements automatiques sont enregistrés dans la table d'alias (origine « automatique ») et peuvent être corrigés. Un échec est inscrit au journal des rejets avec le motif « équipe non rapprochée ».

### Pages
| URL | Contenu |
|---|---|
| `/` | Matchs détectés triés par date. Filtres date / pays / ligue / seuils de cotes, bouton « Rafraîchir », heure de la dernière extraction, bouton « Analyser » (HTMX) |
| `/analyse` | Une carte par match (Classement, Forme, H2H, score X/3, verdict). Filtre « seulement 3/3 », tri par score ou par date, **export CSV** |
| `/rejets` | Journal des matchs rejetés avec le motif : coupe, niveau > 2, non référencé, cotes hors seuils, cotes N/D, équipe non rapprochée |
| `/aliases` | Table d'alias OddsPortal ↔ API-Football |
| `/api/matches` | JSON |

Tous les matchs de championnat éligibles et cotés sont stockés, ce qui permet **d'élargir** les seuils depuis l'interface. Les seuils par défaut décident du journal « cotes hors seuils » et de l'analyse automatique.

### Extraction quotidienne vers l'artefact « Favori Confirmé »

`python -m tools.daily_snapshot --out data/snapshot.json` lance une extraction complète (J à J+3), puis écrit un instantané JSON : matchs de championnat éligibles avec cotes, rejets, analyses API-Football si une clé est configurée. Une tâche planifiée Claude Code l'exécute chaque jour et envoie le fichier dans la base de l'artefact (document `oddsportal/latest`), où la page applique les seuils et les 3 critères.

### Planification
APScheduler relance l'extraction **toutes les 2 h** (`REFRESH_INTERVAL_HOURS`), suivie de l'analyse automatique des matchs retenus. Une seule extraction peut tourner à la fois.

### Quota API-Football
Chaque réponse est mise en cache dans SQLite (table `api_cache`, TTL `API_CACHE_TTL_HOURS` = 12 h, 7 à 30 jours pour les ligues et équipes). Par match analysé, et à froid, on compte environ 7 requêtes : saison, équipes, classement, 2 × matchs, H2H. Les matchs suivants de la même ligue réutilisent la saison, les équipes et le classement. Le plan gratuit (100 requêtes/jour) suffit donc pour quelques dizaines de matchs par jour.

---

## 2. Arborescence

```
football-odds-analyzer/
├── config.py              # seuils et paramètres (surchargés par .env)
├── leagues.yaml           # ligue → pays → niveau (+ id API-Football)
├── database.py            # modèles SQLAlchemy / SQLite
├── .env.example
├── requirements.txt
├── Dockerfile
├── scraper/
│   ├── selectors.py       # TOUS les sélecteurs CSS OddsPortal
│   ├── oddsportal.py      # navigation Playwright, délais, retries
│   ├── parsers.py         # HTML rendu → RawMatch (testable hors ligne)
│   ├── filters.py         # coupes, niveaux, seuils de cotes
│   ├── leagues.py         # chargement de leagues.yaml
│   ├── cache.py           # cache HTML local
│   ├── models.py
│   └── pipeline.py        # extraction → base + journal des rejets
├── analysis/
│   ├── criteria.py        # 3 critères, score, verdict, probabilité implicite
│   ├── api_football.py    # client API-Football + cache
│   ├── team_matching.py   # rapidfuzz + alias
│   └── service.py         # orchestration de l'analyse d'un match
├── api/
│   ├── main.py            # application FastAPI
│   ├── routes.py          # pages HTML, HTMX, CSV, JSON
│   └── scheduler.py       # APScheduler
├── web/
│   ├── templates/         # Jinja2 (+ partials HTMX)
│   └── static/app.css
└── tests/                 # filtres, critères, parseurs, rapprochement, pipeline, pages
```

---

## 3. Installation locale

Prérequis : **Python 3.11+**.

```bash
cd football-odds-analyzer
python3.11 -m venv .venv
source .venv/bin/activate            # Windows : .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium   # Linux : ajouter --with-deps si des bibliothèques manquent
cp .env.example .env
```

### Clé API-Football
1. Créer un compte sur <https://dashboard.api-football.com/register> (plan gratuit : 100 requêtes/jour).
2. Copier la clé depuis *Account → My Access*.
3. La coller dans `.env` : `API_FOOTBALL_KEY=...`. Elle est envoyée dans l'en-tête `x-apisports-key`.

### Lancement

```bash
uvicorn api.main:app --reload --port 8000
```

Ouvrir <http://localhost:8000>, puis cliquer **Rafraîchir** pour lancer la première extraction. Elle prend plusieurs minutes à cause des délais de politesse de 3 à 8 s par page.

Extraction ou analyse en ligne de commande :

```bash
python -c "from database import init_db; init_db(); from scraper.pipeline import run_extraction; print(run_extraction())"
python -c "from analysis.service import analyze_pending; print(analyze_pending())"
```

### Tests

```bash
pytest
```

Les tests fonctionnent **hors ligne** : fixtures HTML pour le parseur et API-Football simulée par `httpx.MockTransport`.

### Docker

```bash
docker build -t football-odds-analyzer .
docker run --rm -p 8000:8000 --env-file .env -v "$(pwd)/data:/app/data" football-odds-analyzer
```

---

## 4. Maintenance

- **L'extraction ne renvoie plus rien** : un ⚠ apparaît à côté de « Dernière extraction ». Ouvrir une page OddsPortal dans un navigateur, inspecter une ligne de match et mettre à jour `scraper/selectors.py`. Une fois Playwright lancé, le HTML rendu est conservé dans `data/cache/oddsportal/*.html` et peut servir de nouvelle fixture.
- **Nouveau championnat** : l'ajouter dans `leagues.yaml` (chemin OddsPortal, niveau et, si possible, `api_football_id`). Les ligues changent parfois de slug au gré des sponsors : utiliser `aliases`.
- **Équipe non rapprochée** : ajouter l'alias dans `/aliases` (ID visible via `GET /teams?search=nom` de l'API), puis cliquer « Réanalyser ».
- Respecter les conditions d'utilisation d'OddsPortal et d'API-Football. Le scraper est volontairement lent et met en cache ses pages.
