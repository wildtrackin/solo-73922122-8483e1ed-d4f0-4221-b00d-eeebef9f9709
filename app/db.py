"""SQLite 存储层。

三张表：
- sessions:    当前输入（原文/修订文/标签）+ 单调递增的 revision。
               每次修改输入 revision 必变（不是内容哈希，改回去也不会复原）。
- selections:  用户在某个 revision 上的选择，随 revision 失效。
- results:     确认成功后原子写入的最终结果；失败不落任何行。

并发：每次操作独立连接，关键写路径用 BEGIN IMMEDIATE 串行化，
确认时的"检查 revision + 写结果"在同一事务内完成，避免 TOCTOU。
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id         TEXT PRIMARY KEY,
  original   TEXT NOT NULL,
  revised    TEXT NOT NULL,
  labels     TEXT NOT NULL,
  revision   INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS selections (
  session_id TEXT NOT NULL,
  revision   INTEGER NOT NULL,
  data       TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (session_id, revision)
);
CREATE TABLE IF NOT EXISTS results (
  session_id TEXT NOT NULL,
  revision   INTEGER NOT NULL,
  data       TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (session_id, revision)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path() -> str:
    return os.environ.get("DB_PATH", "./data/app.db")


def connect() -> sqlite3.Connection:
    path = db_path()
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


# ---------- sessions ----------

def create_session(original: str, revised: str, labels: list[dict]) -> dict:
    sid = uuid.uuid4().hex
    now = _now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions(id, original, revised, labels, revision,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (sid, original, revised, json.dumps(labels, ensure_ascii=False),
             1, now, now))
    return get_session(sid)


def get_session(sid: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    if row is None:
        return None
    return _session_from_row(row)


def _session_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "original": row["original"],
        "revised": row["revised"],
        "labels": json.loads(row["labels"]),
        "revision": row["revision"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def update_inputs(sid: str, original: str, revised: str,
                  labels: list[dict]) -> dict | None:
    """修改输入：revision 必 +1，旧选择与旧结果同事务删除（改回也不恢复）。"""
    now = _now()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute("SELECT revision FROM sessions WHERE id=?", (sid,))
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            return None
        new_rev = row["revision"] + 1
        conn.execute(
            "UPDATE sessions SET original=?, revised=?, labels=?, revision=?,"
            " updated_at=? WHERE id=?",
            (original, revised, json.dumps(labels, ensure_ascii=False),
             new_rev, now, sid))
        conn.execute("DELETE FROM selections WHERE session_id=?", (sid,))
        conn.execute("DELETE FROM results WHERE session_id=?", (sid,))
        conn.commit()
    return get_session(sid)


# ---------- selections ----------

def get_selections(sid: str, revision: int) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT data FROM selections WHERE session_id=? AND revision=?",
            (sid, revision)).fetchone()
    return json.loads(row["data"]) if row else {}


# ---------- results ----------

def get_result(sid: str, revision: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT data, created_at FROM results"
            " WHERE session_id=? AND revision=?", (sid, revision)).fetchone()
    if row is None:
        return None
    return {"data": json.loads(row["data"]), "created_at": row["created_at"]}
