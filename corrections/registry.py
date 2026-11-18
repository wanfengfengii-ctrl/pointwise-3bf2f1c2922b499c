from dataclasses import dataclass
import sqlite3

from snapshots.rows import valid_record_number

from .changes import CorrectionTransaction
from .store import insert_sheet, load_day_transactions, load_sheet


@dataclass(frozen=True)
class SheetRecord:
    sheet_id: int
    day: str
    station: str
    document: str
    transactions: tuple[CorrectionTransaction, ...]


def record_sheet(db: sqlite3.Connection, day: str, station: str, document: str,
                 transactions: tuple[CorrectionTransaction, ...]) -> SheetRecord:
    sheet_id = insert_sheet(db, day, station, document, transactions)
    return SheetRecord(sheet_id, day, station, document, transactions)


def read_sheet(db: sqlite3.Connection, sheet_id: int) -> SheetRecord | None:
    if not valid_record_number(sheet_id):
        return None
    record = load_sheet(db, sheet_id)
    if record is None:
        return None
    return SheetRecord(sheet_id, *record)


def read_day_transactions(db: sqlite3.Connection, day: str) -> dict:
    return {
        transaction.name: (sheet_id, station, document, transaction)
        for sheet_id, station, document, transaction in load_day_transactions(db, day)
    }
