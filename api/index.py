#!/usr/bin/env python3
"""
Backoffice Admin — cabinets-comptables.name
Déploiement Vercel (serverless Python)

Variables à définir dans Vercel Dashboard → Settings → Environment Variables :
  ADMIN_SECRET_KEY     → chaîne aléatoire longue (ex: openssl rand -hex 32)
  ADMIN_USERNAME       → votre login (défaut: admin)
  ADMIN_PASSWORD       → votre mot de passe (obligatoire)
  GITHUB_TOKEN         → Personal Access Token GitHub (scope: repo)
  GITHUB_REPO          → "owner/repo" (ex: "dupont/cabinets-comptables.name")
  GITHUB_BRANCH        → branche cible (défaut: main)
  ANTHROPIC_API_KEY    → clé Anthropic (optionnel, pour génération blog)
"""

import base64
import csv
import hashlib
import io
import json
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from slugify import slugify
from starlette.middleware.base import BaseHTTPMiddleware

# ─── Chemins ──────────────────────────────────────────────────────────────────

# En Vercel, __file__ est dans /var/task/api/index.py → ROOT = /var/task
ROOT      = Path(__file__).parent.parent
ADMIN_DIR = ROOT / "admin"
DATA_FILE = ROOT / "data" / "cabinets.json"
BLOG_FILE = ROOT / "data" / "blog_posts.json"

BLOG_CATEGORIES = ["Conseils", "Fiscalité", "Comptabilité", "Statuts & Juridique"]

# ─── Config auth ──────────────────────────────────────────────────────────────

TOKEN_TTL_H = 8

# ─── Hachage mot de passe ─────────────────────────────────────────────────────

