#!/usr/bin/env python3
"""
Générateur de site statique SEO pour cabinets-comptables.name
Génère : homepage, pages villes, pages cabinets, sitemap, robots.txt
Sources de données : cabinets.json (local) + Supabase (si configuré)
"""

import json
import logging
import re
import sys
import os
import shutil
from pathlib import Path
from datetime import date

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from slugify import slugify
    import requests
except ImportError:
    print("Dépendances manquantes. Lancez: pip install -r requirements.txt")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT         = Path(__file__).parent.parent
DATA_FILE    = ROOT / "data" / "cabinets.json"
BLOG_FILE    = ROOT / "data" / "blog_posts.json"
STATIC_DIR   = ROOT / "static"
TEMPLATE_DIR = Path(__file__).parent / "templates"
OUTPUT_DIR   = ROOT / "output"

# Palette de couleurs pour les villes (décorative)
CITY_COLORS = [
    "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6",
    "#06b6d4", "#84cc16", "#f97316", "#ec4899", "#14b8a6",
    "#6366f1", "#a855f7", "#0ea5e9", "#22c55e", "#eab308",
    "#f43f5e", "#64748b", "#2dd4bf", "#fb923c", "#a3e635",
]


BLOG_COLORS = [
    "#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ef4444",
]

MONTHS_FR = {
    "01": "janvier", "02": "février", "03": "mars", "04": "avril",
    "05": "mai", "06": "juin", "07": "juillet", "08": "août",
    "09": "septembre", "10": "octobre", "11": "novembre", "12": "décembre",
}


def date_to_fr(iso_date: str) -> str:
    """Convertit '2025-02-19' en '19 février 2025'."""
    parts = iso_date.split("-")
    return f"{int(parts[2])} {MONTHS_FR.get(parts[1], parts[1])} {parts[0]}"


def make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    # Filtre urlencode pour les URLs Google Maps
    from urllib.parse import quote_plus
    env.filters["urlencode"] = quote_plus
    return env


def load_from_supabase() -> list[dict]:
    """Charge les cabinets depuis Supabase via l'API REST (PostgREST).

    Variables d'environnement requises :
      - SUPABASE_URL  : URL du projet (ex: https://xyz.supabase.co)
      - SUPABASE_KEY  : clé anon/public (ou SUPABASE_ANON_KEY)

    Gère la pagination automatiquement (Supabase limite à 1000 lignes).
    """
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")

    if not url or not key:
        log.info("  Supabase non configuré (SUPABASE_URL / SUPABASE_KEY absents)")
        return []

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Prefer": "count=exact",
    }

    all_rows: list[dict] = []
    page_size = 1000
    offset = 0

    try:
        while True:
            api_url = (
                f"{url}/rest/v1/comptables"
                f"?select=*&order=id&offset={offset}&limit={page_size}"
            )
            resp = requests.get(api_url, headers=headers, timeout=30)
            resp.raise_for_status()
            rows = resp.json()
            if not rows:
                break
            all_rows.extend(rows)
            if len(rows) < page_size:
                break
            offset += page_size

        log.info(f"  Supabase : {len(all_rows)} cabinets chargés")
    except Exception as exc:
        log.warning(f"  Erreur Supabase ({exc}), utilisation des données locales uniquement")
        return []

    return all_rows


def _parse_address(address_full: str) -> tuple[str, str, str]:
    """Extrait (rue, code_postal, ville) depuis une adresse complète.

    Formats reconnus :
      "20 Rue d'Athènes, 75009 Paris"
      "20 Rue d'Athènes 75009 Paris"
    """
    if not address_full:
        return ("", "", "")

    # Cherche un code postal français (5 chiffres) suivi du nom de ville
    m = re.search(r",?\s*(\d{5})\s+(.+?)$", address_full)
    if m:
        street = address_full[: m.start()].rstrip(", ")
        return (street, m.group(1), m.group(2).strip())

    return (address_full, "", "")


