# Car Head-Unit Setup — single paywalled Windows program

One `.exe` that provisions a car head unit with our exact set, in the exact
order we did it by hand. The buyer only enables **Wireless ADB**; the program
does everything else.

**Supported head units** — auto-detected, each with its own payload and unlock
(see [`app/profiles.py`](app/profiles.py)):

| Unit | Android | How it is unlocked |
|---|---|---|
| FAW B70 (ECARX) | 9 / API 28 | payload pre-signed with the AOSP platform key its `apkauth` whitelist demands; menu via a patched launcher |
| Dongfeng Aeolus MAGE | 11 / API 30 | clears `persist.apk.sign.verify` (nothing is signed); menu via rows written into the launcher's SQLite `allApp` table — see [`docs/DONGFENG_MAGE.md`](docs/DONGFENG_MAGE.md) |

**Activation model:** each install is a one-time, **pay-then-you-approve**
session. The buyer enters VIN + make/model, sees your card + contacts, and waits
for your approval; on approval the program receives a single-use, server-signed
token and installs once. Backend options:
**[`docs/ACTIVATION_VPS.md`](docs/ACTIVATION_VPS.md)** (self-hosted API + Telegram
bot on your VPS, APKs on R2) or [`docs/ACTIVATION.md`](docs/ACTIVATION.md)
(Cloudflare Worker). (An older offline license-key mode still exists in `keygen/`
but the activation backend supersedes it.)

### What it installs (fixed payload, nothing else)
1. **Back Button** (`nu.back.button`) → install, grant overlay, enable its
   accessibility service → floating system-back button appears.
2. **FreeTube** (`freetube.com`) → install.
3. **Wi-Fi tile** (`com.wifi.shortcut`) → install (opens the hidden Wi-Fi screen).
4. **Yandex Navi** (`ru.yandex.yandexnavi`) → install (already signature-patched so
   it doesn't crash) → grant location/storage/mic permissions.
5. **Patched launcher** (`com.fawcar.dlife6.launcher`) → install as a system
   update, then restart it so the **Wi-Fi / FreeTube / Навигатор** tiles show.

Apps go on **before** the launcher on purpose — its tiles launch those packages
by name, so they must exist first.

All five APKs are pre-aligned and signed with the AOSP **platform** key the unit
trusts (its `apkauth` requirement), and Navi is pre-patched. The program just
`adb install`s them — no signing/patching at runtime — so the only tool it needs
is **adb**.

### Cloud payload
The APKs are **not** bundled in the exe. The program **downloads them from your
cloud every run** (`config.APK_BASE_URL`) and verifies each file's **SHA-256**
against a value pinned in `app/profiles.py` before installing — a tampered or
wrong download is rejected. This keeps the exe small (~15 MB) and lets you update
the payload without reshipping the program. Upload the files in `payload/` to any
static host — see [`payload/UPLOAD.md`](payload/UPLOAD.md).

---

## Files

```
CarApkInstaller/
├─ app/                  the program (paywall + fixed provisioning flow)
│  ├─ config.py          ← EDIT: your card, contacts, price, license public key
│  ├─ licensing.py       Ed25519 license verify + machine-id binding
│  ├─ profiles.py        ← per-car payload + unlock + detection (ADD CARS HERE)
│  ├─ provision.py       generic download→verify→install→post loop
│  ├─ engine.py          adb connect / mDNS reconnect
│  └─ gui.py             paywall + one “Install everything” button
├─ payload/              the APKs per car (hosted on your cloud, not bundled)
├─ keygen/               ★ SELLER-ONLY. Never ship. (make + issue license keys)
├─ tools/fetch_tools.ps1 downloads adb
├─ tools/restyle_icon.py rebuild MAGE-styled launcher icons
├─ docs/DONGFENG_MAGE.md the MAGE unlock, menu DB, icon spec + traps
├─ build/CarApkInstaller.spec
├─ build.bat
└─ requirements.txt
```

Ship `dist\CarApkInstaller.exe` + `dist\tools\` (adb). The exe is small (~15 MB)
because the APKs are pulled from your cloud at runtime, not bundled.

---

## Build the `.exe` (on Windows — PyInstaller can’t cross-compile)

```bat
powershell -ExecutionPolicy Bypass -File tools\fetch_tools.ps1   :: gets adb
python keygen\generate_keys.py                                   :: prints PUBLIC key
:: 1. upload payload\*.apk to your cloud (see payload\UPLOAD.md)
:: 2. edit app\config.py:
::      - APK_BASE_URL  = your cloud folder URL (trailing slash)
::      - LICENSE_PUBLIC_KEY = the printed public key
::      - your card / contacts / price
build.bat                                                        :: → dist\CarApkInstaller.exe
```

## Sell / activate (per install)
1. Buyer runs the exe → enters **VIN + make + model**, sees **your card +
   contacts**, taps **Request activation**.
2. Buyer pays you and sends the shown **request code**.
3. You **Approve** (Telegram button or the admin page) after seeing the payment.
4. The program auto-unlocks and installs. Full backend setup:
   [`docs/ACTIVATION.md`](docs/ACTIVATION.md).

## Buyer runs it
1. Enter VIN + make/model → **Request activation** → pay → wait for approval.
2. Head unit → Developer options → **enable Wireless ADB** (same Wi-Fi as PC),
   approve the ADB prompt once → press **Detect / Reconnect**.
3. Press **Install everything to the car** and watch the log.

---

## Security model (honest)
- License keys are **Ed25519-signed** — only you (holder of
  `keygen/license_private.key`) can mint them; the app ships only the public key.
- Each key is **bound to the buyer’s Machine ID**, so it won’t work on another PC.
- A determined person can still patch the compiled binary to skip the check —
  that is true of any offline program. Server-side activation is the only way to
  remove that; ask if you want it.
- Back up `keygen/license_private.key`. If it leaks, anyone can mint keys.

## Legal note
This ships pre-patched third-party apps (e.g. a signature-patched Yandex
Navigator, a modified FAW launcher, re-signed FreeTube). Re-signing/patching apps
for a device you own is one thing; **redistributing modified copies to paying
customers can violate those apps’ licenses/copyright.** The paywall does not make
that legal — this is your call as the seller. Consider shipping only the tools you
authored (Wi-Fi tile, launcher tweaks, back-button enablement) and letting buyers
supply Navi/FreeTube themselves.
