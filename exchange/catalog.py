from dataclasses import dataclass
import sqlite3

from publication.evidence import SealedDay
from snapshots.rows import LedgerError, require_text
from snapshots.store import write_transaction

from .package import HandoffPackage, parse_package


@dataclass(frozen=True)
class ReceivedCopy:
    day: SealedDay
    checksum: str

    @property
    def result_id(self) -> str:
        return self.day.result_id

    @property
    def origin(self) -> str:
        return self.day.receipt.origin


def initialize_archive(db: sqlite3.Connection) -> None:
    with write_transaction(db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS received_days (
                result_id TEXT PRIMARY KEY NOT NULL,
                origin TEXT NOT NULL,
                checksum TEXT NOT NULL,
                package BLOB NOT NULL
            )
        ''')


def register_copy(db: sqlite3.Connection, package: HandoffPackage) -> ReceivedCopy:
    day = package.day
    result_id = day.result_id
    origin = day.receipt.origin
    with write_transaction(db):
        db.execute('''
            INSERT INTO received_days (result_id, origin, checksum, package) VALUES (?, ?, ?, ?)
            ON CONFLICT (result_id) DO NOTHING
        ''', (result_id, origin, package.checksum, package.wire))
        saved_origin, checksum, wire = db.execute('''
            SELECT origin, checksum, package FROM received_days WHERE result_id = ?
        ''', (result_id,)).fetchone()
        if (saved_origin, checksum, wire) != (origin, package.checksum, package.wire):
            raise LedgerError('COPY_CONFLICT', f'{result_id!r} already names a different fixed package')
    return ReceivedCopy(day, checksum)


def read_received_day(db: sqlite3.Connection, result_id: str) -> ReceivedCopy:
    result_id = require_text(result_id, 'result ID', 'UNKNOWN_RESULT')
    record = db.execute('''
        SELECT origin, checksum, package FROM received_days WHERE result_id = ?
    ''', (result_id,)).fetchone()
    if record is None:
        raise LedgerError('UNKNOWN_RESULT', f'no archived result {result_id!r}')
    origin, checksum, wire = record
    package = parse_package(wire)
    if (package.day.result_id, package.day.receipt.origin, package.checksum) != (result_id, origin, checksum):
        raise LedgerError('BAD_PACKAGE', 'stored copy does not match its archive entry')
    return ReceivedCopy(package.day, checksum)
