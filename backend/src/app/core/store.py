"""Workspace-local persistence. Documents are data, never executable instructions."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from app.core.paths import ROOT as ROOT

DATA = Path(os.environ.get("RAG_DATA_DIR", str(ROOT / "data"))).resolve()
DATA.mkdir(parents=True, exist_ok=True)
os.chmod(DATA, 0o700)
for folder in ("originals", "assets", "models"):
    (DATA / folder).mkdir(exist_ok=True)
LOCK = threading.RLock()

def uid():
    return uuid.uuid4().hex[:16]

def now():
    return time.time()

def digest(value):
    return hashlib.sha256(
        (
            json.dumps(value, sort_keys=True, ensure_ascii=False)
            if not isinstance(value, bytes)
            else value.decode("latin1")
        ).encode()
    ).hexdigest()

def db():
    c = sqlite3.connect(DATA / "workspace.sqlite3", timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c

def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, data TEXT NOT NULL, created REAL, PRIMARY KEY(kind,id));
        CREATE TABLE IF NOT EXISTS vectors (index_id TEXT, chunk_id TEXT, vector BLOB, PRIMARY KEY(index_id,chunk_id));
        CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(index_id UNINDEXED, chunk_id UNINDEXED, text);
        """)
    if not get("settings", "main"):
        put(
            "settings",
            "main",
            {
                "active_connection": "",
                "guidance": "Answer from the selected document. Distinguish evidence, inference and unknowns.",
                "memory_enabled": True,
            },
        )

def put(kind, id, data):
    value = {**data, "id": id}
    with LOCK, db() as c:
        c.execute(
            "INSERT INTO records VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data",
            (kind, id, json.dumps(value, ensure_ascii=False), now()),
        )
    return value

def get(kind, id, required=False):
    with db() as c:
        row = c.execute("SELECT data FROM records WHERE kind=? AND id=?", (kind, id)).fetchone()
    if row:
        return json.loads(row[0])
    if required:
        raise ValueError(f"{kind} not found.")
    return None

def rows(kind):
    with db() as c:
        return [
            json.loads(r[0])
            for r in c.execute(
                "SELECT data FROM records WHERE kind=? ORDER BY created DESC", (kind,)
            )
        ]

def delete(kind, id):
    with LOCK, db() as c:
        c.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, id))

def patch(kind, id, **fields):
    with LOCK:
        return put(kind, id, {**get(kind, id, True), **fields})

def event(run, stage, message, **details):
    return put(
        "events",
        uid(),
        {"run_id": run, "stage": stage, "message": message, "details": details, "time": now()},
    )

def asset_path(relative):
    path = (DATA / relative).resolve()
    if not path.is_relative_to(DATA / "assets") and not path.is_relative_to(DATA / "originals"):
        raise ValueError("Invalid asset path.")
    if not path.is_file():
        raise ValueError("Asset not found.")
    return path

init()
