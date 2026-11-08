"""Price history in a small SQLite file (committed to the repo by the weekly job)."""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from .providers import Quote

SCHEMA = """
CREATE TABLE IF NOT EXISTS quotes (
    checked_on TEXT NOT NULL,
    item_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    travel_date TEXT NOT NULL,
    price REAL NOT NULL,
    currency TEXT NOT NULL,
    detail TEXT,
    link TEXT,
    source TEXT,
    PRIMARY KEY (checked_on, item_id, travel_date, source)
);
"""


class Store:
    def __init__(self, path: str | Path = "data/prices.db"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute(SCHEMA)

    def add(self, q: Quote, checked_on: dt.date) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO quotes VALUES (?,?,?,?,?,?,?,?,?)",
            (checked_on.isoformat(), q.item_id, q.kind, q.travel_date.isoformat(), q.price,
             q.currency, q.detail, q.link, q.source),
        )
        self.db.commit()

    def history(self, item_id: str, source: str) -> list[tuple[dt.date, dt.date, float]]:
        """(checked_on, travel_date, price) rows, oldest first."""
        rows = self.db.execute(
            "SELECT checked_on, travel_date, price FROM quotes WHERE item_id=? AND source=? ORDER BY checked_on",
            (item_id, source),
        ).fetchall()
        return [(dt.date.fromisoformat(c), dt.date.fromisoformat(t), p) for c, t, p in rows]

    def latest(self, item_id: str, source: str) -> list[sqlite3.Row]:
        self.db.row_factory = sqlite3.Row
        rows = self.db.execute(
            """SELECT * FROM quotes WHERE item_id=? AND source=? AND checked_on =
               (SELECT MAX(checked_on) FROM quotes WHERE item_id=? AND source=?) ORDER BY price""",
            (item_id, source, item_id, source),
        ).fetchall()
        self.db.row_factory = None
        return rows
