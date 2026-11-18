import json
from contextlib import closing

from archive.export import fetch_package
from archive.packages import PackageNotFound
from catalog.history import current_revision
from catalog.lifecycle import SourceNotFound, SourceUnavailable, retire_source
from catalog.schema import open_catalog
from catalog.source import load_revision
from handoff import initialize
from intake.register import register
from publish.window import publish_window
from review.read import read_package
from review.result import FurnaceReview, PointReading, ReviewResult, TrayReview
from tests.fixtures import CatalogCase, publication_records, shift_batch, source_records


class TestHandoff(CatalogCase):
    def test_reopen_after_correction(self):
        original = shift_batch()
        old = register(self.db, original)
        old_id, _ = publish_window(self.db, old, 1, 2)
        old_bytes = fetch_package(self.db, old_id)
        corrected = {**original, 'revision': 'corrected', 'temperature': [[1, 41], [2, 17]]}
        new = register(self.db, corrected)
        retire_source(self.db, old)
        self.db.close()
        with closing(open_catalog(self.db_path)) as reopened:
            self.assertEqual(current_revision(reopened, original['batch_id']), new)
            self.assertEqual(fetch_package(reopened, old_id), old_bytes)
            with self.assertRaises(SourceUnavailable):
                publish_window(reopened, old, 1, 2)
            new_id, new_receipt = publish_window(reopened, new, 1, 2)
            new_bytes = fetch_package(reopened, new_id)
            self.assertEqual(new_receipt.revision_id, new)
        expected_old = ReviewResult((
            FurnaceReview(108, (TrayReview((PointReading(None, 9), PointReading(7, None))), TrayReview(()), None)),
        ))
        expected_new = ReviewResult((
            FurnaceReview(108, (TrayReview((PointReading(None, 9), PointReading(17, None))), TrayReview(()), None)),
        ))
        self.assertEqual(read_package(old_bytes), expected_old)
        self.assertEqual(read_package(new_bytes), expected_new)

    def test_retire_exact_revision(self):
        original = shift_batch()
        old = register(self.db, original)
        new = register(self.db, {**original, 'revision': 'r2', 'temperature': [[1, 51], [2, 27]]})
        old_package_id, _ = publish_window(self.db, old, 1, 2)
        old_bytes = fetch_package(self.db, old_package_id)
        self.assertEqual(json.loads(old_bytes)['temperature'], [[2, 7]])
        self.assertEqual(retire_source(self.db, old), old)
        self.assertEqual(retire_source(self.db, old), old)
        self.assertTrue(load_revision(self.db, old).retired)
        self.assertFalse(load_revision(self.db, new).retired)
        with self.assertRaises(SourceUnavailable):
            publish_window(self.db, old, 1, 2)
        fresh, _ = publish_window(self.db, new, 1, 2)
        self.assertEqual(json.loads(fetch_package(self.db, fresh))['temperature'], [[2, 27]])
        self.assertEqual(fetch_package(self.db, old_package_id), old_bytes)
        self.assertEqual(current_revision(self.db, original['batch_id']), new)

    def test_unknown_revision(self):
        revision_id = register(self.db, shift_batch())
        before = source_records(self.db)
        with self.assertRaises(SourceNotFound):
            retire_source(self.db, revision_id + 100)
        self.assertEqual(source_records(self.db), before)

    def test_retired_replay(self):
        original = shift_batch()
        old = register(self.db, original)
        new = register(self.db, {**original, 'revision': 'r2', 'pressure': [[2, 18]]})
        retire_source(self.db, old)
        before = source_records(self.db)
        self.assertEqual(register(self.db, shift_batch()), old)
        self.assertEqual(source_records(self.db), before)
        self.assertEqual(current_revision(self.db, original['batch_id']), new)
        with self.assertRaises(SourceUnavailable):
            publish_window(self.db, old, 1, 2)
        current_package, _ = publish_window(self.db, new, 1, 2)
        self.assertEqual(json.loads(fetch_package(self.db, current_package))['pressure'], [[1, 18]])

    def test_old_package_exact_after_new_publication(self):
        original = shift_batch()
        old = register(self.db, original)
        old_package, _ = publish_window(self.db, old, 1, 2)
        old_bytes = fetch_package(self.db, old_package)
        new = register(self.db, {**original, 'revision': 'r2', 'pressure': [[2, 29]]})
        retire_source(self.db, old)
        new_package, _ = publish_window(self.db, new, 1, 2)
        new_bytes = fetch_package(self.db, new_package)
        self.assertNotEqual(old_package, new_package)
        self.assertNotEqual(old_bytes, new_bytes)
        self.db.close()
        with closing(open_catalog(self.db_path)) as reopened:
            refetched = [fetch_package(reopened, key) for key in (new_package, old_package, new_package, old_package)]
        self.assertEqual(refetched, [new_bytes, old_bytes, new_bytes, old_bytes])
        self.assertEqual(read_package(refetched[0]).rows[0].trays[0].points[0], PointReading(None, 29))
        self.assertEqual(read_package(refetched[1]).rows[0].trays[0].points[0], PointReading(None, 9))

    def test_unknown_package(self):
        revision_id = register(self.db, shift_batch())
        package_id, _ = publish_window(self.db, revision_id, 1, 2)
        for missing in (package_id + 100, 1 << 63, True):
            with self.subTest(missing=missing):
                with self.assertRaises(PackageNotFound):
                    fetch_package(self.db, missing)

    def test_reinitialize_preserves_records(self):
        original = shift_batch()
        old = register(self.db, original)
        old_pkg, _ = publish_window(self.db, old, 1, 2)
        new = register(self.db, {**original, 'revision': 'r2'})
        retire_source(self.db, old)
        new_pkg, _ = publish_window(self.db, new, 0, 1)
        expected_sources = source_records(self.db)
        expected_publications = publication_records(self.db)
        self.db.close()
        with closing(open_catalog(self.db_path)) as reopened:
            initialize(reopened)
            initialize(reopened)
            self.assertEqual(source_records(reopened), expected_sources)
            self.assertEqual(publication_records(reopened), expected_publications)
            self.assertEqual(current_revision(reopened, original['batch_id']), new)
            self.assertTrue(load_revision(reopened, old).retired)
            self.assertEqual(json.loads(fetch_package(reopened, old_pkg))['temperature'], [[2, 7]])
            self.assertEqual(json.loads(fetch_package(reopened, new_pkg))['temperature'], [[1, 41]])
