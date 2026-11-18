import json
import unittest

from archive.export import fetch_package, write_package
from catalog.lifecycle import retire_source
from intake.register import register
from publish.window import publish_window
from review.read import read_package
from review.result import FurnaceReview, PointReading, ReviewResult, TrayReview
from review.validate import PackageValidationError
from tests.fixtures import CatalogCase, detached_window, encode_document, shift_batch


class TestReview(unittest.TestCase):
    def test_independent_positions(self):
        payload = b'''{
            "version": 1, "revision_id": 29, "start": 4, "stop": 5,
            "rows": [{"row_number": 108, "trays": [[{}, {}, {}], [], null]}],
            "temperature": [[3, 7]], "pressure": [[1, 9]]
        }'''
        self.assertEqual(read_package(payload), ReviewResult((
            FurnaceReview(108, (
                TrayReview((PointReading(None, 9), PointReading(None, None), PointReading(7, None))),
                TrayReview(()), None,
            )),
        )))

    def test_accident_package(self):
        result = read_package(detached_window())
        self.assertEqual(result, ReviewResult((
            FurnaceReview(108, (TrayReview((PointReading(None, 9), PointReading(7, None))), TrayReview(()), None)),
        )))

    def test_container_status(self):
        payload = b'''{
            "version": 1, "revision_id": 8, "start": 0, "stop": 4,
            "rows": [
                {"row_number": 12, "trays": null}, {"row_number": 19, "trays": []},
                {"row_number": 24, "trays": [[{}], [], null, [{}]]},
                {"row_number": 30, "trays": [null]}
            ],
            "temperature": [[1, 0], [1, -1]], "pressure": []
        }'''
        self.assertEqual(read_package(payload), ReviewResult((
            FurnaceReview(12, None),
            FurnaceReview(19, ()),
            FurnaceReview(24, (TrayReview((PointReading(0, None),)), TrayReview(()), None, TrayReview((PointReading(-1, None),)))),
            FurnaceReview(30, (None,)),
        )))

    def test_bad_stripe(self):
        raw = json.loads(detached_window())
        raw['temperature'] = [[3, 7]]
        with self.assertRaisesRegex(PackageValidationError, 'temperature.*slot 2'):
            read_package(encode_document(raw))

    def test_late_pressure_out_of_range(self):
        good = {
            'version': 1, 'revision_id': 4, 'start': 0, 'stop': 2,
            'rows': [{'row_number': 9, 'trays': [[{}]]}, {'row_number': 11, 'trays': [[{}]]}],
            'temperature': [[2, 13]], 'pressure': [[1, 9], [1, 15]],
        }
        self.assertEqual(read_package(encode_document(good)), ReviewResult((
            FurnaceReview(9, (TrayReview((PointReading(None, 9),)),)),
            FurnaceReview(11, (TrayReview((PointReading(13, 15),)),)),
        )))
        bad = {**good, 'pressure': [[1, 9], [2, 15]]}
        with self.assertRaisesRegex(PackageValidationError, 'pressure.*slot 2'):
            read_package(encode_document(bad))

    def test_unsupported_version(self):
        raw = json.loads(detached_window())
        for version in (2, True, '1'):
            with self.subTest(version=version):
                raw['version'] = version
                with self.assertRaisesRegex(PackageValidationError, 'unsupported package version'):
                    read_package(encode_document(raw))

    def test_invalid_wire_structure(self):
        raw = json.loads(detached_window())
        cases = (
            b'\xff', b'{',
            detached_window().replace(b'"version": 1', b'"version": 1, "version": 1'),
            encode_document({**raw, 'stop': 3}),
            encode_document({**raw, 'pressure': [[True, 9]]}),
            encode_document({**raw, 'metadata': {}}),
            encode_document({**raw, 'rows': [{'row_number': 1, 'trays': [[{'value': 18}]]}]}),
        )
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(PackageValidationError):
                    read_package(payload)


class TestReviewOffline(CatalogCase):
    def test_offline_fetch(self):
        revision_id = register(self.db, shift_batch())
        package_id, _ = publish_window(self.db, revision_id, 1, 2)
        retire_source(self.db, revision_id)
        original = fetch_package(self.db, package_id)
        self.assertEqual(fetch_package(self.db, package_id), original)
        exchange = self.db_path.with_name('window.json')
        with exchange.open('wb') as stream:
            self.assertEqual(write_package(self.db, package_id, stream), len(original))
        self.db.close()
        payload = exchange.read_bytes()
        self.assertEqual(payload, original)
        self.assertEqual(read_package(payload), ReviewResult((
            FurnaceReview(108, (TrayReview((PointReading(None, 9), PointReading(7, None))), TrayReview(()), None)),
        )))
