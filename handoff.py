import argparse
import json
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from sqlite3 import Connection

from archive.export import fetch_package, write_package
from archive.orders import initialize_orders
from archive.schema import initialize_archive
from catalog.lifecycle import retire_source
from catalog.schema import initialize_catalog, open_catalog, write_transaction
from intake.register import register
from publish.receipt import initialize_receipts
from publish.window import publish_window
from review.read import read_package


_ROOT = Path(__file__).resolve().parent
_WINDOW_CHECKS = {
    'tests.test_publish.TestPublish.test_middle_window',
    'tests.test_review.TestReview.test_accident_package',
}


def initialize(db: Connection) -> None:
    """Create any missing working-catalog structures atomically."""
    with write_transaction(db):
        initialize_catalog(db)
        initialize_archive(db)
        initialize_receipts(db)
        initialize_orders(db)


def _verify() -> int:
    suite = unittest.defaultTestLoader.discover(str(_ROOT / 'tests'), top_level_dir=str(_ROOT))
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    failed_checks = {case.id() for case, _ in outcome.failures}
    if not outcome.errors and failed_checks & _WINDOW_CHECKS:
        print('WINDOW_HANDOFF_MISMATCH', file=sys.stderr)
    if not outcome.wasSuccessful():
        return 1
    return _verify_orders()


def _verify_orders() -> int:
    """Run the whole-order joint checks after the unit regression passes."""
    import order_examples
    try:
        order_examples.baseline()
        order_examples.orders(verify=True)
    except Exception as exc:
        print(f'ORDER_HANDOFF_MISMATCH: {exc}', file=sys.stderr)
        return 1
    return 0


def _report_as_json(payload: bytes) -> dict:
    return json.loads(json.dumps(asdict(read_package(payload))))


def _demo() -> int:
    submission = json.loads((_ROOT / 'samples' / 'shift-batch.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='furnace-handoff-') as work:
        db_path = Path(work) / 'shift.sqlite3'
        exchange = Path(work) / 'night-window.json'
        with closing(open_catalog(db_path)) as db:
            initialize(db)
            revision_id = register(db, submission)
            package_id, receipt = publish_window(db, revision_id, 1, 2)
            with exchange.open('wb') as stream:
                write_package(db, package_id, stream)
            correction = {**submission, 'revision': 'corrected', 'temperature': [[1, 41], [2, 17]]}
            corrected_id = register(db, correction)
            retire_source(db, revision_id)
            corrected_package_id, _ = publish_window(db, corrected_id, 1, 2)

        delivered = exchange.read_bytes()
        actual = json.loads(delivered)
        downstream_actual = _report_as_json(delivered)
        with closing(open_catalog(db_path)) as db:
            initialize(db)
            historic = fetch_package(db, package_id)
            corrected = fetch_package(db, corrected_package_id)
        corrected_report = _report_as_json(corrected)

    expected = {
        'version': 1, 'revision_id': revision_id, 'start': 1, 'stop': 2,
        'rows': [{'row_number': 108, 'trays': [[{}, {}], [], None]}],
        'temperature': [[2, 7]], 'pressure': [[1, 9]],
    }
    downstream_expected = {
        'rows': [{
            'row_number': 108,
            'trays': [
                {'points': [{'temperature': None, 'pressure': 9}, {'temperature': 7, 'pressure': None}]},
                {'points': []},
                None,
            ],
        }],
    }
    if actual != expected or downstream_actual != downstream_expected:
        raise AssertionError('the exchanged window differs from the hand-calculated readings')
    if (receipt.package_id, receipt.revision_id, receipt.start, receipt.stop) != (package_id, revision_id, 1, 2):
        raise AssertionError('publication receipt does not bind the exchanged window')
    if historic != delivered:
        raise AssertionError('historic package bytes changed after correction and reopening')
    corrected_temperature = corrected_report['rows'][0]['trays'][0]['points'][1]['temperature']
    if corrected_temperature != 17:
        raise AssertionError('the corrected package did not contain the corrected reading')

    evidence = {
        'case_id': 'T3',
        'input': {'submission': submission, 'window': [1, 2]},
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': ['intake/register.py', 'publish/window.py', 'publish/commit.py', 'archive/export.py', 'review/read.py', 'review/assemble.py'],
        'oracle': '原行 101 占一个源槽。源槽 2 的温度 7 和源槽 1 的压力 9 在包内分别落在槽 1 和槽 0。包首间隔从 −1 手算。',
    }
    print('POINTWISE_SCENARIO ' + json.dumps(evidence, ensure_ascii=False, separators=(',', ':')))
    print(json.dumps({
        'old_package_id': package_id,
        'corrected_package_id': corrected_package_id,
        'old_bytes_preserved': historic == delivered,
        'corrected_temperature': corrected_temperature,
    }, separators=(',', ':')))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Heat-treatment shift handoff')
    parser.add_argument('command', choices=('verify', 'demo'))
    arguments = parser.parse_args()
    return _verify() if arguments.command == 'verify' else _demo()


if __name__ == '__main__':
    raise SystemExit(main())
