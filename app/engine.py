"""
Device + APK engine. Ports the working flow:
  connect (with Wi-Fi/mDNS reconnect) -> platform-sign (satisfies apkauth)
  -> install. Optional: down-patch APKs that target SDK > 28.

External tools are expected NEXT TO the .exe in a `tools/` folder:
  tools/platform-tools/adb(.exe)
  tools/build-tools/apksigner(.bat)   tools/build-tools/zipalign(.exe)
  tools/apktool.jar
  tools/jre/bin/java(.exe)            (or a system Java on PATH)
The public AOSP platform key is bundled inside the app (resources/keys).
"""
from __future__ import annotations
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

Log = Callable[[str], None]
_WIN = os.name == "nt"
_EXE = ".exe" if _WIN else ""


# --------------------------------------------------------------------------- #
#  Paths (dev vs frozen PyInstaller)
# --------------------------------------------------------------------------- #
def _app_dir() -> Path:
    """Folder that holds the running exe (frozen) or the project root (dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _res_dir() -> Path:
    """Bundled read-only resources (inside the exe when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))  # type: ignore[arg-type]
    return Path(__file__).resolve().parent.parent


TOOLS = _app_dir() / "tools"
KEYS = _res_dir() / "resources" / "keys"


def _tool(*parts: str) -> str:
    return str(TOOLS.joinpath(*parts))


def adb_path() -> str:
    p = _tool("platform-tools", f"adb{_EXE}")
    return p if Path(p).exists() else f"adb{_EXE}"


def _java() -> str:
    p = _tool("jre", "bin", f"java{_EXE}")
    return p if Path(p).exists() else f"java{_EXE}"


def _zipalign() -> str:
    p = _tool("build-tools", f"zipalign{_EXE}")
    return p if Path(p).exists() else f"zipalign{_EXE}"


def _apksigner() -> str:
    # apksigner is a jar+launcher; prefer the bundled launcher, else the jar.
    launcher = _tool("build-tools", "apksigner.bat" if _WIN else "apksigner")
    return launcher


def _run(cmd: list[str], log: Log | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    if log:
        log("$ " + " ".join(os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd)))
    flags = 0
    if _WIN:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console popups
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, creationflags=flags
    )


# --------------------------------------------------------------------------- #
#  Device connection
# --------------------------------------------------------------------------- #
def _adb(args: list[str], log: Log | None = None, timeout: int = 300, serial: str | None = None):
    base = [adb_path()]
    if serial:
        base += ["-s", serial]
    return _run(base + args, log, timeout)


def list_devices(log: Log | None = None) -> list[str]:
    cp = _adb(["devices"], log)
    out = cp.stdout.splitlines()
    devs = []
    for line in out[1:]:
        line = line.strip()
        if line and "\tdevice" in line:
            devs.append(line.split("\t")[0])
    return devs


def _mdns_ip(log: Log | None = None) -> str | None:
    try:
        cp = _adb(["mdns", "services"], log, timeout=15)
        m = re.search(r"(\d+\.\d+\.\d+\.\d+:\d+)", cp.stdout)
        return m.group(1) if m else None
    except Exception:
        return None


def ensure_device(log: Log) -> str | None:
    """Return a ready device serial, reconnecting over Wi-Fi/mDNS if needed."""
    devs = list_devices(log)
    if devs:
        return devs[0]
    log("No device. Searching the network (mDNS)…")
    ip = _mdns_ip(log)
    if ip:
        log(f"Found {ip}, connecting…")
        _adb(["connect", ip], log, timeout=20)
        time.sleep(1)
        devs = list_devices(log)
        if devs:
            return devs[0]
    log("No device found. Make sure the head unit has Wireless ADB enabled and "
        "is on the same network, then press Retry.")
    return None


def is_wireless(serial: str) -> bool:
    """True for a network transport, false for USB.

    Two shapes occur: a plain `192.168.1.50:5555`, and the mDNS service name
    Android 11 wireless debugging reports, `adb-<id>-XXXX._adb-tls-connect._tcp`.
    """
    s = serial or ""
    return bool(re.fullmatch(r"\d+\.\d+\.\d+\.\d+:\d+", s)) or "_tcp" in s


def is_alive(serial: str) -> bool:
    try:
        cp = _adb(["shell", "echo ok"], None, serial=serial, timeout=10)
        return "ok" in (cp.stdout or "")
    except Exception:
        return False


def reconnect(serial: str, log: Log | None = None, timeout: int = 60) -> bool:
    """Wait for a device to come back after adbd restarts (e.g. `adb root`).

    Over USB the transport re-enumerates on its own. Over Wi-Fi the socket is
    gone and the device drops off `adb devices` entirely, so it must be
    re-connected by address before anything else will work.
    """
    deadline = time.time() + timeout
    wireless = is_wireless(serial)
    while time.time() < deadline:
        if wireless:
            # ip:port can be dialled straight back; an mDNS name is re-advertised
            # by the unit, so re-resolve it instead.
            if ":" in serial and "_tcp" not in serial:
                _adb(["connect", serial], None, timeout=15)
            else:
                ip = _mdns_ip(None)
                if ip:
                    _adb(["connect", ip], None, timeout=15)
        if is_alive(serial):
            return True
        time.sleep(1.5)
    if log:
        log(f"  ✗ device {serial} did not come back within {timeout}s.")
        if wireless:
            log("    If the unit's IP changed, press Detect / Reconnect to find "
                "it again, then re-run the install.")
    return False


