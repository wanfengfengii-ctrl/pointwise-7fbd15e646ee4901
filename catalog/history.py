from sqlite3 import Connection


def find_declared_revision(db: Connection, batch_id: str, declared_revision: str) -> int | None:
    row = db.execute(
        'SELECT revision_id FROM source_revisions WHERE batch_id = ? AND declared_revision = ?',
        (batch_id, declared_revision),
    ).fetchone()
    return None if row is None else row[0]


def current_revision(db: Connection, batch_id: str) -> int | None:
    row = db.execute(
        'SELECT revision_id FROM batch_current WHERE batch_id = ?', (batch_id,)
    ).fetchone()
    return None if row is None else row[0]


def set_current_revision(db: Connection, batch_id: str, revision_id: int) -> None:
    db.execute(
        '''INSERT INTO batch_current (batch_id, revision_id) VALUES (?, ?)
           ON CONFLICT (batch_id) DO UPDATE SET revision_id = excluded.revision_id''',
        (batch_id, revision_id),
    )
