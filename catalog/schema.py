import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from os import PathLike


def open_catalog(path: str | PathLike[str]) -> sqlite3.Connection:
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute('PRAGMA foreign_keys = ON')
    except BaseException:
        db.close()
        raise
    return db


def initialize_catalog(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS source_revisions (
            revision_id INTEGER PRIMARY KEY,
            batch_id TEXT NOT NULL,
            declared_revision TEXT NOT NULL,
            observations TEXT NOT NULL,
            retired INTEGER NOT NULL DEFAULT 0 CHECK (retired IN (0, 1)),
            UNIQUE (batch_id, declared_revision),
            UNIQUE (batch_id, revision_id)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS batch_current (
            batch_id TEXT PRIMARY KEY NOT NULL,
            revision_id INTEGER NOT NULL,
            FOREIGN KEY (batch_id, revision_id)
                REFERENCES source_revisions (batch_id, revision_id)
        )
    ''')


def is_record_id(value: object) -> bool:
    return type(value) is int and 0 < value < (1 << 63)


@contextmanager
def write_transaction(db: sqlite3.Connection) -> Iterator[None]:
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise
