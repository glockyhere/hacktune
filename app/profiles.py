"""
Vehicle profiles — one per supported head unit.

Each head unit locks down app installation differently, so each needs its own
payload and its own post-install work. A profile bundles all of that:

    id/name        which car this is, for the UI
    detect         how to recognise the unit from its adb props
    steps          the ordered payload (file, package, sha256 pin, post-step)
    prepare        unlock work done ONCE before any install
    finish         work done ONCE after every install

Supported units
---------------
`faw_b70`   ECARX/FAW B70 — Android 9 / API 28.
            Installs are gated by the unit's `apkauth` whitelist, which only
            accepts the AOSP platform key. Every payload APK is pre-signed with
            that key, and the menu is handled by shipping a patched launcher.

`dongfeng_mage`  Dongfeng Aeolus MAGE (spm8675p1_64_raite) — Android 11 / API 30.
            Completely different lock: the OEM PackageManager rejects any APK
            not signed by Dongfeng with

                SecurityException: DF APK cert incorrect

            This is gated by a persistent property, `persist.apk.sign.verify`,
            and the unit ships userdebug (ro.secure=0, adbd already root), so we
            clear the property instead of signing anything.

            Its launcher (`com.dftc.launcher`) does NOT enumerate installed apps
            — it renders a fixed list from a SQLite table. A newly installed app
            is invisible until it has a row there, so `finish` adds the rows.

Both flows were performed by hand on a real unit before being written down here;
see docs/DONGFENG_MAGE.md for the Dongfeng findings.
"""
from __future__ import annotations

from typing import Callable

from . import engine

Log = Callable[[str], None]


# --------------------------------------------------------------------------- #
#  FAW B70 — platform-signed payload, patched launcher
# --------------------------------------------------------------------------- #
FAW_LAUNCHER_PKG = "com.fawcar.dlife6.launcher"

# Accessibility component for the floating back button.
BACK_A11Y = "nu.back.button/nu.back.button.service.BackButtonService"

# Runtime permissions Navi needs to show the map / locate.
# Runtime permissions ContraCam (antiradar) actually declares, filtered to the
# ones that are grantable on the MAGE's Android 11. Background location is a
# separate grant on API 29+: without it the app stops detecting once the screen
# sleeps, which on a head unit is most of the drive.
ANTIRADAR_PERMS = [
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.ACCESS_BACKGROUND_LOCATION",
]

NAVI_PERMS = [
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.READ_EXTERNAL_STORAGE",
    "android.permission.WRITE_EXTERNAL_STORAGE",
    "android.permission.RECORD_AUDIO",
    "android.permission.READ_PHONE_STATE",
]

FAW_STEPS = [
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
    {"file": "05_launcher.apk",     "pkg": FAW_LAUNCHER_PKG,
     "name": "Patched launcher (Wi-Fi/FreeTube/Навигатор tiles)",
     "post": "launcher", "size": 23543505,
     "sha256": "2af15edfb65024acbc7f09323a1c97a1d9af3035d503fd9cc83e34eda5ed1246"},
]


def _faw_post_backbutton(serial: str, log: Log) -> None:
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
    engine._adb(["shell", "monkey -p nu.back.button -c android.intent.category.LAUNCHER 1"],
                None, serial=serial, timeout=30)
    log("  ✓ floating back button enabled")


def _faw_post_navi(serial: str, log: Log) -> None:
    log("  · granting Navi runtime permissions…")
    for p in NAVI_PERMS:
        engine._adb(["shell", f"pm grant ru.yandex.yandexnavi {p}"],
                    None, serial=serial, timeout=30)
    log("  ✓ permissions granted")


def _faw_post_launcher(serial: str, log: Log) -> None:
    log("  · restarting launcher so the new tiles load…")
    engine._adb(["shell", f"am force-stop {FAW_LAUNCHER_PKG}"],
                None, serial=serial, timeout=30)
    log("  ✓ launcher updated")


# --------------------------------------------------------------------------- #
#  Dongfeng Aeolus MAGE — unlock the cert check, then write launcher DB rows
# --------------------------------------------------------------------------- #
DF_LAUNCHER_PKG = "com.dftc.launcher"

# The OEM signature gate. 1 = enforce "DF APK cert incorrect", 0 = allow.
DF_SIGN_VERIFY_PROP = "persist.apk.sign.verify"

# The launcher's app-list database. Note user_de (device-encrypted), not /data/data.
DF_DB = f"/data/user_de/0/{DF_LAUNCHER_PKG}/databases/launcher.db"

# Settings key the launcher's AppListLoader watches with a ContentObserver.
# Pulsing it makes the launcher re-read the table WITHOUT a force-stop — which
# matters, because force-stopping the launcher desyncs SystemUI's CarStatusBar
# and leaves the hardware app-menu button dead until SystemUI restarts.
DF_RELOAD_KEY = "show_launcher_test_app_key"

