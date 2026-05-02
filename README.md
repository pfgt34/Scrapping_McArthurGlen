# Scraping Framework — Guide de démarrage

Ce dépôt contient un framework ETL léger pour scraper des centres commerciaux (hybride static + Selenium), un exemple spécialisé pour McArthurGlen et une UI locale pour afficher le catalogue de McArthurGlen Provence.

## Prérequis
- Python 3.10+ installé
- Chrome (ou Chromium) si vous utilisez le mode dynamique (Selenium)
- ChromeDriver correspondant à votre version de Chrome (ou configurez `webdriver-manager`)

## Installation (Windows - PowerShell)

1) Créez et activez un environnement virtuel:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2) Installez les dépendances et le package en mode editable:

```powershell
pip install -r requirements.txt
pip install -e .
```

Remarque: le projet utilise `selenium` pour le rendu dynamique. Assurez-vous que `chromedriver` est disponible dans le `PATH` ou utilisez `webdriver-manager`.

## Commandes utiles

- Lancer l'UI locale (provence dashboard) et forcer un rafraîchissement des données frontend :

```powershell
python -m scraping_framework --provence-ui --refresh-frontend-data
```

- Lancer un crawl d'un centre spécifique (ex: URL d'une page centre):

```powershell
python -m scraping_framework --center-url "https://www.mcarthurglen.com/en/provence/stores/"
```

- Lancer le pipeline complet (extraction → processeur → snapshots) via l'API CLI:

```powershell
python -m scraping_framework --run-pipeline --profile mcarthurglen:provence
```

Consultez `python -m scraping_framework --help` pour toutes les options disponibles.

## Données et logs
- Raw HTML: `data/raw/<centre_id>/<YYYY-MM-DD>/...`
- Snapshots CSV: `data/processed/<centre_id>/<YYYY-MM-DD>.csv`
- Diffs (ouvertures/fermetures): `data/diffs/<centre_id>/...`
- Logs: `logs/`

## Notes importantes
- Le mode statique (BeautifulSoup) est préféré quand possible. Certains sites (notamment McArthurGlen) rendent le contenu via JS; usez `--requires-javascript` ou laissez l'UI forcer le rendu dynamique.
- Respectez les conditions d'utilisation des sites et les règles robots.txt. Ajoutez throttling, proxies et backoff pour un usage responsable.
- Pour Selenium en CI / production, envisagez `webdriver-manager`, des images Docker avec Chrome headless, ou des services cloud (Browserless, Playwright cloud, etc.).

## Dépannage rapide
- Erreur Selenium / ChromeDriver: vérifiez la version du ChromeDriver et qu'il est dans le `PATH`.
- Pas de données / listes incomplètes: retenter en mode dynamique (`requires_javascript=True`).
- Problèmes d'import: installez le package editable `pip install -e .` depuis la racine du projet.
