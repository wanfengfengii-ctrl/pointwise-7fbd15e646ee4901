import sqlite3
from collections.abc import Callable

from archive.packages import store_package
from catalog.lifecycle import load_available_revision
from catalog.schema import write_transaction
from catalog.source import SourceRevision
from publish.receipt import PublicationReceipt, record_receipt


class PublicationCommitError(RuntimeError):
    pass


def commit_publication(
    db: sqlite3.Connection,
    revision_id: int,
    start: int,
    stop: int,
    build: Callable[[SourceRevision], bytes],
) -> tuple[int, PublicationReceipt]:
    try:
        with write_transaction(db):
            source = load_available_revision(db, revision_id)
            payload = build(source)
            package_id = store_package(db, payload)
            receipt = record_receipt(db, package_id, source.revision_id, start, stop)
    except sqlite3.Error as exc:
        raise PublicationCommitError(f'publication could not be committed: {exc}') from exc
    return package_id, receipt