def map_supabase_row(row: dict) -> dict:
    """Convertit une ligne Supabase vers le format cabinets.json."""
    street, postal_code, city = _parse_address(row.get("address") or "")

    rating_raw = row.get("rating")
    rating = str(rating_raw) if rating_raw is not None else ""

    lat = row.get("latitude")
    lng = row.get("longitude")

    return {
        "name": row.get("name") or "",
        "address": street,
        "city": city,
        "postal_code": postal_code,
        "phone": row.get("phone") or "",
        "website": row.get("website") or "",
        "rating": rating,
        "rating_info": row.get("rating_info") or "",
        "category": row.get("category") or "",
        "open_hours": row.get("open_hours") or "",
        "lat": float(lat) if lat is not None else None,
        "lng": float(lng) if lng is not None else None,
        "featured_image": row.get("featured_image") or "",
        "bing_maps_url": row.get("bing_maps_url") or "",
        "email": row.get("emails") or "",
        "facebook": row.get("facebook") or "",
        "instagram": row.get("instagram") or "",
        "twitter": row.get("twitter") or "",
        "external_id": row.get("id") or "",
    }


def merge_data(local: list[dict], supabase_rows: list[dict]) -> list[dict]:
    """Fusionne données locales et Supabase sans écraser les données existantes.

    Logique :
      - Les cabinets existants dans le JSON local sont conservés tels quels.
      - Pour un cabinet présent dans les deux sources (même external_id),
        seuls les champs VIDES du local sont complétés par Supabase.
      - Les cabinets uniquement dans Supabase sont ajoutés (s'ils ont une ville).
    """
    if not supabase_rows:
        return local

    # Indexer les données locales par external_id
    local_by_id: dict[str, dict] = {}
    for cab in local:
        eid = cab.get("external_id", "")
        if eid:
            local_by_id[eid] = cab

    added = 0
    enriched = 0

    for row in supabase_rows:
        mapped = map_supabase_row(row)
        eid = mapped.get("external_id", "")

        if eid and eid in local_by_id:
            # Cabinet existe localement — compléter les champs vides uniquement
            existing = local_by_id[eid]
            touched = False
            for key, value in mapped.items():
                if value and not existing.get(key):
                    existing[key] = value
                    touched = True
            if touched:
                enriched += 1
        else:
            # Nouveau cabinet depuis Supabase
            if mapped.get("city") and mapped.get("name"):
                local.append(mapped)
                if eid:
                    local_by_id[eid] = mapped
                added += 1

    log.info(
        f"  Fusion : {added} nouveaux cabinets ajoutés, "
        f"{enriched} cabinets existants enrichis"
    )
    return local


def load_data() -> list[dict]:
    # Charger les données locales (cabinets.json)
    local_data = []
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            local_data = json.load(f)
        log.info(f"  Fichier local : {len(local_data)} cabinets")
    else:
        log.warning(f"  Fichier local introuvable : {DATA_FILE}")

    # Charger depuis Supabase (si configuré)
    supabase_rows = load_from_supabase()

    # Fusionner (les données locales ont priorité)
    data = merge_data(local_data, supabase_rows)

    if not data:
        log.error("Aucune donnée disponible (ni locale, ni Supabase). Arrêt.")
        sys.exit(1)

    log.info(f"  Total après fusion : {len(data)} cabinets")

    # Ajouter le slug à chaque cabinet
    used_slugs = {}
    for cabinet in data:
        base = slugify(f"{cabinet['name']}-{cabinet.get('city', 'inconnu')}")
        if base in used_slugs:
            used_slugs[base] += 1
            cabinet["slug"] = f"{base}-{used_slugs[base]}"
        else:
            used_slugs[base] = 1
            cabinet["slug"] = base

    return data


def group_by_city(data: list[dict]) -> dict[str, list[dict]]:
    cities: dict[str, list[dict]] = {}
    for cabinet in data:
        city = cabinet.get("city", "Inconnue").strip()
        if city not in cities:
            cities[city] = []
        cities[city].append(cabinet)
    return cities


