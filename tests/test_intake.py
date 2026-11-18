from copy import deepcopy

from catalog.history import current_revision, find_declared_revision
from catalog.source import load_revision
from intake.input import SubmissionInputError
from intake.register import register
from intake.revision import RevisionConflict
from intake.validate import RegistrationValidationError
from layout.stripe import StripeEntry
from tests.fixtures import CatalogCase, shift_batch, source_records


class TestRegister(CatalogCase):
    def test_repeat(self):
        batch = shift_batch()
        first = register(self.db, batch)
        second = register(self.db, shift_batch())
        self.assertEqual(first, second)
        revisions, current = source_records(self.db)
        self.assertEqual(len(revisions), 1)
        self.assertEqual(current, [(batch['batch_id'], first)])
        self.assertEqual(find_declared_revision(self.db, batch['batch_id'], batch['revision']), first)
        stored = load_revision(self.db, first)
        self.assertEqual([row.row_number for row in stored.rows], [101, 108])
        self.assertEqual(stored.temperature, (StripeEntry(1, 41), StripeEntry(2, 7)))
        self.assertEqual(stored.pressure, (StripeEntry(2, 9),))
        self.assertFalse(stored.retired)

    def test_payload_conflict(self):
        original = shift_batch()
        original_id = register(self.db, original)
        before = source_records(self.db)
        self.assertEqual(register(self.db, deepcopy(original)), original_id)
        changes = {
            'temperature': [[1, 41], [2, 17]],
            'pressure': [[2, 19]],
            'rows': [{'row_number': 101, 'trays': [[{}]]}, {'row_number': 108, 'trays': [[{}, {}], None, None]}],
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                with self.assertRaises(RevisionConflict):
                    register(self.db, {**original, field: value})
                self.assertEqual(source_records(self.db), before)
        self.assertEqual(current_revision(self.db, original['batch_id']), original_id)

    def test_out_of_range_slot(self):
        batch = {
            'batch_id': 'two-slot', 'revision': 'initial',
            'rows': [{'row_number': 12, 'trays': [[{}, {}]]}],
            'temperature': [[3, 44]], 'pressure': [],
        }
        with self.assertRaisesRegex(RegistrationValidationError, 'temperature.*slot 2'):
            register(self.db, batch)
        self.assertEqual(source_records(self.db), ([], []))
        self.assertIsNone(current_revision(self.db, 'two-slot'))

    def test_invalid_row_order(self):
        original = shift_batch()
        register(self.db, original)
        before = source_records(self.db)
        invalid_rows = (list(reversed(original['rows'])), [original['rows'][0]] * 2)
        for rows in invalid_rows:
            with self.subTest(rows=rows):
                with self.assertRaisesRegex(RegistrationValidationError, 'strictly increasing'):
                    register(self.db, {**original, 'revision': 'bad order', 'rows': rows})
                self.assertEqual(source_records(self.db), before)

    def test_pressure_boundary(self):
        batch = {
            'batch_id': 'pressure-check', 'revision': 'valid',
            'rows': [{'row_number': 12, 'trays': [[{}, {}]]}],
            'temperature': [], 'pressure': [[2, 0]],
        }
        good_id = register(self.db, batch)
        self.assertEqual(load_revision(self.db, good_id).pressure, (StripeEntry(2, 0),))
        before = source_records(self.db)
        with self.assertRaisesRegex(RegistrationValidationError, 'pressure.*slot 2'):
            register(self.db, {**batch, 'revision': 'out of bounds', 'pressure': [[3, 0]]})
        self.assertEqual(source_records(self.db), before)

    def test_malformed_submission(self):
        batch = shift_batch()
        for change in ({'batch_id': ' '}, {'rows': [{'row_number': True, 'trays': []}]}, {'pressure': [[1, None]]}):
            with self.subTest(change=change):
                with self.assertRaises(SubmissionInputError):
                    register(self.db, {**batch, **change})
                self.assertEqual(source_records(self.db), ([], []))

    def test_nonpositive_gap_rejected(self):
        batch = shift_batch()
        for gap in (0, -1):
            with self.subTest(gap=gap):
                with self.assertRaisesRegex(RegistrationValidationError, 'positive integer gap'):
                    register(self.db, {**batch, 'pressure': [[gap, 9]]})
        self.assertEqual(source_records(self.db), ([], []))
