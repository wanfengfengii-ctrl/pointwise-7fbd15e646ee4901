from sqlite3 import Connection

from catalog.history import find_declared_revision
from catalog.source import load_revision
from intake.input import BatchSubmission


class RevisionConflict(ValueError):
    pass


def resolve_revision(db: Connection, submission: BatchSubmission) -> int | None:
    revision_id = find_declared_revision(db, submission.batch_id, submission.declared_revision)
    if revision_id is None:
        return None
    existing = load_revision(db, revision_id)
    if existing is None:
        raise RuntimeError('declared revision disappeared during registration')
    if (
        existing.rows != submission.rows
        or existing.temperature != submission.temperature
        or existing.pressure != submission.pressure
    ):
        raise RevisionConflict('this batch and revision label already bind different observations')
    return revision_id
