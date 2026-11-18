import json
from contextlib import closing

from archive.export import fetch_package
from catalog.lifecycle import SourceNotFound, SourceUnavailable, retire_source
from catalog.schema import open_catalog
from intake.register import register
from publish.commit import PublicationCommitError
from publish.receipt import PublicationReceipt
from publish.window import InvalidWindow, publish_window
from review.read import read_package
from review.result import FurnaceReview, PointReading, ReviewResult, TrayReview
from tests.fixtures import (
    CatalogCase,
    fail_publication_at_commit,
    publication_records,
    refuse_receipt_after_package_insert,
    shift_batch,
)


class TestPublish(CatalogCase):
    def test_middle_window(self):
        revision_id = register(self.db, shift_batch())
        package_id, _ = publish_window(self.db, revision_id, 1, 2)
        raw = json.loads(fetch_package(self.db, package_id))
        self.assertDictEqual(raw, {
            'version': 1, 'revision_id': revision_id, 'start': 1, 'stop': 2,
            'rows': [{'row_number': 108, 'trays': [[{}, {}], [], None]}],
            'temperature': [[2, 7]], 'pressure': [[1, 9]],
        })

    def test_first_gap_rebase(self):
        batch = {
            'batch_id': 'multi-row', 'revision': 'r1',
            'rows': [
                {'row_number': 10, 'trays': [[{}, {}, {}]]},
                {'row_number': 20, 'trays': None},
                {'row_number': 42, 'trays': [[], [{}, {}, {}, {}], None]},
                {'row_number': 70, 'trays': [[{}]]},
                {'row_number': 85, 'trays': [[{}]]},
            ],
            'temperature': [[2, 55], [2, 0], [3, -5], [2, 66]],
            'pressure': [[1, 99], [4, 3], [3, 5], [1, 100]],
        }
        revision_id = register(self.db, batch)
        package_id, _ = publish_window(self.db, revision_id, 2, 4)
        payload = fetch_package(self.db, package_id)
        self.assertEqual(json.loads(payload), {
            'version': 1, 'revision_id': revision_id, 'start': 2, 'stop': 4,
            'rows': [
                {'row_number': 42, 'trays': [[], [{}, {}, {}, {}], None]},
                {'row_number': 70, 'trays': [[{}]]},
            ],
            'temperature': [[1, 0], [3, -5]], 'pressure': [[2, 3], [3, 5]],
        })
        expected = ReviewResult((
            FurnaceReview(42, (TrayReview(()), TrayReview((
                PointReading(0, None), PointReading(None, 3), PointReading(None, None), PointReading(-5, None),
            )), None)),
            FurnaceReview(70, (TrayReview((PointReading(None, 5),)),)),
        ))
        self.assertEqual(read_package(payload), expected)

    def test_receipt_binding(self):
        revision_id = register(self.db, shift_batch())
        package_id, receipt = publish_window(self.db, revision_id, 0, 1)
        self.assertEqual(receipt, PublicationReceipt(package_id, revision_id, 0, 1))
        with closing(open_catalog(self.db_path)) as observer:
            packages, receipts = publication_records(observer)
            self.assertEqual(packages, [(package_id, fetch_package(self.db, package_id))])
            self.assertEqual(receipts, [(package_id, revision_id, 0, 1)])
        wire = json.loads(packages[0][1])
        self.assertEqual((wire['revision_id'], wire['start'], wire['stop']), (revision_id, 0, 1))
        self.assertEqual(wire['rows'], [{'row_number': 101, 'trays': [[{}]]}])
        self.assertEqual((wire['temperature'], wire['pressure']), ([[1, 41]], []))

    def test_bad_window(self):
        revision_id = register(self.db, shift_batch())
        for start, stop in ((1, 3), (-1, 1), (2, 1), (True, 2), (0, 1.0)):
            with self.subTest(start=start, stop=stop):
                with self.assertRaises(InvalidWindow):
                    publish_window(self.db, revision_id, start, stop)
                self.assertEqual(publication_records(self.db), ([], []))

    def test_unavailable_revision(self):
        revision_id = register(self.db, shift_batch())
        retire_source(self.db, revision_id)
        with self.assertRaises(SourceUnavailable):
            publish_window(self.db, revision_id, 1, 1)
        with self.assertRaises(SourceNotFound):
            publish_window(self.db, revision_id + 100, 0, 1)
        self.assertEqual(publication_records(self.db), ([], []))

    def test_commit_failure(self):
        revision_id = register(self.db, shift_batch())
        previous_id, _ = publish_window(self.db, revision_id, 1, 2)
        before = publication_records(self.db)
        fail_publication_at_commit(self.db)
        with self.assertRaisesRegex(PublicationCommitError, 'FOREIGN KEY'):
            publish_window(self.db, revision_id, 0, 1)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(self.db.execute('SELECT * FROM deferred_receipt_check').fetchall(), [])
        with closing(open_catalog(self.db_path)) as observer:
            self.assertEqual(publication_records(observer), before)
            self.assertEqual(fetch_package(observer, previous_id), before[0][0][1])
        self.db.execute('DROP TRIGGER require_deferred_receipt_parent')
        retried_id, _ = publish_window(self.db, revision_id, 0, 1)
        self.assertNotEqual(retried_id, previous_id)
        self.assertEqual(json.loads(fetch_package(self.db, retried_id))['temperature'], [[1, 41]])

    def test_after_package_insert(self):
        revision_id = register(self.db, shift_batch())
        earlier_id, _ = publish_window(self.db, revision_id, 1, 2)
        earlier_bytes = fetch_package(self.db, earlier_id)
        before = publication_records(self.db)
        refuse_receipt_after_package_insert(self.db)
        with self.assertRaisesRegex(PublicationCommitError, 'receipt refused after package insert'):
            publish_window(self.db, revision_id, 0, 2)
        self.assertEqual(publication_records(self.db), before)
        with closing(open_catalog(self.db_path)) as observer:
            self.assertEqual(publication_records(observer), before)
            self.assertEqual(fetch_package(observer, earlier_id), earlier_bytes)

    def test_empty_window(self):
        revision_id = register(self.db, shift_batch())
        package_id, receipt = publish_window(self.db, revision_id, 1, 1)
        payload = fetch_package(self.db, package_id)
        self.assertEqual(receipt, PublicationReceipt(package_id, revision_id, 1, 1))
        self.assertEqual(json.loads(payload), {
            'version': 1, 'revision_id': revision_id, 'start': 1, 'stop': 1,
            'rows': [], 'temperature': [], 'pressure': [],
        })
        self.assertEqual(read_package(payload), ReviewResult(()))

    def test_zero_slot_rows(self):
        batch = shift_batch()
        batch['rows'][1:1] = [
            {'row_number': 102, 'trays': None},
            {'row_number': 104, 'trays': []},
            {'row_number': 105, 'trays': [[], None]},
        ]
        revision_id = register(self.db, batch)
        package_id, receipt = publish_window(self.db, revision_id, 1, 4)
        payload = fetch_package(self.db, package_id)
        self.assertEqual(receipt, PublicationReceipt(package_id, revision_id, 1, 4))
        self.assertEqual(json.loads(payload), {
            'version': 1, 'revision_id': revision_id, 'start': 1, 'stop': 4,
            'rows': [
                {'row_number': 102, 'trays': None},
                {'row_number': 104, 'trays': []},
                {'row_number': 105, 'trays': [[], None]},
            ],
            'temperature': [], 'pressure': [],
        })
        self.assertEqual(read_package(payload), ReviewResult((
            FurnaceReview(102, None), FurnaceReview(104, ()), FurnaceReview(105, (TrayReview(()), None)),
        )))
