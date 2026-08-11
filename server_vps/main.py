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

from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse

from store import Store
from telegram import Bot

DB_PATH = os.environ.get("DB_PATH", "/var/lib/carapk/activations.db")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

store = Store(DB_PATH, os.environ.get("SIGNING_KEY_PKCS8", ""))
bot = Bot(TG_BOT_TOKEN, TG_CHAT_ID, store) if (TG_BOT_TOKEN and TG_CHAT_ID) else None

app = FastAPI()


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
