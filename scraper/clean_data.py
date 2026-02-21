#!/usr/bin/env python3
"""
Nettoyage et déduplication des données cabinets.
Normalise les noms, adresses, téléphones.
"""

import json
import re
import logging
from pathlib import Path

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ROOT = Path(__file__).parent.parent
DATA_FILE = ROOT / "data" / "cabinets.json"


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return ""
    if len(digits) == 10:
        return f"{digits[0:2]} {digits[2:4]} {digits[4:6]} {digits[6:8]} {digits[8:10]}"
    return phone.strip()


def normalize_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"\s+", " ", name)
    return name


def dedup_key(cabinet: dict) -> str:
    """Clé de déduplication : nom normalisé + code postal."""
    name = re.sub(r"\W", "", cabinet.get("name", "").lower())
    cp = re.sub(r"\D", "", cabinet.get("postal_code", ""))
    return f"{name}_{cp}"


def clean(data: list[dict]) -> list[dict]:
    seen = {}
    cleaned = []

    for item in data:
        item["name"] = normalize_name(item.get("name", ""))
        item["phone"] = normalize_phone(item.get("phone", ""))
        item["address"] = item.get("address", "").strip()
        item["city"] = item.get("city", "").strip().title()
        item["postal_code"] = re.sub(r"\D", "", item.get("postal_code", ""))
        item["website"] = item.get("website", "").strip()
        item["rating"] = item.get("rating", "").strip()

        if not item["name"]:
            continue

        key = dedup_key(item)
        if key not in seen:
            seen[key] = True
            cleaned.append(item)

    return cleaned


def main():
    if not DATA_FILE.exists():
        log.error(f"Fichier introuvable : {DATA_FILE}")
        return

    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    log.info(f"Données brutes : {len(data)} entrées")
    cleaned = clean(data)
    log.info(f"Après nettoyage : {len(cleaned)} entrées")

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)

    log.info(f"✅ Données nettoyées sauvegardées dans {DATA_FILE}")


if __name__ == "__main__":
    main()
