from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from publication import initialize_source
from snapshots import LedgerError, ObservationRow, freeze_table, read_revision


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        initialize_source(self.db, 'puan')

    def test_frozen_revision_keeps_values_and_source(self):
        first = freeze_table(self.db, 'd1', 'morning', [('x', 3)])
        second = freeze_table(self.db, 'd1', 'late', [('x', 4)])
        self.assertNotEqual(first, second)
        self.assertEqual(read_revision(self.db, first).rows, (ObservationRow('x', 3),))
        self.assertEqual(read_revision(self.db, first).source, 'morning')
        self.assertEqual(read_revision(self.db, second).rows, (ObservationRow('x', 4),))
        self.assertEqual(read_revision(self.db, second).source, 'late')
        self.assertIsNone(read_revision(self.db, second + 1))

    def test_reinitialize_preserves_registered_revisions(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'source.sqlite3'
            with closing(sqlite3.connect(path)) as source:
                first = freeze_table_after_initialization(source)
                second = freeze_table(source, 'd1', 'late', {'x': 4})
            with closing(sqlite3.connect(path)) as source:
                initialize_source(source, 'puan')
                with self.assertRaisesRegex(LedgerError, 'ORIGIN_CONFLICT'):
                    initialize_source(source, 'other')
                self.assertEqual(read_revision(source, first).rows[0].value, 3)
                self.assertEqual(read_revision(source, second).rows[0].value, 4)
                self.assertEqual(source.execute('SELECT COUNT(*) FROM revisions').fetchone(), (2,))

    def test_duplicate_rows_reject_the_entire_table(self):
        first = freeze_table(self.db, 'd1', 'accepted', [('x', 3)])
        with self.assertRaisesRegex(LedgerError, 'DUPLICATE_ROW'):
            freeze_table(self.db, 'd1', 'duplicate', [('x', 3), ('x', 4)])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM revisions').fetchone(), (1,))
        self.assertEqual(read_revision(self.db, first).rows[0].value, 3)

    def test_invalid_readings_and_keys_do_not_add_rows(self):
        for rows in ([('x', None)], [('x', True)], [('x', 1.0)], [('x', '2')],
                     [('x',)], [(' x', 4)], [('x\x00', 4)], [('', 4)]):
            with self.subTest(rows=rows), self.assertRaises(LedgerError):
                freeze_table(self.db, 'd1', 'invalid', rows)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM revisions').fetchone(), (0,))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM observation_rows').fetchone(), (0,))

    def test_integer_readings_exceed_sqlite_and_decimal_string_limits(self):
        huge = 1 << 18000
        number = freeze_table(self.db, 'd1', 'large readings', {'x': huge, 'y': -huge, 'z': 0})
        actual = {row.key: row.value for row in read_revision(self.db, number).rows}
        self.assertTrue(actual == {'x': huge, 'y': -huge, 'z': 0})
        kinds = self.db.execute('SELECT DISTINCT typeof(reading) FROM observation_rows').fetchall()
        self.assertEqual(kinds, [('text',)])


def freeze_table_after_initialization(db):
    initialize_source(db, 'puan')
    return freeze_table(db, 'd1', 'morning', {'x': 3})
