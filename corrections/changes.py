from dataclasses import dataclass

from snapshots.rows import LedgerError, ordered_items, require_text, validate_reading


@dataclass(frozen=True)
class RowChange:
    key: str
    old: int
    new: int


@dataclass(frozen=True)
class CorrectionTransaction:
    name: str
    changes: tuple[RowChange, ...]


def validate_transaction(transaction: CorrectionTransaction) -> CorrectionTransaction:
    if not isinstance(transaction, CorrectionTransaction):
        raise LedgerError('INVALID_TRANSACTION', 'expected a CorrectionTransaction')
    name = require_text(transaction.name, 'transaction name', 'INVALID_TRANSACTION')
    changes = ordered_items(transaction.changes, 'changes', 'INVALID_TRANSACTION')
    if not changes:
        raise LedgerError('INVALID_TRANSACTION', f'{name!r} has no changes')
    by_key = {}
    for change in changes:
        if not isinstance(change, RowChange):
            raise LedgerError('INVALID_TRANSACTION', 'expected a RowChange')
        key = require_text(change.key, 'change key', 'INVALID_TRANSACTION')
        if key in by_key:
            raise LedgerError('DUPLICATE_CHANGE', f'{name!r} changes {key!r} more than once')
        by_key[key] = RowChange(key, validate_reading(change.old), validate_reading(change.new))
    return CorrectionTransaction(name, tuple(by_key[key] for key in sorted(by_key)))
