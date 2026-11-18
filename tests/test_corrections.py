from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from corrections import CorrectionTransaction, RowChange, read_sheet, register_sheet
from corrections.registry import read_day_transactions
from publication import initialize_source, seal_day
from snapshots import LedgerError, freeze_table


def transaction(name, *changes):
    return CorrectionTransaction(name, tuple(RowChange(*change) for change in changes))


class CorrectionTests(unittest.TestCase):
    def test_duplicate_change_rejects_the_whole_sheet(self):
        with closing(sqlite3.connect(':memory:')) as db:
            initialize_source(db, 'puan')
            old = register_sheet(db, 'd1', 'north', 'old', (transaction('B', ('x', 0, 1)),))
            with self.assertRaisesRegex(LedgerError, 'DUPLICATE_CHANGE'):
                register_sheet(db, 'd1', 'south', 'bad sheet', (
                    transaction('A', ('y', 0, 1)), transaction('C', ('x', 0, 1), ('x', 1, 2)),
                ))
            self.assertEqual(read_sheet(db, old.sheet_id), old)
            self.assertEqual(list(read_day_transactions(db, 'd1')), ['B'])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM correction_sheets').fetchone(), (1,))

    def test_same_day_name_conflict_rolls_back_all_rows_after_reopen(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'source.sqlite3'
            with closing(sqlite3.connect(path)) as db:
                initialize_source(db, 'puan')
                old = register_sheet(db, 'd1', 'north', 'original B', (transaction('B', ('x', 0, 1)),))
                with self.assertRaisesRegex(LedgerError, 'TRANSACTION_CONFLICT'):
                    register_sheet(db, 'd1', 'south', 'conflicting original', (
                        transaction('A', ('y', 0, 1)), transaction('B', ('x', 0, 2)),
                    ))
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(read_sheet(db, old.sheet_id), old)
                self.assertEqual(read_day_transactions(db, 'd1'), {
                    'B': (old.sheet_id, 'north', 'original B', old.transactions[0]),
                })
                self.assertEqual(db.execute('SELECT COUNT(*) FROM correction_sheets').fetchone(), (1,))
                self.assertEqual(db.execute('SELECT COUNT(*) FROM correction_rows').fetchone(), (1,))
                first = freeze_table(db, 'd1', 'opening', {'y': 0})
                last = freeze_table(db, 'd1', 'closing', {'y': 1})
                with self.assertRaisesRegex(LedgerError, 'UNKNOWN_TRANSACTION'):
                    seal_day(db, first, last, ('A',))

    def test_duplicate_name_and_invalid_change_inputs_do_not_register(self):
        with closing(sqlite3.connect(':memory:')) as db:
            initialize_source(db, 'puan')
            for records, code in (
                ((transaction('A', ('x', 0, 1)), transaction('A', ('y', 0, 1))), 'DUPLICATE_TRANSACTION'),
                ((transaction('X', ('x', True, 1)),), 'INVALID_READING'),
                ((transaction('Y', ('x', 0, None)),), 'INVALID_READING'),
                ((transaction('Z'),), 'INVALID_TRANSACTION'),
                ((), 'INVALID_SHEET'),
            ):
                with self.subTest(code=code), self.assertRaisesRegex(LedgerError, code):
                    register_sheet(db, 'd1', 'north', 'invalid', records)
            self.assertEqual(read_day_transactions(db, 'd1'), {})
            self.assertEqual(db.execute('SELECT COUNT(*) FROM correction_sheets').fetchone(), (0,))

    def test_original_keeps_transaction_order_and_exact_changes(self):
        with closing(sqlite3.connect(':memory:')) as db:
            initialize_source(db, 'puan')
            huge = 2**100
            record = register_sheet(db, 'd1', 'north', 'worksheet 8', (
                transaction('B', ('y', -huge, 0), ('x', 7, -9)), transaction('A', ('x', 0, 7)),
            ))
            self.assertEqual(read_sheet(db, record.sheet_id), record)
            self.assertEqual(record.transactions, (
                transaction('B', ('x', 7, -9), ('y', -huge, 0)), transaction('A', ('x', 0, 7)),
            ))
