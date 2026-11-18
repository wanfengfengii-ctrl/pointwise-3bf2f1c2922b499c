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
    """按请求列序（保留重复列）投影每条同表共现状态，整元组去重后按字典序排列。"""
    return sorted({tuple(state[column] for column in columns) for state in states})
