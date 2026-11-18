from itertools import product

from snapshots.rows import LedgerError, ordered_items, require_text


def resolve_columns(row_keys: tuple[str, ...], keys) -> tuple[int, ...]:
    positions = {key: column for column, key in enumerate(row_keys)}
    request = ordered_items(keys, 'review keys', 'INVALID_KEY_REQUEST')
    columns = []
    for key in request:
        key = require_text(key, 'review key', 'UNKNOWN_ROW')
        if key not in positions:
            raise LedgerError('UNKNOWN_ROW', f'{key!r} is not in this sealed day')
        columns.append(positions[key])
    return tuple(columns)


def project_joint_rows(states: tuple[tuple[int, ...], ...],
                       columns: tuple[int, ...]) -> list[tuple[int, ...]]:
    unique_columns = tuple(dict.fromkeys(columns))
    domains = [sorted({state[column] for state in states}) for column in unique_columns]
    positions = {column: index for index, column in enumerate(unique_columns)}
    request = tuple(positions[column] for column in columns)
    return sorted(tuple(choice[index] for index in request) for choice in product(*domains))