def city_meta(cities_grouped: dict[str, list[dict]]) -> list[dict]:
    """Construit la liste des villes avec slug, count, couleur."""
    city_list = []
    for i, (name, cabinets) in enumerate(sorted(cities_grouped.items())):
        city_list.append({
            "name": name,
            "slug": slugify(name),
            "count": len(cabinets),
            "color": CITY_COLORS[i % len(CITY_COLORS)],
        })
    return city_list


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def generate_homepage(env: Environment, cities: list[dict], data: list[dict], blog_posts: list[dict] = None) -> None:
    tpl = env.get_template("index.html")
    html = tpl.render(
        cities=cities,
        total_cabinets=len(data),
        total_cities=len(cities),
        recent_cabinets=data[:12],
        blog_posts=(blog_posts or [])[:3],
    )
    write_file(OUTPUT_DIR / "index.html", html)
    log.info("  ✅ Homepage générée")


def generate_villes_index(env: Environment, cities: list[dict], data: list[dict]) -> None:
    tpl = env.get_template("villes_index.html")
    html = tpl.render(
        cities=cities,
        total_cabinets=len(data),
        total_cities=len(cities),
    )
    write_file(OUTPUT_DIR / "villes" / "index.html", html)
    log.info("  ✅ Index villes généré")


def generate_city_pages(
    env: Environment,
    cities_grouped: dict[str, list[dict]],
    cities: list[dict],
) -> None:
    tpl = env.get_template("ville.html")
    city_meta_map = {c["name"]: c for c in cities}

    # Villes à afficher dans la sidebar (toutes sauf la courante)
    all_cities_sidebar = [
        {"name": c["name"], "slug": c["slug"], "count": c["count"]}
        for c in sorted(cities, key=lambda x: -x["count"])
    ]

    for city_name, cabinets in cities_grouped.items():
        city_slug = slugify(city_name)
        city_count = len(cabinets)
        other_cities = [c for c in all_cities_sidebar if c["name"] != city_name][:10]

        html = tpl.render(
            city_name=city_name,
            city_slug=city_slug,
            city_count=city_count,
            cabinets=cabinets,
            other_cities=other_cities,
        )
        write_file(OUTPUT_DIR / "villes" / city_slug / "index.html", html)

    log.info(f"  ✅ {len(cities_grouped)} pages villes générées")


def generate_cabinet_pages(
    env: Environment,
    data: list[dict],
    cities_grouped: dict[str, list[dict]],
) -> None:
    tpl = env.get_template("cabinet.html")

    for cabinet in data:
        city = cabinet["city"]
        city_slug = slugify(city)

        # 5 cabinets proches (même ville, différent)
        same_city = [c for c in cities_grouped.get(city, []) if c["slug"] != cabinet["slug"]]
        nearby = same_city[:5]

        html = tpl.render(
            cabinet=cabinet,
            city_slug=city_slug,
            nearby_cabinets=nearby,
        )
        write_file(OUTPUT_DIR / "cabinets" / cabinet["slug"] / "index.html", html)

    log.info(f"  ✅ {len(data)} pages cabinets générées")


def generate_search_index(data: list[dict], cities: list[dict]) -> None:
    """Génère /search-index.json pour le moteur de recherche côté client."""
    index = []

    # Villes en premier (priorité dans les résultats)
    for city in sorted(cities, key=lambda c: -c["count"]):
        index.append({
            "t": "v",                  # type: ville
            "n": city["name"],         # name
            "s": city["slug"],         # slug
            "c": city["count"],        # count
        })

    # Cabinets (nom + ville + slug)
    for cabinet in data:
        index.append({
            "t": "c",                              # type: cabinet
            "n": cabinet["name"],                  # name
            "v": cabinet.get("city", ""),          # ville
            "s": cabinet["slug"],                  # slug
        })

    output_path = OUTPUT_DIR / "search-index.json"
    output_path.write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    log.info(f"  ✅ search-index.json généré ({len(index)} entrées)")


