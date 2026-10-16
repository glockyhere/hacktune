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
import time
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

    # like the web client: the unit's serial keys its fleet enrolment
    serial = adb(a.serial, "shell", "getprop ro.serialno").strip()
    req = urllib.request.Request(f"{a.api}/api/plan", method="POST",
                                 data=json.dumps({"token": a.token, "profile": a.profile,
                                                  "serial": serial}).encode(),
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
            for attempt in range(4):        # the Mac's own link drops too
                try:
                    data = urllib.request.urlopen(a.api + op["url"], timeout=300).read()
                    if hashlib.sha256(data).hexdigest() == op["sha256"]:
                        break
                    print(tag, "checksum mismatch, downloading again")
                except OSError as e:
                    print(tag, f"download failed ({e}), retrying")
                time.sleep(5 * (attempt + 1))
            else:
                sys.exit(f"{tag}: could not download {op['file']}")
            with tempfile.NamedTemporaryFile(suffix=".apk", delete=False) as f:
                f.write(data)
            remote = op["to"] if k == "push" else f"/data/local/tmp/carapk_plan_{i}.apk"
            # a USB drop answers with nothing: wait for the unit and redo the step
            # (every step is idempotent), as the web client does
            for attempt in range(3):
                adb(a.serial, "wait-for-device")
                pushed = subprocess.run(["adb"] + (["-s", a.serial] if a.serial else [])
                                        + ["push", f.name, remote], capture_output=True, text=True)
                if pushed.returncode != 0:
                    print(tag, "push dropped, retrying"); time.sleep(5); continue
                if k == "push":
                    break
                out = sh(f"pm install {' '.join(op.get('flags') or [])} {remote}")
                sh(f"rm -f {remote}")
                if "Success" in out or out.strip():
                    break
                print(tag, "no answer from the unit, retrying"); time.sleep(5)
            os.unlink(f.name)
            if k == "push":
                if pushed.returncode != 0:
                    sys.exit(f"{tag}: could not copy {op['file']}")
                print(tag, op["file"], "copied")
                continue
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
