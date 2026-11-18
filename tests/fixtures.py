import json
import tempfile
import unittest
from pathlib import Path
from sqlite3 import Connection

from catalog.schema import open_catalog
from handoff import initialize


_SAMPLES = Path(__file__).resolve().parents[1] / 'samples'


def shift_batch() -> dict:
    return json.loads((_SAMPLES / 'shift-batch.json').read_text(encoding='utf-8'))


def detached_window() -> bytes:
    return (_SAMPLES / 'window-package.json').read_bytes()


def encode_document(document: dict) -> bytes:
    return json.dumps(document, separators=(',', ':')).encode('utf-8')


def publication_records(db: Connection) -> tuple[list, list]:
    return (
        db.execute('SELECT package_id, payload FROM packages ORDER BY package_id').fetchall(),
        db.execute('''SELECT package_id, revision_id, start_row, stop_row
                      FROM publication_receipts ORDER BY package_id''').fetchall(),
    )


def order_records(db: Connection) -> tuple[list, list]:
    return (
        db.execute('''SELECT order_id, revision_id, start_row, stop_row, manifest
                      FROM order_manifests ORDER BY order_id''').fetchall(),
        db.execute('''SELECT order_id, station, payload
                      FROM order_volumes ORDER BY order_id, station''').fetchall(),
    )


def source_records(db: Connection) -> tuple[list, list]:
    return (
        db.execute('''SELECT revision_id, batch_id, declared_revision, observations, retired
                      FROM source_revisions ORDER BY revision_id''').fetchall(),
        db.execute('SELECT batch_id, revision_id FROM batch_current ORDER BY batch_id').fetchall(),
    )


class CatalogCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='test-furnace-handoff-')
        self.addCleanup(directory.cleanup)
        self.db_path = Path(directory.name) / 'catalog.sqlite3'
        self.db = open_catalog(self.db_path)
        self.addCleanup(self.db.close)
        initialize(self.db)


def refuse_receipt_after_package_insert(db: Connection) -> None:
    db.execute('''
        CREATE TEMP TRIGGER refuse_receipt
        BEFORE INSERT ON publication_receipts
        WHEN EXISTS (SELECT 1 FROM packages WHERE package_id = NEW.package_id)
        BEGIN
            SELECT RAISE(ABORT, 'receipt refused after package insert');
        END
    ''')


def fail_publication_at_commit(db: Connection) -> None:
    db.execute('''
        CREATE TABLE deferred_receipt_check (
            package_id INTEGER NOT NULL REFERENCES packages (package_id)
                DEFERRABLE INITIALLY DEFERRED
        )
    ''')
    db.execute('''
        CREATE TEMP TRIGGER require_deferred_receipt_parent
        AFTER INSERT ON publication_receipts
        BEGIN
            INSERT INTO deferred_receipt_check (package_id) VALUES (-1);
        END
    ''')
