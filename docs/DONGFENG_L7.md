# Dongfeng Aeolus L7 (web only)

Qualcomm SM6125 "trinket", Android 10 **userdebug**, adb shell is already root,
SELinux permissive. `ro.product.model` = `trinket for arm64` (the web client
detects the L7 by "trinket"). Provisioned over a **USB cable**. Recipe:
`server_vps/plan.py` → `_l7_ops`; payload pins: `server_vps/l7/payload.json`.
There is no desktop-app profile (`web_only` in `RECIPES`).

Research and build sources live outside this repo, in `~/Desktop/L8/`
(`ru-ui/` translation + overlay builder, `re/sysui-tiles/` SystemUI patch,
`re/settings-lock/` SystemSettings patch, `lock/` password tool,
`fleet/` remote-language server + agent).

## Before connecting: ADB is hidden

Settings → System → information page → tap **MCU version** 5× within 3 s →
password → engineering screen → ADB switch. On a stock car the password is
`HelloFengshen2023`; once our package is installed it is the car's own password
(below). It is not persistent: every restart turns adb off again, so the buyer
enables it right before pressing Connect.

## One package

`dongfeng_l7` (model "L7"; activations for the retired "L7 RU" / "L7 Apps"
packages are accepted too, `models` in `RECIPES`, enforced by `/api/plan`).
We install **no apps**: buyers who want apps buy the car's engineering password
from the seller, turn ADB on and install their own.

1. `root` + a `require` on `ro.build.fingerprint` containing
   `QKQ1.210910.001/75:userdebug` (both system patches are built from this
   exact build; any other firmware stops with nothing installed).
2. **Russian interface**: 49 RRO overlays (`l7ru_<target>.apk`, platform/AOSP
   test keys, /data only), enabled in one loop; `persist.sys.locale=ru-RU` +
   `system_locales`.
3. **Launcher + lock** (`system` phase): `l7_systemui.apk` and `l7_settings.apk`
   are `push`ed to `/data/local/tmp`, then one shell step (`must`: a refusal
   stops the install with a message) builds a single **multi-package staged
   session** with `pm install-create --multi-package --staged --enable-rollback`
   / `install-write` / `install-add-session` / `install-commit`. Both apps are
   *persistent*, and `pm install` refuses persistent updates unless the session
   is staged (`INSTALL_STAGED` skips the check); Android 10 allows only one
   pending staged session, hence one session for both. Stale ready sessions
   are abandoned first. Applied on the final restart.
4. **Remote language agent**, then a detached `sleep 20; reboot`.

### Launcher patch (`l7_systemui.apk`)

The stock all-apps grid is a hardcoded list in SystemUI. The patch adds one
tile per user-installed launcher app (real icon, launches it). The list is
built when the grid activity is first created, so an app installed later gets
its tile **after the next restart**.

### Engineering lock (`l7_settings.apk`)

The stock firmware opens its engineering screens with two well-known passwords:
`HelloFengshen2023` (System info → MCU version ×5 → ADB switch) and `PDSN_` + the
last 6 characters of the PDSN (PDSN tile ×5 → vehicle-mode settings).
`l7_settings.apk` is the stock SystemSettings with one hook:
`FactoryPwdEditView.checkPasswordIsTrue` compares the typed text with
`L7Lock.accept()` instead of the stock string, so both prompts accept one
per-car password and nothing else:

    password = 10 chars of HMAC-SHA256(salt, "L7ENG:" + PDSN) over A–Z/2–9 (no I L O 0 1)

The PDSN comes from `persist.qinggan.vehicle.pdsn`, the value the System page
shows, so a buyer can read it to the seller. The salt is
`~/.config/axolotl/l7-eng-salt` on the seller's Mac (back it up: without it no
password can be recovered), baked into the APK at build time. Look a password
up with `~/Desktop/L8/lock/passwd.py <PDSN>` (no argument: reads it over adb).
Known limit: the salt can be extracted from the APK, which lets someone who
does so derive any car's password. A factory reset restores the stock
passwords along with removing everything else in /data.

### Remote language agent

With `FLEET_URL`/`FLEET_ADMIN_KEY` set, `fleet.py` enrols the car in the
seller's dashboard keyed by the unit serial (`ro.serialno`, sent by the client),
then VIN, so a reinstall reuses the same row and token. The plan pushes
`l7/l7agent.sh` (base64 in 2000-char shell chunks, SHA-256 checked), its config
and `l7_langagent.apk`, stopping an already-running agent first. Dashboard down
→ the agent ops are left out; the install still completes.

## Certify without a browser

`python3 tools/run_plan.py --token <approved token> --profile dongfeng_l7 --serial <unit>`
runs the plan over adb with the browser's op semantics (retries USB drops and
download resets; `--from N` resumes).
