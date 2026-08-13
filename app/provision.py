"""
The provisioning flow. Reproduces EXACTLY what we did by hand on each unit.

The head unit is auto-detected and the matching profile from `profiles.py`
drives everything — payload, unlock work, post-install steps. Two units are
supported today:

FAW B70 (Android 9)
  1. Back Button (nu.back.button)       install → grant overlay → enable a11y
  2. FreeTube (freetube.com)            install
  3. Wi-Fi shortcut (com.wifi.shortcut) install
  4. Yandex Navi (ru.yandex.yandexnavi) install → grant perms
  5. Patched launcher (…dlife6.launcher) install as system update → force-stop
  Apps go in BEFORE the launcher, because the launcher's tiles launch those
  packages by name — they must already be present. Every APK is pre-signed with
  the AOSP platform key the unit's apkauth whitelist demands.

Dongfeng Aeolus MAGE (Android 11)
  0. clear `persist.apk.sign.verify` (the unit rejects foreign certs otherwise)
  1. FreeTube (freetube.com)            install
  2. Yandex Navi (ru.yandex.yandexnavi) install → grant perms
  3. write both into the launcher's `allApp` table, then pulse the settings key
     the launcher observes so it reloads the menu in place.
  Nothing is re-signed here: the unlock in step 0 is what makes the installs
  work. See docs/DONGFENG_MAGE.md.

Every APK is downloaded from config.APK_BASE_URL and checked against a pinned
sha256 before it is installed.
"""
from __future__ import annotations
from pathlib import Path
from typing import Callable

from . import engine, config, download, profiles

Log = Callable[[str], None]

# Kept as module-level names so existing callers/imports keep working.
BACK_A11Y = profiles.BACK_A11Y
NAVI_PERMS = profiles.NAVI_PERMS
LAUNCHER_PKG = profiles.FAW_LAUNCHER_PKG

# Default listing for UI built before a device is detected.
STEPS = profiles.FAW_STEPS


def steps_for(profile: dict | None = None) -> list[dict]:
    """The ordered payload for a profile (defaults to FAW, as before)."""
    return (profile or profiles.get(profiles.DEFAULT_PROFILE))["steps"]


# ---- install one already-prepared apk (no re-signing at runtime) ----------- #
def _install(apk: Path, serial: str, log: Log, flags: list[str]) -> bool:
    cp = engine._adb(["install", *flags, str(apk)], log, serial=serial, timeout=900)
    blob = cp.stdout + cp.stderr
    if "Success" in blob:
        return True
    log("  ✗ install failed:\n  " + blob.strip().replace("\n", "\n  "))
    if "DF APK cert incorrect" in blob:
        log("  → the unit's signature check is still active; the unlock step "
            "did not take effect.")
    return False


# ---- the whole flow -------------------------------------------------------- #
def provision(serial: str, log: Log, profile: dict | None = None) -> bool:
    base = config.APK_BASE_URL.strip()
    if not base or "your-cloud-host" in base:
        log("✗ Cloud URL not configured (config.APK_BASE_URL). "
            "Set it to the folder where the APKs are hosted.")
        return False
    if not base.endswith("/"):
        base += "/"

    if profile is None:
        profile, props = profiles.detect(serial, log)
        log(f"Head unit: {profile['name']} "
            f"({props.get('model','?')} · Android {props.get('android','?')})")

    steps = profile["steps"]
    flags = profile.get("install_flags", ["-r", "-d"])
    post_map = profile.get("post", {})

    # Unit-specific unlock BEFORE anything is installed.
    prepare = profile.get("prepare")
    if prepare and not prepare(serial, log):
        log("✗ Could not prepare the head unit — nothing was installed.")
        return False

    dl = download.download_dir()
    total = len(steps)
    all_ok = True
    log("\nDownloading payload from the cloud and installing…")
    for i, step in enumerate(steps, 1):
        log(f"\n[{i}/{total}] {step['name']}  ({step['pkg']})")
        url = base + step["file"]
        dest = dl / step["file"]
        log("  · downloading…")
        if not download.fetch(url, dest, step["sha256"], log, step.get("size", 0)):
            all_ok = False
            log(f"  ✗ {step['name']}: download/verify failed — skipping.")
            continue
        # The B70 is provisioned over Wi-Fi and the Navi payload is ~100 MB —
        # that push is where a link drops. Re-check the transport before
        # sending rather than burning the download on a dead socket. (On the
        # MAGE's USB cable this is a no-op.)
        if not engine.is_alive(serial):
            log("  · connection dropped — reconnecting…")
            if not engine.reconnect(serial, log, timeout=60):
                all_ok = False
                log(f"  ✗ {step['name']}: head unit unreachable — skipping.")
                continue

        log("  · installing…")
        if not _install(dest, serial, log, flags):
            all_ok = False
            log(f"  ✗ {step['name']} failed — continuing with the rest.")
            continue
        log(f"  ✓ installed {step['pkg']}")
        post = step.get("post")
        if post and post in post_map:
            try:
                post_map[post](serial, log)
            except Exception as e:
                log(f"  ! post-step warning: {e}")

    # Unit-specific wrap-up (e.g. adding the apps to the Dongfeng menu).
    finish = profile.get("finish")
    if finish:
        try:
            if not finish(serial, log):
                all_ok = False
        except Exception as e:
            all_ok = False
            log(f"  ! finish-step failed: {e}")

    # remove the freshly-downloaded APKs — they are pulled again next run.
    download.cleanup()

    log("\n" + ("✓ All done. Reboot the head unit if the tiles don't appear immediately."
               if all_ok else
               "Finished with some failures — see the log above."))
    return all_ok
