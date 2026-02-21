#!/usr/bin/env python3
"""
Enrichissement des cabinets SIRENE via l'API Google Places.

Pour chaque cabinet : téléphone, site web, note Google, nombre d'avis,
coordonnées GPS précises.

Pré-requis :
    export GOOGLE_PLACES_API_KEY="AIza..."
    # Console Google Cloud → activer "Places API (New)" ou "Places API"
    # https://console.cloud.google.com/apis/library

Coût estimé (nouvelle API Places v1, $200/mois offerts) :
    Text Search  Basic    → $32 / 1000 req  (trouver le place_id)
    Place Details Contact → $17 / 1000 req  (téléphone + site web)
    Place Details Atmosphere → $3 / 1000 req (note + avis)
    ─────────────────────────────────────────
    Total ≈ $52 / 1000 cabinets enrichis

    Exemple avec --limit 3800 : 3800 × $52/1000 ≈ $198  ✅ (sous les $200 gratuits)

Usage :
    # Enrichir jusqu'à 3800 cabinets (reste dans le quota gratuit)
    python scraper/enrich_google_places.py --limit 3800

    # Enrichir seulement Paris et Lyon
    python scraper/enrich_google_places.py --cities Paris,Lyon

    # Reprendre là où on s'est arrêté (le script sauvegarde la progression)
    python scraper/enrich_google_places.py --limit 3800

    # Voir le bilan sans enrichir (dry-run)
    python scraper/enrich_google_places.py --dry-run
"""

import json
import os
import sys
import time
import logging
import argparse
from pathlib import Path

try:
    import requests
except ImportError:
    print("Lancez: pip install requests")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT         = Path(__file__).parent.parent
DATA_DIR     = ROOT / "data"
INPUT_FILE   = DATA_DIR / "cabinets.json"
OUTPUT_FILE  = DATA_DIR / "cabinets.json"      # on enrichit en place
PROGRESS_FILE = DATA_DIR / ".enrich_progress.json"  # checkpoint pour reprendre

PLACES_API_BASE = "https://maps.googleapis.com/maps/api/place"
DELAY_SEARCH  = 0.5   # secondes entre Text Search
DELAY_DETAILS = 0.4   # secondes entre Place Details
MAX_RETRIES   = 3


# ─── Session HTTP ────────────────────────────────────────────────────────────

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "cabinets-comptables.name/enrichment",
    "Accept": "application/json",
})


