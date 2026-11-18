from dataclasses import dataclass
import sqlite3

from corrections.selection import SelectedTransaction, select_transactions
from snapshots.read import read_revision
from snapshots.revisions import Revision
from snapshots.rows import LedgerError

from .commit import commit_sealed_day
from .evidence import SealReceipt, build_evidence
from .replay import evaluate_replay


@dataclass(frozen=True)
class DayBatch:
    opening: Revision
    closing: Revision
    transactions: tuple[SelectedTransaction, ...]


def resolve_batch(db: sqlite3.Connection, opening_id: int, closing_id: int, transaction_ids) -> DayBatch:
    opening = read_revision(db, opening_id)
    closing = read_revision(db, closing_id)
    if opening is None or closing is None:
        raise LedgerError('UNKNOWN_REVISION', 'both fixed revisions must exist')
    if opening.day != closing.day:
        raise LedgerError('DAY_CONFLICT', 'opening and closing revisions must be for the same day')
    if opening.row_keys != closing.row_keys:
        raise LedgerError('KEY_SET_MISMATCH', 'opening and closing revisions have different row keys')
    transactions = select_transactions(db, opening.day, transaction_ids)
    known_keys = set(opening.row_keys)
    for selected in transactions:
        for change in selected.transaction.changes:
            if change.key not in known_keys:
                raise LedgerError('UNKNOWN_CHANGE_ROW',
                                  f'{selected.transaction.name!r} changes unknown row {change.key!r}')
    return DayBatch(opening, closing, transactions)


def seal_day(db: sqlite3.Connection, opening_id: int, closing_id: int,
             transaction_ids, *, fail_before_commit: bool = False) -> SealReceipt:
    batch = resolve_batch(db, opening_id, closing_id, transaction_ids)
    replay = evaluate_replay(
        batch.opening.row_keys,
        tuple(row.value for row in batch.opening.rows),
        tuple(row.value for row in batch.closing.rows),
        tuple(selected.transaction for selected in batch.transactions),
    )
    if not replay.has_completion:
        raise LedgerError('DAY_REPLAY_MISMATCH', 'no order uses all selected transactions and reaches closing')
    evidence = build_evidence(batch.opening, batch.closing, batch.transactions, replay)
    return commit_sealed_day(db, evidence, fail_before_commit=fail_before_commit)
