"""
Enrol an Aeolus L7 in the seller's language fleet (fleet.staldern.com) when its
plan is issued, so the seller can switch that car's UI language RU/ZH remotely.

  FLEET_URL        base URL of the fleet server (e.g. https://fleet.staldern.com)
  FLEET_ADMIN_KEY  its admin key (X-Admin-Key)

One enrolment per CAR, keyed by VIN: the two L7 packages are separate purchases,
and a car that buys both, or a buyer who relinks and fetches the plan again, must
get the SAME token, never a duplicate dashboard row. (No VIN → keyed by the
activation instead.) If the fleet server is unset or unreachable, enrol() returns
None and the plan simply leaves the agent out; a paid install must never fail
because of the seller's dashboard.
"""
from __future__ import annotations
import json
import os
import sqlite3
import urllib.request

FLEET_URL = os.environ.get("FLEET_URL", "").rstrip("/")
FLEET_ADMIN_KEY = os.environ.get("FLEET_ADMIN_KEY", "")


class Fleet:
    def __init__(self, db_path: str):
        self.db_path = db_path
        with sqlite3.connect(db_path) as c:
            c.execute("CREATE TABLE IF NOT EXISTS fleet_cars("
                      "rid TEXT PRIMARY KEY, car_id TEXT, token TEXT, created INTEGER)")
            if "vin" not in [r[1] for r in c.execute("PRAGMA table_info(fleet_cars)")]:
                c.execute("ALTER TABLE fleet_cars ADD COLUMN vin TEXT")

    def _known(self, key: str) -> str | None:
        with sqlite3.connect(self.db_path) as c:
            row = c.execute("SELECT token FROM fleet_cars WHERE vin=? ORDER BY created LIMIT 1",
                            (key,)).fetchone()
        return row[0] if row else None

    def enrol(self, rid: str, vin: str, name: str) -> dict | None:
        """{"server": FLEET_URL, "token": ...} for this car, or None."""
        if not (FLEET_URL and FLEET_ADMIN_KEY):
            return None
        key = (vin or "").strip().upper() or f"rid:{rid}"
        token = self._known(key)
        if token:
            return {"server": FLEET_URL, "token": token}
        try:
            req = urllib.request.Request(
                f"{FLEET_URL}/api/v1/admin/cars", method="POST",
                data=json.dumps({"name": name[:80]}).encode(),
                # Cloudflare in front of the fleet answers 403 (error 1010) to
                # urllib's default "Python-urllib/x" user agent: name ourselves
                headers={"X-Admin-Key": FLEET_ADMIN_KEY, "Content-Type": "application/json",
                         "User-Agent": "axolotl-activation/1"})
            with urllib.request.urlopen(req, timeout=10) as r:
                car = json.load(r)
        except Exception as e:  # dashboard down: install without the agent
            print(f"fleet enrol failed for {rid}: {e}", flush=True)
            return None
        with sqlite3.connect(self.db_path) as c:
            c.execute("INSERT OR IGNORE INTO fleet_cars(rid,car_id,token,created,vin) "
                      "VALUES(?,?,?,strftime('%s','now'),?)", (rid, car["id"], car["token"], key))
        # two simultaneous first fetches: both get whichever enrolment came first
        return {"server": FLEET_URL, "token": self._known(key) or car["token"]}
