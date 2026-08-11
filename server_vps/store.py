"""
SQLite storage + Ed25519 token signing for the activation service.

Token format is IDENTICAL to what app/activation.py verifies:
    base64url(compact-json payload) + "." + base64url(ed25519 signature)
    payload = {rid, mid, vin, make, model, iat, nonce, tag:"activation"}
The signing private key is a PKCS8 (base64) value from env — it never leaves the VPS.
"""
from __future__ import annotations
import base64
import json
import os
import secrets
import sqlite3
import threading
import time

from cryptography.hazmat.primitives.serialization import load_der_private_key

_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no I/L/O/0/1
_lock = threading.Lock()


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


class Store:
    def __init__(self, db_path: str, signing_key_pkcs8_b64: str):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS requests(
                 rid TEXT PRIMARY KEY, code TEXT, mid TEXT, vin TEXT,
                 make TEXT, model TEXT, status TEXT, token TEXT,
                 delivered INTEGER DEFAULT 0, created INTEGER, approved_at INTEGER)"""
        )
        self.db.commit()
        if not signing_key_pkcs8_b64:
            raise RuntimeError("SIGNING_KEY_PKCS8 not set")
        self._priv = load_der_private_key(base64.b64decode(signing_key_pkcs8_b64), password=None)

    # ---- signing ---------------------------------------------------------- #
    def _sign(self, payload: dict) -> str:
        pb = json.dumps(payload, separators=(",", ":")).encode()
        return _b64url(pb) + "." + _b64url(self._priv.sign(pb))

    # ---- requests --------------------------------------------------------- #
    def create(self, mid: str, vin: str, make: str, model: str) -> dict:
        rid = secrets.token_hex(16)
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        rec = dict(rid=rid, code=code, mid=mid, vin=vin.upper(), make=make,
                   model=model, status="pending", token=None, delivered=0,
                   created=int(time.time()), approved_at=None)
        with _lock:
            self.db.execute(
                "INSERT INTO requests(rid,code,mid,vin,make,model,status,created) "
                "VALUES(?,?,?,?,?,?, 'pending', ?)",
                (rid, code, rec["mid"], rec["vin"], make, model, rec["created"]))
            self.db.commit()
        return rec

    def get(self, rid: str) -> dict | None:
        r = self.db.execute("SELECT * FROM requests WHERE rid=?", (rid,)).fetchone()
        return dict(r) if r else None

    def pending(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM requests WHERE status='pending' ORDER BY created").fetchall()
        return [dict(r) for r in rows]

    def approve(self, rid: str) -> dict | None:
        with _lock:
            r = self.db.execute("SELECT * FROM requests WHERE rid=?", (rid,)).fetchone()
            if not r:
                return None
            rec = dict(r)
            if rec["status"] == "approved":
                return rec
            payload = {"rid": rec["rid"], "mid": rec["mid"], "vin": rec["vin"],
                       "make": rec["make"], "model": rec["model"],
                       "iat": int(time.time()),
                       "nonce": _b64url(secrets.token_bytes(12)), "tag": "activation"}
            token = self._sign(payload)
            self.db.execute(
                "UPDATE requests SET status='approved', token=?, delivered=0, approved_at=? "
                "WHERE rid=?", (token, int(time.time()), rid))
            self.db.commit()
            rec.update(status="approved", token=token)
            return rec

    def reject(self, rid: str) -> bool:
        with _lock:
            cur = self.db.execute(
                "UPDATE requests SET status='rejected' WHERE rid=?", (rid,))
            self.db.commit()
            return cur.rowcount > 0

    def deliver_once(self, rid: str) -> tuple[str, str | None]:
        """Return (status, token). Token is returned only the first time."""
        with _lock:
            r = self.db.execute("SELECT * FROM requests WHERE rid=?", (rid,)).fetchone()
            if not r:
                return ("unknown", None)
            rec = dict(r)
            if rec["status"] == "approved" and not rec["delivered"]:
                self.db.execute("UPDATE requests SET delivered=1 WHERE rid=?", (rid,))
                self.db.commit()
                return ("approved", rec["token"])
            return (rec["status"], None)
