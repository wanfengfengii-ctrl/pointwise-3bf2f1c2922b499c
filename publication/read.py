import sqlite3

from snapshots.rows import LedgerError, require_text

from .evidence import SealReceipt, SealedDay, check_receipt_binding, decode_evidence


def read_sealed_day(db: sqlite3.Connection, result_id: str) -> SealedDay:
    result_id = require_text(result_id, 'result ID', 'UNKNOWN_RESULT')
    record = db.execute('''
        SELECT r.day, r.origin, d.evidence
          FROM successful_receipts AS r JOIN sealed_days AS d USING (serial)
         WHERE r.result_id = ?
    ''', (result_id,)).fetchone()
    if record is None:
        raise LedgerError('UNKNOWN_RESULT', f'no published result {result_id!r}')
    day, origin, encoded = record
    receipt = SealReceipt(result_id, day, origin)
    evidence = decode_evidence(encoded)
    check_receipt_binding(receipt, evidence)
    return SealedDay(receipt, evidence)
