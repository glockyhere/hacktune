# CLAUDE.md — project context & handoff

Read this first. It orients you (a fresh Claude, likely on Windows) on what this
project is, what's already done and *verified live*, and what's left. The next
work is **GUI polish + minor details** — see "TODO" at the bottom.

## What this is
`CarApkInstaller` — a paywalled Windows program that provisions a specific
ECARX/FAW **car head unit** (Android 9 / API 28, ARM) over **Wireless ADB**. One
button installs a fixed set of apps and enables everything they need. Each install
is a **pay → seller approves → one-time activation** session.

The head unit only accepts apps signed with the **AOSP platform key** (its
`apkauth` whitelist). All payload APKs are pre-signed with that key (and Yandex
Navi is pre-patched to survive re-signing), so the program just `adb install`s
them — no signing at runtime.

## Architecture (3 pieces, all built)
1. **Desktop app** (`app/`, Python + tkinter) — the product buyers run.
2. **Cloud payload** — the 5 APKs live on **Cloudflare R2** (not in the repo, not
   in the exe). The app downloads them each run and checks a **pinned SHA-256**.
3. **Activation backend** (`server_vps/`, FastAPI + SQLite + Telegram bot) — runs
   on the seller's VPS. Buyer requests → seller approves in Telegram → backend
   signs a **one-time Ed25519 token** bound to the car's VIN + the buyer's machine
   → app verifies with an embedded public key. (A Cloudflare Worker equivalent is
   in `server/` as an alternative; the VPS one is the chosen path.)