def generate_sitemap(env: Environment, data: list[dict], cities: list[dict], blog_posts: list[dict] = None) -> None:
    tpl = env.get_template("sitemap.xml.j2")
    xml = tpl.render(
        cities=cities,
        cabinets=data,
        blog_posts=blog_posts or [],
        lastmod=date.today().isoformat(),
    )
    write_file(OUTPUT_DIR / "sitemap.xml", xml)
    log.info("  ✅ Sitemap généré")


def generate_robots(output_dir: Path) -> None:
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /404\n\n"
        "Sitemap: https://cabinets-comptables.name/sitemap.xml\n"
    )
    write_file(output_dir / "robots.txt", content)
    log.info("  ✅ robots.txt généré")


def generate_404(env: Environment) -> None:
    """Page 404 simple."""
    html = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>Page introuvable — Cabinets-Comptables.name</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50 min-h-screen flex items-center justify-center">
  <div class="text-center p-8">
    <div class="text-8xl font-bold text-blue-200 mb-4">404</div>
    <h1 class="text-2xl font-bold text-gray-800 mb-2">Page introuvable</h1>
    <p class="text-gray-500 mb-6">La page que vous cherchez n'existe pas ou a été déplacée.</p>
    <a href="/" class="bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 transition font-medium">
      Retour à l'accueil
    </a>
  </div>
</body>
</html>"""
    write_file(OUTPUT_DIR / "404.html", html)
    log.info("  ✅ Page 404 générée")


def generate_contact() -> None:
    html = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Contact — Cabinets-Comptables.name</title>
  <meta name="description" content="Contactez Cabinets-Comptables.name pour toute question, signalement d'erreur ou demande de mise à jour concernant l'annuaire des cabinets comptables.">
  <meta name="robots" content="index, follow">
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50">

  <!-- Navigation -->
  <header class="shadow-md" style="background-color:#162d4a;">
    <div class="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
      <a href="/" class="flex items-center gap-3">
        <div class="w-10 h-10 bg-blue-400 rounded-lg flex items-center justify-center text-white font-bold text-lg">C</div>
        <div>
          <span class="text-white font-bold text-lg leading-tight block">Cabinets-Comptables</span>
          <span class="text-blue-300 text-xs">.name — Annuaire national</span>
        </div>
      </a>
      <nav class="hidden md:flex items-center gap-6 text-sm">
        <a href="/" class="text-blue-200 hover:text-white transition">Accueil</a>
        <a href="/villes/" class="text-blue-200 hover:text-white transition">Villes</a>
        <a href="/contact/" class="text-white font-medium">Contact</a>
      </nav>
    </div>
  </header>

  <main class="max-w-3xl mx-auto px-4 py-12">
    <h1 class="text-3xl font-bold text-gray-900 mb-2">Contact</h1>
    <p class="text-gray-500 mb-8">Une erreur dans notre annuaire&nbsp;? Une mise à jour à signaler&nbsp;? Écrivez-nous.</p>

    <div class="grid md:grid-cols-2 gap-8">

      <!-- Formulaire -->
      <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
        <h2 class="font-bold text-gray-800 mb-4">Envoyer un message</h2>
        <form action="mailto:contact@cabinets-comptables.name" method="GET" class="space-y-4">
          <div>
            <label for="subject" class="block text-sm font-medium text-gray-700 mb-1">Objet</label>
            <select id="subject" name="subject"
                    class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="Signalement d'erreur">Signalement d'erreur</option>
              <option value="Mise à jour d'informations">Mise à jour d'informations</option>
              <option value="Demande de suppression">Demande de suppression</option>
              <option value="Partenariat">Partenariat</option>
              <option value="Autre">Autre</option>
            </select>
          </div>
          <div>
            <label for="body" class="block text-sm font-medium text-gray-700 mb-1">Message</label>
            <textarea id="body" name="body" rows="5"
                      placeholder="Décrivez votre demande..."
                      class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"></textarea>
          </div>
          <button type="submit"
                  class="w-full bg-blue-600 text-white font-medium rounded-lg px-4 py-2 hover:bg-blue-700 transition text-sm">
            Envoyer par e-mail
          </button>
        </form>
        <p class="text-xs text-gray-400 mt-3">
          Ce formulaire ouvre votre client e-mail. Vous pouvez aussi écrire directement à
          <a href="mailto:contact@cabinets-comptables.name" class="text-blue-500 hover:underline">contact@cabinets-comptables.name</a>.
        </p>
      </div>

      <!-- Informations -->
      <div class="space-y-5">
        <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h2 class="font-bold text-gray-800 mb-3">Signaler une erreur</h2>
          <p class="text-sm text-gray-600 leading-relaxed">
            Les données de cet annuaire proviennent de sources publiques et sont mises à jour
            mensuellement. Si vous constatez une erreur (adresse incorrecte, cabinet fermé,
            numéro erroné), merci de nous le signaler.
          </p>
        </div>

        <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h2 class="font-bold text-gray-800 mb-3">Demande de suppression</h2>
          <p class="text-sm text-gray-600 leading-relaxed">
            Conformément au RGPD, vous pouvez demander la suppression des informations
            professionnelles vous concernant. Précisez le nom du cabinet et la ville dans
            votre message.
          </p>
        </div>

        <div class="bg-blue-50 rounded-xl border border-blue-100 p-5">
          <p class="text-sm text-blue-700">
            <strong>Délai de réponse&nbsp;:</strong> nous traitons les demandes sous 5 jours ouvrés.
          </p>
        </div>
      </div>

    </div>
  </main>

  <!-- Footer -->
  <footer class="mt-16 border-t border-gray-200 bg-white">
    <div class="max-w-6xl mx-auto px-4 py-8 text-center text-xs text-gray-400">
      <p>© 2025 Cabinets-Comptables.name — Annuaire non officiel à titre informatif.</p>
      <div class="flex justify-center gap-4 mt-2">
        <a href="/" class="hover:text-blue-600">Accueil</a>
        <a href="/villes/" class="hover:text-blue-600">Villes</a>
        <a href="/mentions-legales/" class="hover:text-blue-600">Mentions légales</a>
      </div>
    </div>
  </footer>

</body>
</html>"""
    write_file(OUTPUT_DIR / "contact" / "index.html", html)
    log.info("  ✅ Page contact générée")


