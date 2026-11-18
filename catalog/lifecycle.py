from sqlite3 import Connection

from catalog.schema import is_record_id, write_transaction
from catalog.source import SourceRevision, load_revision


class SourceNotFound(LookupError):
    pass


class SourceUnavailable(ValueError):
    pass


def load_available_revision(db: Connection, revision_id: int) -> SourceRevision:
    revision = load_revision(db, revision_id)
    if revision is None:
        raise SourceNotFound(revision_id)
    if revision.retired:
        raise SourceUnavailable(f'source revision {revision_id} is retired')
    return revision


def retire_source(db: Connection, revision_id: int) -> int:
    if not is_record_id(revision_id):
        raise SourceNotFound(revision_id)
    with write_transaction(db):
        cursor = db.execute(
            'UPDATE source_revisions SET retired = 1 WHERE revision_id = ?',
            (revision_id,),
        )
        if cursor.rowcount != 1:
            raise SourceNotFound(revision_id)
    return revision_id
