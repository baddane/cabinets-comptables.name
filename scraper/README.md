# Scraper — Alternatives à PagesJaunes

PagesJaunes bloque les requêtes automatiques (HTTP 403). Voici les alternatives :

## Option 1 — Données de démonstration (défaut)
Le scraper génère automatiquement 750+ cabinets réalistes si le scraping échoue.
Le site est **immédiatement déployable** avec ces données.

## Option 2 — ScrapingBee / ScraperAPI
Services de scraping avec rotation de proxies et résolution de CAPTCHAs.

```python
# Exemple avec ScraperAPI
url = f"http://api.scraperapi.com?api_key=VOTRE_CLE&url={url_pages_jaunes}"
resp = requests.get(url)
```

## Option 3 — Sirene API (données officielles INPI)
API officielle française des entreprises. Gratuite, légale, fiable.
- URL : https://api.insee.fr/catalogue/site/themes/wso2/subthemes/insee/pages/item-info.jag?name=Sirene&version=V3&provider=insee
- Filtrer par code NAF : `6920Z` (Activités comptables)

## Option 4 — Société.com / Pappers.fr
Ces sites ont des APIs et des données plus propres sur les sociétés françaises.
- Pappers : https://www.pappers.fr/api (freemium)

## Option 5 — Scraping headless (Playwright)
```bash
pip install playwright
playwright install chromium
```
Permet de contourner certaines protections JS.
