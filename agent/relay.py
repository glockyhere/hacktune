"""
Axolotl relay — lets the website reach a wireless head unit (FAW B70).

WHY THIS EXISTS
---------------
A browser cannot open a raw TCP socket, so a web page cannot reach a head unit
that is only on Wi-Fi. This bridges a localhost WebSocket to the unit's TCP
:5555 and carries the raw ADB protocol both ways; ya-webadb in the page then
runs over it exactly as it would over USB.

USB cars (Dongfeng MAGE) do NOT need this — the page reaches them with WebUSB.

BUILT FOR NON-TECHNICAL USERS
-----------------------------
The buyer double-clicks one file. No arguments, no Python, no adb, nothing to
configure. It finds the car by scanning the local network for an open ADB port,
prints plain-language status, and stays open so a mistake can be read rather
than flashing past. Anything that can be recovered from is explained in the
window instead of raising a traceback.

Security posture (unchanged)
----------------------------
* Binds 127.0.0.1 ONLY. Nothing off this machine can reach it, and binding to
  localhost also avoids a Windows Firewall prompt.
* Requires the buyer's one-time activation token, checked against the backend
  before any bridge opens, so a random page they happen to visit cannot drive
  their car over the localhost socket.
* Carries bytes only: no recipe, no payload, no signing key.

Developer usage (the buyer never types this):
    python relay.py [--api https://api.axolotl.uz] [--target 192.168.1.50:5555]
"""
from __future__ import annotations
import argparse
import asyncio
import json
import re
import socket
import subprocess
import sys
import urllib.request
from urllib.parse import urlparse, parse_qs

try:
    import websockets
except ImportError:
    print("The 'websockets' package is missing.  pip install websockets")
    input("\nPress Enter to close…")
    raise SystemExit(1)

HOST = "127.0.0.1"
PORT = 8765
ADB_PORT = 5555
DEFAULT_API = "https://api.axolotl.uz"


# --------------------------------------------------------------------------- #
#  Talking to the buyer
# --------------------------------------------------------------------------- #
def say(msg: str = "") -> None:
    print(msg, flush=True)


def hold(msg: str) -> None:
    """Report something fatal, then WAIT. A window that vanishes teaches nothing."""
    say()
    say("  " + msg)
    say()
    try:
        input("  Press Enter to close this window…")
    except (EOFError, KeyboardInterrupt):
        pass
    raise SystemExit(1)


# --------------------------------------------------------------------------- #
#  Finding the car, without requiring adb
# --------------------------------------------------------------------------- #
def local_prefixes() -> list[str]:
    """The /24s this machine sits on, best-effort and without extra packages."""
    out: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))          # no traffic; just picks the route
        ip = s.getsockname()[0]
        s.close()
        out.append(ip.rsplit(".", 1)[0])
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            pre = info[4][0].rsplit(".", 1)[0]
            if not pre.startswith("127.") and pre not in out:
                out.append(pre)
    except Exception:
        pass
    return out


async def _open(ip: str, port: int, timeout: float) -> str | None:
    try:
        fut = asyncio.open_connection(ip, port)
        reader, writer = await asyncio.wait_for(fut, timeout)
        writer.close()
        return f"{ip}:{port}"
    except Exception:
        return None


async def scan_for_unit() -> str | None:
    """Sweep the local /24s for an open ADB port. Takes a couple of seconds."""
    for prefix in local_prefixes():
        say(f"  · looking for the car on {prefix}.0/24 …")
        hosts = [f"{prefix}.{n}" for n in range(1, 255)]
        found = [r for r in await asyncio.gather(
            *(_open(h, ADB_PORT, 0.6) for h in hosts)) if r]
        if found:
            return found[0]
    return None


def discover_via_adb() -> str | None:
    """If adb happens to be installed, let it answer first — it is faster."""
    try:
        cp = subprocess.run(["adb", "mdns", "services"],
                            capture_output=True, text=True, timeout=10)
        m = re.search(r"(\d+\.\d+\.\d+\.\d+:\d+)", cp.stdout)
        return m.group(1) if m else None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
#  Backend check + the bridge itself
# --------------------------------------------------------------------------- #
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


def make_handler(api: str, target_box: dict):
    async def handler(ws):
        q = parse_qs(urlparse(ws.request.path).query)
        token = (q.get("token") or [""])[0]
        if not token or not verify_token(api, token):
            await ws.close(code=4001, reason="unauthorized")
            say("  ✗ a page tried to connect without a valid activation. Ignored.")
            return

        target = (q.get("target") or [""])[0] or target_box.get("target")
        if not target:
            target = discover_via_adb() or await scan_for_unit()
            target_box["target"] = target
        if not target:
            await ws.close(code=4004, reason="no head unit found")
            say("  ✗ Could not find the car on this network.")
            say("    Check that the car and this computer are on the SAME Wi-Fi,")
            say("    and that Wireless ADB is switched on in the car.")
            return

        ip, _, port = target.partition(":")
        say(f"  · connected to the car at {ip} — installing…")
        try:
            reader, writer = await asyncio.open_connection(ip, int(port or ADB_PORT))
        except Exception as e:
            target_box["target"] = None          # force a re-scan next attempt
            await ws.close(code=4005, reason="cannot reach head unit")
            say(f"  ✗ Lost the car at {ip}: {e}")
            say("    Its address may have changed. Press Connect again.")
            return
        await bridge(ws, reader, writer)
        say("  · finished with the car. You can close this window when the")
        say("    website says the install is complete.")
    return handler


async def main() -> None:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--api", default=DEFAULT_API)
    ap.add_argument("--target", default=None)
    ap.add_argument("-h", "--help", action="store_true")
    a, _ = ap.parse_known_args()
    if a.help:
        say(__doc__)
        return

    say("=" * 62)
    say("  Axolotl — car connection helper")
    say("=" * 62)
    say()
    say("  Keep this window open while the website installs the apps.")
    say()

    target = a.target
    if not target:
        target = discover_via_adb()
        if not target:
            target = await scan_for_unit()

    if target:
        say(f"  ✓ Found your car at {target.split(':')[0]}")
    else:
        say("  ! Could not find the car yet. That is usually one of:")
        say("      · Wireless ADB is not switched on in the car")
        say("      · the car and this computer are on different Wi-Fi networks")
        say("    It will look again when you press Connect on the website.")
    say()
    say("  ✓ Ready. Go back to the website and press Connect.")
    say()

    try:
        async with websockets.serve(make_handler(a.api, {"target": target}), HOST, PORT):
            await asyncio.Future()
    except OSError as e:
        if getattr(e, "errno", None) in (48, 98, 10048):   # address already in use
            hold("This helper is already running in another window. "
                 "Use that one, or close it and start this again.")
        hold(f"Could not start: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        say("\n  Stopped.")
    except Exception as e:                        # never show a traceback to a buyer
        hold(f"Something went wrong: {e}")