def generate_mentions_legales() -> None:
    html = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>Mentions légales — Cabinets-Comptables.name</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50">
  <div class="max-w-3xl mx-auto px-4 py-12">
    <h1 class="text-3xl font-bold text-gray-900 mb-6">Mentions légales</h1>
    <div class="bg-white rounded-xl p-8 shadow-sm space-y-6 text-sm text-gray-600 leading-relaxed">
      <section>
        <h2 class="font-bold text-gray-800 text-base mb-2">Éditeur du site</h2>
        <p>Cabinets-Comptables.name est un annuaire en ligne à titre informatif.</p>
      </section>
      <section>
        <h2 class="font-bold text-gray-800 text-base mb-2">Nature des informations</h2>
        <p>
          Les informations présentées sur ce site proviennent de sources publiques et sont
          fournies à titre indicatif. L'exactitude des données n'est pas garantie.
          En cas d'erreur, veuillez nous contacter.
        </p>
      </section>
      <section>
        <h2 class="font-bold text-gray-800 text-base mb-2">Données personnelles</h2>
        <p>
          Ce site ne collecte pas de données personnelles des visiteurs.
          Les informations affichées sont des données professionnelles publiques.
        </p>
      </section>
      <section>
        <h2 class="font-bold text-gray-800 text-base mb-2">Hébergement</h2>
        <p>Ce site est hébergé sur Vercel Inc., San Francisco, CA, USA.</p>
      </section>
    </div>
    <a href="/" class="block mt-6 text-sm text-blue-600 hover:underline">← Retour à l'accueil</a>
  </div>
