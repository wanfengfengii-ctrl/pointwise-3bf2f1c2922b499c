import sqlite3

from snapshots.rows import LedgerError, require_text
from snapshots.store import write_transaction

from .evidence import SealReceipt, SealedEvidence, encode_evidence


def initialize_publication_store(db: sqlite3.Connection, origin: str) -> None:
    origin = require_text(origin, 'ledger origin')
    with write_transaction(db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS publication_origin (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                origin TEXT NOT NULL
            )
        ''')
        db.execute('''
            INSERT INTO publication_origin (singleton, origin) VALUES (1, ?)
            ON CONFLICT (singleton) DO NOTHING
        ''', (origin,))
        stored_origin, = db.execute('SELECT origin FROM publication_origin').fetchone()
        if stored_origin != origin:
            raise LedgerError('ORIGIN_CONFLICT', 'the source ledger already has a different origin')
        db.execute('''
            CREATE TABLE IF NOT EXISTS sealed_days (
                serial INTEGER PRIMARY KEY,
                evidence TEXT NOT NULL
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS successful_receipts (
                serial INTEGER PRIMARY KEY REFERENCES sealed_days(serial),
                result_id TEXT NOT NULL UNIQUE,
                day TEXT NOT NULL,
                origin TEXT NOT NULL
            )
        ''')


def commit_sealed_day(db: sqlite3.Connection, evidence: SealedEvidence, *,
                      fail_before_commit: bool = False) -> SealReceipt:
    encoded = encode_evidence(evidence)
    with write_transaction(db):
        origin, = db.execute('SELECT origin FROM publication_origin').fetchone()
        serial = db.execute('INSERT INTO sealed_days (evidence) VALUES (?)', (encoded,)).lastrowid
        receipt = SealReceipt(f'{origin}/{serial}', evidence.opening.day, origin)
        db.execute('''
            INSERT INTO successful_receipts (serial, result_id, day, origin)
            VALUES (?, ?, ?, ?)
        ''', (serial, receipt.result_id, receipt.day, receipt.origin))
        if fail_before_commit:
            raise LedgerError('COMMIT_FAILED', 'publication stopped after staging the day and receipt')
    return receipt
