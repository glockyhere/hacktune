# CLAUDE.md — project context & handoff

Read this first. It orients you (a fresh Claude, likely on Windows) on what this
project is, what's already done and *verified live*, and what's left. The next
work is **GUI polish + minor details** — see "TODO" at the bottom.

## What this is
`CarApkInstaller` — a paywalled Windows program that provisions **car head units**
over **Wireless ADB**. One button installs a fixed set of apps and enables
everything they need. Each install is a **pay → seller approves → one-time
activation** session.

Two units are supported. The unit is auto-detected and the matching profile in
`app/profiles.py` drives the payload and all post-install work:

- **FAW B70 (ECARX)** — Android 9 / API 28. Only accepts apps signed with the
  **AOSP platform key** (its `apkauth` whitelist). All payload APKs are
  pre-signed with that key (and Yandex Navi is pre-patched to survive
  re-signing), so the program just `adb install`s them — no signing at runtime.
  The menu is handled by shipping a patched launcher.
- **Dongfeng Aeolus MAGE** — Android 11 / API 30. Completely different lock: the
  OEM PackageManager rejects foreign certs with `DF APK cert incorrect`, gated by
  the property `persist.apk.sign.verify`. The unit is userdebug with root adb, so
  the installer **clears the property instead of signing anything**. Its launcher
  renders a fixed list from a SQLite table, so installed apps stay invisible
  until the installer writes rows into `allApp`. Full details and the traps:
  **`docs/DONGFENG_MAGE.md` — read it before touching that profile.**

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
- **Dongfeng MAGE profile proven manually on a real unit (2026-08-13)**:
  property unlock → both APKs install → menu rows added → both tiles appear at
  native 120px size and launch; survives a launcher + SystemUI restart. Verified
  over **USB**, which is exactly how the MAGE is provisioned in the field (the
  B70 is the wireless one). Same last-mile gap: not yet replayed through the exe.

