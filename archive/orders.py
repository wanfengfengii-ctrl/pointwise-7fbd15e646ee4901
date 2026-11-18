from sqlite3 import Connection

from catalog.schema import is_record_id


class OrderNotFound(LookupError):
    pass


def initialize_orders(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS order_manifests (
            order_id INTEGER PRIMARY KEY,
            revision_id INTEGER NOT NULL REFERENCES source_revisions (revision_id),
            start_row INTEGER NOT NULL CHECK (start_row >= 0),
            stop_row INTEGER NOT NULL CHECK (stop_row > start_row),
            manifest BLOB NOT NULL CHECK (typeof(manifest) = 'blob' AND length(manifest) > 0)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS order_volumes (
            order_id INTEGER NOT NULL REFERENCES order_manifests (order_id),
            station INTEGER NOT NULL CHECK (station >= 0),
            payload BLOB NOT NULL CHECK (typeof(payload) = 'blob' AND length(payload) > 0),
            PRIMARY KEY (order_id, station)
        )
    ''')


def next_order_id(db: Connection) -> int:
    """Reserve the next order number inside the caller's IMMEDIATE transaction."""
    row = db.execute('SELECT COALESCE(MAX(order_id), 0) + 1 FROM order_manifests').fetchone()
    return row[0]


def store_order(
    db: Connection,
    order_id: int,
    revision_id: int,
    start: int,
    stop: int,
    manifest: bytes,
    volumes: list[bytes],
) -> int:
    """Store the manifest and every member inside the caller's order transaction."""
    db.execute(
        '''INSERT INTO order_manifests (order_id, revision_id, start_row, stop_row, manifest)
           VALUES (?, ?, ?, ?, ?)''',
        (order_id, revision_id, start, stop, manifest),
    )
    for station, payload in enumerate(volumes):
        db.execute(
            'INSERT INTO order_volumes (order_id, station, payload) VALUES (?, ?, ?)',
            (order_id, station, payload),
        )
    return order_id


def load_order(db: Connection, order_id: int) -> tuple[bytes, tuple[bytes, ...]]:
    if not is_record_id(order_id):
        raise OrderNotFound(order_id)
    row = db.execute('SELECT manifest FROM order_manifests WHERE order_id = ?', (order_id,)).fetchone()
    if row is None:
        raise OrderNotFound(order_id)
    volumes = db.execute(
        'SELECT payload FROM order_volumes WHERE order_id = ? ORDER BY station',
        (order_id,),
    ).fetchall()
    return row[0], tuple(item[0] for item in volumes)
