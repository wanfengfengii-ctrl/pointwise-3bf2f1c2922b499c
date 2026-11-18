import sqlite3

from snapshots.rows import LedgerError, ordered_items, require_text

from .changes import validate_transaction
from .registry import SheetRecord, record_sheet


def register_sheet(db: sqlite3.Connection, day: str, station: str, document: str,
                   transactions) -> SheetRecord:
    day = require_text(day, 'day')
    station = require_text(station, 'station')
    document = require_text(document, 'correction document')
    records = tuple(validate_transaction(item) for item in
                    ordered_items(transactions, 'transactions', 'INVALID_SHEET'))
    if not records:
        raise LedgerError('INVALID_SHEET', 'a sheet must name at least one transaction')
    if len({record.name for record in records}) != len(records):
        raise LedgerError('DUPLICATE_TRANSACTION', 'a sheet repeats a transaction name')
    return record_sheet(db, day, station, document, records)
