"""
Local wireless relay for the FAW B70 (Android 9, Wireless ADB).

A browser cannot open a raw TCP socket to the head unit's adb port, so the web
page cannot reach a wireless car on its own. This tiny agent bridges a localhost
WebSocket to the unit's TCP :5555, carrying the raw ADB protocol both ways.
ya-webadb in the page runs over that WebSocket exactly as it would over USB.

USB cars (Dongfeng MAGE) do NOT need this — the page talks to them via WebUSB.

Security posture
----------------
* Binds 127.0.0.1 ONLY. Nothing off the machine can reach it.
* Requires a per-session `token` (the same one-time activation token the buyer
  already holds). The agent asks the backend whether that token is valid before
  opening any bridge, so a random web page the buyer happens to visit cannot
  drive their car.
* Carries bytes only. It holds no recipe, no payload, no signing key.

Run:
    python relay.py --api https://api.example.com [--target 192.168.1.50:5555]

If --target is omitted, the unit is discovered with `adb mdns services`.

Requires:  pip install websockets   (and adb on PATH for discovery)
"""
from __future__ import annotations
import argparse
import asyncio
import json
import re
import subprocess
import urllib.request
from urllib.parse import urlparse, parse_qs

import websockets

HOST = "127.0.0.1"
PORT = 8765


def verify_token(api: str, token: str) -> bool:
    try:
        req = urllib.request.Request(
            api.rstrip("/") + "/api/verify",
            data=json.dumps({"token": token}).encode(),
            headers={"content-type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return bool(json.loads(r.read()).get("ok"))
    except Exception:
        return False


def discover_target() -> str | None:
    try:
        cp = subprocess.run(["adb", "mdns", "services"],
                            capture_output=True, text=True, timeout=15)
        m = re.search(r"(\d+\.\d+\.\d+\.\d+:\d+)", cp.stdout)
        return m.group(1) if m else None
    except Exception:
        return None


async def bridge(ws, tcp_reader, tcp_writer):
    async def ws_to_tcp():
        async for msg in ws:
            if isinstance(msg, str):
                msg = msg.encode()
            tcp_writer.write(msg)
            await tcp_writer.drain()
        tcp_writer.close()

    async def tcp_to_ws():
        try:
            while True:
                data = await tcp_reader.read(65536)
                if not data:
                    break
                await ws.send(data)
        finally:
            await ws.close()

    await asyncio.gather(ws_to_tcp(), tcp_to_ws(), return_exceptions=True)


def make_handler(api: str, default_target: str | None):
    async def handler(ws):
        q = parse_qs(urlparse(ws.request.path).query)
        token = (q.get("token") or [""])[0]
        if not token or not verify_token(api, token):
            await ws.close(code=4001, reason="unauthorized")
            print("  ✗ rejected a connection with no/invalid token")
            return

        target = (q.get("target") or [default_target or ""])[0] or discover_target()
        if not target:
            await ws.close(code=4004, reason="no head unit found")
            print("  ✗ no target head unit (pass --target or connect Wireless ADB)")
            return

        ip, _, port = target.partition(":")
        print(f"  · bridging browser ⇄ {ip}:{port or 5555}")
        try:
            reader, writer = await asyncio.open_connection(ip, int(port or 5555))
        except Exception as e:
            await ws.close(code=4005, reason="cannot reach head unit")
            print(f"  ✗ cannot connect to {target}: {e}")
            return
        await bridge(ws, reader, writer)
        print("  · bridge closed")
    return handler


async def main() -> None:
    ap = argparse.ArgumentParser(description="CarApk wireless ADB relay (localhost only)")
    ap.add_argument("--api", required=True, help="activation backend base URL")
    ap.add_argument("--target", default=None, help="head unit ip:port (default: mDNS)")
    a = ap.parse_args()

    print(f"CarApk relay on ws://{HOST}:{PORT}  (backend: {a.api})")
    print("Leave this window open during the install. Ctrl-C to stop.")
    async with websockets.serve(make_handler(a.api, a.target), HOST, PORT):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
