"""One SQLite writer, bounded observation history, conservative boundary events."""
import json
import hashlib
import sqlite3
import threading
from .model import classify, in_bbox, utc


class Store:
    def __init__(self, path, config):
        self.config = config
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS ships(mmsi TEXT PRIMARY KEY, body TEXT NOT NULL, updated REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS positions(mmsi TEXT, time REAL, lat REAL, lon REAL, speed REAL, PRIMARY KEY(mmsi,time));
          CREATE INDEX IF NOT EXISTS positions_time ON positions(time);
          CREATE TABLE IF NOT EXISTS states(mmsi TEXT, harbour TEXT, body TEXT, PRIMARY KEY(mmsi,harbour));
          CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, mmsi TEXT, harbour TEXT, kind TEXT, time REAL, boundary_hash TEXT);
          CREATE INDEX IF NOT EXISTS events_lookup ON events(harbour,time);
          CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT);
        ''')
        self.db.commit()
        self.last_prune = 0

    def meta(self, key, value):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", (key, json.dumps(value)))
            self.db.commit()

    def metadata(self):
        with self.lock:
            return {row[0]: json.loads(row[1]) for row in self.db.execute("SELECT key,value FROM metadata")}

    def ingest(self, observation):
        with self.lock:
            mmsi = observation["mmsi"]
            row = self.db.execute("SELECT body FROM ships WHERE mmsi=?", (mmsi,)).fetchone()
            ship = json.loads(row[0]) if row else {"mmsi": mmsi}
            stamp = observation["observed_at"]
            key = "position_at" if "position_at" in observation else "static_at"
            if observation.get(key, stamp) <= ship.get(key, -1):
                return False
            previous = dict(ship)
            ship.update(observation)
            # A delayed static report must not make last observed time go backwards.
            ship["observed_at"] = max(stamp, previous.get("observed_at", stamp))
            if "position_at" in observation:
                relevant = [h for h in self.config["harbours"] if in_bbox(ship["lat"], ship["lon"], h["subscription_bbox"])]
                if not relevant:
                    return False
                ship["harbours"] = [h["id"] for h in relevant]
                last_track = self.db.execute("SELECT MAX(time) FROM positions WHERE mmsi=?", (mmsi,)).fetchone()[0]
                if last_track is None or stamp-last_track >= self.config["track_interval_seconds"]:
                    self.db.execute("INSERT OR IGNORE INTO positions VALUES(?,?,?,?,?)", (mmsi, stamp, ship["lat"], ship["lon"], ship.get("speed")))
                for harbour in relevant:
                    self._state(ship, harbour, stamp)
            self.db.execute("INSERT OR REPLACE INTO ships VALUES(?,?,?)", (mmsi, json.dumps(ship), ship["observed_at"]))
            self.db.commit()
            if stamp-self.last_prune > 3600:
                self.prune(stamp)
            return True

    def _state(self, ship, harbour, stamp):
        row = self.db.execute("SELECT body FROM states WHERE mmsi=? AND harbour=?", (ship["mmsi"], harbour["id"])).fetchone()
        old = json.loads(row[0]) if row else None
        within, anchored = classify(ship, harbour)
        boundary_hash = hashlib.sha256(json.dumps({"boundary": harbour["boundary"], "anchorage": harbour["anchorage"]}, sort_keys=True).encode()).hexdigest()[:16]
        gap = old is None or stamp-old["last_seen"] > self.config["transition_gap_seconds"] or old.get("boundary_hash") != boundary_hash
        if gap:
            # No invented arrivals/exits across an observation gap or initial discovery.
            state = {"within": within, "anchored": False, "anchor_since": None, "pending_anchor": stamp if anchored else None, "pending_within": None, "first_seen": stamp, "continuity_since": stamp, "last_seen": stamp, "gap": old is not None}
        else:
            state = old.copy()
            state["last_seen"] = stamp
            if within != old["within"]:
                pending = old.get("pending_within")
                if pending is not None and pending["value"] == within and stamp > pending["time"]:
                    state["within"] = within
                    state["pending_within"] = None
                    self.db.execute("INSERT INTO events(mmsi,harbour,kind,time,boundary_hash) VALUES(?,?,?,?,?)", (ship["mmsi"], harbour["id"], "entry" if within else "exit", stamp, boundary_hash))
                else:
                    state["pending_within"] = {"value": within, "time": stamp}
            else:
                state["pending_within"] = None
            if anchored:
                if old.get("pending_anchor") is None:
                    state["pending_anchor"] = stamp
                elif stamp-old["pending_anchor"] >= 120 and not old["anchored"]:
                    state["anchored"] = True
                    state["anchor_since"] = old["pending_anchor"]
                    self.db.execute("INSERT INTO events(mmsi,harbour,kind,time,boundary_hash) VALUES(?,?,?,?,?)", (ship["mmsi"], harbour["id"], "anchor_observed", stamp, boundary_hash))
            else:
                if old["anchored"]:
                    self.db.execute("INSERT INTO events(mmsi,harbour,kind,time,boundary_hash) VALUES(?,?,?,?,?)", (ship["mmsi"], harbour["id"], "anchor_ended", stamp, boundary_hash))
                state.update(anchored=False, anchor_since=None, pending_anchor=None)
        state["boundary_hash"] = boundary_hash
        self.db.execute("INSERT OR REPLACE INTO states VALUES(?,?,?)", (ship["mmsi"], harbour["id"], json.dumps(state)))

    def prune(self, now):
        cutoff = now-self.config["retention_days"]*86400
        with self.lock:
            self.db.execute("DELETE FROM positions WHERE time<?", (cutoff,))
            self.db.execute("DELETE FROM events WHERE time<?", (cutoff,))
            self.db.execute("DELETE FROM ships WHERE updated<?", (cutoff,))
            self.db.execute("DELETE FROM states WHERE mmsi NOT IN (SELECT mmsi FROM ships)")
            self.db.commit()
            self.last_prune = now

    def snapshot(self, harbour, now):
        with self.lock:
            rows = self.db.execute("SELECT s.body,t.body FROM ships s JOIN states t ON s.mmsi=t.mmsi WHERE t.harbour=? AND s.updated>? ORDER BY s.updated DESC LIMIT 2000", (harbour, now-86400)).fetchall()
            ships = []
            for row in rows:
                ship, state = json.loads(row[0]), json.loads(row[1])
                # States/events remain historical, but a vessel's latest global
                # position must not appear as current in a previously visited port.
                if harbour not in ship.get("harbours", []):
                    continue
                if not ship.get("position_at"):
                    continue
                ship["state"] = state
                ship["stale"] = now-ship["position_at"] > self.config["stale_seconds"]
                ships.append(ship)
            return ships

    def events(self, harbour, since, limit=200):
        with self.lock:
            rows = self.db.execute("SELECT e.*,s.body FROM events e LEFT JOIN ships s ON s.mmsi=e.mmsi WHERE e.harbour=? AND e.time>=? ORDER BY e.time DESC LIMIT ?", (harbour, since, limit)).fetchall()
            return [{"id": r["id"], "mmsi": r["mmsi"], "kind": r["kind"], "time": r["time"], "boundary_hash": r["boundary_hash"], "name": json.loads(r["body"]).get("name") if r["body"] else None} for r in rows]

    def counts(self, harbour, since):
        with self.lock:
            return {row[0]: row[1] for row in self.db.execute("SELECT kind,COUNT(*) FROM events WHERE harbour=? AND time>=? GROUP BY kind", (harbour, since))}

    def track(self, mmsi, since):
        with self.lock:
            rows = list(self.db.execute("SELECT time,lat,lon,speed FROM positions WHERE mmsi=? AND time>=? ORDER BY time DESC LIMIT 1440", (mmsi, since)))
            return [dict(row) for row in reversed(rows)]
