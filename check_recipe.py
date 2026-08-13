"""
Guard against drift between the two copies of the recipe.

The desktop app's recipe lives in app/profiles.py; the web backend's copy lives
in server_vps/plan.py (it must, so the browser carries none of it). They MUST
agree on the security-critical values — payload hashes above all, since a wrong
pin means the SHA-256 check rejects a good download or, worse, a mismatch slips
through on one path but not the other.

Run before shipping either side:  python check_recipe.py
Exit 0 = in sync, 1 = drift (printed).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "server_vps"))

from app import profiles          # noqa: E402
import plan                       # noqa: E402


def main() -> int:
    problems = []

    # 1. payload hashes identical and same file set
    desktop = {s["file"]: s["sha256"]
               for p in profiles.PROFILES.values() for s in p["steps"]}
    if set(desktop) != set(plan.PAYLOAD):
        problems.append(f"file sets differ: {set(desktop) ^ set(plan.PAYLOAD)}")
    for f, h in desktop.items():
        if plan.PAYLOAD.get(f) != h:
            problems.append(f"hash drift for {f}")

    # 2. every profile the desktop knows is buildable server-side
    for pid in profiles.PROFILES:
        if pid not in plan.RECIPES:
            problems.append(f"profile {pid} missing from server plan")

    # 3. install flags per file match between the two recipes
    for pid, rec in plan.RECIPES.items():
        server_flags = {o["file"]: o["flags"]
                        for o in rec["build"]() if o["op"] == "install"}
        desktop_flags = {s["file"]: profiles.get(pid).get("install_flags", ["-r", "-d"])
                         for s in profiles.get(pid)["steps"]}
        for f, fl in server_flags.items():
            if desktop_flags.get(f) != fl:
                problems.append(f"{pid}: install flags for {f} differ "
                                f"({fl} vs {desktop_flags.get(f)})")

    if problems:
        print("RECIPE DRIFT:")
        for p in problems:
            print("  ✗ " + p)
        return 1
    print("✓ desktop (app/profiles.py) and web (server_vps/plan.py) recipes agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
