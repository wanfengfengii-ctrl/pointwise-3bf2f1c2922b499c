from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from corrections import CorrectionTransaction, RowChange, register_sheet
from exchange import export_day, import_day, initialize_archive, read_received_day
from publication import initialize_source, seal_day
from review import audit_after
from snapshots import LedgerError, freeze_table


def json_text(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


class HandoffTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.source_path = Path(folder.name) / 'source.sqlite3'
        self.archive_path = Path(folder.name) / 'archive.sqlite3'
        self.source = sqlite3.connect(self.source_path)
        self.archive = sqlite3.connect(self.archive_path)
        self.addCleanup(self.source.close)
        self.addCleanup(self.archive.close)
        initialize_source(self.source, '浦岸/测站')
        initialize_archive(self.archive)

    def publish(self, db, value, name='A'):
        first = freeze_table(db, 'd1', 'original opening', {'x': 0, 'y': 7})
        last = freeze_table(db, 'd1', 'original closing', {'x': value, 'y': 7})
        register_sheet(db, 'd1', 'north', f'field sheet {name}', (
            CorrectionTransaction(name, (RowChange('x', 0, value),)),
        ))
        receipt = seal_day(db, first, last, (name,))
        return receipt, export_day(db, receipt.result_id)

    def test_offline_reopen_retains_old_receipt_and_key_positions(self):
        receipt, blob = self.publish(self.source, 1)
        copy = import_day(self.archive, blob)
        online = audit_after(self.source, receipt.result_id, 'A', ('x', 'x'))
        self.assertEqual(online, [(1, 1)])
        freeze_table(self.source, 'd1', 'later correction', {'x': 99, 'y': 23})
        self.assertEqual(audit_after(self.source, receipt.result_id, 'A', ('x', 'x')), online)
        self.assertEqual(export_day(self.source, receipt.result_id), blob)
        self.archive.close()
        self.source.close()
        self.source_path.unlink()
        with closing(sqlite3.connect(self.archive_path)) as reopened:
            initialize_archive(reopened)
            recovered = read_received_day(reopened, receipt.result_id)
            self.assertEqual(recovered, copy)
            self.assertEqual(recovered.origin, '浦岸/测站')
            self.assertEqual(recovered.day.receipt, receipt)
            self.assertEqual(recovered.day.evidence.opening.source, 'original opening')
            selected, = recovered.day.evidence.transactions
            self.assertEqual((selected.station, selected.document), ('north', 'field sheet A'))
            self.assertEqual(audit_after(reopened, receipt.result_id, 'A', ('x', 'x'), archive=True), [(1, 1)])
            self.assertEqual(audit_after(reopened, receipt.result_id, 'A', ('y', 'x', 'y'), archive=True),
                             [(7, 1, 7)])

    def test_unknown_result_cannot_be_exported(self):
        with self.assertRaisesRegex(LedgerError, 'UNKNOWN_RESULT'):
            export_day(self.source, 'missing/1')

    def assert_original_copy(self, receipt, value):
        self.assertEqual(self.archive.execute('SELECT COUNT(*) FROM received_days').fetchone(), (1,))
        self.assertEqual(audit_after(self.archive, receipt.result_id, 'A', ('x',), archive=True), [(value,)])

    def test_truncated_handoff_preserves_existing_copy(self):
        original, blob = self.publish(self.source, 1)
        import_day(self.archive, blob)
        other, other_blob = self.publish(self.source, 2, 'B')
        with self.assertRaisesRegex(LedgerError, 'BAD_PACKAGE'):
            import_day(self.archive, other_blob[:-17])
        with self.assertRaisesRegex(LedgerError, 'UNKNOWN_RESULT'):
            read_received_day(self.archive, other.result_id)
        self.assert_original_copy(original, 1)

    def test_changed_reading_with_original_checksum_is_rejected(self):
        original, blob = self.publish(self.source, 1)
        import_day(self.archive, blob)
        other, other_blob = self.publish(self.source, 2, 'B')
        envelope = json.loads(other_blob)
        evidence = json.loads(envelope['body']['evidence'])
        evidence['after'][0][1][0][1] = '0x8'
        envelope['body']['evidence'] = json_text(evidence)
        with self.assertRaisesRegex(LedgerError, 'BAD_PACKAGE'):
            import_day(self.archive, json_text(envelope).encode('ascii'))
        with self.assertRaisesRegex(LedgerError, 'UNKNOWN_RESULT'):
            read_received_day(self.archive, other.result_id)
        self.assert_original_copy(original, 1)

    def test_receipt_origin_must_still_match_when_checksum_is_valid(self):
        _, blob = self.publish(self.source, 1)
        envelope = json.loads(blob)
        envelope['body']['origin'] = 'other'
        envelope['sha256'] = sha256(json_text(envelope['body']).encode('ascii')).hexdigest()
        with self.assertRaisesRegex(LedgerError, 'BAD_PACKAGE'):
            import_day(self.archive, json_text(envelope).encode('ascii'))
        self.assertEqual(self.archive.execute('SELECT COUNT(*) FROM received_days').fetchone(), (0,))

    def test_same_content_retry_returns_first_copy(self):
        receipt, blob = self.publish(self.source, 1)
        first = import_day(self.archive, blob)
        self.assertEqual(import_day(self.archive, blob + b'\n'), first)
        self.assertEqual(read_received_day(self.archive, receipt.result_id), first)
        self.assert_original_copy(receipt, 1)

    def test_valid_conflicting_copy_cannot_replace_original(self):
        original, blob = self.publish(self.source, 1)
        with closing(sqlite3.connect(':memory:')) as duplicate_origin:
            initialize_source(duplicate_origin, '浦岸/测站')
            same_id, different_blob = self.publish(duplicate_origin, 5)
        self.assertEqual(same_id.result_id, original.result_id)
        self.assertNotEqual(different_blob, blob)
        with closing(sqlite3.connect(':memory:')) as separate_archive:
            initialize_archive(separate_archive)
            accepted = import_day(separate_archive, different_blob)
            self.assertEqual(accepted.result_id, original.result_id)
            self.assertEqual(audit_after(separate_archive, original.result_id, 'A', ('x',), archive=True), [(5,)])
        first = import_day(self.archive, blob)
        with self.assertRaisesRegex(LedgerError, 'COPY_CONFLICT'):
            import_day(self.archive, different_blob)
        self.assert_original_copy(original, 1)
        self.archive.close()
        with closing(sqlite3.connect(self.archive_path)) as reopened:
            self.assertEqual(read_received_day(reopened, original.result_id), first)
            self.assertEqual(audit_after(reopened, original.result_id, 'A', ('x',), archive=True), [(1,)])

    def test_large_signed_readings_survive_entire_handoff(self):
        value = -(1 << 18000)
        receipt, blob = self.publish(self.source, value)
        import_day(self.archive, blob)
        actual = audit_after(self.archive, receipt.result_id, 'A', ('x', 'y'), archive=True)
        self.assertTrue(actual == [(value, 7)])
