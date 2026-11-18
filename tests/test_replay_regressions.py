"""事故回归：互斥更正拒签、联合读值只取完整重放中的同表共现状态。"""
from contextlib import closing
import sqlite3
import unittest

from corrections import CorrectionTransaction, RowChange, register_sheet
from exchange import export_day
from publication import initialize_source, read_sealed_day, seal_day
from review import audit_after
from snapshots import LedgerError, freeze_table


def transaction(name, *changes):
    return CorrectionTransaction(name, tuple(RowChange(*change) for change in changes))


class ReplayRegressionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        initialize_source(self.db, 'puan')

    def assert_publication_counts(self, expected):
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM sealed_days').fetchone(), (expected,))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM successful_receipts').fetchone(), (expected,))

    def test_individually_valid_pair_cannot_share_one_batch(self):
        # 事故第一批：A、D 各自单独都能到账，但同一批里先做的一笔会让另一笔旧值失效。
        first = freeze_table(self.db, 'd1', 'opening', {'x': 0})
        last = freeze_table(self.db, 'd1', 'closing', {'x': 2})
        register_sheet(self.db, 'd1', 'north', 'north original', (transaction('A', ('x', 0, 1)),))
        register_sheet(self.db, 'd1', 'south', 'south original', (transaction('D', ('x', 0, 2)),))
        with self.assertRaisesRegex(LedgerError, 'DAY_REPLAY_MISMATCH'):
            seal_day(self.db, first, last, ('A', 'D'))
        self.assert_publication_counts(0)
        # 拒签不留成果；单独封存 D 仍合法，且不受此前失败影响。
        receipt = seal_day(self.db, first, last, ('D',))
        self.assertEqual(audit_after(self.db, receipt.result_id, 'D', ('x',)), [(2,)])
        self.assert_publication_counts(1)

    def test_chain_must_wait_for_restored_old_value(self):
        # B 把 x 还原为 0 之后 C 才能生效，完整顺序只有 A、B、C 一种。
        first = freeze_table(self.db, 'd1', 'opening', {'x': 0})
        last = freeze_table(self.db, 'd1', 'closing', {'x': 2})
        register_sheet(self.db, 'd1', 'north', 'chained corrections', (
            transaction('A', ('x', 0, 1)), transaction('B', ('x', 1, 0)),
            transaction('C', ('x', 0, 2)),
        ))
        receipt = seal_day(self.db, first, last, ('C', 'A', 'B'))
        self.assertEqual(audit_after(self.db, receipt.result_id, 'A', ('x',)), [(1,)])
        self.assertEqual(audit_after(self.db, receipt.result_id, 'B', ('x',)), [(0,)])
        self.assertEqual(audit_after(self.db, receipt.result_id, 'C', ('x',)), [(2,)])

    def test_every_transaction_joint_states_come_from_complete_replays(self):
        # 事故第二批：M 可插入四个位置；A、B、D 相对顺序固定，联合读值不得拆开重组。
        first = freeze_table(self.db, 'd1', 'opening', {'x': 0, 'y': 0, 'w': 0, 'z': 0})
        last = freeze_table(self.db, 'd1', 'closing', {'x': 2, 'y': 2, 'w': 1, 'z': 1})
        register_sheet(self.db, 'd1', 'north', 'north original', (
            transaction('D', ('x', 0, 2), ('y', 0, 2)),
            transaction('A', ('x', 0, 1), ('y', 0, 1), ('w', 0, 1)),
        ))
        register_sheet(self.db, 'd1', 'south', 'south original', (
            transaction('M', ('z', 0, 1)), transaction('B', ('x', 1, 0), ('y', 1, 0)),
        ))
        receipt = seal_day(self.db, first, last, ('D', 'M', 'B', 'A'))
        result_id = receipt.result_id
        joint = [(0, 0, 0), (0, 0, 1), (1, 1, 1), (2, 2, 1)]
        self.assertEqual(audit_after(self.db, result_id, 'M', ('x', 'y', 'w')), joint)
        self.assertEqual(audit_after(self.db, result_id, 'M', ('w', 'x', 'w')),
                         [(0, 0, 0), (1, 0, 1), (1, 1, 1), (1, 2, 1)])
        # x、y 始终同时改变：其他事务提交时联合值各自只有一个。
        self.assertEqual(audit_after(self.db, result_id, 'A', ('x', 'y', 'w')), [(1, 1, 1)])
        self.assertEqual(audit_after(self.db, result_id, 'B', ('x', 'y', 'w')), [(0, 0, 1)])
        self.assertEqual(audit_after(self.db, result_id, 'D', ('x', 'y', 'w')), [(2, 2, 1)])
        self.assertEqual(audit_after(self.db, result_id, 'D', ('z',)), [(0,), (1,)])

    def test_failed_seal_and_later_corrections_keep_previous_result(self):
        first = freeze_table(self.db, 'd1', 'opening', {'x': 0})
        last = freeze_table(self.db, 'd1', 'closing', {'x': 1})
        register_sheet(self.db, 'd1', 'north', 'valid work', (transaction('A', ('x', 0, 1)),))
        receipt = seal_day(self.db, first, last, ('A',))
        blob = export_day(self.db, receipt.result_id)
        # 后到更正与既有成果同名日：互斥新批拒签，旧成果、回执和交班件字节不变。
        register_sheet(self.db, 'd1', 'south', 'later correction', (transaction('D', ('x', 0, 2)),))
        with self.assertRaisesRegex(LedgerError, 'DAY_REPLAY_MISMATCH'):
            seal_day(self.db, first, last, ('A', 'D'))
        self.assert_publication_counts(1)
        self.assertEqual(read_sealed_day(self.db, receipt.result_id).receipt, receipt)
        self.assertEqual(export_day(self.db, receipt.result_id), blob)
        self.assertEqual(audit_after(self.db, receipt.result_id, 'A', ('x',)), [(1,)])


if __name__ == '__main__':
    unittest.main()
