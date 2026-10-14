# Dongfeng Aeolus L7 (web only)

Qualcomm SM6125 "trinket", Android 10 **userdebug**, adb shell is already root,
SELinux permissive. `ro.product.model` = `trinket for arm64` (the web client
detects the L7 by "trinket"). Provisioned over a **USB cable**. Recipe:
`server_vps/plan.py` → `_l7_ru_ops` / `_l7_apps_ops`; payload pins: `server_vps/l7/payload.json`.
There is no desktop-app profile (`web_only` in `RECIPES`).

Research and build sources live outside this repo, in `~/Desktop/L8/`
(`ru-ui/` translation + overlay builder, `re/sysui-tiles/` SystemUI patch,
`re/freetube/` inset fix, `fleet/` remote-language server + agent).

## Before connecting: ADB is hidden

Settings → System → information page → tap **MCU version** 5× within 3 s →
password `HelloFengshen2023` → engineering screen → ADB switch. It is not
persistent: every restart turns adb off again, so the buyer enables it right
before pressing Connect.

## Two packages, sold separately

The picker has two L7 seats; each is its own activation, approval and payment.
The seat's model name ("L7 RU" / "L7 Apps") goes into the activation request,
so the Telegram request says which package was bought, and `/api/plan` refuses
(403) a token whose `model` doesn't match the requested recipe.

Both start with `root` + a `require` on `ro.build.fingerprint` containing
`QKQ1.210910.001/75:userdebug` (the SystemUI patch is built from this exact
build; any other firmware stops with nothing installed), and both end with the
remote-language agent and a detached `sleep 20; reboot`.

**`dongfeng_l7_ru` — Russian interface (64 ops)**: 49 RRO overlays
(`l7ru_<target>.apk`, platform/AOSP test keys, /data only), enabled in one
loop; `persist.sys.locale=ru-RU` + `system_locales`.

**`dongfeng_l7_apps` — Apps (26 ops)**: Yandex Navi + Antiradar = the MAGE
files (`df02`, `df03`, original signatures; the L7 has no install allowlist);
`l7_freetube.apk` = FreeTube with a 64 px top inset (the L7 status bar,
`TYPE_QG_SYSTEMUI_STATUSBAR`, reserves no insets, so apps draw under it). Then
the **tiles**: the stock all-apps grid is a hardcoded list in SystemUI, a
*persistent* app, and `pm install` refuses persistent updates unless the session
is **staged** (`INSTALL_STAGED` skips the check). So `l7_systemui.apk` installs
with `--staged --enable-rollback` (pending staged sessions are abandoned first)
and applies on the reboot; it adds one tile per user-installed launcher app.

**Remote language agent (both)**: with `FLEET_URL`/`FLEET_ADMIN_KEY` set,
`fleet.py` enrols the car in the seller's dashboard **once per VIN**, so a car
that buys both packages is one dashboard row with one token. The plan pushes
`l7/l7agent.sh` (base64 in 2000-char shell chunks, SHA-256 checked), its config
and `l7_langagent.apk`, stopping an already-running agent first. Dashboard down
→ the agent ops are left out; the install still completes.

## Certify without a browser

`python tools/run_plan.py --token <approved token> --profile dongfeng_l7_ru` (or `dongfeng_l7_apps`)
runs the plan over adb with the browser's op semantics.

## Engineering password lock (built, not yet enabled)

The stock firmware opens its engineering screens with two well-known passwords:
`HelloFengshen2023` (System info → MCU version ×5 → ADB switch) and `PDSN_` + the
last 6 characters of the PDSN (PDSN tile ×5 → vehicle-mode settings). Anyone who
knows them can turn ADB on and copy the installed software.

`l7_settings.apk` (source: `~/Desktop/L8/re/settings-lock/`) is the stock
SystemSettings with one hook: `FactoryPwdEditView.checkPasswordIsTrue` compares the
typed text with `L7Lock.accept()` instead of the stock string. Both prompts then
accept one per-car password and nothing else:

    password = 10 chars of HMAC-SHA256(salt, "L7ENG:" + PDSN) over A–Z/2–9 (no I L O 0 1)

The PDSN comes from `persist.qinggan.vehicle.pdsn`, the same value the System page
shows. The salt is `~/.config/axolotl/l7-eng-salt` on the seller's Mac, and the build
writes it into the APK. To look up a car's password:
`~/Desktop/L8/lock/passwd.py <PDSN>`, or run it with no argument and the car on adb.

- SystemSettings is persistent, so the update is **staged** (`--staged
  --enable-rollback`) and applies on the restart that ends the RU package.
- Web: the RU package stages it only when the API runs with `L7_LOCK=1`. The switch
  is off until the lock has been verified on a car.
- `new-car.sh` always stages it, in **one** multi-package session together with the
  SystemUI tiles (Android 10 allows a single pending staged session).
- A factory reset removes it along with everything else in /data.
