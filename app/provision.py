"""
The fixed provisioning flow — reproduces EXACTLY what we did by hand, in order:

  1. Back Button (nu.back.button)      install → grant overlay → enable a11y service
  2. FreeTube (freetube.com)           install
  3. Wi-Fi shortcut (com.wifi.shortcut) install
  4. Yandex Navi (ru.yandex.yandexnavi) install (already patched+signed) → grant perms
  5. Patched launcher (…dlife6.launcher) install as system update → force-stop to reload

Apps are installed BEFORE the launcher, because the launcher's Wi-Fi / FreeTube /
Навигатор tiles launch those packages by name — they must already be present.

Every APK in payload/ is already zip-aligned and signed with the AOSP platform
key the head unit trusts, so we just `adb install` — no signing at runtime.
"""
from __future__ import annotations
from pathlib import Path
from typing import Callable

from . import engine, config, download

Log = Callable[[str], None]

# Accessibility component for the floating back button.
BACK_A11Y = "nu.back.button/nu.back.button.service.BackButtonService"

# Runtime permissions Navi needs to show the map / locate.
NAVI_PERMS = [
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.READ_EXTERNAL_STORAGE",
    "android.permission.WRITE_EXTERNAL_STORAGE",
    "android.permission.RECORD_AUDIO",
    "android.permission.READ_PHONE_STATE",
]

LAUNCHER_PKG = "com.fawcar.dlife6.launcher"

# Ordered payload. Each APK is downloaded from config.APK_BASE_URL + file and
# checked against sha256 before install. size is only for the progress bar.
STEPS = [
    {"file": "01_backbutton.apk",   "pkg": "nu.back.button",       "name": "Back Button",
     "post": "backbutton", "size": 3510839,
     "sha256": "309d21cc25541f6897263e9dcfe6e13c60006e8de9493b71ee6dd0cbce59302a"},
    {"file": "02_freetube.apk",     "pkg": "freetube.com",         "name": "FreeTube",
     "post": None, "size": 4108203,
     "sha256": "9855866cb3958b44eefba7da712d155e51c0a6d77ba3ae722eb53a60ef5330db"},
    {"file": "03_wifishortcut.apk", "pkg": "com.wifi.shortcut",    "name": "Wi-Fi tile",
     "post": None, "size": 8535,
     "sha256": "5d5bd806e98cc36b5273ecbe6928a9baa77aef31c2c86968f62471c580bf4eb4"},
    {"file": "04_yandexnavi.apk",   "pkg": "ru.yandex.yandexnavi", "name": "Yandex Navi",
     "post": "navi", "size": 105968735,
     "sha256": "225485fdc99670cd67bb6d5c996a37b79a9e10a2827b12bfaef197be7c92586a"},
    {"file": "05_launcher.apk",     "pkg": LAUNCHER_PKG,
     "name": "Patched launcher (Wi-Fi/FreeTube/Навигатор tiles)",
     "post": "launcher", "size": 23543505,
     "sha256": "2af15edfb65024acbc7f09323a1c97a1d9af3035d503fd9cc83e34eda5ed1246"},
]


# ---- post-install actions (exact commands we used) ------------------------- #
def _post_backbutton(serial: str, log: Log) -> None:
    log("  · granting overlay permission (SYSTEM_ALERT_WINDOW)…")
    engine._adb(["shell", "appops set nu.back.button SYSTEM_ALERT_WINDOW allow"],
                log, serial=serial, timeout=30)
    log("  · enabling the accessibility service…")
    cp = engine._adb(["shell", "settings get secure enabled_accessibility_services"],
                     None, serial=serial, timeout=30)
    cur = (cp.stdout or "").strip()
    if "back.button" in cur:
        new = cur
    elif not cur or cur == "null":
        new = BACK_A11Y
    else:
        new = cur + ":" + BACK_A11Y
    engine._adb(["shell", f"settings put secure enabled_accessibility_services '{new}'"],
                None, serial=serial, timeout=30)
    engine._adb(["shell", "settings put secure accessibility_enabled 1"],
                None, serial=serial, timeout=30)
    # kick the overlay to life
    engine._adb(["shell", "monkey -p nu.back.button -c android.intent.category.LAUNCHER 1"],
                None, serial=serial, timeout=30)
    log("  ✓ floating back button enabled")


def _post_navi(serial: str, log: Log) -> None:
    log("  · granting Navi runtime permissions…")
    for p in NAVI_PERMS:
        engine._adb(["shell", f"pm grant ru.yandex.yandexnavi {p}"],
                    None, serial=serial, timeout=30)
    log("  ✓ permissions granted")


def _post_launcher(serial: str, log: Log) -> None:
    log("  · restarting launcher so the new tiles load…")
    engine._adb(["shell", f"am force-stop {LAUNCHER_PKG}"], None, serial=serial, timeout=30)
    log("  ✓ launcher updated")


_POST = {"backbutton": _post_backbutton, "navi": _post_navi, "launcher": _post_launcher}


# ---- install one already-signed apk (no re-signing) ------------------------ #
def _install_signed(apk: Path, serial: str, log: Log) -> bool:
    cp = engine._adb(["install", "-r", "-d", str(apk)], log, serial=serial, timeout=900)
    blob = cp.stdout + cp.stderr
    if "Success" in blob:
        return True
    log("  ✗ install failed:\n  " + blob.strip().replace("\n", "\n  "))
    return False


# ---- the whole flow -------------------------------------------------------- #
def provision(serial: str, log: Log) -> bool:
    base = config.APK_BASE_URL.strip()
    if not base or "your-cloud-host" in base:
        log("✗ Cloud URL not configured (config.APK_BASE_URL). "
            "Set it to the folder where the APKs are hosted.")
        return False
    if not base.endswith("/"):
        base += "/"

    dl = download.download_dir()
    total = len(STEPS)
    all_ok = True
    log("Downloading payload from the cloud and installing…")
    for i, step in enumerate(STEPS, 1):
        log(f"\n[{i}/{total}] {step['name']}  ({step['pkg']})")
        url = base + step["file"]
        dest = dl / step["file"]
        log("  · downloading…")
        if not download.fetch(url, dest, step["sha256"], log, step.get("size", 0)):
            all_ok = False
            log(f"  ✗ {step['name']}: download/verify failed — skipping.")
            continue
        log("  · installing…")
        if not _install_signed(dest, serial, log):
            all_ok = False
            log(f"  ✗ {step['name']} failed — continuing with the rest.")
            continue
        log(f"  ✓ installed {step['pkg']}")
        post = step.get("post")
        if post and post in _POST:
            try:
                _POST[post](serial, log)
            except Exception as e:
                log(f"  ! post-step warning: {e}")

    # remove the freshly-downloaded APKs — they are pulled again next run.
    download.cleanup()

    log("\n" + ("✓ All done. Reboot the head unit if the tiles don't appear immediately."
               if all_ok else
               "Finished with some failures — see the log above."))
    return all_ok
