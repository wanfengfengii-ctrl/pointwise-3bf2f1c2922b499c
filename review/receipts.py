from publication.evidence import SealedEvidence
from snapshots.rows import LedgerError, require_text


def find_transaction_states(evidence: SealedEvidence, transaction_id: str) -> tuple[tuple[int, ...], ...]:
    transaction_id = require_text(transaction_id, 'transaction name', 'UNKNOWN_TRANSACTION')
    for name, states in evidence.after:
        if transaction_id == name:
            return states
    raise LedgerError('UNKNOWN_TRANSACTION', f'{transaction_id!r} is not in this sealed day')