DF_STEPS = [
    {"file": "df01_freetube.apk",   "pkg": "freetube.com",         "name": "FreeTube",
     "post": None, "size": 4497273,
     "sha256": "222a15442da6e36676cb6f5a2bcfc4589be4cfe940ce5079bc6c9633a7620f20"},
    {"file": "df02_yandexnavi.apk", "pkg": "ru.yandex.yandexnavi", "name": "Yandex Navi",
     "post": "navi", "size": 106087315,
     "sha256": "6e0260b07e1f909e9dea2b2896932b4a6dd4cf1dc277abfe387963e7f6dafe2f"},
    {"file": "df03_antiradar.apk", "pkg": "com.mybedy.antiradar", "name": "Antiradar (ContraCam)",
     "post": "antiradar", "size": 39923373,
     "sha256": "eb1e9420b8a8e1c24acb098af7b93c69fbbbd20fdabd1fba8bf201427a889081"},
]

# Rows written into the launcher's `allApp` table so the apps appear in the menu.
#
# icon: "" makes the launcher fall back to PackageManager.getApplicationIcon(),
# i.e. the app's own icon. df01_freetube.apk already carries an icon restyled to
# the OEM tile spec (see tools/restyle_icon.py), so it lands correctly sized.
#
# Yandex ships a 48x48 mdpi icon that the launcher upscales into a big blurry
# square, and its APK canNOT be restyled: ru.yandex.yandexnavi verifies its own
# signature in com.yandex.passport and dies with
#     IllegalStateException: Internal error, application signature mismatch
# So we point it at `icon_allapp_navi`, an unused navigation tile already inside
# the OEM launcher — genuine native artwork, correct geometry, nothing patched.
DF_MENU_ROWS = [
    {"pkg": "freetube.com",         "label": "FreeTube",         "icon": ""},
    {"pkg": "ru.yandex.yandexnavi", "label": "Яндекс Навигатор",  "icon": "icon_allapp_navi"},
    {"pkg": "com.mybedy.antiradar",  "label": "Antiradar",         "icon": ""},
]


def _sh(serial: str, cmd: str, log: Log | None = None, timeout: int = 60) -> str:
    cp = engine._adb(["shell", cmd], log, serial=serial, timeout=timeout)
    return (cp.stdout or "") + (cp.stderr or "")


def _df_ensure_root(serial: str, log: Log) -> bool:
    """Make sure adbd is root before touching the signature property.

    The MAGE is provisioned over USB, where `adb root` restarts adbd and the
    transport simply re-enumerates — cheap and safe. We still check `id -u`
    first and skip the restart when adbd is already root (it is, on these
    userdebug units), and still wait for the transport to come back, so the
    step also holds up if a unit is ever reached over the network.
    """
    uid = _sh(serial, "id -u").strip()
    if uid == "0":
        log("  · adbd is already root")
        return True

    log("  · restarting adbd as root…")
    engine._adb(["root"], None, serial=serial, timeout=30)
    if not engine.reconnect(serial, log, timeout=60):
        log("  ✗ lost the head unit after `adb root`. Re-seat the USB cable "
            "(or press Detect / Reconnect), then run the install again.")
        return False

    uid = _sh(serial, "id -u").strip()
    if uid != "0":
        log("  ✗ adbd is not root. This unit must be a userdebug build "
            "(ro.debuggable=1) for the unlock to work.")
        return False
    log("  · adbd is root")
    return True


def _df_prepare(serial: str, log: Log) -> bool:
    """Clear the OEM cert check so unsigned/third-party APKs install."""
    log("Unlocking the head unit's APK signature check…")
    if not _df_ensure_root(serial, log):
        return False

    before = _sh(serial, f"getprop {DF_SIGN_VERIFY_PROP}").strip()
    log(f"  · {DF_SIGN_VERIFY_PROP} is currently '{before or 'unset'}'")
    _sh(serial, f"setprop {DF_SIGN_VERIFY_PROP} 0")
    now = _sh(serial, f"getprop {DF_SIGN_VERIFY_PROP}").strip()
    if now != "0":
        log("  ✗ Could not clear the signature check. The unit must be a userdebug "
            "build with root adb (ro.debuggable=1). Installs will be rejected with "
            "'DF APK cert incorrect'.")
        return False
    log("  ✓ signature check disabled (persists across reboots)")
    return True


def _df_post_navi(serial: str, log: Log) -> None:
    log("  · granting Navi runtime permissions…")
    for p in NAVI_PERMS:
        _sh(serial, f"pm grant ru.yandex.yandexnavi {p}")
    log("  ✓ permissions granted")


