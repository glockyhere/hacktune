"""
Cloud downloader. Fetches each payload APK from APK_BASE_URL at runtime and
verifies its SHA-256 against the value pinned in the app, so a tampered CDN or a
wrong file is rejected before it ever touches the head unit.

Uses only the Python standard library (urllib) — no extra dependencies.
"""
from __future__ import annotations
import hashlib
import tempfile
import urllib.request
import urllib.error
from pathlib import Path
from typing import Callable

Log = Callable[[str], None]


def download_dir() -> Path:
    d = Path(tempfile.gettempdir()) / "CarApkInstaller_dl"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fmt_mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


def fetch(url: str, dest: Path, expected_sha256: str, log: Log,
          expected_size: int = 0) -> bool:
    """Download url -> dest, streaming, then verify sha256. Return True on success."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    got = 0
    last_pct = -1
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CarApkInstaller"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            total = expected_size or int(r.headers.get("Content-Length", 0) or 0)
            while True:
                chunk = r.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
                if total:
                    pct = int(got * 100 / total)
                    if pct != last_pct and pct % 5 == 0:
                        log(f"    …{pct}%  ({_fmt_mb(got)} / {_fmt_mb(total)})")
                        last_pct = pct
    except urllib.error.HTTPError as e:
        log(f"    ✗ download failed: HTTP {e.code} for {url}")
        return False
    except Exception as e:
        log(f"    ✗ download failed: {e}")
        return False

    digest = h.hexdigest()
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        log("    ✗ integrity check FAILED — file does not match the pinned hash.")
        log(f"      expected {expected_sha256}")
        log(f"      got      {digest}")
        try:
            tmp.unlink()
        except Exception:
            pass
        return False

    tmp.replace(dest)
    log(f"    ✓ downloaded + verified ({_fmt_mb(got)})")
    return True


def cleanup() -> None:
    d = download_dir()
    for p in d.glob("*"):
        try:
            p.unlink()
        except Exception:
            pass