def api_get(endpoint: str, params: dict) -> dict:
    """GET avec retry exponentiel."""
    url = f"{PLACES_API_BASE}/{endpoint}/json"
    for attempt in range(MAX_RETRIES):
        try:
            resp = SESSION.get(url, params=params, timeout=15)
            if resp.status_code == 429:
                wait = 5 * (2 ** attempt)
                log.warning(f"Rate-limit (429) — attente {wait}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "")
            if status == "OVER_QUERY_LIMIT":
                log.error("Quota Google Places dépassé. Attendez demain ou augmentez votre quota.")
                sys.exit(1)
            return data
        except requests.Timeout:
            log.warning(f"Timeout (tentative {attempt + 1}/{MAX_RETRIES})")
            time.sleep(2 ** attempt)
        except requests.RequestException as e:
            log.error(f"Erreur réseau: {e}")
            time.sleep(2 ** attempt)
    return {}


# ─── Google Places Text Search ────────────────────────────────────────────────

def find_place(api_key: str, cabinet: dict) -> str | None:
    """
    Recherche un cabinet sur Google Places et retourne son place_id.
    Utilise le nom + ville pour maximiser la précision.
    """
    query = f"{cabinet['name']} {cabinet['city']} expert comptable"
    params = {
        "query": query,
        "type": "accounting",
        "language": "fr",
        "key": api_key,
        # Champs de base (Basic tier, moins cher)
        "fields": "place_id,name,formatted_address,geometry",
    }
    # Si on a des coordonnées SIRENE, on centre la recherche
    if cabinet.get("lat") and cabinet.get("lng"):
        params["location"] = f"{cabinet['lat']},{cabinet['lng']}"
        params["radius"] = 2000

    data = api_get("textsearch", params)
    results = data.get("results", [])
    if not results:
        return None

    # On prend le premier résultat — généralement le bon
    best = results[0]
    return best.get("place_id")


# ─── Google Places Details ────────────────────────────────────────────────────

def get_details(api_key: str, place_id: str) -> dict:
    """
    Récupère les détails d'un établissement Google Places :
    téléphone, site web, note, nombre d'avis, coordonnées GPS.
    """
    params = {
        "place_id": place_id,
        # Basic : geometry (coordonnées précises)
        # Contact : formatted_phone_number, website
        # Atmosphere : rating, user_ratings_total
        "fields": (
            "formatted_phone_number,"
            "international_phone_number,"
            "website,"
            "rating,"
            "user_ratings_total,"
            "geometry/location,"
            "business_status"
        ),
        "language": "fr",
        "key": api_key,
    }
    data = api_get("details", params)
    result = data.get("result", {})

    # Ignorer les établissements fermés définitivement
    if result.get("business_status") == "CLOSED_PERMANENTLY":
        return {}

    return result


# ─── Normalisation téléphone ─────────────────────────────────────────────────

def fmt_phone(raw: str) -> str:
    if not raw:
        return ""
    # Préférer le format local (0X XX XX XX XX)
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) == 11 and digits.startswith("33"):
        digits = "0" + digits[2:]
    if len(digits) == 10 and digits.startswith("0"):
        return " ".join(digits[i:i+2] for i in range(0, 10, 2))
    return raw.strip()


# ─── Chargement / sauvegarde ──────────────────────────────────────────────────

