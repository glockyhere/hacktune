"""
Offline license verification — the security core.

Model (industry-standard offline scheme):
  * You generate ONE Ed25519 keypair (keygen/generate_keys.py).
  * The PRIVATE key stays with you and signs license keys. It is never shipped.
  * The PUBLIC key is embedded in the app (config.LICENSE_PUBLIC_KEY) and can
    only *verify*, never *mint*. So a customer cannot forge a key.
  * Every license is bound to the buyer's Machine ID (a hash of stable hardware
    identifiers), so one key will not activate on a different machine.

A license string looks like:  <base64url(payload_json)>.<base64url(signature)>
payload_json = {"mid": <machine id>, "tag": <product tag>,
                "iss": <unix issue time>, "exp": <unix expiry or 0=never>,
                "ref": <free buyer reference>}

Honest limits: this stops key forging and casual key-sharing. It does NOT stop
someone who patches the compiled binary to skip the check. That is true of every
program that runs on the customer's own computer; only server-side validation
removes it. See README "Security model".
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import config


# --------------------------------------------------------------------------- #
#  Machine ID
# --------------------------------------------------------------------------- #
def _windows_machine_guid() -> str:
    try:
        import winreg  # type: ignore
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        )
        val, _ = winreg.QueryValueEx(key, "MachineGuid")
        return str(val)
    except Exception:
        return ""


def _mac_hardware_uuid() -> str:
    try:
        out = subprocess.check_output(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            text=True, stderr=subprocess.DEVNULL, timeout=5,
        )
        for line in out.splitlines():
            if "IOPlatformUUID" in line:
                return line.split('"')[-2]
    except Exception:
        pass
    return ""


def machine_id() -> str:
    """A stable, non-reversible fingerprint of this computer."""
    parts = [
        platform.system(),
        platform.machine(),
        _windows_machine_guid(),
        _mac_hardware_uuid(),
        str(getattr(os, "getlogin", lambda: "")()) if False else "",
    ]
    # MAC address of the primary interface as a fallback contributor.
    try:
        import uuid
        parts.append(f"{uuid.getnode():012x}")
    except Exception:
        pass
    raw = "|".join(p for p in parts if p)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()
    # Present as human-friendly grouped id, e.g. ABCD-EF12-3456-7890
    short = digest[:16]
    return "-".join(short[i:i + 4] for i in range(0, 16, 4))


# --------------------------------------------------------------------------- #
#  License store
# --------------------------------------------------------------------------- #
def _license_path() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    d = Path(base) / "CarApkInstaller"
    d.mkdir(parents=True, exist_ok=True)
    return d / "license.key"


def save_license(license_str: str) -> None:
    _license_path().write_text(license_str.strip(), encoding="utf-8")


def load_license() -> str | None:
    p = _license_path()
    if p.exists():
        s = p.read_text(encoding="utf-8").strip()
        return s or None
    return None


# --------------------------------------------------------------------------- #
#  Verification
# --------------------------------------------------------------------------- #
def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


class LicenseResult:
    def __init__(self, ok: bool, reason: str = "", payload: dict | None = None):
        self.ok = ok
        self.reason = reason
        self.payload = payload or {}


def verify_license(license_str: str, *, mid: str | None = None) -> LicenseResult:
    """Verify a license string against the embedded public key + this machine."""
    if not license_str:
        return LicenseResult(False, "No license present.")
    pub_b64 = config.LICENSE_PUBLIC_KEY.strip()
    if not pub_b64 or pub_b64.startswith("PASTE_"):
        return LicenseResult(False, "App is not configured with a license public key.")
    try:
        pub = Ed25519PublicKey.from_public_bytes(_b64url_decode(pub_b64))
    except Exception:
        return LicenseResult(False, "Invalid public key in app configuration.")

    try:
        payload_b64, sig_b64 = license_str.strip().split(".", 1)
        payload_bytes = _b64url_decode(payload_b64)
        signature = _b64url_decode(sig_b64)
    except Exception:
        return LicenseResult(False, "License key is malformed.")

    try:
        pub.verify(signature, payload_bytes)
    except InvalidSignature:
        return LicenseResult(False, "License signature is invalid (key not issued by us).")
    except Exception:
        return LicenseResult(False, "License signature could not be checked.")

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return LicenseResult(False, "License payload is corrupt.")

    if payload.get("tag") != config.LICENSE_PRODUCT_TAG:
        return LicenseResult(False, "License is for a different product.")

    this_mid = mid or machine_id()
    if payload.get("mid") != this_mid:
        return LicenseResult(False, "License is bound to a different machine.")

    exp = int(payload.get("exp", 0) or 0)
    if exp and time.time() > exp:
        return LicenseResult(False, "License has expired.")

    return LicenseResult(True, "Valid.", payload)


def current_status() -> LicenseResult:
    """Verify whatever license is stored on disk."""
    return verify_license(load_license() or "")
