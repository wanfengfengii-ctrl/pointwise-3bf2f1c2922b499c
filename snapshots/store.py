from contextlib import contextmanager
import sqlite3

from .revisions import Revision
from .rows import ObservationRow, decode_reading, encode_reading


@contextmanager
def write_transaction(db: sqlite3.Connection):
    """Own one SQLite write transaction, including an unsuccessful commit."""
    if db.in_transaction:
        raise sqlite3.ProgrammingError('a ledger write requires an idle connection')
    db.execute('PRAGMA foreign_keys = ON')
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def initialize_revision_store(db: sqlite3.Connection) -> None:
    with write_transaction(db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS revisions (
                revision_id INTEGER PRIMARY KEY,
                day TEXT NOT NULL,
                source TEXT NOT NULL
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS observation_rows (
                revision_id INTEGER NOT NULL REFERENCES revisions(revision_id),
                row_key TEXT NOT NULL,
                reading TEXT NOT NULL,
                PRIMARY KEY (revision_id, row_key)
            )
        ''')


def insert_revision(db: sqlite3.Connection, day: str, source: str,
                    rows: tuple[ObservationRow, ...]) -> int:
    with write_transaction(db):
        revision_id = db.execute(
            'INSERT INTO revisions (day, source) VALUES (?, ?)', (day, source)
        ).lastrowid
        db.executemany(
            'INSERT INTO observation_rows (revision_id, row_key, reading) VALUES (?, ?, ?)',
            ((revision_id, row.key, encode_reading(row.value)) for row in rows),
        )
    return revision_id


def load_revision(db: sqlite3.Connection, revision_id: int) -> Revision | None:
    header = db.execute(
        'SELECT day, source FROM revisions WHERE revision_id = ?', (revision_id,)
    ).fetchone()
    if header is None:
        return None
    day, source = header
    records = db.execute('''
        SELECT row_key, reading FROM observation_rows
        WHERE revision_id = ? ORDER BY row_key
    ''', (revision_id,))
    rows = tuple(ObservationRow(key, decode_reading(reading)) for key, reading in records)
    return Revision(revision_id, day, source, rows)
