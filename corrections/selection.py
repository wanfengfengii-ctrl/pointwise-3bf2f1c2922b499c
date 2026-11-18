from dataclasses import dataclass
import sqlite3

from snapshots.rows import LedgerError, ordered_items, require_text

from .changes import CorrectionTransaction
from .registry import read_day_transactions


MAX_TRANSACTIONS = 10


@dataclass(frozen=True)
class SelectedTransaction:
    sheet_id: int
    station: str
    document: str
    transaction: CorrectionTransaction


def select_transactions(db: sqlite3.Connection, day: str, transaction_ids) -> tuple[SelectedTransaction, ...]:
    names = tuple(require_text(name, 'transaction name', 'INVALID_SELECTION') for name in
                  ordered_items(transaction_ids, 'transaction selection', 'INVALID_SELECTION'))
    if len(names) > MAX_TRANSACTIONS:
        raise LedgerError('INVALID_SELECTION', f'a day batch may select at most {MAX_TRANSACTIONS} transactions')
    if len(set(names)) != len(names):
        raise LedgerError('DUPLICATE_SELECTION', 'a transaction can be selected only once')
    if not names:
        return ()
    available = read_day_transactions(db, day)
    missing = sorted(set(names) - available.keys())
    if missing:
        raise LedgerError('UNKNOWN_TRANSACTION', f'{missing[0]!r} is not registered for {day!r}')
    return tuple(SelectedTransaction(*available[name]) for name in sorted(names))
