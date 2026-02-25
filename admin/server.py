#!/usr/bin/env python3
"""
Backoffice Admin — cabinets-comptables.name

Lancement local :
    pip install -r admin/requirements.txt
    python admin/server.py
    → http://localhost:8080/admin

Déploiement Railway (public) :
    Variables à définir dans Railway Dashboard :
      ADMIN_SECRET_KEY   → chaîne aléatoire longue (ex: openssl rand -hex 32)
      ADMIN_USERNAME     → votre login (défaut: admin)
      ADMIN_PASSWORD     → mot de passe initial (si non défini, généré au démarrage)
      GOOGLE_PLACES_API_KEY → clé Google Places (optionnel)
      PORT               → 8080 (défini dans railway.toml)
"""

import asyncio
import json
import os
import secrets
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import hashlib
from itsdangerous import TimestampSigner, BadSignature, SignatureExpired
from slugify import slugify
from starlette.middleware.base import BaseHTTPMiddleware

# ─── Chemins ─────────────────────────────────────────────────────────────────

ROOT        = Path(__file__).parent.parent
ADMIN_DIR   = ROOT / "admin"
DATA_FILE   = ROOT / "data" / "cabinets.json"
BLOG_FILE   = ROOT / "data" / "blog_posts.json"
LOGS_DIR    = ADMIN_DIR / "logs"
CREDS_FILE  = ADMIN_DIR / ".credentials"   # non versionné
LOGS_DIR.mkdir(exist_ok=True)

BLOG_CATEGORIES = ["Conseils", "Fiscalité", "Comptabilité", "Statuts & Juridique"]

# ─── Config auth ──────────────────────────────────────────────────────────────

TOKEN_TTL_H = 8

# ─── Hachage mot de passe (PBKDF2-HMAC-SHA256, Python pur) ───────────────────