def _hash_password(password: str, salt: str | None = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"{salt}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    if "$" not in stored:
        return False
    salt, _ = stored.split("$", 1)
    return secrets.compare_digest(_hash_password(password, salt), stored)


# ─── Auth chargée depuis les variables d'env Vercel uniquement ───────────────

SECRET_KEY     = os.environ.get("ADMIN_SECRET_KEY") or secrets.token_hex(32)
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")

_plain_pw = os.environ.get("ADMIN_PASSWORD", "").strip()
if not _plain_pw:
    # Fallback : hash brut (déconseillé, utiliser ADMIN_PASSWORD)
    ADMIN_PASS_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")
else:
    ADMIN_PASS_HASH = _hash_password(_plain_pw)

# ─── GitHub API ───────────────────────────────────────────────────────────────

GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO   = os.environ.get("GITHUB_REPO", "")   # "owner/repo"
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

_GH_API = "https://api.github.com"
_GH_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


async def _github_commit_file(repo_path: str, content_str: str, commit_msg: str) -> bool:
    """
    Commit une mise à jour de fichier via la Git Data API GitHub.
    Supporte les fichiers > 1 MB (contrairement à la Contents API).
    Retourne True si succès.
    """
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return False

    hdrs = {**_GH_HEADERS, "Authorization": f"Bearer {GITHUB_TOKEN}"}

    try:
        async with httpx.AsyncClient(timeout=30) as gh:
            # 1. SHA du dernier commit sur la branche
            r = await gh.get(
                f"{_GH_API}/repos/{GITHUB_REPO}/git/ref/heads/{GITHUB_BRANCH}",
                headers=hdrs,
            )
            r.raise_for_status()
            commit_sha = r.json()["object"]["sha"]

            # 2. Arbre du commit
            r = await gh.get(
                f"{_GH_API}/repos/{GITHUB_REPO}/git/commits/{commit_sha}",
                headers=hdrs,
            )
            r.raise_for_status()
            base_tree_sha = r.json()["tree"]["sha"]

            # 3. Créer un nouveau blob (base64)
            encoded = base64.b64encode(content_str.encode("utf-8")).decode()
            r = await gh.post(
                f"{_GH_API}/repos/{GITHUB_REPO}/git/blobs",
                headers=hdrs,
                json={"content": encoded, "encoding": "base64"},
            )
            r.raise_for_status()
            blob_sha = r.json()["sha"]

            # 4. Créer un nouvel arbre
            r = await gh.post(
                f"{_GH_API}/repos/{GITHUB_REPO}/git/trees",
                headers=hdrs,
                json={
                    "base_tree": base_tree_sha,
                    "tree": [
                        {
                            "path": repo_path,
                            "mode": "100644",
                            "type": "blob",
                            "sha": blob_sha,
                        }
                    ],
                },
            )
            r.raise_for_status()
            new_tree_sha = r.json()["sha"]

            # 5. Créer le commit
            r = await gh.post(
                f"{_GH_API}/repos/{GITHUB_REPO}/git/commits",
                headers=hdrs,
                json={
                    "message": commit_msg,
                    "tree": new_tree_sha,
                    "parents": [commit_sha],
                },
            )
            r.raise_for_status()
            new_commit_sha = r.json()["sha"]

            # 6. Mettre à jour la ref de la branche
            r = await gh.patch(
                f"{_GH_API}/repos/{GITHUB_REPO}/git/refs/heads/{GITHUB_BRANCH}",
                headers=hdrs,
                json={"sha": new_commit_sha},
            )
            r.raise_for_status()
            return True

    except Exception as exc:
        print(f"[github] Erreur commit : {exc}")
        return False


# ─── Données ──────────────────────────────────────────────────────────────────

def load_data() -> list[dict]:
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def load_blog() -> list[dict]:
    if BLOG_FILE.exists():
        with open(BLOG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def data_stats(cabinets: list[dict]) -> dict:
    n = len(cabinets)
    cities  = len({c.get("city", "") for c in cabinets if c.get("city")})
    phones  = sum(1 for c in cabinets if c.get("phone"))
    ratings = sum(1 for c in cabinets if c.get("rating"))
    gps     = sum(1 for c in cabinets if c.get("lat") and c.get("lng"))
    webs    = sum(1 for c in cabinets if c.get("website"))
    return {
        "total": n, "cities": cities,
        "phones": phones,   "pct_phone":  round(phones  / n * 100) if n else 0,
        "ratings": ratings, "pct_rating": round(ratings / n * 100) if n else 0,
        "gps": gps,         "pct_gps":    round(gps     / n * 100) if n else 0,
        "websites": webs,   "pct_web":    round(webs    / n * 100) if n else 0,
    }


# ─── Application ──────────────────────────────────────────────────────────────

app = FastAPI(docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(ADMIN_DIR / "templates"))


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# ─── Utilitaires auth ─────────────────────────────────────────────────────────

_signer = TimestampSigner(SECRET_KEY)


def _make_token(username: str) -> str:
    return _signer.sign(username).decode()


def _get_current_user(request: Request) -> Optional[str]:
    token = request.cookies.get("admin_token")
    if not token:
        return None
    try:
        username = _signer.unsign(token, max_age=TOKEN_TTL_H * 3600)
        return username.decode()
    except (BadSignature, SignatureExpired):
        return None


def _require_auth(request: Request) -> str:
    user = _get_current_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/admin/login"},
        )
    return user


def _redirect_login(msg: str = "") -> RedirectResponse:
    url = "/admin/login"
    if msg:
        url += f"?error={msg}"
    return RedirectResponse(url, status_code=303)


# ─── Routes : auth ────────────────────────────────────────────────────────────

@app.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if _get_current_user(request):
        return RedirectResponse("/admin/", 303)
    if not ADMIN_PASS_HASH:
        return HTMLResponse(
            "<h2 style='font-family:sans-serif;color:red;padding:2em'>"
            "⚠️ Variable ADMIN_PASSWORD non définie dans Vercel.<br>"
            "Ajoutez-la dans Vercel → Settings → Environment Variables."
            "</h2>",
            status_code=503,
        )
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": request.query_params.get("error", ""),
    })


