#!/usr/bin/env python3
"""
sync_supabase_to_json.py
Télécharge tous les cabinets depuis Supabase (table `comptables`)
et écrase data/cabinets.json avec les données mappées.

Usage:
    SUPABASE_URL=https://xxx.supabase.co SUPABASE_KEY=eyJ... python sync_supabase_to_json.py

Ou avec un .env local :
    python sync_supabase_to_json.py --env .env
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Installez requests : pip install requests")

# ── Config ────────────────────────────────────────────────────────────────────

ROOT      = Path(__file__).parent
DATA_FILE = ROOT / "data" / "cabinets.json"
TABLE     = "comptables"
PAGE_SIZE = 1000

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_env(path: str):
    """Charge les variables depuis un fichier .env (simple key=value)."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def parse_address(raw: str):
    """Extrait rue, code postal et ville depuis une adresse libre."""
    raw = raw.strip()
    m = re.search(r"(\d{5})\s+(.+)$", raw)
    if m:
        postal_code = m.group(1)
        city        = m.group(2).strip()
        street      = raw[: m.start()].rstrip(", ").strip()
    else:
        # Pas de code postal trouvé
        parts = [p.strip() for p in raw.rsplit(",", 1)]
        street      = parts[0] if len(parts) > 1 else raw
        city        = parts[-1]
        postal_code = ""
    return street, postal_code, city


def map_row(row: dict) -> dict:
    """Convertit une ligne Supabase vers le format cabinets.json."""
    street, postal_code, city = parse_address(row.get("address") or "")
    rating_raw = row.get("rating")
    lat = row.get("latitude")
    lng = row.get("longitude")
    reviews_count = row.get("reviews_count")
    return {
        "name":           row.get("name") or "",
        "address":        street,
        "city":           city or row.get("city") or "",
        "postal_code":    postal_code,
        "phone":          row.get("phone") or "",
        "website":        row.get("website") or "",
        "rating":         str(rating_raw) if rating_raw is not None else "",
        "reviews_count":  int(reviews_count) if reviews_count else 0,
        "rating_info":    row.get("rating_info") or "",
        "category":       row.get("category") or "",
        "open_hours":     row.get("open_hours") or "",
        "lat":            float(lat) if lat is not None else None,
        "lng":            float(lng) if lng is not None else None,
        "featured_image": row.get("featured_image") or "",
        "google_maps_url":row.get("google_maps_url") or row.get("bing_maps_url") or "",
        "email":          row.get("emails") or row.get("email") or "",
        "facebook":       row.get("facebook") or "",
        "instagram":      row.get("instagram") or "",
        "twitter":        row.get("twitter") or "",
        "external_id":    str(row.get("id") or ""),
    }


# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_all(url: str, key: str) -> list[dict]:
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Prefer": "count=exact",
    }
    all_rows: list[dict] = []
    offset = 0

    while True:
        endpoint = (
            f"{url}/rest/v1/{TABLE}"
            f"?select=*&order=id&offset={offset}&limit={PAGE_SIZE}"
        )
        resp = requests.get(endpoint, headers=headers, timeout=30)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            break
        all_rows.extend(rows)
        print(f"  Reçu {len(all_rows)} lignes…", end="\r", flush=True)
        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    print()  # newline après \r
    return all_rows


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Sync Supabase → cabinets.json")
    parser.add_argument("--env", default=None, help="Chemin vers fichier .env")
    parser.add_argument("--dry-run", action="store_true", help="Ne pas écrire le fichier")
    args = parser.parse_args()

    # Charger .env si fourni
    if args.env:
        load_env(args.env)

    supabase_url = (
        os.environ.get("SUPABASE_URL")
        or os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
    ).rstrip("/")
    supabase_key = (
        os.environ.get("SUPABASE_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
        or os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY", "")
    )

    if not supabase_url or not supabase_key:
        sys.exit(
            "❌  Variables manquantes.\n"
            "Définissez SUPABASE_URL et SUPABASE_KEY (ou SUPABASE_ANON_KEY)\n"
            "ou passez --env chemin/vers/.env"
        )

    print(f"🔗  Connexion à {supabase_url}")
    print(f"📥  Téléchargement de la table `{TABLE}`…")

    try:
        rows = fetch_all(supabase_url, supabase_key)
    except requests.HTTPError as e:
        sys.exit(f"❌  Erreur HTTP : {e}\n{e.response.text[:400]}")

    print(f"✅  {len(rows)} lignes récupérées")

    cabinets = [map_row(r) for r in rows]

    # Générer les slugs manquants
    from unicodedata import normalize, category as ucat
    def slugify(text: str) -> str:
        text = normalize("NFD", text)
        text = "".join(c for c in text if ucat(c) != "Mn")
        text = text.lower().strip()
        text = re.sub(r"[^a-z0-9\s-]", "", text)
        text = re.sub(r"[\s]+", "-", text)
        return re.sub(r"-+", "-", text)

    slug_counts: dict[str, int] = {}
    for cab in cabinets:
        if not cab.get("slug"):
            base = slugify(f"{cab['name']}-{cab['city']}")
            if base in slug_counts:
                slug_counts[base] += 1
                cab["slug"] = f"{base}-{slug_counts[base]}"
            else:
                slug_counts[base] = 0
                cab["slug"] = base

    if args.dry_run:
        print(f"🧪  Dry-run : {len(cabinets)} cabinets mappés, fichier non écrit.")
        print(f"    Exemple : {json.dumps(cabinets[0], ensure_ascii=False, indent=2)[:400]}")
        return

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(cabinets, f, ensure_ascii=False, indent=2)

    size_kb = DATA_FILE.stat().st_size / 1024
    print(f"💾  {DATA_FILE} écrit — {len(cabinets)} cabinets, {size_kb:.0f} Ko")


if __name__ == "__main__":
    main()
