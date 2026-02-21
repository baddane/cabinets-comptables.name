#!/usr/bin/env python3
"""
Scraper SIRENE — API officielle gouvernementale (api.gouv.fr)
Endpoint : recherche-entreprises.api.gouv.fr

Source : données INSEE/SIRENE — open data, licence Etalab 2.0 (domaine public)
Aucune clé API requise.

Code NAF 69.20Z = « Activités comptables »
Couvre tous les experts-comptables, commissaires aux comptes et cabinets
comptables de France métropolitaine et DOM.

Usage :
    python scraper/scrape_sirene.py
    # Options :
    python scraper/scrape_sirene.py --max 5000      # limiter à 5 000 résultats
    python scraper/scrape_sirene.py --dept 75,69    # filtre département
    python scraper/scrape_sirene.py --output data/cabinets.json

Sortie : data/cabinets.json (remplace le fichier existant)
"""

import json
import time
import logging
import argparse
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("Dépendances manquantes. Lancez: pip install requests")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT       = Path(__file__).parent.parent
DATA_DIR   = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# ─── Configuration ────────────────────────────────────────────────────────────

API_BASE    = "https://recherche-entreprises.api.gouv.fr"
NAF_CODE    = "69.20Z"          # Activités comptables
PER_PAGE    = 25                # Maximum supporté par l'API
DELAY       = 0.4               # Secondes entre chaque requête (politesse)
MAX_RETRIES = 3                 # Tentatives en cas d'erreur réseau

# Départements métropolitains + DOM (pour filtre optionnel)
ALL_DEPTS = [str(i).zfill(2) for i in range(1, 96) if i != 20] + [
    "2A", "2B",           # Corse
    "971", "972", "973", "974", "976",  # DOM
]

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "cabinets-comptables.name/1.0 (scraper SIRENE open-data, contact@cabinets-comptables.name)",
    "Accept": "application/json",
})


# ─── Appels API ───────────────────────────────────────────────────────────────