def _hash_password(password: str, salt: str | None = None) -> str:
    """Retourne 'salt$hash' (PBKDF2-HMAC-SHA256, 260 000 itérations)."""
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"{salt}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    """Vérifie un mot de passe contre un hash 'salt$hash'."""
    if "$" not in stored:
        return False
    salt, _ = stored.split("$", 1)
    return secrets.compare_digest(_hash_password(password, salt), stored)

SECRET_KEY        = os.environ.get("ADMIN_SECRET_KEY") or secrets.token_hex(32)
ADMIN_USERNAME    = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASS_HASH   = os.environ.get("ADMIN_PASSWORD_HASH", "")
GOOGLE_API_KEY    = os.environ.get("GOOGLE_PLACES_API_KEY", "")
ANTHROPIC_KEY     = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_KEY        = os.environ.get("GEMINI_API_KEY", "")
DEEPSEEK_KEY      = os.environ.get("DEEPSEEK_API_KEY", "")
OPENAI_KEY        = os.environ.get("OPENAI_API_KEY", "")

# Priorité 1 : ADMIN_PASSWORD en clair dans les env vars Railway
_plain_pw = os.environ.get("ADMIN_PASSWORD", "").strip()
if _plain_pw:
    # Supprimer le fichier .credentials périmé pour éviter les conflits
    if CREDS_FILE.exists():
        CREDS_FILE.unlink()
        print("[auth] .credentials supprimé — ADMIN_PASSWORD (env) prend la main")
    ADMIN_PASS_HASH = _hash_password(_plain_pw)
    print(f"[auth] ✅ Mot de passe chargé depuis ADMIN_PASSWORD (login: {ADMIN_USERNAME})")

# Priorité 2 : ADMIN_PASSWORD_HASH en format 'salt$pbkdf2_hex'
elif ADMIN_PASS_HASH:
    if "$" not in ADMIN_PASS_HASH:
        print("[auth] ⚠️  ADMIN_PASSWORD_HASH format invalide. Définissez ADMIN_PASSWORD.")
        ADMIN_PASS_HASH = ""

# Priorité 3 : fichier .credentials existant
if not ADMIN_PASS_HASH:
    if CREDS_FILE.exists():
        with open(CREDS_FILE) as f:
            _c = json.load(f)
        ADMIN_USERNAME  = _c.get("username", ADMIN_USERNAME)
        ADMIN_PASS_HASH = _c.get("password_hash", "")
        print(f"[auth] Credentials chargés depuis {CREDS_FILE}")
    else:
        # Priorité 4 : génération automatique (premier lancement)
        _pw = secrets.token_urlsafe(16)
        ADMIN_PASS_HASH = _hash_password(_pw)
        with open(CREDS_FILE, "w") as f:
            json.dump({"username": ADMIN_USERNAME, "password_hash": ADMIN_PASS_HASH}, f)
        print("\n" + "=" * 60)
        print("  PREMIER LANCEMENT — CREDENTIALS GÉNÉRÉS")
        print(f"  Login    : {ADMIN_USERNAME}")
        print(f"  Password : {_pw}")
        print("  → Copiez ce mot de passe dans Railway → Variables → ADMIN_PASSWORD")
        print("=" * 60 + "\n")

# ─── Application ──────────────────────────────────────────────────────────────

app = FastAPI(docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(ADMIN_DIR / "templates"))


# ─── Security headers (remplace vercel.json headers) ─────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response

app.add_middleware(SecurityHeadersMiddleware)

# État des tâches en arrière-plan
_tasks: dict[str, dict] = {}   # {task_id: {status, log_file, started_at}}


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
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER,
                            headers={"Location": "/admin/login"})
    return user


def _redirect_login(msg: str = "") -> RedirectResponse:
    url = "/admin/login"
    if msg:
        url += f"?error={msg}"
    return RedirectResponse(url, status_code=303)


# ─── Données ──────────────────────────────────────────────────────────────────

def load_data() -> list[dict]:
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_data(cabinets: list[dict]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(cabinets, f, ensure_ascii=False, indent=2)


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


# ─── Tâches en arrière-plan ───────────────────────────────────────────────────

async def _run_script(task_id: str, cmd: list[str], log_file: Path) -> None:
    """Lance un script Python en sous-processus et capture sa sortie."""
    _tasks[task_id] = {
        "status": "running",
        "log_file": str(log_file),
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
        "returncode": None,
    }
    try:
        with open(log_file, "w", encoding="utf-8") as lf:
            lf.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Démarrage : {' '.join(cmd)}\n")
            lf.flush()
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=lf,
                stderr=lf,
                cwd=str(ROOT),
            )
            await proc.wait()
            lf.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] Terminé (code {proc.returncode})\n")
        _tasks[task_id]["status"]      = "done" if proc.returncode == 0 else "error"
        _tasks[task_id]["returncode"]  = proc.returncode
        _tasks[task_id]["finished_at"] = datetime.now().isoformat()
    except Exception as e:
        _tasks[task_id]["status"] = "error"
        _tasks[task_id]["finished_at"] = datetime.now().isoformat()
        with open(log_file, "a") as lf:
            lf.write(f"\nErreur interne : {e}\n")


def _is_busy(task_id: str) -> bool:
    return _tasks.get(task_id, {}).get("status") == "running"


# ─── Routes : auth ────────────────────────────────────────────────────────────

@app.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if _get_current_user(request):
        return RedirectResponse("/admin/", 303)
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
    if username == ADMIN_USERNAME and _verify_password(password, ADMIN_PASS_HASH):
        resp = RedirectResponse("/admin/", 303)
        resp.set_cookie(
            "admin_token", _make_token(username),
            httponly=True, secure=True, samesite="strict",
            max_age=TOKEN_TTL_H * 3600,
        )
        return resp
    # Anti-timing : délai artificiel
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
    # Dernière génération
    gen_log = LOGS_DIR / "generate.log"
    last_gen = None
    if gen_log.exists():
        last_gen = datetime.fromtimestamp(gen_log.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user": user,
        "stats": stats, "last_gen": last_gen,
        "tasks": _tasks,
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
    # Filtres
    if q:
        ql = q.lower()
        cabinets = [c for c in cabinets if ql in c.get("name", "").lower()
                                        or ql in c.get("city", "").lower()
                                        or ql in c.get("address", "").lower()]
    if city:
        cabinets = [c for c in cabinets if c.get("city") == city]

    # Tri
    cabinets = sorted(cabinets, key=lambda c: (c.get("city", ""), c.get("name", "")))

    # Pagination
    per_page  = 30
    total     = len(cabinets)
    pages     = max(1, (total + per_page - 1) // per_page)
    page      = max(1, min(page, pages))
    sliced    = cabinets[(page - 1) * per_page: page * per_page]

    # Liste des villes pour filtre dropdown (même jeu de données filtré en amont)
    all_cities = sorted({c.get("city", "") for c in load_data() if c.get("city")})

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
    rating_info: str   = Form(""),
    category: str      = Form(""),
    open_hours: str    = Form(""),
    lat: str           = Form(""),
    lng: str           = Form(""),
    featured_image: str = Form(""),
    bing_maps_url: str = Form(""),
    email: str         = Form(""),
    facebook: str      = Form(""),
    instagram: str     = Form(""),
    twitter: str       = Form(""),
    external_id: str   = Form(""),
):
    name = name.strip()
    city = city.strip()
    if not name or not city:
        return templates.TemplateResponse("cabinet_form.html", {
            "request": request, "user": user,
            "cabinet": request._form, "mode": "new",
            "error": "Le nom et la ville sont obligatoires.",
        })
    new_cab = {
        "name": name, "address": address.strip(),
        "city": city, "postal_code": postal_code.strip(),
        "phone": phone.strip(), "website": website.strip(),
        "rating": rating.strip(),
        "reviews_count": int(reviews_count or 0),
        "rating_info": rating_info.strip(),
        "category": category.strip(),
        "open_hours": open_hours.strip(),
        "lat": float(lat) if lat.strip() else "",
        "lng": float(lng) if lng.strip() else "",
        "featured_image": featured_image.strip(),
        "bing_maps_url": bing_maps_url.strip(),
        "email": email.strip(),
        "facebook": facebook.strip(),
        "instagram": instagram.strip(),
        "twitter": twitter.strip(),
        "external_id": external_id.strip(),
    }
    cabinets = load_data()
    cabinets.append(new_cab)
    save_data(cabinets)
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
    rating_info: str   = Form(""),
    category: str      = Form(""),
    open_hours: str    = Form(""),
    lat: str           = Form(""),
    lng: str           = Form(""),
    featured_image: str = Form(""),
    bing_maps_url: str = Form(""),
    email: str         = Form(""),
    facebook: str      = Form(""),
    instagram: str     = Form(""),
    twitter: str       = Form(""),
    external_id: str   = Form(""),
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
        "rating_info": rating_info.strip(),
        "category": category.strip(),
        "open_hours": open_hours.strip(),
        "lat": float(lat) if lat.strip() else "",
        "lng": float(lng) if lng.strip() else "",
        "featured_image": featured_image.strip(),
        "bing_maps_url": bing_maps_url.strip(),
        "email": email.strip(),
        "facebook": facebook.strip(),
        "instagram": instagram.strip(),
        "twitter": twitter.strip(),
        "external_id": external_id.strip(),
    })
    save_data(cabinets)
    return RedirectResponse("/admin/cabinets?updated=1", 303)


@app.post("/admin/cabinets/{idx}/delete")
async def cabinet_delete(request: Request, idx: int, user: str = Depends(_require_auth)):
    cabinets = load_data()
    if idx < 0 or idx >= len(cabinets):
        raise HTTPException(404)
    cabinets.pop(idx)
    save_data(cabinets)
    return RedirectResponse("/admin/cabinets?deleted=1", 303)


# ─── Routes : scraper / outils ────────────────────────────────────────────────

@app.get("/admin/outils", response_class=HTMLResponse)
async def outils_page(request: Request, user: str = Depends(_require_auth)):
    return templates.TemplateResponse("scraper.html", {
        "request": request, "user": user,
        "tasks": _tasks,
        "google_key_ok": bool(GOOGLE_API_KEY),
        "vercel_mode": False,
    })



@app.post("/admin/outils/enrich")
async def launch_enrich(
    request: Request, user: str = Depends(_require_auth),
    limit: str   = Form("1000"),
    cities: str  = Form(""),
):
    task_id = "enrich"
    if _is_busy(task_id):
        return RedirectResponse("/admin/outils?busy=enrich", 303)

    env = {**os.environ}
    if GOOGLE_API_KEY:
        env["GOOGLE_PLACES_API_KEY"] = GOOGLE_API_KEY

    safe_limit = str(max(1, min(10000, int(limit or 1000))))
    cmd = [sys.executable, "scraper/enrich_google_places.py", "--limit", safe_limit]
    if cities.strip():
        safe_cities = ",".join(c.strip() for c in cities.split(",") if c.strip().replace(" ", "").isalpha())
        if safe_cities:
            cmd += ["--cities", safe_cities]

    log_file = LOGS_DIR / "enrich.log"
    asyncio.create_task(_run_script(task_id, cmd, log_file))
    return RedirectResponse("/admin/outils?started=enrich", 303)


@app.post("/admin/outils/generate")
async def launch_generate(request: Request, user: str = Depends(_require_auth)):
    task_id = "generate"
    if _is_busy(task_id):
        return RedirectResponse("/admin/outils?busy=generate", 303)
    log_file = LOGS_DIR / "generate.log"
    asyncio.create_task(_run_script(task_id, [sys.executable, "generator/generate.py"], log_file))
    return RedirectResponse("/admin/outils?started=generate", 303)


# ─── API JSON (polling logs + statuts) ───────────────────────────────────────

@app.get("/admin/api/task/{task_id}")
async def api_task_status(task_id: str, request: Request, user: str = Depends(_require_auth)):
    task = _tasks.get(task_id)
    if not task:
        return JSONResponse({"status": "idle"})
    log_file = Path(task.get("log_file", ""))
    log_content = ""
    if log_file.exists():
        # Dernières 200 lignes
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        log_content = "\n".join(lines[-200:])
    return JSONResponse({**task, "log": log_content})


@app.get("/admin/api/stats")
async def api_stats(request: Request, user: str = Depends(_require_auth)):
    return JSONResponse(data_stats(load_data()))


# ─── Changement de mot de passe ──────────────────────────────────────────────

@app.get("/admin/password", response_class=HTMLResponse)
async def password_page(request: Request, user: str = Depends(_require_auth)):
    return templates.TemplateResponse("password.html", {
        "request": request, "user": user, "success": False, "error": "",
    })


@app.post("/admin/password")
async def password_change(
    request: Request, user: str = Depends(_require_auth),
    current: str  = Form(""),
    new_pw: str   = Form(""),
    confirm: str  = Form(""),
):
    global ADMIN_PASS_HASH
    error = ""
    if not _verify_password(current, ADMIN_PASS_HASH):
        error = "Mot de passe actuel incorrect."
    elif len(new_pw) < 12:
        error = "Le nouveau mot de passe doit faire au moins 12 caractères."
    elif new_pw != confirm:
        error = "Les mots de passe ne correspondent pas."
    if error:
        return templates.TemplateResponse("password.html", {
            "request": request, "user": user, "success": False, "error": error,
        })
    ADMIN_PASS_HASH = _hash_password(new_pw)
    with open(CREDS_FILE, "w") as f:
        json.dump({"username": ADMIN_USERNAME, "password_hash": ADMIN_PASS_HASH}, f)
    return templates.TemplateResponse("password.html", {
        "request": request, "user": user, "success": True, "error": "",
    })


# ─── Blog — données ───────────────────────────────────────────────────────────

def load_blog() -> list[dict]:
    if BLOG_FILE.exists():
        with open(BLOG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_blog(posts: list[dict]) -> None:
    with open(BLOG_FILE, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


# ─── Blog — helper LLM ────────────────────────────────────────────────────────

LLM_LABELS = {
    "claude":   "Claude (Anthropic)",
    "gemini":   "Gemini (Google)",
    "deepseek": "DeepSeek",
    "chatgpt":  "ChatGPT (OpenAI)",
}


def _llm_keys_status() -> dict[str, bool]:
    return {
        "claude":   bool(ANTHROPIC_KEY),
        "gemini":   bool(GEMINI_KEY),
        "deepseek": bool(DEEPSEEK_KEY),
        "chatgpt":  bool(OPENAI_KEY),
    }


async def _call_llm(llm: str, prompt: str) -> str:
    """Appelle le LLM sélectionné et retourne le texte brut de la réponse."""
    if llm == "claude":
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=ANTHROPIC_KEY)
        msg = await client.messages.create(
            model="claude-sonnet-4-6", max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()

    if llm == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        resp = await asyncio.to_thread(model.generate_content, prompt)
        return resp.text.strip()

    if llm == "deepseek":
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
        resp = await client.chat.completions.create(
            model="deepseek-chat", max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content.strip()

    if llm == "chatgpt":
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=OPENAI_KEY)
        resp = await client.chat.completions.create(
            model="gpt-4o-mini", max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content.strip()

    raise ValueError(f"LLM inconnu : {llm}")


def _clean_llm_json(raw: str) -> str:
    """Retire les blocs ```json ... ``` éventuels."""
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


# ─── Blog — routes ────────────────────────────────────────────────────────────

@app.get("/admin/blog", response_class=HTMLResponse)
async def blog_list(request: Request, user: str = Depends(_require_auth)):
    posts = load_blog()
    return templates.TemplateResponse("blog.html", {
        "request": request, "user": user,
        "posts": posts,
        "categories": BLOG_CATEGORIES,
        "api_key_ok": any(_llm_keys_status().values()),
        "llm_keys": _llm_keys_status(),
        "llm_labels": LLM_LABELS,
    })


@app.post("/admin/blog/generate")
async def blog_generate(
    request: Request,
    user: str       = Depends(_require_auth),
    topic: str      = Form(""),
    category: str   = Form("Conseils"),
    word_count: str = Form("700"),
    llm: str        = Form("claude"),
):
    llm = llm.strip().lower()
    keys = _llm_keys_status()
    if not keys.get(llm):
        return JSONResponse(
            {"error": f"Clé API pour {LLM_LABELS.get(llm, llm)} manquante. "
                      f"Définissez la variable d'environnement correspondante."},
            status_code=400,
        )
    topic = topic.strip()
    if not topic:
        return JSONResponse({"error": "Veuillez saisir un sujet."}, status_code=400)

    # Charger les articles existants pour l'interlinking
    existing = load_blog()
    interlink_list = "\n".join(
        f'- <a href="/blog/{p["slug"]}/">{p["title"]}</a>'
        for p in existing
    )
    interlink_instruction = (
        "\n\nArticles déjà publiés sur ce site (pour interlinking) :\n"
        + interlink_list
        + "\nConsigne interlinking : intégrer naturellement 2 à 3 liens vers ces articles "
          "pertinents dans le corps du texte, en utilisant exactement le format "
          '<a href="/blog/SLUG/">Titre de l\'article</a>.'
        if existing else ""
    )

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
        "- Pas de balise <html>, <head>, <body> ni de doctype\n"
        + interlink_instruction + "\n\n"
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
        raw = await _call_llm(llm, prompt)
        raw = _clean_llm_json(raw)
        article = json.loads(raw)
        for field in ("title", "slug", "description", "content"):
            if field not in article:
                raise ValueError(f"Champ manquant dans la réponse : {field}")
        article["category"]     = category
        article["date"]         = datetime.now().strftime("%Y-%m-%d")
        article["reading_time"] = int(article.get("reading_time") or
                                      max(1, len(article["content"].split()) // 200))
        return JSONResponse(article)
    except json.JSONDecodeError as exc:
        return JSONResponse({"error": f"Réponse IA mal formée (JSON invalide) : {exc}"}, status_code=500)
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
    # Éviter les slugs en doublon
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
    save_blog(posts)

    # Régénérer le site en arrière-plan
    log_file = LOGS_DIR / "generate.log"
    asyncio.create_task(_run_script("generate", [sys.executable, "generator/generate.py"], log_file))

    return RedirectResponse(f"/admin/blog?published={slug}", 303)


@app.post("/admin/blog/{slug}/delete")
async def blog_delete(request: Request, slug: str, user: str = Depends(_require_auth)):
    posts = load_blog()
    posts = [p for p in posts if p["slug"] != slug]
    save_blog(posts)
    return RedirectResponse("/admin/blog?deleted=1", 303)


# ─── Redirects legacy (anciens URLs Vercel) ───────────────────────────────────

@app.get("/cabinet/{slug}")
async def redirect_cabinet(slug: str):
    return RedirectResponse(f"/cabinets/{slug}/", status_code=308)


@app.get("/ville/{slug}")
async def redirect_ville(slug: str):
    return RedirectResponse(f"/villes/{slug}/", status_code=308)


# ─── Site statique (monté EN DERNIER pour ne pas masquer les routes /admin) ───

_output_dir = ROOT / "output"
if _output_dir.exists():
    app.mount("/", StaticFiles(directory=str(_output_dir), html=True), name="site")


# ─── Démarrage ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Admin backoffice → http://localhost:{port}/admin")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
