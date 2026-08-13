# Web client — architecture and what "hidden" actually means

There are now two front-ends over the same backend:

- **Desktop** (`app/`, tkinter → an .exe) — the original.
- **Web** (`webapp/`, static page + a tiny local agent for wireless) — this doc.

Both end at the same activation backend (`server_vps/`) and the same head units.

## Read this first: the honest security boundary

You cannot hide code that runs in a browser. Devtools shows every byte of a web
page; a PyInstaller .exe unpacks in a minute. So "nobody can see how it works"
is **not** achievable and is not what protects you.

What *is* achievable, and what this design does: **put nothing worth stealing in
the client.** The web page is a generic ADB op-runner. It learns what to do only
after a paid, approved session, and only in memory:

| Secret | Where it lives | In the client? |
|---|---|---|
| Ed25519 signing key (mints tokens) | VPS env only | never |
| The recipe (unlock, install order, launcher DB rows) | `server_vps/plan.py` | only the ops for one approved session, in RAM |
| Payload APKs | private origin behind the VPS | fetched via expiring signed URLs |
| Payload URLs | minted per session, ~15 min TTL | only during that session |

Reverse-engineer the page and you get an executor that can run *some* ADB
commands — but not the sequence, not the files, not a way to mint a token. The
value moved to the server. That is the real thing behind "it just works and
nothing is exposed": the client is disposable.

### What an approved buyer can still do

Once someone pays and is approved, the APKs and the op list reach their browser —
they must, to install. A determined buyer can capture that one session. This is
unavoidable for any installer, native or web. The goal is to raise the cost from
"share a public URL" (which is where the project was — see below) to
"reverse-engineer a live, time-boxed, approved session." That is a large jump.

### The hole this closes

Before this, the payload sat on a **public** bucket: an anonymous
`HEAD https://pub-….r2.dev/03_wifishortcut.apk` returned `200`. Anyone with the
URL downloaded all the APKs for free; the paywall sold convenience, not access.
The signed-URL flow below makes the bucket private and gates every download.

## The flow

```
Browser (webapp/, hosted — holds no recipe, no payload, no key)
  │  POST /api/request        VIN + make + model + browser machine-id
  │  GET  /api/status         poll until approved → one-time Ed25519 token
  │  ── connect to the car (WebUSB or local relay) ──
  │  POST /api/plan  {token, profile}    ← server verifies token, returns ops
  │                                         with short-lived signed /dl URLs
  │  for each op: run it over ADB
  │      install ops: GET /dl/<file>?…sig…  (SHA-256 checked in-browser)
  │  POST /api/consume {token}            ← burn the token when done
  ▼
VPS: server_vps/  (FastAPI)
  /api/plan     verify_token() → build_plan() with signed URLs   (plan.py)
  /dl/<file>    verify signed URL → stream from PRIVATE origin
  /api/verify   cheap token check for the relay
```

Endpoints added to `server_vps/main.py`: `/api/plan`, `/dl/{file}`,
`/api/verify`, `/api/consume`. The token contract is unchanged, so the desktop
app and the Telegram approval flow keep working as-is.

## Reaching the car from a browser

A browser cannot open a raw TCP socket, so it cannot talk to a wireless unit's
`:5555` directly ([Direct Sockets is Isolated-Web-App only](https://developer.chrome.com/docs/iwa/direct-sockets)).
The two cars split cleanly:

| Car | Link | How the page reaches ADB | Buyer installs? |
|---|---|---|---|
| **Dongfeng MAGE** | USB | **WebUSB** via [ya-webadb](https://github.com/yume-chan/ya-webadb), straight from Chrome | nothing |
| **FAW B70** | wireless | **local relay** (`agent/relay.py`) bridging a localhost WebSocket to `:5555`; ya-webadb runs over it | the relay |

So the MAGE is the "pure web, nothing installed" case. The B70 still needs one
small local process, because no browser can raw-TCP to it — that is a browser
security rule, not a gap in this design.

### The relay is not a back door

`agent/relay.py` binds `127.0.0.1` only, carries bytes only (no recipe, no key),
and refuses to bridge until the backend confirms the session token
(`/api/verify`). That stops a random site the buyer visits from driving their
car over the localhost socket.

## Build & host

```bash
# web client (static — host the built files anywhere, or same-origin with the API)
cd webapp
npm install
npm run build         # -> webapp/dist/, deploy it

# wireless relay (only buyers with a FAW B70 run this)
cd agent
pip install websockets
python relay.py --api https://api.<your-host>
```

Backend env to add for downloads (see `server_vps/main.py`):

```
DOWNLOAD_HMAC_KEY   random secret; signs /dl URLs
PAYLOAD_ORIGIN      PRIVATE base URL the VPS streams APKs from (NOT the public bucket)
DOWNLOAD_TTL        signed-URL lifetime in seconds (default 900)
```

Make the R2 bucket private and point `PAYLOAD_ORIGIN` at it (or at any origin only
the VPS can reach). For scale, swap the stream-through in `/dl` for an R2/S3
pre-signed redirect — same gate, less VPS bandwidth.

## Keep the two recipes in sync

The recipe exists twice on purpose: `app/profiles.py` (desktop) and
`server_vps/plan.py` (web, so the browser carries none of it). They must agree on
payload hashes and install flags. Before shipping either side:

```bash
python check_recipe.py      # fails loudly on drift
```

## Verified / not

- **Backend gate** — unit-tested: valid token → plan; tampered/expired/rejected/
  consumed → refused; signed URLs reject every tamper (`check_recipe.py` plus the
  inline tests run during development).
- **Recipe parity** — enforced by `check_recipe.py`.
- **Not yet exercised on a car:** the ADB transport (WebUSB and the relay). That
  needs `npm install` (ya-webadb) and a real unit. `webapp/transport.js` is
  written against ya-webadb's API and is the one seam to validate on hardware.
- **`adb root` over WebUSB:** we cannot restart adbd to root from the browser.
  The MAGE boots adbd already root, so the `root` op just verifies `id -u == 0`
  and fails clearly if not. Confirm on the unit.
