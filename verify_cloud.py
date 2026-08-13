"""
Check that the cloud host is serving all payload APKs correctly.

    python verify_cloud.py                 # uses APK_BASE_URL from app/config.py
    python verify_cloud.py https://.../ba/ # or pass a base URL to test

Every profile's payload is checked (FAW B70 + Dongfeng MAGE). For each file it
downloads and checks the pinned SHA-256, so a green run means the program will
work end-to-end for buyers.
"""
import sys
import tempfile
from pathlib import Path

from app import config, download, profiles


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else config.APK_BASE_URL).strip()
    if not base or "your-cloud-host" in base:
        print("No cloud URL. Pass one as an argument or set APK_BASE_URL in app/config.py.")
        return 2
    if not base.endswith("/"):
        base += "/"

    print(f"Base URL: {base}\n")
    tmp = Path(tempfile.mkdtemp())
    ok = True
    seen: set[str] = set()
    for prof in profiles.PROFILES.values():
        print(f"── {prof['name']} ──")
        for s in prof["steps"]:
            if s["file"] in seen:       # a file shared by two profiles
                continue
            seen.add(s["file"])
            print(f"• {s['file']}")
            good = download.fetch(base + s["file"], tmp / s["file"], s["sha256"],
                                  lambda m: print("  " + m.strip()), s.get("size", 0))
            ok = ok and good
            print()
    print("RESULT:", "✓ all files present and verified" if ok else "✗ problems above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
