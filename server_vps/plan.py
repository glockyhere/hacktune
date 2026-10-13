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
import json
import time
from pathlib import Path

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
    "df04_backbutton.apk": "1ea675b78b7fa3ada1073910a00342738cf5ccea7c34836d7891a54269305b36",
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
    # NOT READ_PHONE_STATE: neither Navi build declares it, so `pm grant`
    # raises SecurityException. Confirmed on a MAGE 2026-08-24 and by
    # reading both manifests. READ_EXTERNAL_STORAGE is absent from the
    # manifests too but Android implicitly splits it out of
    # WRITE_EXTERNAL_STORAGE, so granting that one does work.
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
        _install("df04_backbutton.apk", G),
        {"op": "shell", "cmd": "appops set nu.back.button SYSTEM_ALERT_WINDOW allow"},
        # append, never overwrite: the unit has its own accessibility services
        {"op": "shell", "cmd": 'cur=$(settings get secure enabled_accessibility_services); case "$cur" in *nu.back.button*) :;; \'\'|null) settings put secure enabled_accessibility_services \'nu.back.button/nu.back.button.service.BackButtonService\';; *) settings put secure enabled_accessibility_services "$cur:nu.back.button/nu.back.button.service.BackButtonService";; esac'},
        {"op": "shell", "cmd": "settings put secure accessibility_enabled 1"},
        # The overlay only starts after the app has been opened once. NOT via
        # `monkey`: on the MAGE that binary is a stub that prints its own
        # argv and exits without launching anything, so the step silently did
        # nothing. `am start` on the resolved activity actually launches it.
        {"op": "shell", "cmd": "am start -n nu.back.button/.activity.WelcomeActivity"},
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


# --------------------------------------------------------------------------- #
#  Dongfeng Aeolus L7 (Qualcomm trinket, Android 10 userdebug, root adb).
#  See docs/DONGFENG_L7.md. Payload pins live in l7/payload.json: 49 Russian
#  RRO overlays (l7ru_<target>.apk), FreeTube with a 64 px top inset (the L7
#  status bar reserves no space), the patched SystemUI that adds a tile per
#  user-installed app to the stock all-apps grid, and the fleet agent launcher.
# --------------------------------------------------------------------------- #
_L7_DIR = Path(__file__).with_name("l7")
_L7_PAYLOAD = json.loads((_L7_DIR / "payload.json").read_text())
PAYLOAD.update(_L7_PAYLOAD)
# SystemUI-tiles is a patch of this exact build's SystemUI: never run elsewhere.
_L7_FIRMWARE = "QKQ1.210910.001/75:userdebug"
_L7_AGENT_DIR = "/data/local/l7agent"


def _l7_agent_ops(fleet: dict) -> list[dict]:
    """Push l7agent.sh + its config and start it via the boot launcher.

    The plan can only `install` APKs, so the script travels as base64 in shell
    ops (small chunks keep every adb command line short) and is checked against
    its SHA-256 on the car before use.
    """
    script = (_L7_DIR / "l7agent.sh").read_bytes()
    b64 = base64.b64encode(script).decode()
    sha = hashlib.sha256(script).hexdigest()
    d, R = _L7_AGENT_DIR, "remote"
    ops = [
        _install("l7_langagent.apk", ["-r"]) | {"phase": R},
        {"op": "shell", "phase": R,
         "cmd": f"mkdir -p {d} && chmod 777 {d} && : > {d}/l7agent.b64"},
    ]
    ops += [{"op": "shell", "phase": R, "cmd": f"printf '%s' '{b64[i:i + 2000]}' >> {d}/l7agent.b64"}
            for i in range(0, len(b64), 2000)]
    ops += [
        {"op": "shell", "phase": R,
         "cmd": f"base64 -d {d}/l7agent.b64 > {d}/l7agent.sh && rm -f {d}/l7agent.b64 && "
                f"chmod 755 {d}/l7agent.sh && "
                f"[ \"$(sha256sum {d}/l7agent.sh | cut -d' ' -f1)\" = {sha} ] || "
                "echo 'Error: language agent script corrupted'"},
        # A car that already runs the agent (it bought the other L7 package
        # first) gets the same token again; stop the old instance so exactly one
        # agent polls. Its trap removes the lock; rm is for a stale one.
        {"op": "shell", "phase": R,
         "cmd": f"printf 'SERVER=%s\\nTOKEN=%s\\n' '{fleet['server']}' '{fleet['token']}' > {d}/config"
                f" && chmod 644 {d}/config && "
                f"{{ [ -f {d}/lock.d/pid ] && kill $(cat {d}/lock.d/pid) 2>/dev/null; sleep 1; "
                f"rm -rf {d}/lock.d; }}"},
        {"op": "shell", "phase": R,
         "cmd": "am start-foreground-service -n uz.l7ru.langagent/.AgentService"},
    ]
    return ops


# The L7 is sold as two separate packages. Each starts with the same gate and
# ends with the agent (when the dashboard is up) and a restart.
_L7_GATE = [
    {"op": "root"},
    {"op": "require", "prop": "ro.build.fingerprint", "contains": _L7_FIRMWARE,
     "message": "This head unit runs a firmware version Axolotl doesn't support yet. "
                "Nothing was installed. Message us with a photo of its software version."},
]