def api_get(path: str, params: dict) -> dict:
    """GET avec retry exponentiel."""
    url = f"{API_BASE}{path}"
    for attempt in range(MAX_RETRIES):
        try:
            resp = SESSION.get(url, params=params, timeout=20)
            if resp.status_code == 429:
                wait = 5 * (attempt + 1)
                log.warning(f"Rate-limit (429) — attente {wait}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.Timeout:
            log.warning(f"Timeout (tentative {attempt + 1}/{MAX_RETRIES})")
            time.sleep(2 ** attempt)
        except requests.RequestException as e:
            log.error(f"Erreur réseau: {e}")
            time.sleep(2 ** attempt)
    return {}


def fetch_page(page: int, dept: str | None = None) -> dict:
    params = {
        "activite_principale": NAF_CODE,
        "per_page": PER_PAGE,
        "page": page,
        "etat_administratif": "A",      # Uniquement établissements actifs
    }
    if dept:
        params["departement"] = dept
    return api_get("/search", params)


# ─── Normalisation ────────────────────────────────────────────────────────────

def _to_float(val) -> float | str:
    """Convertit une valeur en float, retourne '' si impossible (ex: '[NON-DIFFUSIBLE]')."""
    if not val:
        return ""
    try:
        return float(val)
    except (ValueError, TypeError):
        return ""


def normalize_phone(raw: str) -> str:
    """Formate un numéro français en XX XX XX XX XX."""
    if not raw:
        return ""
    digits = "".join(c for c in raw if c.isdigit())
    # Numéros français : 10 chiffres commençant par 0
    if len(digits) == 10 and digits.startswith("0"):
        return " ".join(digits[i:i+2] for i in range(0, 10, 2))
    # International +33
    if len(digits) == 11 and digits.startswith("33"):
        d = "0" + digits[2:]
        return " ".join(d[i:i+2] for i in range(0, 10, 2))
    return raw.strip()


def extract_cabinet(result: dict) -> dict | None:
    """Convertit un résultat API en dict cabinet."""
    siege = result.get("siege") or {}

    name = (
        result.get("nom_complet")
        or result.get("nom_raison_sociale")
        or ""
    ).strip()
    if not name:
        return None

    # Rejeter les entrées non-diffusibles (données masquées)
    if "[NON-DIFFUSIBLE]" in name:
        return None

    # Ignorer les établissements sans ville connue
    city_raw = siege.get("libelle_commune", "") or ""
    if not city_raw or "[NON-DIFFUSIBLE]" in city_raw:
        return None

    # Adresse
    address_parts = []
    num   = siege.get("numero_voie", "")
    type_ = siege.get("type_voie", "")
    lib   = siege.get("libelle_voie", "")
    if num:  address_parts.append(str(num))
    if type_: address_parts.append(type_.capitalize())
    if lib:   address_parts.append(lib.title())
    address = " ".join(address_parts)

    postal_code  = siege.get("code_postal", "") or ""
    city         = city_raw.title().strip()

    # Coordonnées GPS (disponibles pour ~90 % des établissements)
    lat = siege.get("latitude")
    lng = siege.get("longitude")

    # Téléphone — SIRENE ne contient pas les téléphones (données privées)
    # Le champ est laissé vide pour une éventuelle enrichissement ultérieur

    return {
        "name":         name,
        "address":      address,
        "city":         city,
        "postal_code":  postal_code,
        "phone":        "",
        "website":      "",
        "rating":       "",
        "reviews_count": 0,
        "lat":          _to_float(lat),
        "lng":          _to_float(lng),
        "siren":        result.get("siren", ""),
        "siret":        siege.get("siret", ""),
    }


# ─── Scraping par département ─────────────────────────────────────────────────

def scrape_dept(dept: str, max_per_dept: int = 2000) -> list[dict]:
    """Récupère tous les cabinets d'un département."""
    cabinets = []

    # 1ère page pour connaître le total
    first = fetch_page(1, dept)
    total = first.get("total_results", 0)
    if total == 0:
        return []

    pages_needed = min((total + PER_PAGE - 1) // PER_PAGE,
                       max_per_dept // PER_PAGE + 1)
    log.info(f"    Dept {dept} : {total} établissements → {pages_needed} pages")

    for page in range(1, pages_needed + 1):
        data = first if page == 1 else fetch_page(page, dept)
        for result in data.get("results", []):
            cab = extract_cabinet(result)
            if cab:
                cabinets.append(cab)
        if page < pages_needed:
            time.sleep(DELAY)

    return cabinets


def scrape_national(max_total: int = 10000) -> list[dict]:
    """Récupère sans filtre département (pour un aperçu national rapide)."""
    cabinets = []

    first = fetch_page(1)
    total = first.get("total_results", 0)
    log.info(f"Total SIRENE 69.20Z : {total} établissements actifs")

    pages = min((total + PER_PAGE - 1) // PER_PAGE,
                max_total // PER_PAGE)

    for page in range(1, pages + 1):
        data = first if page == 1 else fetch_page(page)
        new = 0
        for result in data.get("results", []):
            cab = extract_cabinet(result)
            if cab:
                cabinets.append(cab)
                new += 1
        if page % 20 == 0 or page == pages:
            log.info(f"  Page {page}/{pages} — {len(cabinets)} cabinets récupérés")
        time.sleep(DELAY)

    return cabinets


# ─── Dédoublonnage ────────────────────────────────────────────────────────────

def deduplicate(cabinets: list[dict]) -> list[dict]:
    """Supprime les doublons par SIRET (identifiant unique)."""
    seen_sirets = set()
    unique = []
    for c in cabinets:
        siret = c.get("siret", "")
        if siret and siret in seen_sirets:
            continue
        if siret:
            seen_sirets.add(siret)
        unique.append(c)
    log.info(f"Après dédoublonnage : {len(unique)} cabinets uniques")
    return unique


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Scrape les cabinets comptables depuis l'API SIRENE officielle"
    )
    parser.add_argument(
        "--max", type=int, default=10000,
        help="Nombre maximum de cabinets à récupérer (défaut: 10000)"
    )
    parser.add_argument(
        "--dept", type=str, default="",
        help="Départements à filtrer, séparés par virgules (ex: 75,69,13). "
             "Vide = tous les départements."
    )
    parser.add_argument(
        "--output", type=str, default=str(DATA_DIR / "cabinets.json"),
        help="Fichier de sortie JSON"
    )
    parser.add_argument(
        "--mode", choices=["national", "dept"], default="national",
        help="Mode : national (pagination globale) ou dept (par département)"
    )
    args = parser.parse_args()

    output_file = Path(args.output)
    log.info("=== Scraper SIRENE — Cabinets comptables (69.20Z) ===")
    log.info(f"Source : {API_BASE} (open data INSEE)")
    log.info(f"Max résultats : {args.max}")

    # --- Récupération ---
    all_cabinets: list[dict] = []

    if args.dept:
        depts = [d.strip() for d in args.dept.split(",") if d.strip()]
        log.info(f"Mode département : {depts}")
        max_per = max(args.max // len(depts), 500)
        for dept in depts:
            log.info(f"--- Département {dept} ---")
            cabs = scrape_dept(dept, max_per_dept=max_per)
            log.info(f"  → {len(cabs)} cabinets")
            all_cabinets.extend(cabs)
    elif args.mode == "dept":
        log.info("Mode : tous les départements")
        max_per = max(args.max // len(ALL_DEPTS), 100)
        for dept in ALL_DEPTS:
            log.info(f"--- Département {dept} ---")
            try:
                cabs = scrape_dept(dept, max_per_dept=max_per)
                log.info(f"  → {len(cabs)} cabinets")
                all_cabinets.extend(cabs)
                # Sauvegarder régulièrement
                if len(all_cabinets) % 1000 < 50:
                    _save(all_cabinets, output_file, partial=True)
            except Exception as e:
                log.error(f"Erreur dept {dept}: {e}")
    else:
        log.info("Mode : national (pagination globale)")
        all_cabinets = scrape_national(max_total=args.max)

    # --- Dédoublonnage & tri ---
    all_cabinets = deduplicate(all_cabinets)
    all_cabinets.sort(key=lambda c: (c.get("city", ""), c.get("name", "")))

    # --- Sauvegarde finale ---
    _save(all_cabinets, output_file)

    log.info("\n=== Terminé ===")
    log.info(f"  ✅ {len(all_cabinets)} cabinets sauvegardés dans {output_file}")
    log.info("  Relancez le générateur : python generator/generate.py")


def _save(data: list[dict], path: Path, partial: bool = False) -> None:
    label = "(partiel)" if partial else ""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if not partial:
        log.info(f"Sauvegarde {label}: {len(data)} cabinets → {path}")


if __name__ == "__main__":
    main()