## Current status — LIVE and verified (do NOT redo)
- **Activation backend is deployed** at `https://api.89.117.48.15.nip.io`
  (Caddy + Let's Encrypt, Telegram bot `@plexilotlbot`). `config.py` is wired to
  it with the real `ACTIVATION_PUBLIC_KEY`.
- **Full loop certified live:** request → Telegram approve → one-time token →
  `activation.verify_token` == True; single-use enforced; wrong-VIN/other-machine
  rejected. Proven by scripted test on 2026-08-11.
- **R2 payload verified:** all 5 APKs download and match their pinned SHA-256
  (`python verify_cloud.py`).
- **On-device install proven manually** (each `adb install` / permission / launcher
  step succeeded on the real unit). NOT yet replayed *through the exe* end-to-end
  because the car has been offline — that's the only uncertified last mile.

## Repo layout
```
app/
  config.py      ← seller edits: card, contacts, price, ACTIVATION_URL/KEY, R2 URL
  gui.py         ← tkinter UI (request → wait-for-approval → installer). MAIN GUI FILE.
  activation.py  ← activation client (submit/poll/verify one-time token)
  provision.py   ← the fixed install flow + post-steps (STEPS list + sha256 pins)
  engine.py      ← adb: device detect, Wi-Fi/mDNS reconnect, install
  download.py    ← cloud downloader with SHA-256 verify
  licensing.py   ← machine_id() (used by activation) + old offline-license verify (legacy)
keygen/          ← SELLER-ONLY tools. generate_activation_keys.py makes the signing
                   keypair (private → VPS secret; public → config.py). NEVER commit keys.
server_vps/      ← the deployed backend (store.py, telegram.py, main.py, systemd, Caddy)
server/          ← Cloudflare Worker alternative (not used; kept for reference)
payload/         ← UPLOAD.md only; the *.apk are gitignored and live on R2
tools/           ← fetch_tools.ps1 downloads adb; adb itself is gitignored
build/           ← PyInstaller spec
docs/            ← CLOUD_R2.md, ACTIVATION_VPS.md (deploy guides), ACTIVATION.md (Worker)
verify_cloud.py  ← checks R2 serves every APK with the right hash
main.py, build.bat, requirements.txt, README.md
```

## Build / run / test (Windows)
```bat
:: one-time tooling
powershell -ExecutionPolicy Bypass -File tools\fetch_tools.ps1   :: gets adb into tools\
python -m pip install -r requirements.txt                        :: cryptography, pyinstaller

:: run in dev (fast GUI iteration — no build needed)
python main.py

:: build the shippable exe
build.bat            :: -> dist\CarApkInstaller.exe  (+ dist\tools\)
```
- **GUI dev without a car:** `python main.py` opens on the activation *request*
  screen. Activation calls hit the LIVE backend, so you can drive the real
  request→approve→installer flow (approve via the seller's Telegram). The installer
  screen's "Detect" will just say "not connected" with no unit — fine for UI work.
- **verify the cloud** anytime: `python verify_cloud.py`.

## Hard rules / gotchas (don't break these)
- **Token format is a cross-language contract.** The app verifies
  `base64url(compact-json payload) + "." + base64url(ed25519 sig)` with payload
  keys `{rid,mid,vin,make,model,iat,nonce,tag:"activation"}`. `server_vps/store.py`
  and the app must stay byte-compatible. If you touch either, re-run the interop
  test (see git history / the console tests) before shipping.
- **Never commit secrets or binaries.** `.gitignore` blocks `*.apk`,
  `keygen/license_private.key`, `server_vps/*.env`, `*.db`. Keep it that way.
- **Payload hashes are pinned** in `provision.py` (`STEPS[*].sha256`). If an APK is
  ever re-built, re-upload to R2 AND update the pin, or the app will (correctly)
  reject it.
- **Wireless ADB IP changes** on the unit between sessions; `engine.ensure_device`
  already re-discovers via `adb mdns services`. Keep that behavior.
- **One uvicorn worker only** on the VPS (single process owns the Telegram poller +
  SQLite). Don't add workers.
- **nip.io is temporary DNS.** Before real sales, move to the seller's own domain
  (update Caddyfile host + `ACTIVATION_API_URL`, rebuild). Noted for the seller.
- **Config still has placeholders** the seller must fill: `PAYMENT`/`CONTACTS`/
  `PRICE_TEXT` in `config.py`. `ACTIVATION_*` and `APK_BASE_URL` are already real.
- **Legal:** the payload includes modified third-party apps (signature-patched
  Yandex Navi, modified FAW launcher, re-signed FreeTube). Redistribution is the
  seller's responsibility; don't expand that surface without flagging it.

## TODO — GUI & minor details (the next work)
GUI lives in `app/gui.py`. Style tokens (colors/fonts) are at the top. Suggested:
- [ ] **Log box needs a scrollbar** (the installer `Text` has none) and should
      auto-grow with the window; test long logs.
- [ ] **Add an app icon** — create `resources/app.ico`; the spec already wires it
      if present. Also set a window icon at runtime.
- [ ] **Copy button for Machine ID** on the request screen (wait screen already
      has a copy for the code).
- [ ] **Russian/Uzbek UI** — the market is RU/UZ; consider localizing labels (the
      head unit UI is Russian). At least the buyer-facing strings.
- [ ] **Window centering + slightly larger default**; make screens scale cleanly.
- [ ] **Nicer states:** spinner/progress during download+install instead of only
      text; disable inputs while a request is in flight (partly done).
- [ ] **VIN validation** is basic (11–17 alnum). Consider a proper VIN check
      (17 chars, no I/O/Q) with a soft warning rather than hard block.
- [ ] **Legacy cleanup (optional):** the offline-license path in `licensing.py`
      (`verify_license`, `save/load_license`) and `keygen/generate_keys.py` /
      `issue_license.py` are superseded by activation. `machine_id()` is still used.
      Leave `machine_id`, consider removing the rest to avoid confusion.
- [ ] **Persist the approved session** so closing the app mid-install doesn't force
      a new approval (store token + rid; re-open goes back to installer until the
      install is marked consumed). `activation.mark_consumed`/`is_consumed` exist.
- [ ] **Certify the last mile:** when a head unit is available, run the whole flow
      through the built exe once (request→approve→download→install) and note it here.

## Handy references
- Deploy the backend: `docs/ACTIVATION_VPS.md`
- Host/refresh the payload: `docs/CLOUD_R2.md`, `payload/UPLOAD.md`
- Seller keypair: `python keygen/generate_activation_keys.py`
