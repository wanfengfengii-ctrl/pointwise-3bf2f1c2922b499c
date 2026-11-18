from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from corrections import CorrectionTransaction, RowChange, register_sheet
from exchange import export_day, import_day, initialize_archive
from publication import initialize_source, seal_day
from review import audit_after
from snapshots import LedgerError, freeze_table


def transaction(name, *changes):
    return CorrectionTransaction(name, tuple(RowChange(*change) for change in changes))


class ReviewTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.source_path = Path(folder.name) / 'source.sqlite3'
        self.archive_path = Path(folder.name) / 'archive.sqlite3'
        self.source = sqlite3.connect(self.source_path)
        self.addCleanup(self.source.close)
        initialize_source(self.source, 'puan')

    def simple_batch(self):
        first = freeze_table(self.source, 'd1', 'opening', {'x': 0, 'y': 0, 'z': 0})
        last = freeze_table(self.source, 'd1', 'closing', {'x': 1, 'y': 1, 'z': 1})
        register_sheet(self.source, 'd1', 'north', 'A sheet', (transaction('A', ('x', 0, 1), ('y', 0, 1)),))
        register_sheet(self.source, 'd1', 'south', 'M sheet', (transaction('M', ('z', 0, 1)),))
        return seal_day(self.source, first, last, ('M', 'A'))

    def handoff_and_close_source(self, receipts):
        with closing(sqlite3.connect(self.archive_path)) as archive:
            initialize_archive(archive)
            for receipt in receipts:
                import_day(archive, export_day(self.source, receipt.result_id))
        self.source.close()
        self.source_path.unlink()

    def test_joint_rows_remain_correlated_online_and_after_handoff(self):
        receipt = self.simple_batch()
        online = audit_after(self.source, receipt.result_id, 'M', ('x', 'y'))
        self.assertEqual(online, [(0, 0), (1, 1)])
        self.handoff_and_close_source((receipt,))
        with closing(sqlite3.connect(self.archive_path)) as archive:
            self.assertEqual(audit_after(archive, receipt.result_id, 'M', ('x', 'y'), archive=True),
                             [(0, 0), (1, 1)])

    def test_only_completable_prefixes_contribute_at_named_receipt(self):
        day = 'd1'
        initial = {'x': 0, 'y': 0, 'w': 0, 'z': 0}
        terminal = {'x': 2, 'y': 2, 'w': 1, 'z': 1}
        first = freeze_table(self.source, day, 'opening', initial)
        last = freeze_table(self.source, day, 'closing', terminal)
        north = (transaction('D', ('x', 0, 2), ('y', 0, 2)),
                 transaction('A', ('x', 0, 1), ('y', 0, 1), ('w', 0, 1)))
        south = (transaction('M', ('z', 0, 1)), transaction('B', ('x', 1, 0), ('y', 1, 0)))
        register_sheet(self.source, day, 'north', 'north original', north)
        register_sheet(self.source, day, 'south', 'south original', south)
        orders = (('D', 'M', 'B', 'A'), ('M', 'A', 'B', 'D'))
        receipts = tuple(seal_day(self.source, first, last, order) for order in orders)
        expected = [(0, 0, 0), (0, 0, 1), (1, 1, 1), (2, 2, 1)]
        repeated = [(0, 0, 0), (1, 0, 1), (1, 1, 1), (1, 2, 1)]
        online = [audit_after(self.source, receipt.result_id, 'M', ('x', 'y', 'w')) for receipt in receipts]
        self.assertEqual(online, [expected, expected])
        self.handoff_and_close_source(receipts)
        downstream = []
        with closing(sqlite3.connect(self.archive_path)) as archive:
            for receipt in receipts:
                result = audit_after(archive, receipt.result_id, 'M', ('x', 'y', 'w'), archive=True)
                self.assertEqual(result, expected)
                self.assertNotIn((2, 2, 0), result)
                self.assertNotIn((0, 1, 1), result)
                self.assertEqual(audit_after(archive, receipt.result_id, 'M', ('w', 'x', 'w'), archive=True),
                                 repeated)
                self.assertEqual(audit_after(archive, receipt.result_id, 'M', ('w',), archive=True), [(0,), (1,)])
                downstream.append(result)
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'n9.complete_prefix',
            'input': {'opening': initial, 'closing': terminal, 'selection_orders': orders,
                      'transactions': {item.name: [[change.key, change.old, change.new]
                                                   for change in item.changes] for item in north + south},
                      'receipt_transaction': 'M', 'keys': ['x', 'y', 'w']},
            'expected': [expected, expected], 'actual': online,
            'downstream_expected': [expected, expected], 'downstream_actual': downstream,
            'code_paths': ['publication/reconcile.py', 'publication/replay.py', 'publication/evidence.py',
                           'exchange/catalog.py', 'review/audit.py', 'review/projection.py'],
            'oracle': 'A、B、D 必须依次生效，M 可插在四个间隙。D 先执行会阻断 A。',
        }, ensure_ascii=False))

    def test_query_errors_and_empty_projection(self):
        receipt = self.simple_batch()
        for db, archived in ((self.source, False),):
            self.check_queries(db, receipt, archived)
        self.handoff_and_close_source((receipt,))
        with closing(sqlite3.connect(self.archive_path)) as archive:
            self.check_queries(archive, receipt, True)

    def check_queries(self, db, receipt, archived):
        self.assertEqual(audit_after(db, receipt.result_id, 'M', (), archive=archived), [()])
        for result_id, name, keys, code in (
            ('missing/3', 'M', ('x',), 'UNKNOWN_RESULT'),
            (receipt.result_id, 'absent', (), 'UNKNOWN_TRANSACTION'),
            (receipt.result_id, 'M', ('x', 'absent', 'y'), 'UNKNOWN_ROW'),
            (receipt.result_id, 'M', 'x', 'INVALID_KEY_REQUEST'),
        ):
            with self.subTest(archive=archived, code=code), self.assertRaisesRegex(LedgerError, code):
                audit_after(db, result_id, name, keys, archive=archived)
