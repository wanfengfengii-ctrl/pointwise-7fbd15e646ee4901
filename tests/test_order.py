import hashlib
import itertools
import json
import unittest
from contextlib import closing

from archive.export import fetch_order, fetch_package
from archive.orders import OrderNotFound
from archive.volume import VolumeEnvelope, decode_volume, encode_volume
from catalog.lifecycle import SourceNotFound, SourceUnavailable, retire_source
from catalog.schema import open_catalog
from handoff import initialize
from intake.register import register
from layout.shape import FurnaceRow, TrayShape
from order_examples import EXPECTED, balanced_submission, publication_fault, tie_submission
from publish.commit import PublicationCommitError
from publish.plan import plan_cuts, row_costs
from publish.window import InvalidWindow, publish_order, publish_window
from review.read import read_order, read_package
from review.result import FurnaceReview, PointReading, ReviewResult, TrayReview
from review.validate import PackageValidationError
from tests.fixtures import CatalogCase, order_records, publication_records


class TestPlanCuts(unittest.TestCase):
    """独立的小例切点对照：峰值最小，同峰值取字典序最小的切点。"""

    def test_balanced_example(self):
        self.assertEqual(plan_cuts([4, 2, 2, 4], [8, 8]), ((2,), (6, 6)))

    def test_tie_examples(self):
        self.assertEqual(plan_cuts([1, 2, 2, 6], [6, 6, 6]), ((1, 3), (1, 4, 6)))
        self.assertEqual(plan_cuts([1, 2, 2, 6], [6, 2, 6]), ((2, 3), (3, 2, 6)))
        self.assertIsNone(plan_cuts([1, 2, 2, 6], [6, 6, 5]))

    def test_same_peak_takes_lexicographically_smallest_cuts(self):
        self.assertEqual(plan_cuts([1, 2, 1], [3, 3]), ((1,), (1, 3)))
        self.assertIsNone(plan_cuts([1, 2, 1], [2, 2]))
        self.assertEqual(plan_cuts([2, 2, 2, 2], [4, 4]), ((2,), (4, 4)))
        self.assertEqual(plan_cuts([3, 1, 1, 3], [4, 4]), ((2,), (4, 4)))

    def test_single_station(self):
        self.assertEqual(plan_cuts([4, 2, 2, 4], [12]), ((), (12,)))
        self.assertEqual(plan_cuts([5], [5]), ((), (5,)))
        self.assertIsNone(plan_cuts([5], [4]))

    def test_station_count_limits(self):
        self.assertEqual(plan_cuts([1, 1], [1, 1]), ((1,), (1, 1)))
        self.assertIsNone(plan_cuts([1, 1], [1, 1, 1]))

    def test_row_costs(self):
        rows = (
            FurnaceRow(10, (TrayShape(2),)),
            FurnaceRow(20, None),
            FurnaceRow(30, (TrayShape(0), None)),
        )
        self.assertEqual(row_costs(rows), [3, 1, 1])


