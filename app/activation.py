"""
Client for the activation backend. One paid, seller-approved request == one install.

Flow used by the GUI:
  submit_request(vin, make, model) -> (rid, code)     # POST /api/request
  poll_status(rid)                 -> (state, token)  # GET  /api/status
  verify_token(token, vin)         -> ActivationResult # local Ed25519 check + bind

The token is signed by YOUR Worker's private key; the app only holds the public
key, so it can verify but never mint. Single-use is enforced by the server.
"""
from __future__ import annotations
import base64
import json
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import config, licensing


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _api(path: str) -> str:
    base = config.ACTIVATION_API_URL.strip().rstrip("/")
    return base + path


def _post(path: str, body: dict, timeout: int = 30) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(_api(path), data=data,
                                 headers={"content-type": "application/json",
                                          "User-Agent": "CarApkInstaller"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _get(path: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(_api(path), headers={"User-Agent": "CarApkInstaller"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def configured() -> bool:
    u = config.ACTIVATION_API_URL.strip()
    k = config.ACTIVATION_PUBLIC_KEY.strip()
    return bool(u) and "example.com" not in u and bool(k) and not k.startswith("PASTE_")


# --------------------------------------------------------------------------- #
def submit_request(vin: str, make: str, model: str) -> tuple[str, str]:
    """Create a pending request. Returns (rid, human code)."""
    r = _post("/api/request", {
        "mid": licensing.machine_id(),
        "vin": vin.strip().upper(), "make": make.strip(), "model": model.strip(),
    })
    return r["rid"], r.get("code", "")


def poll_status(rid: str) -> tuple[str, str | None]:
    """Return (status, token-or-None). status: pending|approved|rejected|unknown."""
    r = _get(f"/api/status?rid={urllib.parse.quote(rid)}")
    return r.get("status", "unknown"), r.get("token")


class ActivationResult:
    def __init__(self, ok: bool, reason: str = "", payload: dict | None = None):
        self.ok, self.reason, self.payload = ok, reason, payload or {}


def verify_token(token: str, vin: str) -> ActivationResult:
    """Verify the server-signed token, bound to THIS machine and the entered VIN."""
    pub_b64 = config.ACTIVATION_PUBLIC_KEY.strip()
    if not pub_b64 or pub_b64.startswith("PASTE_"):
        return ActivationResult(False, "App not configured with an activation public key.")
    try:
        pub = Ed25519PublicKey.from_public_bytes(_b64url_decode(pub_b64))
        payload_b64, sig_b64 = token.split(".", 1)
        payload_bytes = _b64url_decode(payload_b64)
        pub.verify(_b64url_decode(sig_b64), payload_bytes)
    except InvalidSignature:
        return ActivationResult(False, "Activation signature invalid.")
    except Exception:
        return ActivationResult(False, "Activation token malformed.")

    payload = json.loads(payload_bytes.decode())
    if payload.get("tag") != "activation":
        return ActivationResult(False, "Wrong token type.")
    if payload.get("mid") != licensing.machine_id():
        return ActivationResult(False, "Activation is bound to a different machine.")
    if payload.get("vin", "").upper() != vin.strip().upper():
        return ActivationResult(False, "Activation VIN does not match.")
    return ActivationResult(True, "Valid.", payload)


# ---- local record so a burned token can't re-run an install --------------- #
def _consumed_path() -> Path:
    return licensing._license_path().parent / "consumed.json"


def mark_consumed(rid: str) -> None:
    p = _consumed_path()
    try:
        data = json.loads(p.read_text()) if p.exists() else []
    except Exception:
        data = []
    if rid not in data:
        data.append(rid)
    p.write_text(json.dumps(data))


def is_consumed(rid: str) -> bool:
    p = _consumed_path()
    try:
        return p.exists() and rid in json.loads(p.read_text())
    except Exception:
        return False