## Repo layout
```
app/
  config.py      ← seller edits: card, contacts, price, ACTIVATION_URL/KEY, R2 URL
  gui.py         ← tkinter UI (request → wait-for-approval → installer). MAIN GUI FILE.
  activation.py  ← activation client (submit/poll/verify one-time token)
  profiles.py    ← PER-CAR profiles: payload + unlock + post-steps + detection.
                   ADD NEW HEAD UNITS HERE, not in provision.py.
  provision.py   ← generic download→verify→install→post loop, driven by a profile
  engine.py      ← adb: device detect, Wi-Fi/mDNS reconnect, install
  download.py    ← cloud downloader with SHA-256 verify
  licensing.py   ← machine_id() (used by activation) + old offline-license verify (legacy)
keygen/          ← SELLER-ONLY tools. generate_activation_keys.py makes the signing
                   keypair (private → VPS secret; public → config.py). NEVER commit keys.
server_vps/      ← the deployed backend (store.py, telegram.py, main.py, systemd, Caddy)
                   plan.py = server-issued recipe + signed download URLs (web client)
server/          ← Cloudflare Worker alternative (not used; kept for reference)
webapp/          ← WEB client (thin, holds no recipe/payload/key). See docs/WEBAPP.md
                   Vite build: `npm ci && npm run build && npm run preflight`.
                   public/ is copied verbatim (config.js stays hand-editable
                   after deploy); transport.js is the only bare-specifier file
                   and lands in its own lazily-loaded chunk.
deploy/          ← production.env(.example) + configure.py: ONE file drives the
                   domain, cards, Caddyfile and VPS env. See docs/DEPLOY.md
agent/           ← relay.py: localhost WebSocket↔:5555 bridge for WIRELESS cars (B70)
payload/         ← UPLOAD.md only; the *.apk are gitignored and live on R2
                   01–05 = FAW B70;  df01–df02 = Dongfeng MAGE
tools/           ← fetch_tools.ps1 downloads adb; adb itself is gitignored
                   restyle_icon.py = rebuild MAGE-styled launcher icons
build/           ← PyInstaller spec
docs/            ← CLOUD_R2.md, ACTIVATION_VPS.md, ACTIVATION.md, DONGFENG_MAGE.md,
                   WEBAPP.md (web client architecture + honest security boundary)
verify_cloud.py  ← checks R2 serves every APK with the right hash
check_recipe.py  ← guards app/profiles.py vs server_vps/plan.py from drifting
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
- **Payload hashes are pinned** in `profiles.py` (`FAW_STEPS`/`DF_STEPS[*].sha256`).
  If an APK is ever re-built, re-upload to R2 AND update the pin, or the app will
  (correctly) reject it.
- **Never `am force-stop com.dftc.launcher`** on the Dongfeng. It desyncs
  SystemUI's CarStatusBar and kills the hardware app-menu button until SystemUI
  is restarted. Reload the menu by pulsing `show_launcher_test_app_key` instead —
  `profiles._df_finish` already does. Full explanation in `docs/DONGFENG_MAGE.md`.
- **Never re-sign Yandex Navi for the Dongfeng.** `com.yandex.passport` verifies
  its own signature and crash-loops with `application signature mismatch`. The
  MAGE payload ships it pristine. (The FAW copy is patched around this; reusing
  that patched build on a MAGE is an untested idea, noted in the doc.)
- **The recipe lives twice** now: `app/profiles.py` (desktop) and
  `server_vps/plan.py` (web — the browser must carry none of it). Run
  `python check_recipe.py` after editing either; it fails on hash/flag drift.
- **The web client must stay dumb.** Never hardcode packages, properties, the
  launcher DB layout, or payload URLs in `webapp/`. Those come from `/api/plan`
  per approved session. The whole security argument is "the client holds nothing
  worth stealing" — see `docs/WEBAPP.md`. Obscurity is NOT the protection.
- **Payload must be gated.** The web `/dl` flow assumes a PRIVATE origin
  (`PAYLOAD_ORIGIN`); the old public `pub-*.r2.dev` bucket lets anyone download
  the APKs free. Make the bucket private before selling.
- **Connection per car:** FAW B70 is **always Wireless ADB**; Dongfeng MAGE is
  **always a USB cable**. Each profile in `profiles.py` carries `connection` and
  `connect_hint`, and the GUI shows the right instruction once the car is known.
- **Wireless ADB IP changes** on the B70 between sessions; `engine.ensure_device`
  already re-discovers via `adb mdns services`. Keep that behavior.
- **`adb root` restarts adbd**, which would drop a wireless link (the B70). The
  MAGE unlock needs root but runs over USB, where the transport just
  re-enumerates. `profiles._df_ensure_root` still skips `adb root` when adbd is
  already root (it is, on the MAGE) and otherwise waits via `engine.reconnect()`,
  so it is safe either way — don't reintroduce a bare `adb root; wait-for-device`.
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
- [x] **Payload delivery is done for the WEB path** — all 8 APKs live on the VPS
      at `/var/lib/carapk/payload`, served by `/dl` behind signed URLs and
      hash-verified end to end. No public bucket involved.
- [ ] **Desktop app still downloads from the PUBLIC bucket.** `APK_BASE_URL` in
      `app/config.py` points at `pub-*.r2.dev`: the FAW payload is still free to
      anyone with the URL, and the MAGE payload was never uploaded there, so the
      desktop app cannot provision a MAGE at all. Move it onto `/api/plan` +
      signed `/dl` (it already holds a token) — the change is in `app/download.py`.
- [ ] **~~Upload the MAGE payload to R2~~** (superseded by the above) — `df01_freetube.apk`, `df02_yandexnavi.apk`
      are staged in `payload/` but NOT yet uploaded; `verify_cloud.py` will fail on
      them until they are. See `payload/UPLOAD.md` and `docs/DEPLOY.md` step 3.
- [ ] **Web client — validate the ADB transport on hardware.** This is now the
      LAST functional unknown. The bundle itself is fixed and proven: `npm run
      build` produces `dist/assets/transport-*.js` with real ya-webadb in it, and
      `connectUsb`/`connectRelay` resolve at runtime (verified in-browser). But no
      ADB session has ever been driven from a browser. Try MAGE over USB first
      (pure WebUSB, nothing to install), then B70 with `agent/relay.py`.
- [ ] **Deploy to the custom domain** — `docs/DEPLOY.md` is the runbook. Fill
      `deploy/production.env`, run `python deploy/configure.py`, then follow it.
      The VPS still runs the pre-CORS build, so the web client fails every call
      with "Load failed" until step 4 of that doc is done.
- [ ] **Empty or disable the public R2 bucket.** The web path no longer uses it,
      but `01`–`05` still return 200 there, so the FAW payload remains free to
      anyone with the URL. Do this only after the desktop app is moved off it.
- [ ] **B70 over wireless (already the field setup):** re-confirm the ~100 MB
      Navi push survives a Wi-Fi drop mid-install now that provision.py re-checks
      the transport and reconnects before each push. MAGE is USB — no such gap.
- [ ] **Optional, MAGE:** try the FAW's patched `04_yandexnavi.apk` on a MAGE. If
      it survives (no `signature mismatch` in `logcat -b crash`), it can be
      restyled with `tools/restyle_icon.py` and Yandex gets its real yellow-arrow
      icon instead of the OEM `icon_allapp_navi` tile.

## Handy references
- Deploy the backend: `docs/ACTIVATION_VPS.md`
- Host/refresh the payload: `docs/CLOUD_R2.md`, `payload/UPLOAD.md`
- Seller keypair: `python keygen/generate_activation_keys.py`
