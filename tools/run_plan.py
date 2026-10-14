"""
Run a server-issued plan against a USB car with plain adb — the same op
semantics as webapp/app.js execOp(), for certifying a recipe without a browser.

    python tools/run_plan.py --token <activation token> --profile dongfeng_l7 \
        [--api https://api.axolotl.uz] [--serial <adb serial>] [--from N] [--dry-run]

Downloads go through the plan's signed /dl URLs and are SHA-256 checked, so this
also proves the payload on the VPS. It never consumes the token.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

BAD = ("Exception", "Failure", "error:", "Error:", "Denied")


def adb(serial: str | None, *args: str) -> str:
    cmd = ["adb"] + (["-s", serial] if serial else []) + list(args)
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--api", default="https://api.axolotl.uz")
    ap.add_argument("--serial")
    ap.add_argument("--from", dest="start", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    req = urllib.request.Request(f"{a.api}/api/plan", method="POST",
                                 data=json.dumps({"token": a.token, "profile": a.profile}).encode(),
                                 headers={"content-type": "application/json"})
    plan = json.load(urllib.request.urlopen(req, timeout=60))
    ops = plan["ops"]
    print(f"plan {plan['profile']}: {len(ops)} ops")
    sh = lambda c: adb(a.serial, "shell", c)  # noqa: E731

    for i, op in enumerate(ops[a.start:], a.start):
        tag = f"[{i + 1:02d}/{len(ops)}] {op.get('phase', '')} {op['op']}"
        if a.dry_run:
            print(tag, op.get("file") or op.get("cmd") or op.get("key") or op.get("prop") or "")
            continue
        k = op["op"]
        if k == "root":
            if sh("id -u").strip() != "0":
                sys.exit(f"{tag}: not root")
        elif k == "require":
            v = sh(f"getprop {op['prop']}").strip()
            if op["contains"] not in v:
                sys.exit(f"{tag}: {op['message']} ({v})")
        elif k == "setprop":
            sh(f"setprop {op['key']} {op['value']}")
            if sh(f"getprop {op['key']}").strip() != op["value"]:
                sys.exit(f"{tag}: setprop rejected")
        elif k in ("install", "push"):
            data = urllib.request.urlopen(a.api + op["url"], timeout=300).read()
            if hashlib.sha256(data).hexdigest() != op["sha256"]:
                sys.exit(f"{tag}: checksum mismatch for {op['file']}")
            with tempfile.NamedTemporaryFile(suffix=".apk", delete=False) as f:
                f.write(data)
            remote = op["to"] if k == "push" else f"/data/local/tmp/carapk_plan_{i}.apk"
            adb(a.serial, "push", f.name, remote)
            os.unlink(f.name)
            if k == "push":
                print(tag, op["file"], "copied")
                continue
            out = sh(f"pm install {' '.join(op.get('flags') or [])} {remote}")
            sh(f"rm -f {remote}")
            if "Success" not in out:
                sys.exit(f"{tag}: install {op['file']} failed: {out.strip()}")
            print(tag, op["file"], "installed")
            continue
        elif k in ("shell", "sqlite", "settings"):
            cmd = (f"sqlite3 {op['db']} '{op['stmt']}'" if k == "sqlite"
                   else f"settings put {op['ns']} {op['key']} {op['value']}" if k == "settings"
                   else op["cmd"])
            out = sh(cmd)
            if any(b in out for b in BAD):
                if op.get("must"):
                    sys.exit(f"{tag}: {op.get('message', 'required step failed')} ({out.strip()[:200]})")
                print(tag, "WARN", out.strip().splitlines()[0][:100])
                continue
        else:
            sys.exit(f"{tag}: unknown op")
        print(tag, "ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
