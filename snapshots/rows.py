from collections.abc import Mapping, Set
from dataclasses import dataclass
import re


class LedgerError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(f'{code}: {detail}')
        self.code = code


@dataclass(frozen=True)
class ObservationRow:
    key: str
    value: int


def require_text(value: object, label: str, code: str = 'INVALID_TEXT') -> str:
    if type(value) is not str or not value or value.strip() != value or '\x00' in value:
        raise LedgerError(code, f'{label} must be nonempty, trimmed text without NUL')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise LedgerError(code, f'{label} must be UTF-8 text') from exc
    return value


def ordered_items(value: object, label: str, code: str) -> tuple:
    if isinstance(value, (str, bytes, bytearray, Mapping, Set)):
        raise LedgerError(code, f'{label} must be an ordered iterable')
    try:
        return tuple(value)
    except TypeError as exc:
        raise LedgerError(code, f'{label} must be an ordered iterable') from exc


def valid_record_number(value: object) -> bool:
    return type(value) is int and 0 < value <= 2**63 - 1


def validate_reading(value: object) -> int:
    if type(value) is not int:
        raise LedgerError('INVALID_READING', 'each reading must be an integer')
    return value


def validate_rows(rows) -> tuple[ObservationRow, ...]:
    if isinstance(rows, Mapping):
        rows = tuple(rows.items())
    by_key = {}
    for item in ordered_items(rows, 'rows', 'INVALID_ROW'):
        if isinstance(item, ObservationRow):
            key, value = item.key, item.value
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            key, value = item
        else:
            raise LedgerError('INVALID_ROW', 'each row needs a key and a reading')
        key = require_text(key, 'row key', 'INVALID_ROW')
        if key in by_key:
            raise LedgerError('DUPLICATE_ROW', f'repeated observation key {key!r}')
        by_key[key] = ObservationRow(key, validate_reading(value))
    return tuple(by_key[key] for key in sorted(by_key))


def encode_reading(value: int) -> str:
    return hex(validate_reading(value))


_HEX_READING = re.compile(r'(?:0x0|-?0x[1-9a-f][0-9a-f]*)\Z')


def decode_reading(value: str) -> int:
    if type(value) is not str or _HEX_READING.fullmatch(value) is None:
        raise LedgerError('INVALID_READING', 'invalid hexadecimal reading')
    return int(value, 16)
