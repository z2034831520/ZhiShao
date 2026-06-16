import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta

from settings import BASE_DIR


class Store:
    """SQLite-backed product data store for metrics, events, and actions."""

    def __init__(self, db_path=None):
        self.db_path = db_path or os.path.join(BASE_DIR, "logs", "zhishao.db")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.lock = threading.RLock()
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self.lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metrics_daily (
                    date TEXT PRIMARY KEY,
                    online_seconds REAL DEFAULT 0,
                    seen_seconds REAL DEFAULT 0,
                    active_seconds REAL DEFAULT 0,
                    search_seconds REAL DEFAULT 0,
                    target_seen_frames INTEGER DEFAULT 0,
                    total_frames INTEGER DEFAULT 0,
                    suspect_fall_count INTEGER DEFAULT 0,
                    confirmed_fall_count INTEGER DEFAULT 0,
                    rejected_fall_count INTEGER DEFAULT 0,
                    validation_failed_count INTEGER DEFAULT 0,
                    alerts_sent_count INTEGER DEFAULT 0,
                    lock_lost_count INTEGER DEFAULT 0,
                    last_seen_time TEXT DEFAULT '',
                    fall_mode TEXT DEFAULT '保守',
                    updated_at TEXT DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    type TEXT NOT NULL,
                    level TEXT DEFAULT 'info',
                    message TEXT NOT NULL,
                    data TEXT DEFAULT '{}',
                    handled INTEGER DEFAULT 0,
                    action TEXT DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS family_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    action TEXT NOT NULL,
                    note TEXT DEFAULT '',
                    source TEXT DEFAULT 'feishu'
                )
                """
            )

    def today(self):
        return datetime.now().strftime("%Y-%m-%d")

    def now_text(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def ensure_metrics(self, date=None):
        date = date or self.today()
        with self.lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO metrics_daily(date, updated_at) VALUES(?, ?)",
                (date, self.now_text()),
            )
        return date

    def add_metrics(self, date=None, **increments):
        date = self.ensure_metrics(date)
        allowed = {
            "online_seconds",
            "seen_seconds",
            "active_seconds",
            "search_seconds",
            "target_seen_frames",
            "total_frames",
            "suspect_fall_count",
            "confirmed_fall_count",
            "rejected_fall_count",
            "validation_failed_count",
            "alerts_sent_count",
            "lock_lost_count",
        }
        updates = []
        values = []
        for key, value in increments.items():
            if key in allowed:
                updates.append(f"{key} = {key} + ?")
                values.append(value)
        if not updates:
            return self.get_metrics(date)
        updates.append("updated_at = ?")
        values.append(self.now_text())
        values.append(date)
        with self.lock, self._connect() as conn:
            conn.execute(f"UPDATE metrics_daily SET {', '.join(updates)} WHERE date = ?", values)
        return self.get_metrics(date)

    def set_metrics(self, date=None, **fields):
        date = self.ensure_metrics(date)
        allowed = {"last_seen_time", "fall_mode", "updated_at"}
        updates = []
        values = []
        for key, value in fields.items():
            if key in allowed:
                updates.append(f"{key} = ?")
                values.append(value)
        if not updates:
            return self.get_metrics(date)
        updates.append("updated_at = ?")
        values.append(self.now_text())
        values.append(date)
        with self.lock, self._connect() as conn:
            conn.execute(f"UPDATE metrics_daily SET {', '.join(updates)} WHERE date = ?", values)
        return self.get_metrics(date)

    def get_metrics(self, date=None):
        date = self.ensure_metrics(date)
        with self.lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM metrics_daily WHERE date = ?", (date,)).fetchone()
        return dict(row) if row else {}

    def get_week_metrics(self, days=7):
        rows = []
        for i in range(days - 1, -1, -1):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            rows.append(self.get_metrics(date))
        return rows

    def record_event(self, event_type, message, level="info", data=None, handled=False, action=""):
        payload = json.dumps(data or {}, ensure_ascii=False)
        with self.lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO events(ts, type, level, message, data, handled, action) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (self.now_text(), event_type, level, message, payload, 1 if handled else 0, action),
            )

    def list_events(self, limit=20, date=None):
        params = []
        where = ""
        if date:
            where = "WHERE ts LIKE ?"
            params.append(f"{date}%")
        params.append(limit)
        with self.lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM events {where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        events = []
        for row in rows:
            item = dict(row)
            try:
                item["data"] = json.loads(item.get("data") or "{}")
            except Exception:
                item["data"] = {}
            events.append(item)
        return events

    def record_family_action(self, action, note="", source="feishu"):
        with self.lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO family_actions(ts, action, note, source) VALUES(?, ?, ?, ?)",
                (self.now_text(), action, note, source),
            )
        self.record_event("family_action", f"家属处置：{action}", "info", {"note": note, "source": source}, True, action)

    def count_family_actions(self, date=None):
        date = date or self.today()
        with self.lock, self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM family_actions WHERE ts LIKE ?", (f"{date}%",)).fetchone()
        return int(row["c"] if row else 0)

    def set_runtime_value(self, key, value):
        text = json.dumps(value, ensure_ascii=False)
        with self.lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO runtime_state(key, value, updated_at) VALUES(?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, text, self.now_text()),
            )

    def get_runtime_value(self, key, default=None):
        with self.lock, self._connect() as conn:
            row = conn.execute("SELECT value FROM runtime_state WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return default

