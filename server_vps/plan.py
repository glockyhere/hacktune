"""
Server-issued provisioning PLAN — the part that keeps the web client dumb.

The desktop app hardcodes the recipe in app/profiles.py. The web client must
NOT: anything shipped to a browser is readable. So the recipe lives here, on the
server, and is handed out only in exchange for a valid one-time activation token.

A plan is a list of TYPED OPERATIONS the client executes blindly:

    {"op":"root"}                                     restart adbd as root
    {"op":"setprop","key":..,"value":..}              set a system property
    {"op":"install","file":..,"url":..,"sha256":..,"flags":[..]}
    {"op":"shell","cmd":..}                            arbitrary adb shell
    {"op":"sqlite","db":..,"stmt":..}                  one SQL statement
    {"op":"settings","ns":..,"key":..,"value":..}      settings put

The client knows how to run each *verb* over adb, but carries none of the
product-specific *values* — no package names, no property names, no launcher DB
layout. Those exist in the browser only for the lifetime of one paid session.

`install` ops carry a short-lived HMAC-signed download URL (see sign_url), so the
payload bucket can be private: no token, no plan, no URLs, no APKs.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import time

# --------------------------------------------------------------------------- #
#  Payload pins. Must match app/profiles.py and the files on the origin.
# --------------------------------------------------------------------------- #
PAYLOAD = {
    "01_backbutton.apk":   "309d21cc25541f6897263e9dcfe6e13c60006e8de9493b71ee6dd0cbce59302a",
    "02_freetube.apk":     "9855866cb3958b44eefba7da712d155e51c0a6d77ba3ae722eb53a60ef5330db",
    "03_wifishortcut.apk": "5d5bd806e98cc36b5273ecbe6928a9baa77aef31c2c86968f62471c580bf4eb4",
    "04_yandexnavi.apk":   "225485fdc99670cd67bb6d5c996a37b79a9e10a2827b12bfaef197be7c92586a",
    "05_launcher.apk":     "2af15edfb65024acbc7f09323a1c97a1d9af3035d503fd9cc83e34eda5ed1246",
    "df01_freetube.apk":   "222a15442da6e36676cb6f5a2bcfc4589be4cfe940ce5079bc6c9633a7620f20",
    "df02_yandexnavi.apk": "6e0260b07e1f909e9dea2b2896932b4a6dd4cf1dc277abfe387963e7f6dafe2f",
    "df03_antiradar.apk":  "eb1e9420b8a8e1c24acb098af7b93c69fbbbd20fdabd1fba8bf201427a889081",
}

# Runtime permissions Navi needs, shared by both cars.
_ANTIRADAR_PERMS = [
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.ACCESS_BACKGROUND_LOCATION",
]

_NAVI_PERMS = [
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.READ_EXTERNAL_STORAGE",
    "android.permission.WRITE_EXTERNAL_STORAGE",
    "android.permission.RECORD_AUDIO",
    "android.permission.READ_PHONE_STATE",
]

_DF_LAUNCHER_DB = "/data/user_de/0/com.dftc.launcher/databases/launcher.db"


def _grant(pkg: str) -> list[dict]:
    return [{"op": "shell", "cmd": f"pm grant {pkg} {p}"} for p in _NAVI_PERMS]


# --------------------------------------------------------------------------- #
#  The recipes, as op lists. `_install` is filled with a signed URL per session.
# --------------------------------------------------------------------------- #
def _install(file: str, flags: list[str]) -> dict:
    return {"op": "install", "file": file, "sha256": PAYLOAD[file], "flags": flags}


def _faw_ops() -> list[dict]:
    F = ["-r", "-d"]
    return [
        _install("01_backbutton.apk", F),
        {"op": "shell", "cmd": "appops set nu.back.button SYSTEM_ALERT_WINDOW allow"},
        {"op": "shell", "cmd": "settings put secure enabled_accessibility_services "
                               "nu.back.button/nu.back.button.service.BackButtonService"},
        {"op": "shell", "cmd": "settings put secure accessibility_enabled 1"},
        _install("02_freetube.apk", F),
        _install("03_wifishortcut.apk", F),
        _install("04_yandexnavi.apk", F),
        *_grant("ru.yandex.yandexnavi"),
        _install("05_launcher.apk", F),
        {"op": "shell", "cmd": "am force-stop com.fawcar.dlife6.launcher"},
    ]


def _mage_ops() -> list[dict]:
    G = ["-r", "-g"]
    db = _DF_LAUNCHER_DB
    ins = "insert into allApp (appName,pkgName,iconName,position) values"
    return [
        {"op": "root"},
        {"op": "setprop", "key": "persist.apk.sign.verify", "value": "0"},
        _install("df01_freetube.apk", G),
        _install("df02_yandexnavi.apk", G),
        _install("df03_antiradar.apk", G),
        *_grant("ru.yandex.yandexnavi"),
        *[{"op": "shell", "cmd": f"pm grant com.mybedy.antiradar {p}"}
          for p in _ANTIRADAR_PERMS],
        # overlay is an appop, not a runtime permission: -g and pm grant cannot
        # set it, and without it the speed-camera warnings cannot draw over the map
        {"op": "shell", "cmd": "appops set com.mybedy.antiradar SYSTEM_ALERT_WINDOW allow"},
        # menu rows — idempotent (delete then insert at max+1)
        {"op": "sqlite", "db": db, "stmt": "delete from allApp where pkgName='freetube.com';"},
        {"op": "sqlite", "db": db,
         "stmt": f"{ins} ('FreeTube','freetube.com','',(select ifnull(max(position),-1)+1 from allApp));"},
        {"op": "sqlite", "db": db, "stmt": "delete from allApp where pkgName='ru.yandex.yandexnavi';"},
        {"op": "sqlite", "db": db,
         "stmt": f"{ins} ('Яндекс Навигатор','ru.yandex.yandexnavi','icon_allapp_navi',"
                 "(select ifnull(max(position),-1)+1 from allApp));"},
        {"op": "sqlite", "db": db, "stmt": "delete from allApp where pkgName='com.mybedy.antiradar';"},
        {"op": "sqlite", "db": db,
         "stmt": f"{ins} ('Antiradar','com.mybedy.antiradar','',"
                 "(select ifnull(max(position),-1)+1 from allApp));"},
        # reload the launcher WITHOUT force-stop (see docs/DONGFENG_MAGE.md)
        {"op": "settings", "ns": "global", "key": "show_launcher_test_app_key", "value": "1"},
        {"op": "settings", "ns": "global", "key": "show_launcher_test_app_key", "value": "0"},
    ]


RECIPES = {
    "faw_b70":       {"name": "FAW B70 (ECARX)",      "connection": "wireless", "build": _faw_ops},
    "dongfeng_mage": {"name": "Dongfeng Aeolus MAGE", "connection": "usb",      "build": _mage_ops},
}


# --------------------------------------------------------------------------- #
#  Short-lived signed download URLs
# --------------------------------------------------------------------------- #
def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def sign_url(file: str, rid: str, hmac_key: bytes, ttl: int = 900,
             now: int | None = None) -> str:
    """Relative signed URL: /dl/<file>?rid=..&exp=..&sig=.. valid for ttl seconds."""
    exp = int(now if now is not None else time.time()) + ttl
    msg = f"{file}\n{rid}\n{exp}".encode()
    sig = _b64url(hmac.new(hmac_key, msg, hashlib.sha256).digest())
    return f"/dl/{file}?rid={rid}&exp={exp}&sig={sig}"


def verify_url(file: str, rid: str, exp: str, sig: str, hmac_key: bytes,
               now: int | None = None) -> tuple[bool, str]:
    """Constant-time check of a signed download URL. Returns (ok, reason)."""
    if file not in PAYLOAD:
        return (False, "unknown file")
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return (False, "bad exp")
    if (now if now is not None else time.time()) > exp_i:
        return (False, "expired")
    msg = f"{file}\n{rid}\n{exp_i}".encode()
    want = _b64url(hmac.new(hmac_key, msg, hashlib.sha256).digest())
    if not hmac.compare_digest(want, sig or ""):
        return (False, "bad signature")
    return (True, "ok")


def build_plan(profile_id: str, rid: str, hmac_key: bytes, ttl: int = 900,
               now: int | None = None) -> dict:
    """The full session plan: metadata + ops with signed URLs injected."""
    rec = RECIPES.get(profile_id)
    if not rec:
        raise KeyError(f"unknown profile {profile_id!r}")
    ops = rec["build"]()
    for op in ops:
        if op["op"] == "install":
            op["url"] = sign_url(op["file"], rid, hmac_key, ttl, now)
    return {
        "profile": profile_id,
        "name": rec["name"],
        "connection": rec["connection"],
        "ops": ops,
        "expires_in": ttl,
    }
