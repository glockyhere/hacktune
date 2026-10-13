# Dongfeng Aeolus L7 (web only)

Qualcomm SM6125 "trinket", Android 10 **userdebug**, adb shell is already root,
SELinux permissive. `ro.product.model` = `trinket for arm64` (the web client
detects the L7 by "trinket"). Provisioned over a **USB cable**. Recipe:
`server_vps/plan.py` → `_l7_ops`; payload pins: `server_vps/l7/payload.json`.
There is no desktop-app profile (`web_only` in `RECIPES`).

Research and build sources live outside this repo, in `~/Desktop/L8/`
(`ru-ui/` translation + overlay builder, `re/sysui-tiles/` SystemUI patch,
`re/freetube/` inset fix, `fleet/` remote-language server + agent).

## Before connecting: ADB is hidden

Settings → System → information page → tap **MCU version** 5× within 3 s →
password `HelloFengshen2023` → engineering screen → ADB switch. It is not
persistent: every restart turns adb off again, so the buyer enables it right
before pressing Connect.

## What the recipe does (78 ops)

1. `require` `ro.build.fingerprint` contains `QKQ1.210910.001/75:userdebug`.
   The SystemUI patch is built from this exact build's SystemUI; any other
   firmware stops here with nothing installed.
2. **Russian interface**: 49 RRO overlays (`l7ru_<target>.apk`, platform/AOSP
   test keys, /data only), enabled in one loop; `persist.sys.locale=ru-RU` +
   `system_locales`. Takes effect after the restart.
3. **Apps**: Yandex Navi + Antiradar = the MAGE files (`df02`, `df03`, original
   signatures; the L7 has no install allowlist). `l7_freetube.apk` = FreeTube
   with a 64 px top inset: the L7 status bar (`TYPE_QG_SYSTEMUI_STATUSBAR`,
   64 px) reserves no insets, so apps draw under it and their top bar is not
   touchable.
4. **Remote language control**: when `FLEET_URL`/`FLEET_ADMIN_KEY` are set,
   `fleet.py` enrols the car in the seller's dashboard once per activation
   (name = make model VIN) and the plan pushes `l7/l7agent.sh` (base64 in
   2000-char shell chunks, SHA-256 checked), its config and the
   `l7_langagent.apk` boot launcher. Dashboard down → these ops are omitted.
5. **App tiles**: the stock all-apps grid is a hardcoded list in SystemUI, a
   *persistent* app. `pm install` refuses persistent updates unless the session
   is **staged** (`INSTALL_STAGED` skips the check in PackageManagerService), so
   `l7_systemui.apk` installs with `--staged --enable-rollback` and applies on the
   next boot. It adds one tile per user-installed launcher app (any app added
   later gets a tile too). Pending staged sessions are abandoned first.
6. Detached `sleep 20; reboot`, so the browser finishes and unlinks first.

## Certify without a browser

`python tools/run_plan.py --token <approved token> --profile dongfeng_l7`
runs the plan over adb with the browser's op semantics.