def _l7_finish(ctx: dict | None) -> list[dict]:
    fleet = (ctx or {}).get("fleet")
    return [
        # remote language control (seller's fleet dashboard); skipped if it's down
        *(_l7_agent_ops(fleet) if fleet else []),
        # restart so the changes appear. Delayed and detached: the browser marks
        # the session done and unlinks before the car goes down.
        {"op": "shell", "phase": "restart",
         "cmd": "setsid sh -c 'sleep 20; reboot' </dev/null >/dev/null 2>&1 &"},
    ]


def _l7_ru_ops(ctx: dict | None = None) -> list[dict]:
    """Russian interface: overlays live in /data, the system partitions are untouched."""
    overlays = sorted(f for f in _L7_PAYLOAD if f.startswith("l7ru_"))
    L = "language"
    return [
        *_L7_GATE,
        *[_install(f, ["-r"]) | {"phase": L} for f in overlays],
        {"op": "shell", "phase": L,
         "cmd": "for p in $(cmd overlay list | grep -o 'uz\\.l7ru\\.overlay\\.[A-Za-z0-9_.]*'); "
                "do cmd overlay enable --user 0 $p; done"},
        {"op": "setprop", "phase": L, "key": "persist.sys.locale", "value": "ru-RU"},
        {"op": "settings", "phase": L, "ns": "system", "key": "system_locales", "value": "ru-RU"},
        *_l7_finish(ctx),
    ]


def _l7_apps_ops(ctx: dict | None = None) -> list[dict]:
    """Navi, Antiradar, FreeTube + their tiles in the stock all-apps grid."""
    G = ["-r", "-g"]
    M = "menu"
    return [
        *_L7_GATE,
        # Navi and Antiradar are the MAGE builds: original signatures
        _install("df02_yandexnavi.apk", G),
        *_grant("ru.yandex.yandexnavi"),
        _install("df03_antiradar.apk", G),
        *[{"op": "shell", "cmd": f"pm grant com.mybedy.antiradar {p}"} for p in _ANTIRADAR_PERMS],
        {"op": "shell", "phase": "apps", "cmd": "appops set com.mybedy.antiradar SYSTEM_ALERT_WINDOW allow"},
        _install("l7_freetube.apk", ["-r"]),
        # all-apps tiles: SystemUI is persistent, so only a STAGED install may
        # update it; it applies on the next boot. Drop any half-finished earlier
        # staged session first, or the new one is refused.
        {"op": "shell", "phase": M,
         "cmd": "for id in $(pm get-stagedsessions | sed -n "
                "'s/.*sessionId = \\([0-9]*\\); isStaged = true; isStagedSessionReady = true.*/\\1/p'); "
                "do pm install-abandon $id; done"},
        _install("l7_systemui.apk", ["--staged", "--enable-rollback"]) | {"phase": M},
        *_l7_finish(ctx),
    ]


_L7_RU_FILES = {f for f in _L7_PAYLOAD if f.startswith("l7ru_")} | {"l7_langagent.apk"}
_L7_APPS_FILES = {"l7_freetube.apk", "l7_systemui.apk", "l7_langagent.apk"}

RECIPES = {
    "faw_b70":       {"name": "FAW B70 (ECARX)",      "connection": "wireless", "build": _faw_ops},
    "dongfeng_mage": {"name": "Dongfeng Aeolus MAGE", "connection": "usb",      "build": _mage_ops},
    # The two L7 packages are separate purchases: an activation is only good for
    # the package it was requested for (its token's `model`, set by the client's
    # picker), which main.py enforces. Web only: no desktop profile
    # (check_recipe.py skips web_only recipes' own files).
    "dongfeng_l7_ru":   {"name": "Dongfeng Aeolus L7 · Russian interface", "connection": "usb",
                         "build": _l7_ru_ops, "ctx": True, "web_only": True, "files": _L7_RU_FILES,
                         "model": "L7 RU",
                         "done": "The head unit restarts by itself in about 20 seconds and "
                                 "comes back in Russian."},
    "dongfeng_l7_apps": {"name": "Dongfeng Aeolus L7 · Apps", "connection": "usb",
                         "build": _l7_apps_ops, "ctx": True, "web_only": True, "files": _L7_APPS_FILES,
                         "model": "L7 Apps",
                         "done": "The head unit restarts by itself in about 20 seconds. Navigator, "
                                 "ContraCam and FreeTube then have their own tiles under All apps."},
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
               now: int | None = None, ctx: dict | None = None) -> dict:
    """The full session plan: metadata + ops with signed URLs injected.

    ctx carries per-session values for recipes that declare "ctx" (the L7's
    fleet token); the others take no arguments.
    """
    rec = RECIPES.get(profile_id)
    if not rec:
        raise KeyError(f"unknown profile {profile_id!r}")
    ops = rec["build"](ctx) if rec.get("ctx") else rec["build"]()
    for op in ops:
        if op["op"] == "install":
            op["url"] = sign_url(op["file"], rid, hmac_key, ttl, now)
    return {
        "profile": profile_id,
        "name": rec["name"],
        "connection": rec["connection"],
        "ops": ops,
        "expires_in": ttl,
        **({"done": rec["done"]} if rec.get("done") else {}),
    }