class TestPublishOrder(CatalogCase):
    def setUp(self):
        super().setUp()
        self.revision = register(self.db, balanced_submission())

    def test_balanced_order(self):
        order_id, manifest = publish_order(self.db, self.revision, 0, 4, [8, 8])
        plan = json.loads(manifest)
        self.assertEqual(
            {key: plan[key] for key in ('order_id', 'revision_id', 'start', 'stop', 'cuts', 'costs')},
            {'order_id': order_id, 'revision_id': self.revision, 'start': 0, 'stop': 4,
             'cuts': [2], 'costs': [6, 6]},
        )
        fetched_manifest, volumes = fetch_order(self.db, order_id)
        self.assertEqual(fetched_manifest, manifest)
        self.assertEqual(len(volumes), 2)
        self.assertEqual(
            [member['sha256'] for member in plan['volumes']],
            [hashlib.sha256(payload).hexdigest() for payload in volumes],
        )
        self.assertEqual(
            [(member['station'], member['start'], member['stop']) for member in plan['volumes']],
            [(0, 0, 2), (1, 2, 4)],
        )
        first = json.loads(volumes[0])
        self.assertEqual(
            (first['order_id'], first['revision_id'], first['station'], first['start'], first['stop']),
            (order_id, self.revision, 0, 0, 2),
        )
        self.assertEqual(first['rows'], [
            {'row_number': 101, 'trays': [[{}, {}, {}]]},
            {'row_number': 108, 'trays': [[{}], [], None]},
        ])
        self.assertEqual((first['temperature'], first['pressure']), ([[1, 41]], [[3, 18], [1, 9]]))
        second = json.loads(volumes[1])
        self.assertEqual(
            (second['order_id'], second['revision_id'], second['station'], second['start'], second['stop']),
            (order_id, self.revision, 1, 2, 4),
        )
        self.assertEqual([row['row_number'] for row in second['rows']], [120, 137])
        self.assertEqual((second['temperature'], second['pressure']), ([[1, 7], [1, 0]], [[4, 23]]))
        self.assertEqual(read_order(manifest, volumes), EXPECTED)

    def test_order_issue_leaves_v1_tables_untouched(self):
        before = publication_records(self.db)
        publish_order(self.db, self.revision, 0, 4, [8, 8])
        self.assertEqual(publication_records(self.db), before)

    def test_reissue_gets_new_identity_and_orders_do_not_mix(self):
        a_id, a_manifest = publish_order(self.db, self.revision, 0, 4, [8, 8])
        b_id, b_manifest = publish_order(self.db, self.revision, 0, 4, [8, 8])
        self.assertNotEqual(a_id, b_id)
        self.assertNotEqual(a_manifest, b_manifest)
        a_volumes = fetch_order(self.db, a_id)[1]
        b_volumes = fetch_order(self.db, b_id)[1]
        self.assertNotEqual(a_volumes, b_volumes)
        # 同修订、同窗口、同正文的另一单的卷也不得混收
        for swapped in ((a_volumes[0], b_volumes[1]), (b_volumes[0], a_volumes[1])):
            with self.subTest(swapped=swapped):
                with self.assertRaises(PackageValidationError):
                    read_order(a_manifest, swapped)
        self.assertEqual(read_order(a_manifest, a_volumes), EXPECTED)
        self.assertEqual(read_order(b_manifest, b_volumes), EXPECTED)

    def test_tie_plans_and_no_solution(self):
        tie = register(self.db, tie_submission())
        for caps, cuts, costs in (([6, 6, 6], [2, 4], [1, 4, 6]), ([6, 2, 6], [3, 4], [3, 2, 6])):
            with self.subTest(caps=caps):
                order_id, manifest = publish_order(self.db, tie, 1, 5, caps)
                plan = json.loads(manifest)
                self.assertEqual((plan['cuts'], plan['costs']), (cuts, costs))
                self.assertEqual(len(fetch_order(self.db, order_id)[1]), 3)
        before = order_records(self.db)
        with self.assertRaises(ValueError):
            publish_order(self.db, tie, 1, 5, [6, 6, 5])
        self.assertEqual(order_records(self.db), before)

    def test_invalid_window(self):
        before = order_records(self.db)
        for start, stop in ((0, 0), (2, 1), (-1, 2), (0, 5), (True, 2), (0, 1.0), (0.0, 4)):
            with self.subTest(start=start, stop=stop):
                with self.assertRaises(InvalidWindow):
                    publish_order(self.db, self.revision, start, stop, [8, 8])
        self.assertEqual(order_records(self.db), before)

    def test_invalid_caps(self):
        before = order_records(self.db)
        for caps in ([], (), [0], [-3], [True], [1.5], ['8'], [None], '88', None, [[8]]):
            with self.subTest(caps=caps):
                with self.assertRaises(ValueError):
                    publish_order(self.db, self.revision, 0, 4, caps)
        self.assertEqual(order_records(self.db), before)

    def test_source_errors(self):
        with self.assertRaises(SourceNotFound):
            publish_order(self.db, self.revision + 100, 0, 4, [8, 8])
        retire_source(self.db, self.revision)
        with self.assertRaises(SourceUnavailable):
            publish_order(self.db, self.revision, 0, 4, [8, 8])
        self.assertEqual(order_records(self.db), ([], []))

    def test_single_station_order(self):
        order_id, manifest = publish_order(self.db, self.revision, 0, 4, [12])
        plan = json.loads(manifest)
        self.assertEqual((plan['cuts'], plan['costs']), ([], [12]))
        volumes = fetch_order(self.db, order_id)[1]
        self.assertEqual(len(volumes), 1)
        self.assertEqual(read_order(manifest, volumes), EXPECTED)

    def test_subwindow_order(self):
        order_id, manifest = publish_order(self.db, self.revision, 1, 3, [4, 4])
        plan = json.loads(manifest)
        self.assertEqual((plan['cuts'], plan['costs']), ([2], [2, 2]))
        volumes = fetch_order(self.db, order_id)[1]
        self.assertEqual(read_order(manifest, volumes), ReviewResult(EXPECTED.rows[1:3]))

    def test_write_fault_rolls_back_whole_order(self):
        earlier_id, _ = publish_order(self.db, self.revision, 0, 4, [8, 8])
        for table, after in (('order_manifests', 1), ('order_volumes', 1), ('order_volumes', 2)):
            with self.subTest(table=table, after=after):
                before = order_records(self.db)
                with publication_fault(self.db, table, after=after):
                    with self.assertRaises(PublicationCommitError):
                        publish_order(self.db, self.revision, 0, 4, [8, 8])
                    self.assertFalse(self.db.in_transaction)
                    self.assertEqual(order_records(self.db), before)
                retry_id, _ = publish_order(self.db, self.revision, 0, 4, [8, 8])
                self.assertNotEqual(retry_id, earlier_id)
                self.assertEqual(len(order_records(self.db)[0]), len(before[0]) + 1)

    def test_commit_fault_rolls_back_whole_order(self):
        earlier_id, earlier_manifest = publish_order(self.db, self.revision, 0, 4, [8, 8])
        earlier = fetch_order(self.db, earlier_id)
        self.assertEqual(earlier[0], earlier_manifest)
        before = order_records(self.db)
        with publication_fault(self.db, 'order_manifests', at_commit=True):
            with self.assertRaises(PublicationCommitError):
                publish_order(self.db, self.revision, 0, 4, [8, 8])
            self.assertFalse(self.db.in_transaction)
            self.assertEqual(order_records(self.db), before)
        with closing(open_catalog(self.db_path)) as observer:
            self.assertEqual(order_records(observer), before)
            self.assertEqual(fetch_order(observer, earlier_id), earlier)
        retry_id, retry_manifest = publish_order(self.db, self.revision, 0, 4, [8, 8])
        self.assertNotEqual(retry_id, earlier_id)
        self.assertEqual(fetch_order(self.db, retry_id)[0], retry_manifest)

    def test_reopen_after_correction_and_retire(self):
        order_id, manifest = publish_order(self.db, self.revision, 0, 4, [8, 8])
        volumes = fetch_order(self.db, order_id)[1]
        corrected = register(self.db, {
            **balanced_submission(), 'revision': 'corrected',
            'temperature': [[1, 51], [4, 17], [1, 0]],
        })
        retire_source(self.db, self.revision)
        self.db.close()
        with closing(open_catalog(self.db_path)) as reopened:
            initialize(reopened)
            self.assertEqual(fetch_order(reopened, order_id), (manifest, volumes))
            with self.assertRaises(SourceUnavailable):
                publish_order(reopened, self.revision, 0, 4, [8, 8])
            new_id, new_manifest = publish_order(reopened, corrected, 0, 4, [8, 8])
            new_volumes = fetch_order(reopened, new_id)[1]
        self.assertEqual(read_order(manifest, volumes), EXPECTED)
        corrected_rows = read_order(new_manifest, new_volumes).rows
        self.assertEqual(corrected_rows[0].trays[0].points[0], PointReading(51, None))
        self.assertEqual(corrected_rows[2].trays[1].points[0], PointReading(17, None))

    def test_reinitialize_preserves_orders(self):
        order_id, manifest = publish_order(self.db, self.revision, 0, 4, [8, 8])
        expected = order_records(self.db)
        initialize(self.db)
        initialize(self.db)
        self.assertEqual(order_records(self.db), expected)
        self.assertEqual(fetch_order(self.db, order_id)[0], manifest)

    def test_unknown_order(self):
        order_id, _ = publish_order(self.db, self.revision, 0, 4, [8, 8])
        for missing in (order_id + 100, 1 << 63, True, '1'):
            with self.subTest(missing=missing):
                with self.assertRaises(OrderNotFound):
                    fetch_order(self.db, missing)
                with self.assertRaises(LookupError):
                    fetch_order(self.db, missing)


