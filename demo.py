from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from corrections import CorrectionTransaction, RowChange, register_sheet
from exchange import export_day, import_day, initialize_archive, read_received_day
from publication import initialize_source, seal_day
from review import audit_after
from snapshots import freeze_table


def main() -> None:
    day = '2026-11-18'
    opening = {'x': 0, 'y': 0, 'z': 0}
    ending = {'x': 1, 'y': 1, 'z': 1}
    a = CorrectionTransaction('A', (RowChange('x', 0, 1), RowChange('y', 0, 1)))
    m = CorrectionTransaction('M', (RowChange('z', 0, 1),))
    keys = ('x', 'y')
    expected = [(0, 0), (1, 1)]
    with TemporaryDirectory() as folder:
        source_path = Path(folder) / 'observations.sqlite3'
        archive_path = Path(folder) / 'night.sqlite3'
        with closing(sqlite3.connect(source_path)) as source:
            initialize_source(source, 'puan-observations')
            first = freeze_table(source, day, '晨班冻结表', opening)
            last = freeze_table(source, day, '白班日终表', ending)
            register_sheet(source, day, '北工位', '北站更正单', (a,))
            register_sheet(source, day, '南工位', '南站更正单', (m,))
            receipt = seal_day(source, first, last, ('M', 'A'))
            online = audit_after(source, receipt.result_id, 'M', keys)
            blob = export_day(source, receipt.result_id)
            with closing(sqlite3.connect(archive_path)) as archive:
                initialize_archive(archive)
                received = import_day(archive, blob)
            freeze_table(source, day, '后到修订', {'x': 8, 'y': 9, 'z': 1})
        source_path.unlink()
        with closing(sqlite3.connect(archive_path)) as archive:
            restored = read_received_day(archive, receipt.result_id)
            offline = audit_after(archive, receipt.result_id, 'M', keys, archive=True)
        if online != expected or offline != expected or restored != received or restored.day.receipt != receipt:
            raise AssertionError('the archived receipt and joint observations did not match the desk check')
        print(f'成果 {receipt.result_id} 已归档，出处 {restored.origin}，M 提交后的 (x,y) 为 {offline}')
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'n9',
            'input': {'day': day, 'opening': opening, 'closing': ending,
                      'transactions': {'A': [['x', 0, 1], ['y', 0, 1]], 'M': [['z', 0, 1]]},
                      'receipt_transaction': 'M', 'keys': keys},
            'expected': expected,
            'actual': online,
            'downstream_expected': expected,
            'downstream_actual': offline,
            'code_paths': ['publication/replay.py', 'publication/commit.py', 'exchange/export.py',
                           'exchange/import_.py', 'review/audit.py', 'review/projection.py'],
            'oracle': '手算 M→A 与 A→M 两条完整顺序。A 同时改 x 和 y，两值始终相等。',
        }, ensure_ascii=False))


if __name__ == '__main__':
    main()
