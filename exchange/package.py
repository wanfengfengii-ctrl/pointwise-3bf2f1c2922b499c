from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest

from publication.evidence import SealReceipt, SealedDay, canonical_json, check_receipt_binding
from publication.evidence import decode_evidence, encode_evidence, load_json, require_fields
from snapshots.rows import LedgerError, require_text


_FORMAT_VERSION = 1


@dataclass(frozen=True)
class HandoffPackage:
    day: SealedDay
    checksum: str
    wire: bytes


def _checksum(body: dict) -> str:
    return sha256(canonical_json(body).encode('ascii')).hexdigest()


def make_package(day: SealedDay) -> bytes:
    receipt = day.receipt
    check_receipt_binding(receipt, day.evidence)
    body = {
        'version': _FORMAT_VERSION,
        'result_id': day.result_id,
        'origin': receipt.origin,
        'receipt': {'result_id': receipt.result_id, 'day': receipt.day, 'origin': receipt.origin},
        'evidence': encode_evidence(day.evidence),
    }
    return canonical_json({'body': body, 'sha256': _checksum(body)}).encode('ascii')


def parse_package(blob: bytes) -> HandoffPackage:
    try:
        if not isinstance(blob, bytes):
            raise ValueError('a handoff must be bytes')
        envelope = require_fields(load_json(blob.decode('utf-8')), 'body', 'sha256')
        body = require_fields(envelope['body'], 'version', 'result_id', 'origin', 'receipt', 'evidence')
        if type(body['version']) is not int or body['version'] != _FORMAT_VERSION:
            raise ValueError('unsupported handoff version')
        checksum = envelope['sha256']
        if type(checksum) is not str or not checksum.isascii() or not compare_digest(checksum, _checksum(body)):
            raise ValueError('checksum does not match')
        record = require_fields(body['receipt'], 'result_id', 'day', 'origin')
        receipt = SealReceipt(require_text(record['result_id'], 'receipt result ID'),
                              require_text(record['day'], 'receipt day'),
                              require_text(record['origin'], 'receipt origin'))
        if body['result_id'] != receipt.result_id or body['origin'] != receipt.origin:
            raise ValueError('result or origin does not match the receipt')
        if type(body['evidence']) is not str:
            raise ValueError('missing fixed evidence')
        evidence = decode_evidence(body['evidence'])
        check_receipt_binding(receipt, evidence)
        wire = canonical_json(envelope).encode('ascii')
        return HandoffPackage(SealedDay(receipt, evidence), checksum, wire)
    except (TypeError, ValueError, RecursionError) as exc:
        raise LedgerError('BAD_PACKAGE', 'handoff format, checksum or result binding is invalid') from exc