@app.post("/admin/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    import asyncio
    if username == ADMIN_USERNAME and _verify_password(password, ADMIN_PASS_HASH):
        resp = RedirectResponse("/admin/", 303)
        resp.set_cookie(
            "admin_token", _make_token(username),
            httponly=True, secure=True, samesite="strict",
            max_age=TOKEN_TTL_H * 3600,
        )
        return resp
    await asyncio.sleep(0.5)
    return _redirect_login("Identifiants incorrects")


@app.get("/admin/logout")
async def logout():
    resp = RedirectResponse("/admin/login", 303)
    resp.delete_cookie("admin_token")
    return resp


# ─── Routes : dashboard ───────────────────────────────────────────────────────

@app.get("/admin/", response_class=HTMLResponse)
@app.get("/admin", response_class=HTMLResponse)
async def dashboard(request: Request, user: str = Depends(_require_auth)):
    cabinets = load_data()
    stats    = data_stats(cabinets)
    github_ok = bool(GITHUB_TOKEN and GITHUB_REPO)
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user": user,
        "stats": stats, "last_gen": None,
        "tasks": {},
        "github_ok": github_ok,
    })


# ─── Routes : cabinets ────────────────────────────────────────────────────────

@app.get("/admin/cabinets", response_class=HTMLResponse)
async def cabinets_list(
    request: Request,
    user: str = Depends(_require_auth),
    q: str = "",
    city: str = "",
    page: int = 1,
):
    cabinets = load_data()
    if q:
        ql = q.lower()
        cabinets = [c for c in cabinets if ql in c.get("name", "").lower()
                                        or ql in c.get("city", "").lower()
                                        or ql in c.get("address", "").lower()]
    if city:
        cabinets = [c for c in cabinets if c.get("city") == city]

    cabinets = sorted(cabinets, key=lambda c: (c.get("city", ""), c.get("name", "")))

    per_page  = 30
    total     = len(cabinets)
    pages     = max(1, (total + per_page - 1) // per_page)
    page      = max(1, min(page, pages))
    sliced    = cabinets[(page - 1) * per_page: page * per_page]

    all_data   = load_data()
    all_cities = sorted({c.get("city", "") for c in all_data if c.get("city")})

    return templates.TemplateResponse("cabinets.html", {
        "request": request, "user": user,
        "cabinets": sliced, "total": total,
        "page": page, "pages": pages,
        "q": q, "city": city,
        "all_cities": all_cities,
    })


@app.get("/admin/cabinets/new", response_class=HTMLResponse)
async def cabinet_new(request: Request, user: str = Depends(_require_auth)):
    return templates.TemplateResponse("cabinet_form.html", {
        "request": request, "user": user,
        "cabinet": {}, "mode": "new", "error": "",
    })


@app.post("/admin/cabinets/new")
async def cabinet_create(
    request: Request, user: str = Depends(_require_auth),
    name: str          = Form(""),
    address: str       = Form(""),
    city: str          = Form(""),
    postal_code: str   = Form(""),
    phone: str         = Form(""),
    website: str       = Form(""),
    rating: str        = Form(""),
    reviews_count: str = Form("0"),
    lat: str           = Form(""),
    lng: str           = Form(""),
    siren: str         = Form(""),
    siret: str         = Form(""),
):
    name = name.strip(); city = city.strip()
    if not name or not city:
        return templates.TemplateResponse("cabinet_form.html", {
            "request": request, "user": user,
            "cabinet": {}, "mode": "new",
            "error": "Le nom et la ville sont obligatoires.",
        })
    new_cab = {
        "name": name, "address": address.strip(),
        "city": city, "postal_code": postal_code.strip(),
        "phone": phone.strip(), "website": website.strip(),
        "rating": rating.strip(),
        "reviews_count": int(reviews_count or 0),
        "lat": float(lat) if lat.strip() else "",
        "lng": float(lng) if lng.strip() else "",
        "siren": siren.strip(), "siret": siret.strip(),
    }
    cabinets = load_data()
    cabinets.append(new_cab)
    content = json.dumps(cabinets, ensure_ascii=False, indent=2)
    await _github_commit_file(
        "data/cabinets.json", content,
        f"admin: ajout cabinet {name} ({city})",
    )
    return RedirectResponse("/admin/cabinets?created=1", 303)


@app.get("/admin/cabinets/{idx}/edit", response_class=HTMLResponse)
async def cabinet_edit(request: Request, idx: int, user: str = Depends(_require_auth)):
    cabinets = load_data()
    if idx < 0 or idx >= len(cabinets):
        raise HTTPException(404)
    return templates.TemplateResponse("cabinet_form.html", {
        "request": request, "user": user,
        "cabinet": cabinets[idx], "idx": idx, "mode": "edit", "error": "",
    })


@app.post("/admin/cabinets/{idx}/edit")
async def cabinet_update(
    request: Request, idx: int,
    user: str          = Depends(_require_auth),
    name: str          = Form(""),
    address: str       = Form(""),
    city: str          = Form(""),
    postal_code: str   = Form(""),
    phone: str         = Form(""),
    website: str       = Form(""),
    rating: str        = Form(""),
    reviews_count: str = Form("0"),
    lat: str           = Form(""),
    lng: str           = Form(""),
    siren: str         = Form(""),
    siret: str         = Form(""),
):
    cabinets = load_data()
    if idx < 0 or idx >= len(cabinets):
        raise HTTPException(404)
    name = name.strip(); city = city.strip()
    if not name or not city:
        return templates.TemplateResponse("cabinet_form.html", {
            "request": request, "user": user,
            "cabinet": cabinets[idx], "idx": idx, "mode": "edit",
            "error": "Le nom et la ville sont obligatoires.",
        })
    cabinets[idx].update({
        "name": name, "address": address.strip(),
        "city": city, "postal_code": postal_code.strip(),
        "phone": phone.strip(), "website": website.strip(),
        "rating": rating.strip(),
        "reviews_count": int(reviews_count or 0),
        "lat": float(lat) if lat.strip() else "",
        "lng": float(lng) if lng.strip() else "",
        "siren": siren.strip(), "siret": siret.strip(),
    })
    content = json.dumps(cabinets, ensure_ascii=False, indent=2)
    await _github_commit_file(
        "data/cabinets.json", content,
        f"admin: modification cabinet {name} ({city})",
    )
    return RedirectResponse("/admin/cabinets?updated=1", 303)


@app.post("/admin/cabinets/{idx}/delete")
async def cabinet_delete(request: Request, idx: int, user: str = Depends(_require_auth)):
    cabinets = load_data()
    if idx < 0 or idx >= len(cabinets):
        raise HTTPException(404)
    removed = cabinets.pop(idx)
    content = json.dumps(cabinets, ensure_ascii=False, indent=2)
    await _github_commit_file(
        "data/cabinets.json", content,
        f"admin: suppression cabinet {removed.get('name', idx)}",
    )
    return RedirectResponse("/admin/cabinets?deleted=1", 303)


# ─── Routes : blog ────────────────────────────────────────────────────────────

@app.get("/admin/blog", response_class=HTMLResponse)
async def blog_list(request: Request, user: str = Depends(_require_auth)):
    posts = load_blog()
    return templates.TemplateResponse("blog.html", {
        "request": request, "user": user,
        "posts": posts,
        "categories": BLOG_CATEGORIES,
        "api_key_ok": bool(ANTHROPIC_KEY),
    })


@app.post("/admin/blog/generate")
async def blog_generate(
    request: Request,
    user: str       = Depends(_require_auth),
    topic: str      = Form(""),
    category: str   = Form("Conseils"),
    word_count: str = Form("700"),
):
    if not ANTHROPIC_KEY:
        return JSONResponse(
            {"error": "Clé API Anthropic manquante. Définissez ANTHROPIC_API_KEY dans Vercel."},
            status_code=400,
        )
    topic = topic.strip()
    if not topic:
        return JSONResponse({"error": "Veuillez saisir un sujet."}, status_code=400)

    prompt = (
        f"Génère un article de blog professionnel en français pour un site annuaire de cabinets comptables.\n\n"
        f"Sujet : {topic}\n"
        f"Catégorie : {category}\n"
        f"Longueur cible : environ {word_count} mots\n\n"
        "Consignes strictes :\n"
        "- Le contenu est en HTML avec UNIQUEMENT ces balises : <p>, <h2>, <ul>, <li>, <strong>, <a>\n"
        "- 3 à 5 sections titrées avec <h2> (pas de <h1>, pas de <h3>)\n"
        "- Termes techniques importants en <strong>\n"
        "- Terminer par un appel à l'action avec ce lien exact : "
        '<a href="/">l\'annuaire des cabinets comptables</a>\n'
        "- Ton professionnel, pratique, orienté entrepreneurs et PME français\n"
        "- Pas de balise <html>, <head>, <body> ni de doctype\n\n"
        "Retourne UNIQUEMENT un objet JSON valide (sans markdown, sans bloc de code) avec cette structure :\n"
        '{\n'
        '  "title": "Titre accrocheur (60-70 caractères max)",\n'
        '  "slug": "titre-en-kebab-case-sans-accents",\n'
        '  "description": "Meta description de 150-160 caractères",\n'
        '  "reading_time": 7,\n'
        '  "content": "<p>...</p><h2>...</h2>..."\n'
        "}"
    )

    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=ANTHROPIC_KEY)
        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        article = json.loads(raw)
        for field in ("title", "slug", "description", "content"):
            if field not in article:
                raise ValueError(f"Champ manquant : {field}")
        article["category"]     = category
        article["date"]         = datetime.now().strftime("%Y-%m-%d")
        article["reading_time"] = int(article.get("reading_time") or
                                      max(1, len(article["content"].split()) // 200))
        return JSONResponse(article)
    except json.JSONDecodeError as exc:
        return JSONResponse({"error": f"Réponse IA mal formée : {exc}"}, status_code=500)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/admin/blog/publish")
async def blog_publish(
    request: Request,
    user: str         = Depends(_require_auth),
    title: str        = Form(""),
    slug: str         = Form(""),
    description: str  = Form(""),
    category: str     = Form("Conseils"),
    reading_time: str = Form("5"),
    date: str         = Form(""),
    content: str      = Form(""),
):
    title = title.strip()
    slug  = slugify(slug.strip()) if slug.strip() else slugify(title)
    if not title or not content:
        return RedirectResponse("/admin/blog?error=missing", 303)

    posts = load_blog()
    existing_slugs = {p["slug"] for p in posts}
    base_slug, counter = slug, 1
    while slug in existing_slugs:
        slug = f"{base_slug}-{counter}"
        counter += 1

    posts.append({
        "slug":         slug,
        "title":        title,
        "description":  description.strip(),
        "date":         date or datetime.now().strftime("%Y-%m-%d"),
        "category":     category,
        "reading_time": max(1, int(reading_time or 5)),
        "content":      content,
    })
    blog_content = json.dumps(posts, ensure_ascii=False, indent=2)
    await _github_commit_file(
        "data/blog_posts.json", blog_content,
        f"admin: publication article « {title} »",
    )
    return RedirectResponse(f"/admin/blog?published={slug}", 303)


@app.post("/admin/blog/{slug}/delete")
async def blog_delete(request: Request, slug: str, user: str = Depends(_require_auth)):
    posts = load_blog()
    removed_title = next((p["title"] for p in posts if p["slug"] == slug), slug)
    posts = [p for p in posts if p["slug"] != slug]
    blog_content = json.dumps(posts, ensure_ascii=False, indent=2)
    await _github_commit_file(
        "data/blog_posts.json", blog_content,
        f"admin: suppression article « {removed_title} »",
    )
    return RedirectResponse("/admin/blog?deleted=1", 303)


# ─── Routes : changement de mot de passe ─────────────────────────────────────

@app.get("/admin/password", response_class=HTMLResponse)
async def password_page(request: Request, user: str = Depends(_require_auth)):
    return templates.TemplateResponse("password.html", {
        "request": request, "user": user, "success": False, "error": "",
        "vercel_mode": True,
    })


@app.post("/admin/password")
async def password_change(
    request: Request, user: str = Depends(_require_auth),
    current: str = Form(""),
    new_pw: str  = Form(""),
    confirm: str = Form(""),
):
    """En mode Vercel, le mot de passe se change dans les env vars Vercel, pas ici."""
    return templates.TemplateResponse("password.html", {
        "request": request, "user": user, "success": False,
        "error": (
            "En mode Vercel, modifiez votre mot de passe directement dans "
            "Vercel → Settings → Environment Variables → ADMIN_PASSWORD, "
            "puis redéployez."
        ),
        "vercel_mode": True,
    })


# ─── Routes : import CSV / Excel ─────────────────────────────────────────────

IMPORT_COLUMNS = [
    ("nom",          "name",          "Nom du cabinet (obligatoire)"),
    ("adresse",      "address",       "Adresse (numéro + rue)"),
    ("ville",        "city",          "Ville (obligatoire)"),
    ("code_postal",  "postal_code",   "Code postal (ex : 75001)"),
    ("telephone",    "phone",         "Numéro de téléphone"),
    ("site_web",     "website",       "URL du site web"),
    ("note",         "rating",        "Note Google (ex : 4.5)"),
    ("nb_avis",      "reviews_count", "Nombre d'avis Google (entier)"),
    ("latitude",     "lat",           "Latitude GPS (ex : 48.8566)"),
    ("longitude",    "lng",           "Longitude GPS (ex : 2.3522)"),
    ("siren",        "siren",         "Numéro SIREN (9 chiffres)"),
    ("siret",        "siret",         "Numéro SIRET (14 chiffres)"),
]

_COL_MAP: dict[str, str] = {}
for _fr, _en, _ in IMPORT_COLUMNS:
    _COL_MAP[_fr.lower()] = _en
    _COL_MAP[_en.lower()] = _en

_IMPORT_EXAMPLE = [
    "Cabinet Dupont & Associés", "12 rue de la Paix", "Paris", "75001",
    "01 23 45 67 89", "https://www.cabinet-dupont.fr", "4.5", "42",
    "48.8566", "2.3522", "123456789", "12345678900012",
]


def _normalize_import_row(row: dict) -> dict | None:
    out: dict = {}
    for key, val in row.items():
        field = _COL_MAP.get(key.strip().lower().replace(" ", "_"))
        if field:
            out[field] = str(val).strip() if val is not None else ""
    if not out.get("name") or not out.get("city"):
        return None
    try:
        out["reviews_count"] = int(float(out.get("reviews_count") or 0))
    except (ValueError, TypeError):
        out["reviews_count"] = 0
    for f in ("lat", "lng"):
        v = out.get(f, "")
        try:
            out[f] = float(v) if v else ""
        except (ValueError, TypeError):
            out[f] = ""
    return out


@app.get("/admin/import", response_class=HTMLResponse)
async def import_page(request: Request, user: str = Depends(_require_auth)):
    return templates.TemplateResponse("import.html", {
        "request": request, "user": user,
        "columns": IMPORT_COLUMNS, "result": None,
    })


@app.get("/admin/import/template.csv")
async def import_template_csv(user: str = Depends(_require_auth)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c[0] for c in IMPORT_COLUMNS])
    w.writerow(_IMPORT_EXAMPLE)
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=modele_cabinets.csv"},
    )


