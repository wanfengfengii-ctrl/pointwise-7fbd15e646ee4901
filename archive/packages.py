from sqlite3 import Connection

from catalog.schema import is_record_id


class PackageNotFound(LookupError):
    pass


def store_package(db: Connection, payload: bytes) -> int:
    """Store the fixed bytes inside the caller's publication transaction."""
    cursor = db.execute('INSERT INTO packages (payload) VALUES (?)', (payload,))
    return cursor.lastrowid


def load_package(db: Connection, package_id: int) -> bytes:
    if not is_record_id(package_id):
        raise PackageNotFound(package_id)
    row = db.execute('SELECT payload FROM packages WHERE package_id = ?', (package_id,)).fetchone()
    if row is None:
        raise PackageNotFound(package_id)
    return row[0]
