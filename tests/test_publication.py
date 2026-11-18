from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from corrections import CorrectionTransaction, RowChange, register_sheet
from publication import initialize_source, read_sealed_day, seal_day
from review import audit_after
from snapshots import LedgerError, freeze_table


def transaction(name, *changes):
    return CorrectionTransaction(name, tuple(RowChange(*change) for change in changes))


class PublicationTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'publication.sqlite3'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        initialize_source(self.db, 'puan')

    def freeze_pair(self, opening, ending, *, day='d1'):
        return (freeze_table(self.db, day, 'opening', opening),
                freeze_table(self.db, day, 'closing', ending))

    def assert_publication_counts(self, db, expected):
        self.assertEqual(db.execute('SELECT COUNT(*) FROM sealed_days').fetchone(), (expected,))
        self.assertEqual(db.execute('SELECT COUNT(*) FROM successful_receipts').fetchone(), (expected,))

    def test_reverse_delivery_replays_and_binds_receipt(self):
        first, last = self.freeze_pair({'x': 0}, {'x': 2})
        register_sheet(self.db, 'd1', 'north', 'B before A', (
            transaction('B', ('x', 1, 2)), transaction('A', ('x', 0, 1)),
        ))
        receipt = seal_day(self.db, first, last, ('B', 'A'))
        fixed = read_sealed_day(self.db, receipt.result_id)
        self.assertEqual(fixed.receipt, receipt)
        self.assertEqual((fixed.evidence.opening.revision_id, fixed.evidence.closing.revision_id), (first, last))
        self.assertEqual(audit_after(self.db, receipt.result_id, 'A', ['x']), [(1,)])
        self.assert_publication_counts(self.db, 1)

    def test_branch_choice_with_ten_transactions(self):
        start = {'x': 0, **{f'k{i}': 0 for i in range(7)}}
        end = {'x': 2, **{f'k{i}': 1 for i in range(7)}}
        first, last = self.freeze_pair(start, end)
        records = (transaction('A', ('x', 0, 2)), transaction('B', ('x', 0, 1)),
                   transaction('C', ('x', 1, 0))) + tuple(
                       transaction(f'K{i}', (f'k{i}', 0, 1)) for i in range(7)
                   )
        register_sheet(self.db, 'd1', 'north', 'independent corrections', records)
        receipt = seal_day(self.db, first, last, tuple(item.name for item in records))
        self.assertEqual(audit_after(self.db, receipt.result_id, 'A', ('x', 'k0', 'x')),
                         [(2, 0, 2), (2, 1, 2)])
        self.assertEqual(audit_after(self.db, receipt.result_id, 'C', ('x',)), [(0,)])

    def test_partial_old_image_does_not_apply(self):
        first, last = self.freeze_pair({'x': 0, 'y': 0}, {'x': 1, 'y': 2})
        register_sheet(self.db, 'd1', 'north', 'old image', (
            transaction('A', ('x', 0, 1), ('y', 1, 2)),
        ))
        with self.assertRaisesRegex(LedgerError, 'DAY_REPLAY_MISMATCH'):
            seal_day(self.db, first, last, ('A',))
        self.assert_publication_counts(self.db, 0)

    def test_no_common_replay(self):
        first, last = self.freeze_pair({'x': 0}, {'x': 2})
        register_sheet(self.db, 'd1', 'north', 'A original', (transaction('A', ('x', 0, 1)),))
        register_sheet(self.db, 'd1', 'south', 'D original', (transaction('D', ('x', 0, 2)),))
        try:
            seal_day(self.db, first, last, ('A', 'D'))
        except LedgerError as exc:
            self.assertEqual(exc.code, 'DAY_REPLAY_MISMATCH')
        else:
            self.fail('DAY_REPLAY_MISMATCH: incompatible corrections received a success receipt')
        self.assert_publication_counts(self.db, 0)

    def test_all_transactions_used_with_wrong_terminal_table(self):
        first, last = self.freeze_pair({'x': 0, 'y': 0}, {'x': 1, 'y': 9})
        register_sheet(self.db, 'd1', 'north', 'one correction', (transaction('A', ('x', 0, 1)),))
        with self.assertRaisesRegex(LedgerError, 'DAY_REPLAY_MISMATCH'):
            seal_day(self.db, first, last, ('A',))
        self.assert_publication_counts(self.db, 0)

    def test_empty_batch_still_compares_entire_table(self):
        first, last = self.freeze_pair({'x': -7}, {'x': -7})
        receipt = seal_day(self.db, first, last, ())
        self.assertEqual(read_sealed_day(self.db, receipt.result_id).evidence.transactions, ())
        changed = freeze_table(self.db, 'd1', 'different closing', {'x': -8})
        with self.assertRaisesRegex(LedgerError, 'DAY_REPLAY_MISMATCH'):
            seal_day(self.db, first, changed, ())
        self.assert_publication_counts(self.db, 1)

    def test_resolves_originals_within_the_selected_day(self):
        first, last = self.freeze_pair({'x': 0}, {'x': 1})
        register_sheet(self.db, 'd1', 'north', 'd1 original', (transaction('A', ('x', 0, 1)),))
        register_sheet(self.db, 'd2', 'south', 'd2 original', (
            transaction('A', ('x', 0, 2)), transaction('Q', ('x', 0, 1)),
        ))
        second_day = freeze_table(self.db, 'd2', 'other day', {'x': 1})
        with self.assertRaisesRegex(LedgerError, 'DAY_CONFLICT'):
            seal_day(self.db, first, second_day, ('A',))
        with self.assertRaisesRegex(LedgerError, 'UNKNOWN_TRANSACTION'):
            seal_day(self.db, first, last, ('Q',))
        with self.assertRaisesRegex(LedgerError, 'UNKNOWN_REVISION'):
            seal_day(self.db, first, 99, ('A',))
        self.assert_publication_counts(self.db, 0)
        receipt = seal_day(self.db, first, last, ('A',))
        selected, = read_sealed_day(self.db, receipt.result_id).evidence.transactions
        self.assertEqual((selected.station, selected.document), ('north', 'd1 original'))
        self.assertEqual(audit_after(self.db, receipt.result_id, 'A', ('x',)), [(1,)])

    def test_rejects_mismatched_keys_and_changes_outside_the_table(self):
        first, last = self.freeze_pair({'x': 0}, {'y': 0})
        with self.assertRaisesRegex(LedgerError, 'KEY_SET_MISMATCH'):
            seal_day(self.db, first, last, ())
        register_sheet(self.db, 'd1', 'north', 'other key', (transaction('A', ('y', 0, 1)),))
        with self.assertRaisesRegex(LedgerError, 'UNKNOWN_CHANGE_ROW'):
            seal_day(self.db, first, first, ('A',))
        self.assert_publication_counts(self.db, 0)

    def test_duplicate_selection_and_batch_limit(self):
        first, last = self.freeze_pair({'x': 0}, {'x': 0})
        records = tuple(transaction(f'T{i}', ('x', 0, 0)) for i in range(11))
        register_sheet(self.db, 'd1', 'north', 'eleven named corrections', records)
        with self.assertRaisesRegex(LedgerError, 'DUPLICATE_SELECTION'):
            seal_day(self.db, first, last, ('T0', 'T0'))
        with self.assertRaisesRegex(LedgerError, 'INVALID_SELECTION'):
            seal_day(self.db, first, last, tuple(item.name for item in records))
        self.assert_publication_counts(self.db, 0)

    def test_failed_commit_rolls_back_day_and_receipt_across_reopen(self):
        first, last = self.freeze_pair({'x': 0}, {'x': 1})
        register_sheet(self.db, 'd1', 'north', 'valid work', (transaction('A', ('x', 0, 1)),))
        old = seal_day(self.db, first, last, ('A',))
        with self.assertRaisesRegex(LedgerError, 'COMMIT_FAILED.*after staging'):
            seal_day(self.db, first, last, ('A',), fail_before_commit=True)
        self.assertFalse(self.db.in_transaction)
        self.db.close()
        with closing(sqlite3.connect(self.path)) as reopened:
            self.assert_publication_counts(reopened, 1)
            self.assertEqual(read_sealed_day(reopened, old.result_id).receipt, old)
            self.assertEqual(audit_after(reopened, old.result_id, 'A', ('x',)), [(1,)])
            self.assertEqual(reopened.execute('SELECT result_id FROM successful_receipts').fetchall(),
                             [(old.result_id,)])
