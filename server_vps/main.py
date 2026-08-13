"""
Activation API (FastAPI). Run with:  uvicorn main:app --host 127.0.0.1 --port 8080
Put Caddy in front for HTTPS. Config comes from environment variables:

  SIGNING_KEY_PKCS8   base64 PKCS8 Ed25519 private key (keygen/generate_activation_keys.py)
  ADMIN_TOKEN         password for the admin HTTP endpoints (fallback to Telegram)
  TG_BOT_TOKEN        Telegram bot token (BotFather)
  TG_CHAT_ID          your numeric Telegram id (the only approver)
  DB_PATH             sqlite path (default /var/lib/carapk/activations.db)
"""
from __future__ import annotations
import asyncio
import os
import urllib.request

from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

import plan as plan_mod
from store import Store
from telegram import Bot

DB_PATH = os.environ.get("DB_PATH", "/var/lib/carapk/activations.db")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

# Web-provisioning config.
#   DOWNLOAD_HMAC_KEY  secret for signing short-lived /dl URLs (any random string)
#   PAYLOAD_ORIGIN     PRIVATE base URL the server streams APKs from (not public!)
#   DOWNLOAD_TTL       seconds a signed URL stays valid (default 900)
#   PAYLOAD_AUTH       optional "Header-Name: value" sent upstream when fetching
#                      from PAYLOAD_ORIGIN. Lets the payload bucket sit behind a
#                      Cloudflare rule that only admits requests carrying this
#                      secret header, so the origin is unreachable to the public
#                      even if someone learns its hostname. Leave empty if you
#                      gate by source IP instead.
#   WEB_ORIGINS        comma-separated origins allowed to call the API from a
#                      browser (the web client). Unset/"*" => any origin. This
#                      API has NO cookie or session auth — every privileged call
#                      carries a one-time Ed25519 token in the body, so the
#                      origin is not a trust boundary and "*" is safe. Pin it to
#                      the seller's own site(s) if you prefer, e.g.
#                      WEB_ORIGINS="https://install.example.com".
DOWNLOAD_HMAC_KEY = os.environ.get("DOWNLOAD_HMAC_KEY", "").encode()
PAYLOAD_ORIGIN = os.environ.get("PAYLOAD_ORIGIN", "").rstrip("/")
DOWNLOAD_TTL = int(os.environ.get("DOWNLOAD_TTL", "900"))
PAYLOAD_AUTH = os.environ.get("PAYLOAD_AUTH", "").strip()
WEB_ORIGINS = [o.strip() for o in os.environ.get("WEB_ORIGINS", "*").split(",") if o.strip()] or ["*"]

store = Store(DB_PATH, os.environ.get("SIGNING_KEY_PKCS8", ""))
bot = Bot(TG_BOT_TOKEN, TG_CHAT_ID, store) if (TG_BOT_TOKEN and TG_CHAT_ID) else None

app = FastAPI()

# The web client is a static page served from a different origin than this API,
# so browsers gate every call behind CORS. Without this the desktop app works
# (not a browser) but the web app dies on "Load failed" at the preflight. No
# credentials are used (token-in-body, not cookies), so credentials stay off and
# a wildcard origin is legitimate; the middleware also answers the OPTIONS
# preflight automatically.
app.add_middleware(
    CORSMiddleware,
    allow_origins=WEB_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    max_age=600,
)


@app.on_event("startup")
async def _startup():
    if bot:
        asyncio.create_task(bot.poll_loop())


def _admin(authorization: str | None):
    if not ADMIN_TOKEN or authorization != "Bearer " + ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.post("/api/request")
async def api_request(req: Request):
    b = await req.json()
    for f in ("mid", "vin", "make", "model"):
        v = b.get(f)
        if not v or len(str(v)) > 128:
            return JSONResponse({"error": f"invalid {f}"}, status_code=400)
    rec = store.create(b["mid"], b["vin"], b["make"], b["model"])
    if bot:
        try:
            await bot.notify_new(rec)
        except Exception:
            pass
    return {"rid": rec["rid"], "code": rec["code"], "status": "pending"}


@app.get("/api/status")
async def api_status(rid: str):
    status, token = store.deliver_once(rid)
    out = {"status": status}
    if token:
        out["token"] = token
    return out


@app.get("/api/pending")
async def api_pending(authorization: str | None = Header(default=None)):
    _admin(authorization)
    return store.pending()


@app.post("/api/approve")
async def api_approve(req: Request, authorization: str | None = Header(default=None)):
    _admin(authorization)
    rid = (await req.json()).get("rid", "")
    return {"ok": bool(store.approve(rid))}


@app.post("/api/reject")
async def api_reject(req: Request, authorization: str | None = Header(default=None)):
    _admin(authorization)
    rid = (await req.json()).get("rid", "")
    return {"ok": store.reject(rid)}


# --------------------------------------------------------------------------- #
#  Web provisioning: the recipe + payload never ship in the browser.
# --------------------------------------------------------------------------- #
@app.post("/api/plan")
async def api_plan(req: Request):
    """Return the provisioning plan for one approved session.

    The browser presents the one-time token it already received; the server
    verifies it (same key that signed it), then hands back the op list with
    freshly signed, short-lived download URLs. No token → no plan.
    """
    if not DOWNLOAD_HMAC_KEY:
        raise HTTPException(status_code=503, detail="downloads not configured")
    b = await req.json()
    payload = store.verify_token(b.get("token", ""))
    if not payload:
        raise HTTPException(status_code=403, detail="invalid or unapproved token")
    profile = b.get("profile", "")
    if profile not in plan_mod.RECIPES:
        raise HTTPException(status_code=400, detail="unknown profile")
    return plan_mod.build_plan(profile, payload["rid"], DOWNLOAD_HMAC_KEY, DOWNLOAD_TTL)


@app.post("/api/verify")
async def api_verify(req: Request):
    """Cheap token check for the local wireless agent — no recipe returned."""
    token = (await req.json()).get("token", "")
    return {"ok": store.verify_token(token) is not None}


@app.post("/api/consume")
async def api_consume(req: Request):
    """Mark a token spent once its install finished. Idempotent, best-effort."""
    token = (await req.json()).get("token", "")
    return {"ok": store.consume(token)}


@app.get("/dl/{file}")
async def api_download(file: str, rid: str = "", exp: str = "", sig: str = ""):
    """Stream one APK, only for a valid, unexpired signed URL from a plan."""
    if not (DOWNLOAD_HMAC_KEY and PAYLOAD_ORIGIN):
        raise HTTPException(status_code=503, detail="downloads not configured")
    ok, why = plan_mod.verify_url(file, rid, exp, sig, DOWNLOAD_HMAC_KEY)
    if not ok:
        raise HTTPException(status_code=403, detail=why)

    # Pull from the PRIVATE origin and stream to the client. The public never
    # sees the origin URL; the browser only ever holds an expiring /dl link.
    req = urllib.request.Request(f"{PAYLOAD_ORIGIN}/{file}")
    if PAYLOAD_AUTH and ":" in PAYLOAD_AUTH:
        name, _, value = PAYLOAD_AUTH.partition(":")
        req.add_header(name.strip(), value.strip())
    upstream = urllib.request.urlopen(req, timeout=60)

    def body():
        try:
            while True:
                chunk = upstream.read(262144)
                if not chunk:
                    break
                yield chunk
        finally:
            upstream.close()

    headers = {"Content-Disposition": f'attachment; filename="{file}"'}
    length = upstream.headers.get("Content-Length")
    if length:
        headers["Content-Length"] = length
    return StreamingResponse(body(), media_type="application/vnd.android.package-archive",
                             headers=headers)
