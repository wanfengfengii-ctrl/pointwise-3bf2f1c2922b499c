from itertools import groupby
import sqlite3

from snapshots.rows import LedgerError, decode_reading, encode_reading
from snapshots.store import write_transaction

from .changes import CorrectionTransaction, RowChange


def initialize_correction_store(db: sqlite3.Connection) -> None:
    with write_transaction(db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS correction_sheets (
                sheet_id INTEGER PRIMARY KEY,
                day TEXT NOT NULL,
                station TEXT NOT NULL,
                document TEXT NOT NULL,
                UNIQUE (sheet_id, day)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS correction_transactions (
                day TEXT NOT NULL,
                name TEXT NOT NULL,
                sheet_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY (day, name),
                UNIQUE (sheet_id, position),
                FOREIGN KEY (sheet_id, day) REFERENCES correction_sheets(sheet_id, day)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS correction_rows (
                day TEXT NOT NULL,
                name TEXT NOT NULL,
                row_key TEXT NOT NULL,
                old_value TEXT NOT NULL,
                new_value TEXT NOT NULL,
                PRIMARY KEY (day, name, row_key),
                FOREIGN KEY (day, name) REFERENCES correction_transactions(day, name)
            )
        ''')


def insert_sheet(db: sqlite3.Connection, day: str, station: str, document: str,
                 transactions: tuple[CorrectionTransaction, ...]) -> int:
    with write_transaction(db):
        sheet_id = db.execute('''
            INSERT INTO correction_sheets (day, station, document) VALUES (?, ?, ?)
        ''', (day, station, document)).lastrowid
        for position, transaction in enumerate(transactions):
            cursor = db.execute('''
                INSERT INTO correction_transactions (day, name, sheet_id, position)
                VALUES (?, ?, ?, ?) ON CONFLICT (day, name) DO NOTHING
            ''', (day, transaction.name, sheet_id, position))
            if cursor.rowcount == 0:
                raise LedgerError('TRANSACTION_CONFLICT', f'{transaction.name!r} is already registered for {day!r}')
            db.executemany('''
                INSERT INTO correction_rows (day, name, row_key, old_value, new_value)
                VALUES (?, ?, ?, ?, ?)
            ''', ((day, transaction.name, change.key, encode_reading(change.old),
                   encode_reading(change.new)) for change in transaction.changes))
    return sheet_id


_TRANSACTION_ROWS = '''
    SELECT s.sheet_id, s.station, s.document, t.name, c.row_key, c.old_value, c.new_value
      FROM correction_sheets AS s
      JOIN correction_transactions AS t ON (t.sheet_id, t.day) = (s.sheet_id, s.day)
      JOIN correction_rows AS c ON (c.day, c.name) = (t.day, t.name)
'''


def _assemble_transactions(records):
    for (sheet_id, station, document, name), group in groupby(records, lambda row: tuple(row[:4])):
        changes = tuple(
            RowChange(key, decode_reading(old), decode_reading(new))
            for _, _, _, _, key, old, new in group
        )
        yield sheet_id, station, document, CorrectionTransaction(name, changes)


def load_sheet(db: sqlite3.Connection, sheet_id: int):
    header = db.execute('''
        SELECT day, station, document FROM correction_sheets WHERE sheet_id = ?
    ''', (sheet_id,)).fetchone()
    if header is None:
        return None
    records = db.execute(
        _TRANSACTION_ROWS + 'WHERE s.sheet_id = ? ORDER BY t.position, c.row_key', (sheet_id,)
    )
    transactions = tuple(transaction for _, _, _, transaction in _assemble_transactions(records))
    day, station, document = header
    return day, station, document, transactions


def load_day_transactions(db: sqlite3.Connection, day: str):
    records = db.execute(
        _TRANSACTION_ROWS + 'WHERE t.day = ? ORDER BY t.name, c.row_key', (day,)
    )
    return tuple(_assemble_transactions(records))
