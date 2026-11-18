from sqlite3 import Connection

from catalog.history import set_current_revision
from catalog.schema import write_transaction
from catalog.source import store_revision
from intake.input import parse_submission
from intake.revision import resolve_revision
from intake.validate import validate_submission


def register(db: Connection, raw: dict) -> int:
    """Register a batch submission and return its fixed source revision number."""
    submission = parse_submission(raw)
    validate_submission(submission)
    with write_transaction(db):
        revision_id = resolve_revision(db, submission)
        if revision_id is None:
            revision_id = store_revision(
                db,
                submission.batch_id,
                submission.declared_revision,
                submission.rows,
                submission.temperature,
                submission.pressure,
            )
            set_current_revision(db, submission.batch_id, revision_id)
    return revision_id
