from sqlite3 import Connection


def initialize_archive(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS packages (
            package_id INTEGER PRIMARY KEY,
            payload BLOB NOT NULL CHECK (typeof(payload) = 'blob' AND length(payload) > 0)
        )
    ''')