def device_info(serial: str, log: Log | None = None) -> dict:
    props = {}
    cp = _adb(["shell",
               "getprop ro.product.model; getprop ro.build.version.release; "
               "getprop ro.build.version.sdk"], log, serial=serial, timeout=20)
    lines = [l.strip() for l in cp.stdout.splitlines() if l.strip()]
    keys = ["model", "android", "sdk"]
    for k, v in zip(keys, lines):
        props[k] = v
    return props


# --------------------------------------------------------------------------- #
#  Signing + install
# --------------------------------------------------------------------------- #
def platform_sign(src_apk: str, log: Log) -> str:
    """zipalign + sign with the trusted AOSP platform key. Returns signed path."""
    src = Path(src_apk)
    out = Path(tempfile.gettempdir()) / (src.stem + "__signed.apk")
    aligned = Path(tempfile.gettempdir()) / (src.stem + "__aligned.apk")

    cp = _run([_zipalign(), "-f", "-p", "4", str(src), str(aligned)], log, timeout=300)
    if cp.returncode != 0:
        raise RuntimeError("zipalign failed:\n" + (cp.stderr or cp.stdout))

    pk8 = str(KEYS / "platform.pk8")
    cert = str(KEYS / "platform.x509.pem")
    signer = _apksigner()
    if Path(signer).exists():
        cmd = [signer, "sign", "--key", pk8, "--cert", cert, "--out", str(out), str(aligned)]
    else:
        # fall back to invoking the apksigner jar directly via java
        jar = _tool("build-tools", "lib", "apksigner.jar")
        cmd = [_java(), "-jar", jar, "sign", "--key", pk8, "--cert", cert,
               "--out", str(out), str(aligned)]
    cp = _run(cmd, log, timeout=600)
    if cp.returncode != 0:
        raise RuntimeError("apksigner failed:\n" + (cp.stderr or cp.stdout))
    return str(out)


_INVALID = "INSTALL_FAILED_INVALID_APK"
_OLDER = "INSTALL_FAILED_OLDER_SDK"


def install_apk(apk: str, serial: str, log: Log, *, downpatch: bool = True) -> bool:
    """Platform-sign then install. Returns True on success."""
    name = os.path.basename(apk)
    log(f"── {name} ──")
    try:
        log("Signing with trusted platform key…")
        signed = platform_sign(apk, log)
    except Exception as e:
        log(f"✗ Signing failed: {e}")
        return False

    log("Installing…")
    cp = _adb(["install", "-r", "-d", signed], log, serial=serial, timeout=600)
    blob = (cp.stdout + cp.stderr)
    if "Success" in blob:
        log(f"✓ Installed: {name}")
        return True

    if _OLDER in blob:
        log("✗ This APK needs a newer Android than the head unit (min SDK > 28). "
            "Get an older build of the app.")
        return False

    if _INVALID in blob and downpatch:
        log("Parser rejected it (targets a newer SDK). Trying to down-patch to API 28…")
        patched = _downpatch_sdk(apk, log)
        if patched:
            return install_apk(patched, serial, log, downpatch=False)

    log("✗ Install failed:\n" + blob.strip())
    return False


# --------------------------------------------------------------------------- #
#  Optional: down-patch target SDK / strip <queries> for API-28 parsers
# --------------------------------------------------------------------------- #
def _downpatch_sdk(apk: str, log: Log) -> str | None:
    jar = _tool("apktool.jar")
    if not Path(jar).exists():
        log("  apktool.jar not present in tools/ — cannot down-patch.")
        return None
    work = Path(tempfile.mkdtemp())
    dec = work / "dec"
    try:
        cp = _run([_java(), "-jar", jar, "d", "-f", "-o", str(dec), apk], log, timeout=600)
        if cp.returncode != 0:
            log("  apktool decode failed."); return None
        yml = dec / "apktool.yml"
        txt = yml.read_text(encoding="utf-8")
        txt = re.sub(r"targetSdkVersion:\s*'?\d+'?", "targetSdkVersion: '28'", txt)
        yml.write_text(txt, encoding="utf-8")
        man = dec / "AndroidManifest.xml"
        m = man.read_text(encoding="utf-8")
        m = re.sub(r"[ \t]*<queries>.*?</queries>\s*", "", m, flags=re.S)
        man.write_text(m, encoding="utf-8")
        out = str(work / "patched.apk")
        cp = _run([_java(), "-jar", jar, "b", str(dec), "-o", out], log, timeout=900)
        if cp.returncode != 0 or not Path(out).exists():
            log("  apktool rebuild failed."); return None
        log("  Down-patched to API 28.")
        return out
    except Exception as e:
        log(f"  Down-patch error: {e}")
        return None


def install_folder(folder: str, serial: str, log: Log) -> tuple[int, int]:
    apks = sorted(str(p) for p in Path(folder).glob("*.apk"))
    if not apks:
        log("No .apk files found in the selected folder.")
        return (0, 0)
    ok = 0
    for a in apks:
        if install_apk(a, serial, log):
            ok += 1
    log(f"\nDone: {ok}/{len(apks)} installed.")
    return (ok, len(apks))
