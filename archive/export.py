from sqlite3 import Connection
from typing import BinaryIO

from archive.orders import load_order
from archive.packages import load_package


def fetch_package(db: Connection, package_id: int) -> bytes:
    return load_package(db, package_id)


def fetch_order(db: Connection, order_id: int) -> tuple[bytes, tuple[bytes, ...]]:
    """Return the stored manifest and station-ordered member bytes of an order."""
    return load_order(db, order_id)


def write_package(db: Connection, package_id: int, stream: BinaryIO) -> int:
    payload = fetch_package(db, package_id)
    remaining = memoryview(payload)
    while remaining:
        written = stream.write(remaining)
        if written is None or not 0 < written <= len(remaining):
            raise OSError('package output stream made no valid write progress')
        remaining = remaining[written:]
    return len(payload)
