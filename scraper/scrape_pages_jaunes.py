#!/usr/bin/env python3
"""
Scraper PagesJaunes pour les cabinets comptables.
Scrape les 20 plus grandes villes françaises.
En cas d'échec (anti-bot), utilise des données de démonstration réalistes.
"""

import json
import time
import random
import logging
import sys
import os
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Dépendances manquantes. Lancez: pip install -r requirements.txt")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Répertoire racine du projet
ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
OUTPUT_FILE = DATA_DIR / "cabinets.json"

CITIES = [
    ("Paris", "75"),
    ("Lyon", "69"),
    ("Marseille", "13"),
    ("Toulouse", "31"),
    ("Nice", "06"),
    ("Nantes", "44"),
    ("Strasbourg", "67"),
    ("Montpellier", "34"),
    ("Bordeaux", "33"),
    ("Lille", "59"),
    ("Rennes", "35"),
    ("Reims", "51"),
    ("Saint-Etienne", "42"),
    ("Toulon", "83"),
    ("Grenoble", "38"),
    ("Dijon", "21"),
    ("Angers", "49"),
    ("Nimes", "30"),
    ("Villeurbanne", "69"),
    ("Le Mans", "72"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def scrape_city(city: str, dept: str) -> list[dict]:
    """Scrape PagesJaunes pour une ville donnée."""
    results = []
    city_slug = city.lower().replace(" ", "-").replace("é", "e").replace("è", "e")

    for page in range(1, 4):  # max 3 pages par ville
        url = (
            f"https://www.pagesjaunes.fr/pagesblanches/recherche"
            f"?quoiqui=cabinet+comptable&ou={city_slug}&page={page}"
        )
        # URL alternative (annonces pro)
        url_pro = (
            f"https://www.pagesjaunes.fr/annuaire/chercherlespros"
            f"?quoiqui=cabinet+comptable&ou={city_slug}&page={page}"
        )

        try:
            log.info(f"Scraping {city} page {page}...")
            resp = SESSION.get(url_pro, timeout=15)

            if resp.status_code == 403 or resp.status_code == 429:
                log.warning(f"Bloqué par PagesJaunes pour {city} (HTTP {resp.status_code})")
                return results

            if resp.status_code != 200:
                log.warning(f"HTTP {resp.status_code} pour {city}")
                break

            soup = BeautifulSoup(resp.text, "lxml")

            # Sélecteurs PagesJaunes (structure 2024)
            listings = soup.select("div.bi-content, article.result-item, div[data-result-item]")

            if not listings:
                # Tentative avec sélecteurs alternatifs
                listings = soup.select("div.bi-header, li.result")

            if not listings:
                log.info(f"Aucun résultat trouvé pour {city} page {page} — fin")
                break

            for item in listings:
                cabinet = parse_listing(item, city, dept)
                if cabinet:
                    results.append(cabinet)

            # Délai poli entre les pages
            time.sleep(random.uniform(2.0, 3.5))

        except requests.RequestException as e:
            log.error(f"Erreur réseau pour {city}: {e}")
            break

    return results


def parse_listing(item, city: str, dept: str) -> dict | None:
    """Extrait les données d'un résultat PagesJaunes."""
    try:
        # Nom
        name_el = item.select_one("a.denomination-links, span.bi-denomination, h3.name a")
        name = name_el.get_text(strip=True) if name_el else None
        if not name:
            return None

        # Adresse
        addr_el = item.select_one("span.bi-address, address, span[itemprop='streetAddress']")
        address = addr_el.get_text(strip=True) if addr_el else ""

        # Code postal
        cp_el = item.select_one("span[itemprop='postalCode'], span.bi-cp")
        postal_code = cp_el.get_text(strip=True) if cp_el else f"{dept}000"

        # Téléphone
        phone_el = item.select_one("span[data-pj-tel], span.bi-tel, a[href^='tel:']")
        phone = ""
        if phone_el:
            phone = phone_el.get("data-pj-tel") or phone_el.get_text(strip=True)

        # Site web
        web_el = item.select_one("a.bi-website, a[data-pj-website]")
        website = web_el.get("href", "") if web_el else ""
        if website and not website.startswith("http"):
            website = ""

        # Note
        rating_el = item.select_one("span.bi-avis-note, span.rating-value")
        rating = rating_el.get_text(strip=True) if rating_el else ""

        return {
            "name": name,
            "address": address,
            "city": city,
            "postal_code": postal_code,
            "phone": phone,
            "website": website,
            "rating": rating,
        }
    except Exception as e:
        log.debug(f"Erreur parsing: {e}")
        return None


def generate_demo_data() -> list[dict]:
    """
    Génère des données de démonstration réalistes si le scraping échoue.
    Basées sur des structures de cabinets typiques.
    """
    log.info("Génération des données de démonstration...")

    cabinet_types = [
        "Audit & Conseil", "Expertise Comptable", "Gestion & Finance",
        "Compta Services", "Cabinet Fiscal", "Expertise & Gestion",
    ]
    last_names = [
        "Martin", "Bernard", "Dubois", "Thomas", "Robert", "Richard",
        "Petit", "Durand", "Leroy", "Moreau", "Simon", "Laurent",
        "Lefebvre", "Michel", "Garcia", "David", "Bertrand", "Roux",
        "Vincent", "Fournier", "Morel", "Girard", "André", "Mercier",
    ]
    street_types = ["rue", "avenue", "boulevard", "place", "allée", "impasse"]
    street_names = [
        "de la Paix", "du Commerce", "des Fleurs", "Victor Hugo",
        "Jean Jaurès", "de la République", "Gambetta", "du Général de Gaulle",
        "Pasteur", "Voltaire", "de la Liberté", "des Arts",
    ]

    city_data = {
        "Paris":         ("75008", "01 4"),
        "Lyon":          ("69002", "04 7"),
        "Marseille":     ("13001", "04 9"),
        "Toulouse":      ("31000", "05 6"),
        "Nice":          ("06000", "04 9"),
        "Nantes":        ("44000", "02 4"),
        "Strasbourg":    ("67000", "03 8"),
        "Montpellier":   ("34000", "04 6"),
        "Bordeaux":      ("33000", "05 5"),
        "Lille":         ("59000", "03 2"),
        "Rennes":        ("35000", "02 9"),
        "Reims":         ("51100", "03 2"),
        "Saint-Etienne": ("42000", "04 7"),
        "Toulon":        ("83000", "04 9"),
        "Grenoble":      ("38000", "04 7"),
        "Dijon":         ("21000", "03 8"),
        "Angers":        ("49000", "02 4"),
        "Nimes":         ("30000", "04 6"),
        "Villeurbanne":  ("69100", "04 7"),
        "Le Mans":       ("72000", "02 4"),
    }

    data = []
    random.seed(42)  # reproductible

    for city, (base_cp, phone_prefix) in city_data.items():
        count = random.randint(25, 45)
        used_names = set()

        for i in range(count):
            # Nom du cabinet
            ln = random.choice(last_names)
            ln2 = random.choice(last_names)
            ctype = random.choice(cabinet_types)
            forms = [
                f"Cabinet {ln}",
                f"{ln} & {ln2} Expertise Comptable",
                f"Cabinet {ln} - {ctype}",
                f"{ln} {ctype}",
                f"Cabinet d'Expertise {ln}",
            ]
            name = random.choice(forms)
            if name in used_names:
                name = f"{name} {i}"
            used_names.add(name)

            # Adresse
            num = random.randint(1, 120)
            street = f"{num} {random.choice(street_types)} {random.choice(street_names)}"

            # CP avec variation
            cp_num = int(base_cp)
            if city == "Paris":
                cp_num = random.choice([75001, 75002, 75008, 75009, 75010, 75015, 75016, 75017])
            postal_code = str(cp_num)

            # Téléphone
            suffix = "".join([str(random.randint(0, 9)) for _ in range(7)])
            phone = f"{phone_prefix}{suffix[:1]} {suffix[1:3]} {suffix[3:5]} {suffix[5:7]}"

            # Site web (30% des cabinets)
            website = ""
            if random.random() < 0.30:
                slug = name.lower().replace(" ", "-").replace("&", "").replace("'", "")
                slug = "".join(c for c in slug if c.isalnum() or c == "-")
                website = f"https://www.{slug[:20]}.fr"

            # Note (60% des cabinets)
            rating = ""
            if random.random() < 0.60:
                rating = f"{random.uniform(3.5, 5.0):.1f}"

            data.append({
                "name": name,
                "address": street,
                "city": city,
                "postal_code": postal_code,
                "phone": phone,
                "website": website,
                "rating": rating,
            })

    log.info(f"Données de démonstration générées : {len(data)} cabinets")
    return data


def main():
    all_cabinets = []
    scraping_failed = False

    for city, dept in CITIES:
        log.info(f"--- Ville : {city} ---")
        cabinets = scrape_city(city, dept)

        if cabinets:
            log.info(f"  {len(cabinets)} cabinets trouvés pour {city}")
            all_cabinets.extend(cabinets)
        else:
            log.warning(f"  Aucun résultat pour {city} (scraping bloqué ou vide)")
            scraping_failed = True

        time.sleep(random.uniform(1.5, 3.0))

    # Si moins de 50 résultats réels, utiliser les données de démo
    if len(all_cabinets) < 50:
        log.warning(
            f"Seulement {len(all_cabinets)} cabinets scrapés. "
            "Utilisation des données de démonstration."
        )
        all_cabinets = generate_demo_data()

    # Sauvegarde
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_cabinets, f, ensure_ascii=False, indent=2)

    log.info(f"✅ {len(all_cabinets)} cabinets sauvegardés dans {OUTPUT_FILE}")

    if scraping_failed:
        log.warning(
            "⚠️  Le scraping PagesJaunes a été partiellement bloqué. "
            "Données de démonstration utilisées. "
            "Consultez scraper/README.md pour les alternatives."
        )


if __name__ == "__main__":
    main()
