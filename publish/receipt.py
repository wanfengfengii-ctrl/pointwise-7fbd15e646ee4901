from dataclasses import dataclass
from sqlite3 import Connection


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    package_id: int
    revision_id: int
    start: int
    stop: int


def initialize_receipts(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS publication_receipts (
            package_id INTEGER PRIMARY KEY REFERENCES packages (package_id),
            revision_id INTEGER NOT NULL REFERENCES source_revisions (revision_id),
            start_row INTEGER NOT NULL CHECK (start_row >= 0),
            stop_row INTEGER NOT NULL CHECK (stop_row >= start_row)
        )
    ''')


def record_receipt(
    db: Connection, package_id: int, revision_id: int, start: int, stop: int
) -> PublicationReceipt:
    db.execute(
        '''INSERT INTO publication_receipts (package_id, revision_id, start_row, stop_row)
           VALUES (?, ?, ?, ?)''',
        (package_id, revision_id, start, stop),
    )
    return PublicationReceipt(package_id, revision_id, start, stop)
