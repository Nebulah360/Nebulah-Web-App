"""Short-lived SQLite transactions with deterministic handle cleanup."""
from contextlib import contextmanager
import sqlite3

@contextmanager
def open_database(path, **kwargs):
    connection = sqlite3.connect(path, **kwargs)
    try:
        connection.row_factory = sqlite3.Row
        # SQLite's own context manager commits/rolls back, but does not close.
        with connection:
            yield connection
    finally:
        connection.close()
