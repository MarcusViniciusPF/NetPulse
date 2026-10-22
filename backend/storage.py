import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Configuration, Settings, Target


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, kind TEXT NOT NULL,
                address TEXT NOT NULL, enabled INTEGER NOT NULL, archived INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT, target_id INTEGER NOT NULL REFERENCES targets(id),
                timestamp TEXT NOT NULL, success INTEGER, latency_ms REAL, jitter_ms REAL, packet_loss REAL,
                sent INTEGER NOT NULL, received INTEGER NOT NULL, error TEXT);
            CREATE INDEX IF NOT EXISTS measurements_target_time ON measurements(target_id,timestamp);
            CREATE INDEX IF NOT EXISTS measurements_time ON measurements(timestamp);
            CREATE TABLE IF NOT EXISTS outages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, target_id INTEGER NOT NULL REFERENCES targets(id),
                started_at TEXT NOT NULL, recovered_at TEXT, end_reason TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS one_open_outage ON outages(target_id) WHERE recovered_at IS NULL;
            """)
            db.execute("INSERT OR IGNORE INTO settings VALUES (1, ?)", (Settings().model_dump_json(),))

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def config(self):
        with self.connection() as db:
            settings = json.loads(db.execute("SELECT value FROM settings WHERE id=1").fetchone()[0])
            targets = [dict(row) for row in db.execute("SELECT id,name,kind,address,enabled FROM targets WHERE archived=0 ORDER BY id")]
        return Configuration(settings=settings, targets=targets).model_dump() if targets else {"settings": settings, "targets": []}

    def seed(self, gateway: str | None):
        with self.connection() as db:
            if db.execute("SELECT COUNT(*) FROM targets").fetchone()[0]:
                return
            defaults = [("Cloudflare", "ping", "1.1.1.1"), ("Google DNS", "ping", "8.8.8.8"),
                        ("Resolução DNS", "dns", "example.com"), ("HTTPS", "http", "https://example.com")]
            if gateway:
                defaults.insert(0, ("Gateway local", "ping", gateway))
            db.executemany("INSERT INTO targets(name,kind,address,enabled) VALUES (?,?,?,1)", defaults)

    def save_config(self, config: Configuration):
        with self.connection() as db:
            existing = {r[0] for r in db.execute("SELECT id FROM targets WHERE archived=0")}
            for target in config.targets:
                if target.id is not None and target.id not in existing:
                    raise ValueError("Destino inexistente")
            db.execute("UPDATE settings SET value=? WHERE id=1", (config.settings.model_dump_json(),))
            retained = set()
            for t in config.targets:
                if t.id is None:
                    db.execute("INSERT INTO targets(name,kind,address,enabled) VALUES (?,?,?,?)", (t.name,t.kind,t.address,t.enabled))
                else:
                    old = db.execute("SELECT kind,address,enabled FROM targets WHERE id=?", (t.id,)).fetchone()
                    if old[0] != t.kind or old[1] != t.address:
                        raise ValueError("Para alterar tipo/endereço, remova o destino e adicione um novo (preserva o histórico)")
                    db.execute("UPDATE targets SET name=?,enabled=? WHERE id=?", (t.name,t.enabled,t.id))
                    if old[2] and not t.enabled:
                        db.execute("UPDATE outages SET recovered_at=?,end_reason='disabled' WHERE target_id=? AND recovered_at IS NULL", (now(),t.id))
                    retained.add(t.id)
            for removed in existing - retained:
                db.execute("UPDATE targets SET archived=1,enabled=0 WHERE id=?", (removed,))
                db.execute("UPDATE outages SET recovered_at=?,end_reason='removed' WHERE target_id=? AND recovered_at IS NULL", (now(),removed))

    def record(self, target_id, measurement):
        timestamp = now()
        with self.connection() as db:
            target = db.execute("SELECT enabled,archived FROM targets WHERE id=?", (target_id,)).fetchone()
            if not target or not target[0] or target[1]:
                return
            d = measurement.dict()
            db.execute("""INSERT INTO measurements(target_id,timestamp,success,latency_ms,jitter_ms,packet_loss,sent,received,error)
                          VALUES (?,?,?,?,?,?,?,?,?)""", (target_id,timestamp,d['success'],d['latency_ms'],d['jitter_ms'],d['packet_loss'],d['sent'],d['received'],d['error']))
            if d['success'] is False:
                db.execute("INSERT OR IGNORE INTO outages(target_id,started_at) VALUES (?,?)", (target_id,timestamp))
            elif d['success'] is True:
                db.execute("UPDATE outages SET recovered_at=?,end_reason='recovered' WHERE target_id=? AND recovered_at IS NULL", (timestamp,target_id))

    def prune(self, days):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="milliseconds")
        with self.connection() as db:
            db.execute("DELETE FROM measurements WHERE timestamp < ?", (cutoff,))
            db.execute("DELETE FROM outages WHERE recovered_at IS NOT NULL AND recovered_at < ?", (cutoff,))

    def dashboard(self, hours: int, target_id: int | None = None):
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="milliseconds")
        with self.connection() as db:
            targets = []
            for row in db.execute("SELECT * FROM targets WHERE archived=0 ORDER BY id"):
                t = dict(row)
                last = db.execute("SELECT * FROM measurements WHERE target_id=? ORDER BY id DESC LIMIT 1", (t['id'],)).fetchone()
                t['latest'] = dict(last) if last else None
                stats = db.execute("""SELECT count(*) AS samples,avg(latency_ms) AS latency_ms,avg(jitter_ms) AS jitter_ms,
                    100.0*sum(CASE WHEN success=1 THEN 1 ELSE 0 END)/nullif(count(success),0) AS availability,
                    100.0*(sum(sent)-sum(received))/nullif(sum(sent),0) AS packet_loss
                    FROM measurements WHERE target_id=? AND timestamp>=?""", (t['id'],cutoff)).fetchone()
                t['stats'] = dict(stats)
                targets.append(t)
            # Bounded chart, aggregated into <=360 time buckets, per target. Stats use all raw samples.
            bucket_seconds = max(1, hours * 3600 // 360)
            history = [dict(r) for r in db.execute("""SELECT target_id,
                strftime('%Y-%m-%dT%H:%M:%SZ',(CAST(strftime('%s',timestamp) AS INTEGER)/?)*?,'unixepoch') AS timestamp,
                avg(latency_ms) AS latency_ms,avg(jitter_ms) AS jitter_ms,
                100.0*(sum(sent)-sum(received))/nullif(sum(sent),0) AS packet_loss,
                100.0*sum(CASE WHEN success=1 THEN 1 ELSE 0 END)/nullif(count(success),0) AS availability,
                count(*) AS samples FROM measurements WHERE timestamp>=? AND (? IS NULL OR target_id=?)
                GROUP BY target_id,CAST(strftime('%s',timestamp) AS INTEGER)/? ORDER BY timestamp""",
                (bucket_seconds,bucket_seconds,cutoff,target_id,target_id,bucket_seconds))]
            outages = [dict(r) for r in db.execute("""SELECT o.*,t.name,t.kind,t.archived FROM outages o JOIN targets t ON t.id=o.target_id
                WHERE (o.recovered_at IS NULL OR o.recovered_at>=?) AND (? IS NULL OR target_id=?)
                ORDER BY o.id DESC LIMIT 200""", (cutoff,target_id,target_id))]
        return {"targets": targets, "history": history, "outages": outages, "generated_at": now(), "bucket_seconds": bucket_seconds}