def _df_post_antiradar(serial: str, log: Log) -> None:
    log("  · granting Antiradar location permissions…")
    for perm in ANTIRADAR_PERMS:
        _sh(serial, f"pm grant com.mybedy.antiradar {perm}")
    # Floating speed-camera warnings draw over the navigation map. This is an
    # appop, not a runtime permission, so `pm grant` cannot set it — same
    # mechanism the FAW back-button app needs.
    log("  · allowing overlay (SYSTEM_ALERT_WINDOW)…")
    _sh(serial, "appops set com.mybedy.antiradar SYSTEM_ALERT_WINDOW allow")
    log("  ✓ Antiradar configured")


def _sql(serial: str, statement: str, log: Log | None = None) -> str:
    """Run one SQL statement against the launcher DB via the on-device sqlite3."""
    esc = statement.replace('"', r'\"')
    return _sh(serial, f'sqlite3 {DF_DB} "{esc}"', log)


def _df_finish(serial: str, log: Log) -> bool:
    """Add the menu rows, then make the launcher reload without a force-stop."""
    log("\nAdding the apps to the head unit's menu…")

    probe = _sql(serial, "select count(*) from allApp;")
    if not probe.strip().isdigit():
        log("  ✗ Could not read the launcher database. The apps ARE installed, but "
            "they will not show in the menu.\n"
            f"    (tried {DF_DB} — got: {probe.strip() or 'no output'})")
        return False

    for row in DF_MENU_ROWS:
        # idempotent: drop any previous row for this package first
        _sql(serial, f"delete from allApp where pkgName='{row['pkg']}';")
        pos = _sql(serial, "select ifnull(max(position),-1)+1 from allApp;").strip()
        if not pos.isdigit():
            pos = "8"
        label = row["label"].replace("'", "''")
        _sql(serial,
             "insert into allApp (appName,pkgName,iconName,position) "
             f"values ('{label}','{row['pkg']}','{row['icon']}',{pos});")
        log(f"  · {row['label']} → menu position {pos}")

    # Pulse the observed setting so AppListLoader re-reads the table in place.
    log("  · reloading the launcher's app list…")
    _sh(serial, f"settings put global {DF_RELOAD_KEY} 1")
    _sh(serial, f"settings put global {DF_RELOAD_KEY} 0")
    log("  ✓ menu updated")
    return True


# --------------------------------------------------------------------------- #
#  Profile registry
# --------------------------------------------------------------------------- #
PROFILES = {
    "faw_b70": {
        "id": "faw_b70",
        "name": "FAW B70 (ECARX)",
        "android": "9 / API 28",
        # How this unit is reached in the field. B70 is always Wireless ADB.
        "connection": "wireless",
        "connect_hint": ("On the head unit enable Developer options → Wireless ADB, "
                         "then press Detect."),
        "steps": FAW_STEPS,
        "prepare": None,
        "finish": None,
        "post": {
            "backbutton": _faw_post_backbutton,
            "navi": _faw_post_navi,
            "launcher": _faw_post_launcher,
        },
        # Payload is pre-signed with the platform key the unit demands.
        "install_flags": ["-r", "-d"],
        "match": lambda p: (
            "fawcar" in p.get("model", "").lower()
            or "b70" in p.get("model", "").lower()
            or "ecarx" in p.get("device", "").lower()
        ),
    },
    "dongfeng_mage": {
        "id": "dongfeng_mage",
        "name": "Dongfeng Aeolus MAGE",
        "android": "11 / API 30",
        # MAGE is always provisioned over a USB cable, never wireless.
        "connection": "usb",
        "connect_hint": ("Connect the head unit with a USB cable and accept the "
                         "'Allow USB debugging?' prompt on its screen, then press Detect."),
        "steps": DF_STEPS,
        "prepare": _df_prepare,
        "finish": _df_finish,
        "post": {"navi": _df_post_navi, "antiradar": _df_post_antiradar},
        # -g pre-grants runtime permissions; the cert check is already cleared.
        "install_flags": ["-r", "-g"],
        "match": lambda p: (
            "dongfeng" in p.get("model", "").lower()
            or "aeolus" in p.get("model", "").lower()
            or "spm8675" in p.get("device", "").lower()
        ),
    },
}

DEFAULT_PROFILE = "faw_b70"


def detect(serial: str, log: Log | None = None) -> tuple[dict, dict]:
    """Identify the connected unit. Returns (profile, raw device props)."""
    props = engine.device_info(serial, None)
    # device_info only reads model/android/sdk; ro.product.device disambiguates.
    cp = engine._adb(["shell", "getprop ro.product.device"], None,
                     serial=serial, timeout=20)
    props["device"] = (cp.stdout or "").strip()

    for prof in PROFILES.values():
        try:
            if prof["match"](props):
                return prof, props
        except Exception:
            continue
    return PROFILES[DEFAULT_PROFILE], props


def get(profile_id: str) -> dict:
    return PROFILES.get(profile_id, PROFILES[DEFAULT_PROFILE])
