from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import urlparse


def create_schema(database_url: str) -> None:
    if database_url.startswith("sqlite"):
        path_part = database_url.split("///", 1)[-1]
        if path_part == ":memory:":
            database_path = ":memory:"
        else:
            database_path = Path(path_part)
            if not database_path.is_absolute():
                database_path = Path.cwd() / database_path
            database_path.parent.mkdir(parents=True, exist_ok=True)
            database_path = str(database_path)
    else:
        raise ValueError("Only SQLite is configured for the first release")
    with sqlite3.connect(database_path) as connection:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS downloads (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, url TEXT NOT NULL, manga TEXT NOT NULL, chapter REAL NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, download_id INTEGER, status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, level TEXT NOT NULL, job_id TEXT, message TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
