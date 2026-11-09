"""
Remote control for the owner's OWN head unit.

The car reaches this VPS through an frp reverse tunnel (see /etc/frp/frps.toml):
its adbd is published on the VPS loopback at 127.0.0.1:5555 and nowhere else.
These endpoints shell out to adb against that loopback port, so the browser never
touches adb directly and the car's port is never world-exposed.

adb on a head unit is effectively root, so every endpoint is gated by one shared
passphrase (CAR_TOKEN), compared in constant time. No passphrase, no call. The
passphrase rides in the X-Car-Key header, or in ?key= for the screenshot <img>
(an element that cannot set headers). There is no cookie or session.

Config (environment, /etc/carapk/activation.env):
  CAR_TOKEN   the passphrase the panel must present (blank => every call 401s)
  CAR_ADB     adb target, default 127.0.0.1:5555
  ADB_BIN     adb path, default "adb"
"""
from __future__ import annotations

import hmac
import os
import re
import subprocess

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import Response

CAR_TOKEN = os.environ.get("CAR_TOKEN", "")
CAR_ADB = os.environ.get("CAR_ADB", "127.0.0.1:5555")
ADB = os.environ.get("ADB_BIN", "adb")

router = APIRouter(prefix="/api/car")

# A package name and nothing else: this is the one piece of caller input that
# becomes an adb argument rather than going to the device shell verbatim.
PKG_RE = re.compile(r"[A-Za-z0-9._]{1,128}")


def _auth(key: str | None) -> None:
    if not CAR_TOKEN or not key or not hmac.compare_digest(key, CAR_TOKEN):
        raise HTTPException(status_code=401, detail="wrong or missing passphrase")


def _run(args: list[str], timeout: int = 30) -> tuple[int, bytes, bytes]:
    try:
        p = subprocess.run([ADB, *args], capture_output=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, b"", b"the car did not answer in time"
    except FileNotFoundError:
        return 127, b"", b"adb is not installed on the server"


def _adb(args: list[str], timeout: int = 30) -> tuple[int, bytes, bytes]:
    return _run(["-s", CAR_ADB, *args], timeout=timeout)


def _connect() -> None:
    # adb's own server caches the connection; this is a cheap no-op once linked.
    _run(["connect", CAR_ADB], timeout=15)


def _state() -> str:
    rc, out, err = _run(["-s", CAR_ADB, "get-state"], timeout=15)
    return (out or err).decode(errors="replace").strip() or "unknown"


def _text(b: bytes) -> str:
    return b.decode(errors="replace")


def _apps() -> list[str]:
    rc, out, _ = _adb(["shell", "pm", "list", "packages", "-3"], timeout=25)
    if rc != 0:
        return []
    return sorted(
        line[len("package:"):].strip()
        for line in _text(out).splitlines()
        if line.startswith("package:")
    )


@router.post("/status")
def status(x_car_key: str | None = Header(default=None)):
    _auth(x_car_key)
    _connect()
    st = _state()
    online = st == "device"
    info: dict = {"online": online, "state": st, "target": CAR_ADB}
    if not online:
        return info
    rc, out, _ = _adb([
        "shell",
        "echo S:$(getprop ro.serialno);"
        "echo M:$(getprop ro.product.model);"
        "echo B:$(getprop ro.product.brand);"
        "echo A:$(getprop ro.build.version.release);"
        "echo U:$(cut -d. -f1 /proc/uptime 2>/dev/null);"
        "echo P:$(dumpsys battery 2>/dev/null | sed -n 's/.*level: //p');"
        "echo T:$(date +%H:%M:%S)",
    ], timeout=25)
    field = {"S": "serial", "M": "model", "B": "brand", "A": "android",
             "U": "uptime_s", "P": "battery", "T": "clock"}
    for line in _text(out).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            if k in field and v.strip():
                info[field[k]] = v.strip()
    info["apps"] = _apps()
    return info


@router.get("/screen")
def screen(key: str = ""):
    _auth(key)
    _connect()
    rc, out, err = _adb(["exec-out", "screencap", "-p"], timeout=30)
    if rc != 0 or not out:
        raise HTTPException(status_code=503, detail=_text(err) or "no screen")
    return Response(content=out, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@router.post("/shell")
def shell(body: dict = Body(...), x_car_key: str | None = Header(default=None)):
    _auth(x_car_key)
    cmd = str(body.get("cmd", "")).strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="empty command")
    _connect()
    rc, out, err = _adb(["shell", cmd], timeout=45)
    # The command string is handed to the DEVICE shell as one argument, never to
    # the VPS shell, so there is nothing to inject on this side.
    return {"code": rc, "out": (_text(out) + _text(err))[-40000:]}


@router.post("/launch")
def launch(body: dict = Body(...), x_car_key: str | None = Header(default=None)):
    _auth(x_car_key)
    pkg = str(body.get("pkg", "")).strip()
    if not PKG_RE.fullmatch(pkg):
        raise HTTPException(status_code=400, detail="not a package name")
    _connect()
    rc, out, err = _adb(["shell", "monkey", "-p", pkg, "-c",
                         "android.intent.category.LAUNCHER", "1"], timeout=25)
    return {"ok": rc == 0, "out": (_text(out) + _text(err)).strip()}


@router.post("/reboot")
def reboot(x_car_key: str | None = Header(default=None)):
    _auth(x_car_key)
    _connect()
    # Fire and forget: the device drops the link as it goes down, so waiting
    # would only ever time out.
    try:
        subprocess.Popen([ADB, "-s", CAR_ADB, "reboot"])
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="adb is not installed")
    return {"ok": True}
