"""
Enrol an Aeolus L7 in the seller's language fleet (fleet.staldern.com) when its
plan is issued, so the seller can switch that car's UI language RU/ZH remotely.

  FLEET_URL        base URL of the fleet server (e.g. https://fleet.staldern.com)
  FLEET_ADMIN_KEY  its admin key (X-Admin-Key)

One enrolment per activation (rid): a buyer who relinks and fetches the plan again
gets the SAME car token, never a duplicate dashboard row. If the fleet server is
unset or unreachable, enrol() returns None and the plan simply leaves the agent
out; a paid install must never fail because of the seller's dashboard.
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

    def enrol(self, rid: str, name: str) -> dict | None:
        """{"server": FLEET_URL, "token": ...} for this activation, or None."""
        if not (FLEET_URL and FLEET_ADMIN_KEY):
            return None
        with sqlite3.connect(self.db_path) as c:
            row = c.execute("SELECT token FROM fleet_cars WHERE rid=?", (rid,)).fetchone()
        if row:
            return {"server": FLEET_URL, "token": row[0]}
        try:
            req = urllib.request.Request(
                f"{FLEET_URL}/api/v1/admin/cars", method="POST",
                data=json.dumps({"name": name[:80]}).encode(),
                headers={"X-Admin-Key": FLEET_ADMIN_KEY, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                car = json.load(r)
        except Exception as e:  # dashboard down: install without the agent
            print(f"fleet enrol failed for {rid}: {e}", flush=True)
            return None
        with sqlite3.connect(self.db_path) as c:
            c.execute("INSERT OR IGNORE INTO fleet_cars(rid,car_id,token,created) "
                      "VALUES(?,?,?,strftime('%s','now'))", (rid, car["id"], car["token"]))
            # two simultaneous first fetches: both cars get whichever token won
            token = c.execute("SELECT token FROM fleet_cars WHERE rid=?", (rid,)).fetchone()[0]
        return {"server": FLEET_URL, "token": token}
