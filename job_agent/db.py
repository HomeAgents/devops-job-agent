from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(db_path: Path | str = "jobs.db") -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS jobs (link TEXT PRIMARY KEY)")
    return conn


def existing_links(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT link FROM jobs")}


def insert_links(conn: sqlite3.Connection, links: list[str]) -> None:
    for link in links:
        if link:
            conn.execute("INSERT OR IGNORE INTO jobs VALUES (?)", (link,))
    conn.commit()


def filter_new_links(conn: sqlite3.Connection, links: list[str]) -> list[str]:
    have = existing_links(conn)
    return [ln for ln in links if ln and ln not in have]
