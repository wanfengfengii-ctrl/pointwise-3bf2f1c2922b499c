import sqlite3

from .projection import project_joint_rows, resolve_columns
from .read import read_review_day
from .receipts import find_transaction_states


def audit_after(db: sqlite3.Connection, result_id: str, transaction_id: str, keys, *,
                archive: bool = False) -> list[tuple[int, ...]]:
    evidence = read_review_day(db, result_id, archive=archive).evidence
    states = find_transaction_states(evidence, transaction_id)
    columns = resolve_columns(evidence.row_keys, keys)
    return project_joint_rows(states, columns)
