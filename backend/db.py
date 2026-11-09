from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from .models import Snapshot


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise ValueError("数据库版本较新，拒绝覆盖")
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS snapshots (
                  id TEXT PRIMARY KEY, mode TEXT NOT NULL, character_id TEXT NOT NULL,
                  captured_at INTEGER NOT NULL, imported_at INTEGER NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS snapshots_lookup ON snapshots(mode, captured_at DESC);
                CREATE TABLE IF NOT EXISTS prices (
                  id INTEGER PRIMARY KEY, mode TEXT NOT NULL, realm TEXT NOT NULL, item_id INTEGER NOT NULL,
                  copper INTEGER NOT NULL CHECK(copper>=0), recorded_at INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS prices_lookup ON prices(mode, realm, item_id, recorded_at DESC, id DESC);
                CREATE TABLE IF NOT EXISTS advice (
                  id INTEGER PRIMARY KEY, snapshot_id TEXT NOT NULL, kind TEXT NOT NULL,
                  engine TEXT NOT NULL, question TEXT, payload TEXT NOT NULL, created_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks (
                  id INTEGER PRIMARY KEY, mode TEXT NOT NULL, character_id TEXT NOT NULL,
                  title TEXT NOT NULL, note TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,
                  created_at INTEGER NOT NULL, provenance TEXT NOT NULL DEFAULT 'assumption',
                  evidence_ids TEXT NOT NULL DEFAULT '[]');
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reference_cache (
                  name TEXT PRIMARY KEY, build TEXT NOT NULL, built_at TEXT NOT NULL,
                  fetched_at INTEGER NOT NULL, sha256 TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS market_prices (
                  id INTEGER PRIMARY KEY, mode TEXT NOT NULL, scope TEXT NOT NULL, item_id INTEGER NOT NULL,
                  copper INTEGER NOT NULL CHECK(copper>=0), observed_at INTEGER NOT NULL,
                  source TEXT NOT NULL, provenance TEXT NOT NULL,
                  UNIQUE(mode,scope,item_id,copper,observed_at,source));
                CREATE INDEX IF NOT EXISTS market_lookup ON market_prices(mode,scope,item_id,observed_at DESC,id DESC);
                CREATE TABLE IF NOT EXISTS market_snapshots (
                  mode TEXT NOT NULL, scope TEXT NOT NULL, observed_at INTEGER NOT NULL,
                  fetched_at INTEGER NOT NULL, payload TEXT NOT NULL,
                  PRIMARY KEY(mode,scope,observed_at));
                CREATE TABLE IF NOT EXISTS auto_task_links (
                  mode TEXT NOT NULL, character_id TEXT NOT NULL, key TEXT NOT NULL, task_id INTEGER NOT NULL,
                  PRIMARY KEY(mode,character_id,key));
                CREATE TABLE IF NOT EXISTS automation_events (
                  id INTEGER PRIMARY KEY, mode TEXT NOT NULL, kind TEXT NOT NULL,
                  status TEXT NOT NULL, summary TEXT NOT NULL, created_at INTEGER NOT NULL);
            """)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
            if "provenance" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN provenance TEXT NOT NULL DEFAULT 'assumption'")
            if "evidence_ids" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN evidence_ids TEXT NOT NULL DEFAULT '[]'")
            conn.execute("PRAGMA user_version=2")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def save_snapshot(self, snapshot: Snapshot) -> str:
        payload = json.dumps(snapshot.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        ident = hashlib.sha256(payload.encode()).hexdigest()
        with self.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO snapshots VALUES (?,?,?,?,?,?)",
                         (ident, snapshot.data_mode, snapshot.character.identity, snapshot.captured_at,
                          int(time.time()), payload))
        return ident

    def latest(self, mode: str, character_id: str | None = None) -> tuple[str, Snapshot] | None:
        with self.connect() as conn:
            query = "SELECT id,payload FROM snapshots WHERE mode=?"
            args = [mode]
            if character_id:
                query += " AND character_id=?"
                args.append(character_id)
            row = conn.execute(query + " ORDER BY captured_at DESC, imported_at DESC, rowid DESC LIMIT 1", args).fetchone()
        return (row["id"], Snapshot.model_validate_json(row["payload"])) if row else None

    def characters(self, mode):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT character_id,MAX(captured_at) AS captured_at FROM snapshots WHERE mode=? GROUP BY character_id ORDER BY captured_at DESC", (mode,))]

    def add_price(self, mode, realm, item_id, copper):
        if type(copper) is not int or copper < 0 or copper > 10**14 or type(item_id) is not int or item_id <= 0:
            raise ValueError("价格或物品 ID 无效")
        with self.connect() as conn:
            return conn.execute("INSERT INTO prices(mode,realm,item_id,copper,recorded_at) VALUES(?,?,?,?,?)",
                                (mode, realm, item_id, copper, int(time.time()))).lastrowid

    def prices(self, mode, realm):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT p.* FROM prices p WHERE mode=? AND realm=? AND id=(SELECT MAX(p2.id) FROM prices p2 WHERE p2.mode=p.mode AND p2.realm=p.realm AND p2.item_id=p.item_id) ORDER BY item_id", (mode, realm))]

    def price_history(self, mode, realm):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM prices WHERE mode=? AND realm=? ORDER BY id DESC LIMIT 200", (mode, realm))]

    def save_advice(self, snapshot_id, kind, engine, result, question=None):
        with self.connect() as conn:
            return conn.execute("INSERT INTO advice(snapshot_id,kind,engine,question,payload,created_at) VALUES(?,?,?,?,?,?)",
                                (snapshot_id, kind, engine, question, json.dumps(result, ensure_ascii=False), int(time.time()))).lastrowid

    def last_advice(self, snapshot_id, kind="plan"):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM advice WHERE snapshot_id=? AND kind=? ORDER BY id DESC LIMIT 1", (snapshot_id, kind)).fetchone()
        if row:
            result = dict(row)
            result["payload"] = json.loads(result["payload"])
            return result

    def tasks(self, mode, character_id):
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute("SELECT t.*,a.key AS auto_key FROM tasks t LEFT JOIN auto_task_links a ON a.task_id=t.id AND a.mode=t.mode AND a.character_id=t.character_id WHERE t.mode=? AND t.character_id=? ORDER BY t.done,t.id", (mode, character_id))]
        for row in rows:
            row["evidence_ids"] = json.loads(row["evidence_ids"])
        return rows

    def add_task(self, mode, character_id, title, note=""):
        title, note = title.strip(), note.strip()
        if not title or len(title) > 200 or len(note) > 2000:
            raise ValueError("待办标题需为 1–200 字，说明不超过 2000 字")
        with self.connect() as conn:
            return conn.execute("INSERT INTO tasks(mode,character_id,title,note,created_at) VALUES(?,?,?,?,?)",
                                (mode, character_id, title, note, int(time.time()))).lastrowid

    def update_task(self, task_id, mode, character_id, done):
        with self.connect() as conn:
            return conn.execute("UPDATE tasks SET done=? WHERE id=? AND mode=? AND character_id=? AND NOT EXISTS (SELECT 1 FROM auto_task_links a WHERE a.task_id=tasks.id AND a.key LIKE 'quest:%')",
                                (int(done), task_id, mode, character_id)).rowcount > 0

    def delete_task(self, task_id, mode, character_id):
        with self.connect() as conn:
            return conn.execute("DELETE FROM tasks WHERE id=? AND mode=? AND character_id=?", (task_id, mode, character_id)).rowcount > 0

    def set(self, key, value):
        with self.connect() as conn:
            conn.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def get(self, key, default=None):
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def cache_references(self, datasets, build, built_at):
        with self.connect() as conn:
            for name, data in datasets.items():
                payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                conn.execute("INSERT INTO reference_cache VALUES(?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET build=excluded.build,built_at=excluded.built_at,fetched_at=excluded.fetched_at,sha256=excluded.sha256,payload=excluded.payload",
                             (name, build, built_at, int(time.time()), hashlib.sha256(payload.encode()).hexdigest(), payload))

    def reference(self, name):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM reference_cache WHERE name=?", (name,)).fetchone()
        if row:
            result = dict(row)
            result["payload"] = json.loads(result["payload"])
            return result

    def reference_status(self):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT name,build,built_at,fetched_at,sha256 FROM reference_cache ORDER BY name")]

    def save_market_prices(self, mode, scope, prices, source, provenance):
        with self.connect() as conn:
            self._insert_market_prices(conn, mode, scope, prices, source, provenance)

    @staticmethod
    def _insert_market_prices(conn, mode, scope, prices, source, provenance):
        for price in prices:
            if type(price.get("item_id")) is not int or price["item_id"] <= 0 or type(price.get("copper")) is not int or not 0 <= price["copper"] <= 10**14:
                raise ValueError("自动报价格式无效")
            observed = price["observed_at"]
            if type(observed) is not int or observed > time.time() + 300 or observed < 1577836800:
                raise ValueError("自动报价时间无效")
            conn.execute("INSERT OR IGNORE INTO market_prices(mode,scope,item_id,copper,observed_at,source,provenance) VALUES(?,?,?,?,?,?,?)",
                         (mode, scope, price["item_id"], price["copper"], observed, source, provenance))

    def save_market_snapshot(self, mode, metadata, prices):
        """Publish an entire checked market observation atomically, never a partial page."""
        with self.connect() as conn:
            self._insert_market_prices(conn, mode, metadata["scope"], prices, metadata["source"], "assumption")
            conn.execute("INSERT INTO market_snapshots VALUES(?,?,?,?,?) ON CONFLICT(mode,scope,observed_at) DO UPDATE SET fetched_at=excluded.fetched_at,payload=excluded.payload",
                         (mode, metadata["scope"], metadata["observed_at"], int(time.time()),
                          json.dumps(metadata, ensure_ascii=False)))

    def market_snapshot(self, mode, scope):
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM market_snapshots WHERE mode=? AND scope=? ORDER BY observed_at DESC LIMIT 1", (mode, scope)).fetchone()
        return json.loads(row[0]) if row else None

    def market_prices(self, mode, scopes):
        if not scopes:
            return []
        with self.connect() as conn:
            placeholders = ",".join("?" for _ in scopes)
            rows = conn.execute(f"SELECT p.* FROM market_prices p WHERE mode=? AND scope IN ({placeholders}) AND id=(SELECT p2.id FROM market_prices p2 WHERE p2.mode=p.mode AND p2.scope=p.scope AND p2.item_id=p.item_id ORDER BY p2.observed_at DESC,p2.id DESC LIMIT 1) ORDER BY observed_at DESC,id DESC", [mode, *scopes])
            return [dict(row) for row in rows]

    def market_history(self, mode, scopes):
        if not scopes:
            return []
        with self.connect() as conn:
            placeholders = ",".join("?" for _ in scopes)
            return [dict(row) for row in conn.execute(f"SELECT *,observed_at AS recorded_at FROM market_prices WHERE mode=? AND scope IN ({placeholders}) ORDER BY observed_at DESC,id DESC LIMIT 200", [mode, *scopes])]

    def sync_auto_tasks(self, mode, character_id, entries):
        with self.connect() as conn:
            for key, title, note, done, provenance, evidence_ids in entries:
                if provenance not in ("verified", "calculated", "assumption"):
                    raise ValueError("待办证据类别无效")
                evidence_json = json.dumps(evidence_ids, ensure_ascii=False)
                row = conn.execute("SELECT task_id FROM auto_task_links WHERE mode=? AND character_id=? AND key=?", (mode, character_id, key)).fetchone()
                if row:
                    if done is None:
                        conn.execute("UPDATE tasks SET title=?,note=?,provenance=?,evidence_ids=? WHERE id=?", (title, note, provenance, evidence_json, row[0]))
                    else:
                        conn.execute("UPDATE tasks SET title=?,note=?,done=?,provenance=?,evidence_ids=? WHERE id=?", (title, note, int(done), provenance, evidence_json, row[0]))
                else:
                    task_id = conn.execute("INSERT INTO tasks(mode,character_id,title,note,done,created_at,provenance,evidence_ids) VALUES(?,?,?,?,?,?,?,?)", (mode, character_id, title, note, int(done or False), int(time.time()), provenance, evidence_json)).lastrowid
                    conn.execute("INSERT INTO auto_task_links VALUES(?,?,?,?)", (mode, character_id, key, task_id))

    def automation_event(self, mode, kind, status, summary):
        with self.connect() as conn:
            conn.execute("INSERT INTO automation_events(mode,kind,status,summary,created_at) VALUES(?,?,?,?,?)", (mode, kind, status, summary[:1000], int(time.time())))

    def automation_events(self, mode, limit=30):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM automation_events WHERE mode=? ORDER BY id DESC LIMIT ?", (mode, min(limit, 100)))]