class TestReadOrder(CatalogCase):
    def setUp(self):
        super().setUp()
        self.revision = register(self.db, balanced_submission())
        self.order_id, self.manifest = publish_order(self.db, self.revision, 0, 4, [8, 8])
        self.volumes = fetch_order(self.db, self.order_id)[1]

    def test_arrival_order_is_irrelevant(self):
        first, second = self.volumes
        for arrived in ((first, second), (second, first), [second, first], [first, second]):
            with self.subTest(arrived=arrived):
                self.assertEqual(read_order(self.manifest, arrived), EXPECTED)

    def test_three_volume_permutations(self):
        tie = register(self.db, tie_submission())
        _, manifest = publish_order(self.db, tie, 1, 5, [6, 6, 6])
        volumes = fetch_order(self.db, json.loads(manifest)['order_id'])[1]
        expected = ReviewResult((
            FurnaceReview(20, None),
            FurnaceReview(30, (TrayReview((PointReading(17, None),)),)),
            FurnaceReview(44, (TrayReview((PointReading(None, None),)),)),
            FurnaceReview(70, (TrayReview((
                PointReading(None, 19), PointReading(None, None), PointReading(None, None),
                PointReading(None, None), PointReading(None, None),
            )),)),
        ))
        self.assertEqual(len(volumes), 3)
        for arrived in itertools.permutations(volumes):
            with self.subTest(arrived=arrived):
                self.assertEqual(read_order(manifest, arrived), expected)

    def test_missing_extra_duplicate_and_foreign_volumes(self):
        first, second = self.volumes
        cases = [
            (first,), (second,), (first, second, first),
            (first, first), (second, second), (first, b''),
        ]
        other_id, _ = publish_order(self.db, self.revision, 0, 4, [8, 8])
        foreign = fetch_order(self.db, other_id)[1]
        cases.append((first, foreign[1]))
        package_id, _ = publish_window(self.db, self.revision, 0, 2)
        cases.append((first, fetch_package(self.db, package_id)))
        for arrived in cases:
            with self.subTest(arrived=arrived):
                with self.assertRaises(PackageValidationError):
                    read_order(self.manifest, arrived)

    def test_corrupt_volume(self):
        first, second = self.volumes
        for damaged in (second[:-1] + b' ', second[:-5], second + b' '):
            with self.subTest(damaged=damaged):
                with self.assertRaises(PackageValidationError):
                    read_order(self.manifest, (first, damaged))

    def test_bad_manifest(self):
        plan = json.loads(self.manifest)
        cases = [b'\xff', b'{', b'[]', b'{}']
        incomplete = {key: value for key, value in plan.items() if key != 'cuts'}
        cases.append(json.dumps(incomplete).encode())
        cases.append(json.dumps({**plan, 'cuts': [1]}).encode())
        cases.append(json.dumps({**plan, 'cuts': [2, 2]}).encode())
        cases.append(json.dumps({**plan, 'costs': [5, 7]}).encode())
        cases.append(json.dumps({**plan, 'costs': [6]}).encode())
        tampered_digest = json.loads(self.manifest)
        tampered_digest['volumes'][0]['sha256'] = '0' * 64
        cases.append(json.dumps(tampered_digest).encode())
        swapped = json.loads(self.manifest)
        swapped['volumes'] = [swapped['volumes'][1], swapped['volumes'][0]]
        cases.append(json.dumps(swapped).encode())
        duplicated_key = self.manifest.replace(b'"cuts"', b'"start"', 1)
        cases.append(duplicated_key)
        for bad in cases:
            with self.subTest(bad=bad):
                with self.assertRaises(PackageValidationError):
                    read_order(bad, self.volumes)
        with self.assertRaises(PackageValidationError):
            read_order(self.manifest.decode('utf-8'), self.volumes)

    def test_volumes_container_contract(self):
        with self.assertRaises(PackageValidationError):
            read_order(self.manifest, self.volumes[0])
        with self.assertRaises(PackageValidationError):
            read_order(self.manifest, None)
        with self.assertRaises(PackageValidationError):
            read_order(self.manifest, (self.volumes[0], 42))
        with self.assertRaises(PackageValidationError):
            read_order(self.manifest, (self.volumes[0], self.volumes[1].decode('utf-8')))

    def test_crafted_member_with_lying_fields(self):
        real = decode_volume(self.volumes[0])
        lying = encode_volume(VolumeEnvelope(
            real.order_id, real.revision_id, 1, real.start, real.stop,
            real.rows, real.temperature, real.pressure,
        ))
        plan = json.loads(self.manifest)
        plan['volumes'][0]['sha256'] = hashlib.sha256(lying).hexdigest()
        forged = json.dumps(plan, separators=(',', ':')).encode('utf-8')
        with self.assertRaises(PackageValidationError):
            read_order(forged, (lying, self.volumes[1]))

    def test_v1_package_interface_intact(self):
        package_id, _ = publish_window(self.db, self.revision, 1, 2)
        payload = fetch_package(self.db, package_id)
        self.assertEqual(read_package(payload), ReviewResult((EXPECTED.rows[1],)))


if __name__ == '__main__':
    unittest.main()
