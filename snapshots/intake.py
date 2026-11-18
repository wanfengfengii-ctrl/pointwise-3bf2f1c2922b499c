import sqlite3

from .rows import require_text, validate_rows
from .store import insert_revision


def freeze_table(db: sqlite3.Connection, day: str, source: str, rows) -> int:
    day = require_text(day, 'day')
    source = require_text(source, 'table source')
    return insert_revision(db, day, source, validate_rows(rows))