def load_cabinets() -> list[dict]:
    with open(INPUT_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_cabinets(cabinets: list[dict]) -> None:
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(cabinets, f, ensure_ascii=False, indent=2)


def load_progress() -> set[str]:
    """Charge les SIRET déjà enrichis depuis le checkpoint."""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return set(json.load(f).get("done_sirets", []))
    return set()


def save_progress(done_sirets: set[str]) -> None:
    with open(PROGRESS_FILE, "w") as f:
        json.dump({"done_sirets": list(done_sirets)}, f)


# ─── Enrichissement ───────────────────────────────────────────────────────────

def enrich(
    api_key: str,
    cabinets: list[dict],
    limit: int,
    cities: list[str] | None,
    dry_run: bool,
) -> int:
    """
    Enrichit les cabinets manquants de téléphone/note.
    Retourne le nombre de cabinets effectivement enrichis.
    """
    done_sirets = load_progress()

    # Sélection des candidats à enrichir
    # Priorité : cabinets sans téléphone et sans rating
    def needs_enrichment(c: dict) -> bool:
        if c.get("siret") and c["siret"] in done_sirets:
            return False
        # Déjà enrichi si on a au moins le téléphone OU la note
        if c.get("phone") and c.get("rating"):
            return False
        if cities and c.get("city") not in cities:
            return False
        return True

    candidates = [c for c in cabinets if needs_enrichment(c)]
    log.info(f"Cabinets à enrichir : {len(candidates)}")
    log.info(f"Déjà enrichis (checkpoint) : {len(done_sirets)}")

    if limit:
        candidates = candidates[:limit]
        log.info(f"Limité à : {limit}")

    # Estimation du coût
    n = len(candidates)
    cost_search  = n * 0.032   # $32/1000
    cost_details = n * 0.020   # ~$20/1000 (contact + atmosphere)
    cost_total   = cost_search + cost_details
    log.info(f"Coût estimé : ${cost_total:.2f} (Text Search ${cost_search:.2f} + Details ${cost_details:.2f})")
    log.info(f"Quota mensuel Google : $200 offerts — reste estimé après : ${200 - cost_total:.2f}")

    if dry_run:
        log.info("Mode dry-run — aucun appel API effectué.")
        return 0

    if cost_total > 190:
        log.warning(
            f"Coût estimé (${cost_total:.2f}) proche du quota gratuit ($200). "
            "Réduisez --limit ou vérifiez votre quota dans la Console Google Cloud."
        )
        confirm = input("Continuer quand même ? [o/N] ").strip().lower()
        if confirm not in ("o", "oui", "y", "yes"):
            log.info("Annulé.")
            return 0

    enriched = 0
    errors   = 0

    for idx, cab in enumerate(candidates, 1):
        siret = cab.get("siret", "")
        log.info(f"[{idx}/{n}] {cab['name']} — {cab['city']}")

        # 1. Trouver le place_id
        place_id = find_place(api_key, cab)
        time.sleep(DELAY_SEARCH)

        if not place_id:
            log.debug(f"  → Introuvable sur Google Places")
            if siret:
                done_sirets.add(siret)
            errors += 1
            continue

        # 2. Récupérer les détails
        details = get_details(api_key, place_id)
        time.sleep(DELAY_DETAILS)

        if not details:
            log.debug(f"  → Aucun détail ou établissement fermé")
            if siret:
                done_sirets.add(siret)
            continue

        # 3. Mettre à jour le cabinet
        phone = fmt_phone(
            details.get("formatted_phone_number", "")
            or details.get("international_phone_number", "")
        )
        website  = details.get("website", "") or ""
        rating   = details.get("rating")
        reviews  = details.get("user_ratings_total", 0) or 0
        geo      = details.get("geometry", {}).get("location", {})

        if phone:
            cab["phone"] = phone
        if website:
            cab["website"] = website.strip()
        if rating is not None:
            cab["rating"] = str(round(float(rating), 1))
        if reviews:
            cab["reviews_count"] = reviews
        if geo.get("lat") and geo.get("lng"):
            cab["lat"] = geo["lat"]
            cab["lng"] = geo["lng"]

        enriched += 1
        log.info(f"  ✅ tél={phone!r} note={rating} avis={reviews}")

        if siret:
            done_sirets.add(siret)

        # Sauvegarder toutes les 50 entrées
        if enriched % 50 == 0:
            save_cabinets(cabinets)
            save_progress(done_sirets)
            log.info(f"  💾 Checkpoint sauvegardé ({enriched} enrichis)")

    # Sauvegarde finale
    save_cabinets(cabinets)
    save_progress(done_sirets)
    return enriched


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Enrichit les cabinets SIRENE avec données Google Places"
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Nombre maximum de cabinets à enrichir (0 = tous). "
             "Conseil : 3800 reste sous les $200 gratuits."
    )
    parser.add_argument(
        "--cities", type=str, default="",
        help="Filtre sur des villes spécifiques, séparées par virgule (ex: Paris,Lyon,Marseille)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Estimer le coût sans faire d'appels API"
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Ignorer le checkpoint et tout reprendre depuis le début"
    )
    args = parser.parse_args()

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
    if not api_key and not args.dry_run:
        log.error(
            "Clé API manquante.\n"
            "1. Activez 'Places API' sur https://console.cloud.google.com\n"
            "2. Créez une clé API\n"
            "3. export GOOGLE_PLACES_API_KEY='AIza...'\n"
            "4. python scraper/enrich_google_places.py --limit 3800"
        )
        sys.exit(1)

    if args.reset and PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
        log.info("Checkpoint réinitialisé.")

    cities = [c.strip() for c in args.cities.split(",") if c.strip()] if args.cities else None

    log.info("=== Enrichissement Google Places ===")
    log.info(f"Fichier source : {INPUT_FILE}")
    cabinets = load_cabinets()
    log.info(f"Cabinets chargés : {len(cabinets)}")

    enriched = enrich(
        api_key=api_key,
        cabinets=cabinets,
        limit=args.limit,
        cities=cities,
        dry_run=args.dry_run,
    )

    log.info(f"\n=== Terminé : {enriched} cabinets enrichis ===")
    if enriched > 0:
        log.info("Relancez le générateur :")
        log.info("  python generator/generate.py")


if __name__ == "__main__":
    main()