@app.get("/admin/import/template.xlsx")
async def import_template_xlsx(user: str = Depends(_require_auth)):
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cabinets"
    for i, (col_name, _, _desc) in enumerate(IMPORT_COLUMNS, 1):
        cell = ws.cell(row=1, column=i, value=col_name)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1D4ED8")
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[cell.column_letter].width = max(16, len(col_name) + 4)
    for i, val in enumerate(_IMPORT_EXAMPLE, 1):
        ws.cell(row=2, column=i, value=val)
    ws2 = wb.create_sheet("Description colonnes")
    ws2.append(["Colonne", "Description"])
    ws2["A1"].font = Font(bold=True)
    ws2["B1"].font = Font(bold=True)
    for col_name, _, desc in IMPORT_COLUMNS:
        ws2.append([col_name, desc])
    ws2.column_dimensions["A"].width = 20
    ws2.column_dimensions["B"].width = 50

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=modele_cabinets.xlsx"},
    )


@app.post("/admin/import", response_class=HTMLResponse)
async def import_post(
    request: Request,
    user: str = Depends(_require_auth),
    mode: str = Form("merge"),
    file: UploadFile = File(...),
):
    filename = (file.filename or "").lower()
    result: dict = {"added": 0, "updated": 0, "skipped": 0, "errors": [], "total": 0}
    rows: list[dict] = []

    content = await file.read()

    if filename.endswith(".csv"):
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                text = content.decode(enc)
                rows = list(csv.DictReader(io.StringIO(text)))
                break
            except (UnicodeDecodeError, Exception):
                continue
        if not rows:
            result["errors"].append("Impossible de lire le fichier CSV (encodage non reconnu).")
    elif filename.endswith((".xlsx", ".xls")):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            ws = wb.active
            raw_rows = list(ws.iter_rows(values_only=True))
            if raw_rows:
                headers = [str(h or "").strip() for h in raw_rows[0]]
                for row in raw_rows[1:]:
                    rows.append({headers[i]: (str(v) if v is not None else "")
                                 for i, v in enumerate(row)})
        except Exception as e:
            result["errors"].append(f"Erreur lecture Excel : {e}")
    else:
        result["errors"].append("Format non supporté. Utilisez un fichier .csv ou .xlsx")

    if rows:
        cabinets = load_data() if mode == "merge" else []
        idx_siren = {c.get("siren", ""): i for i, c in enumerate(cabinets) if c.get("siren")}
        idx_name  = {
            (c.get("name", "").lower(), c.get("city", "").lower()): i
            for i, c in enumerate(cabinets)
        }
        for row_num, raw in enumerate(rows, 2):
            if all(v in ("", "None", None) for v in raw.values()):
                continue
            result["total"] += 1
            cab = _normalize_import_row(raw)
            if cab is None:
                result["errors"].append(f"Ligne {row_num} : nom ou ville manquant — ignorée")
                result["skipped"] += 1
                continue
            if mode == "merge":
                existing_idx = None
                if cab.get("siren") and cab["siren"] in idx_siren:
                    existing_idx = idx_siren[cab["siren"]]
                else:
                    key = (cab["name"].lower(), cab["city"].lower())
                    existing_idx = idx_name.get(key)
                if existing_idx is not None:
                    cabinets[existing_idx].update({k: v for k, v in cab.items() if v != ""})
                    result["updated"] += 1
                else:
                    cabinets.append(cab)
                    new_idx = len(cabinets) - 1
                    if cab.get("siren"):
                        idx_siren[cab["siren"]] = new_idx
                    idx_name[(cab["name"].lower(), cab["city"].lower())] = new_idx
                    result["added"] += 1
            else:
                cabinets.append(cab)
                result["added"] += 1

        data_content = json.dumps(cabinets, ensure_ascii=False, indent=2)
        await _github_commit_file(
            "data/cabinets.json", data_content,
            f"admin: import CSV ({result['added']} ajoutés, {result['updated']} mis à jour)",
        )

    return templates.TemplateResponse("import.html", {
        "request": request, "user": user,
        "columns": IMPORT_COLUMNS, "result": result,
    })


# ─── API JSON ─────────────────────────────────────────────────────────────────

@app.get("/admin/api/stats")
async def api_stats(request: Request, user: str = Depends(_require_auth)):
    return JSONResponse(data_stats(load_data()))


# ─── Outils (info uniquement en mode Vercel) ──────────────────────────────────

@app.get("/admin/outils", response_class=HTMLResponse)
async def outils_page(request: Request, user: str = Depends(_require_auth)):
    return templates.TemplateResponse("scraper.html", {
        "request": request, "user": user,
        "tasks": {},
        "google_key_ok": False,
        "vercel_mode": True,
    })