</body>
</html>"""
    write_file(OUTPUT_DIR / "mentions-legales" / "index.html", html)
    log.info("  ✅ Mentions légales générées")


def copy_static_assets() -> None:
    """Copie le dossier static/ vers output/ (favicon, etc.)."""
    if not STATIC_DIR.exists():
        return
    for src in STATIC_DIR.iterdir():
        dst = OUTPUT_DIR / src.name
        shutil.copy2(src, dst)
    log.info(f"  ✅ Actifs statiques copiés ({list(STATIC_DIR.iterdir()).__len__()} fichiers)")


def load_blog_posts() -> list[dict]:
    if not BLOG_FILE.exists():
        log.warning("Pas de fichier blog_posts.json trouvé, section blog ignorée.")
        return []
    with open(BLOG_FILE, encoding="utf-8") as f:
        posts = json.load(f)
    for i, post in enumerate(posts):
        post["color"] = BLOG_COLORS[i % len(BLOG_COLORS)]
        post["date_fr"] = date_to_fr(post["date"])
    log.info(f"  Blog : {len(posts)} articles chargés")
    return posts


def generate_politique_de_confidentialite(env: Environment) -> None:
    tpl = env.get_template("politique-de-confidentialite.html")
    html = tpl.render(lastmod=date.today().strftime("%-d %B %Y"))
    write_file(OUTPUT_DIR / "politique-de-confidentialite" / "index.html", html)
    log.info("  ✅ Politique de confidentialité générée")


def generate_blog(env: Environment, posts: list[dict], total_cabinets: int) -> None:
    if not posts:
        return

    # Index du blog
    tpl_index = env.get_template("blog_index.html")
    html = tpl_index.render(posts=posts, total_cabinets=total_cabinets)
    write_file(OUTPUT_DIR / "blog" / "index.html", html)

    # Pages individuelles
    tpl_post = env.get_template("blog_post.html")
    for i, post in enumerate(posts):
        other_posts = [p for j, p in enumerate(posts) if j != i][:4]
        html = tpl_post.render(post=post, other_posts=other_posts)
        write_file(OUTPUT_DIR / "blog" / post["slug"] / "index.html", html)

    log.info(f"  ✅ Blog généré : 1 index + {len(posts)} articles")


def clean_output() -> None:
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)
    log.info(f"  Dossier output/ nettoyé : {OUTPUT_DIR}")


def main():
    log.info("=== Génération du site cabinets-comptables.name ===")

    # 1. Nettoyage
    log.info("1. Nettoyage du dossier output/...")
    clean_output()

    # 2. Chargement des données
    log.info("2. Chargement des données...")
    data = load_data()
    cities_grouped = group_by_city(data)
    cities = city_meta(cities_grouped)
    blog_posts = load_blog_posts()

    # 3. Init Jinja2
    env = make_env()

    # 4. Génération
    log.info("3. Génération des pages...")
    generate_homepage(env, cities, data, blog_posts)
    generate_villes_index(env, cities, data)
    generate_city_pages(env, cities_grouped, cities)
    generate_cabinet_pages(env, data, cities_grouped)
    generate_search_index(data, cities)
    generate_sitemap(env, data, cities, blog_posts)
    generate_robots(OUTPUT_DIR)
    generate_404(env)
    generate_mentions_legales()
    generate_contact()
    generate_politique_de_confidentialite(env)
    generate_blog(env, blog_posts, len(data))
    copy_static_assets()

    # 5. Résumé
    total_html = sum(1 for _ in OUTPUT_DIR.rglob("*.html"))
    log.info("\n=== Génération terminée ===")
    log.info(f"  📄 {total_html} fichiers HTML générés")
    log.info(f"  🏙️  {len(cities)} pages villes")
    log.info(f"  🏢  {len(data)} pages cabinets")
    log.info(f"  📝  {len(blog_posts)} articles blog")
    log.info(f"  📁 Dossier de sortie : {OUTPUT_DIR}")
    log.info("\n  🚀 Pour déployer sur Vercel :")
    log.info("     vercel --prod")


if __name__ == "__main__":
    main()
