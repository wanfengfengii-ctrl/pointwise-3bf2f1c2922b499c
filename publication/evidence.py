from dataclasses import dataclass
import json

from corrections.changes import CorrectionTransaction, RowChange, validate_transaction
from corrections.selection import MAX_TRANSACTIONS, SelectedTransaction
from snapshots.revisions import Revision
from snapshots.rows import LedgerError, decode_reading, encode_reading, require_text
from snapshots.rows import valid_record_number, validate_rows

from .replay import ReplayResult, TransactionStates


@dataclass(frozen=True)
class SealReceipt:
    result_id: str
    day: str
    origin: str


@dataclass(frozen=True)
class SealedEvidence:
    opening: Revision
    closing: Revision
    transactions: tuple[SelectedTransaction, ...]
    row_keys: tuple[str, ...]
    after: TransactionStates


@dataclass(frozen=True)
class SealedDay:
    receipt: SealReceipt
    evidence: SealedEvidence

    @property
    def result_id(self) -> str:
        return self.receipt.result_id


def build_evidence(opening: Revision, closing: Revision,
                   transactions: tuple[SelectedTransaction, ...], replay: ReplayResult) -> SealedEvidence:
    by_transaction = dict(replay.after)
    names = tuple(selected.transaction.name for selected in transactions)
    if not replay.has_completion or set(names) != by_transaction.keys() or any(
        not by_transaction[name] for name in names
    ):
        raise LedgerError('INVALID_EVIDENCE', 'publication requires observations from a complete replay')
    after = tuple((name, by_transaction[name]) for name in names)
    return SealedEvidence(opening, closing, transactions, opening.row_keys, after)


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(',', ':'))


def load_json(text: str):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'duplicate field {key!r}')
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=unique_object)


def require_fields(value, *names):
    if type(value) is not dict or value.keys() != set(names):
        raise ValueError('unexpected fields')
    return value


def _list(value, width: int | None = None) -> list:
    if type(value) is not list or (width is not None and len(value) != width):
        raise ValueError('unexpected evidence array shape')
    return value


def _encode_revision(revision: Revision) -> list:
    return [revision.revision_id, revision.day, revision.source,
            [[row.key, encode_reading(row.value)] for row in revision.rows]]


def _decode_revision(value) -> Revision:
    revision_id, day, source, rows = _list(value, 4)
    if not valid_record_number(revision_id):
        raise ValueError('invalid revision number')
    parsed = [(key, decode_reading(reading)) for key, reading in (_list(row, 2) for row in _list(rows))]
    return Revision(revision_id, require_text(day, 'day'), require_text(source, 'table source'),
                    validate_rows(parsed))


def _encode_selected(selected: SelectedTransaction) -> list:
    transaction = selected.transaction
    changes = [[change.key, encode_reading(change.old), encode_reading(change.new)]
               for change in transaction.changes]
    return [selected.sheet_id, selected.station, selected.document, transaction.name, changes]


def _decode_selected(value) -> SelectedTransaction:
    sheet_id, station, document, name, changes = _list(value, 5)
    if not valid_record_number(sheet_id):
        raise ValueError('invalid correction sheet number')
    parsed = tuple(RowChange(key, decode_reading(old), decode_reading(new))
                   for key, old, new in (_list(change, 3) for change in _list(changes)))
    transaction = validate_transaction(CorrectionTransaction(name, parsed))
    return SelectedTransaction(sheet_id, require_text(station, 'station'),
                               require_text(document, 'correction document'), transaction)


def encode_evidence(evidence: SealedEvidence) -> str:
    return canonical_json({
        'opening': _encode_revision(evidence.opening),
        'closing': _encode_revision(evidence.closing),
        'transactions': [_encode_selected(selected) for selected in evidence.transactions],
        'row_keys': evidence.row_keys,
        'after': [[name, [[encode_reading(value) for value in state] for state in states]]
                  for name, states in evidence.after],
    })


def _decode_evidence(raw: str) -> SealedEvidence:
    data = require_fields(load_json(raw), 'opening', 'closing', 'transactions', 'row_keys', 'after')
    opening = _decode_revision(data['opening'])
    closing = _decode_revision(data['closing'])
    row_keys = tuple(_list(data['row_keys']))
    if opening.day != closing.day or row_keys != opening.row_keys or row_keys != closing.row_keys:
        raise ValueError('revision or column binding mismatch')
    if opening.revision_id == closing.revision_id and opening != closing:
        raise ValueError('conflicting versions of one revision')
    transactions = tuple(_decode_selected(item) for item in _list(data['transactions']))
    names = tuple(selected.transaction.name for selected in transactions)
    if len(names) > MAX_TRANSACTIONS or names != tuple(sorted(set(names))):
        raise ValueError('invalid transaction identities')
    known_keys = set(row_keys)
    for selected in transactions:
        if any(change.key not in known_keys for change in selected.transaction.changes):
            raise ValueError('change outside the fixed column set')
    after = []
    for entry in _list(data['after']):
        name, raw_states = _list(entry, 2)
        states = tuple(tuple(decode_reading(value) for value in _list(state, len(row_keys)))
                       for state in _list(raw_states))
        if not states or states != tuple(sorted(set(states))):
            raise ValueError('invalid fixed observation states')
        after.append((name, states))
    if tuple(name for name, _ in after) != names:
        raise ValueError('observation and transaction binding mismatch')
    evidence = SealedEvidence(opening, closing, transactions, row_keys, tuple(after))
    if encode_evidence(evidence) != raw:
        raise ValueError('noncanonical evidence')
    return evidence


def decode_evidence(raw: str) -> SealedEvidence:
    try:
        return _decode_evidence(raw)
    except (TypeError, ValueError, RecursionError) as exc:
        raise LedgerError('INVALID_EVIDENCE', 'fixed evidence is malformed') from exc


def check_receipt_binding(receipt: SealReceipt, evidence: SealedEvidence) -> None:
    origin = require_text(receipt.origin, 'receipt origin')
    result_id = require_text(receipt.result_id, 'result ID')
    prefix, separator, serial = result_id.rpartition('/')
    serial_valid = (0 < len(serial) <= 19 and serial.isascii() and serial.isdecimal()
                    and not serial.startswith('0') and valid_record_number(int(serial)))
    if not separator or prefix != origin or not serial_valid or receipt.day != evidence.opening.day:
        raise LedgerError('INVALID_RECEIPT', 'receipt does not bind this result and evidence')
