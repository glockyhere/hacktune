"""Fake relay for testing the web client's WebSocket transport WITHOUT a car.

Reproduces the failure that stopped a real install at 7%: the bridge closes
mid-session and the page must report it, not freeze. Behaviour is chosen by the
connect path.

    /drop-after/<n>   accept, then hard-drop the TCP socket after n messages
                      (the browser sees close code 1006 — a Wi-Fi drop)
    /close/<code>     accept, then close cleanly with that code (relay's own
                      4001 / 4004 / 4005 all take this path)
    /silent           accept and never say anything again (a hung car)
    /echo             echo every message back forever (healthy link)

    python webapp/scripts/fake-relay.py [port]
"""
import asyncio
import sys

import websockets

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8799


async def handler(ws, legacy_path=None):
    # Works on both websockets APIs so this test runs anywhere. relay.py itself
    # deliberately requires >=14 rather than straddling both.
    path = legacy_path or getattr(getattr(ws, "request", None), "path", None) or ws.path
    print(f"  connection: {path}", flush=True)

    if path.startswith("/drop-after/"):
        n = int(path.rsplit("/", 1)[1])
        seen = 0
        async for _ in ws:
            seen += 1
            if seen >= n:
                print(f"  dropping the socket after {seen} messages", flush=True)
                # No close frame: the peer sees 1006, exactly like a Wi-Fi drop.
                tr = getattr(ws, "transport", None) or ws.protocol.transport
                tr.abort()
                return
        return

    if path.startswith("/close/"):
        code = int(path.rsplit("/", 1)[1])
        await asyncio.sleep(0.2)
        print(f"  closing with code {code}", flush=True)
        await ws.close(code=code, reason="test")
        return

    if path.startswith("/silent"):
        await asyncio.Future()

    async for msg in ws:                       # /echo
        await ws.send(msg)


async def main():
    async with websockets.serve(handler, "127.0.0.1", PORT,
                                compression=None, max_size=None):
        print(f"fake relay on ws://127.0.0.1:{PORT}", flush=True)
        await asyncio.Future()


asyncio.run(main())
