"""Read allowlisted title names from a bounded, on-console Aurora database copy."""
import re
import sqlite3
from pathlib import Path

MAX_AURORA_DB = 8 * 1024 * 1024


def title_names(path, wanted):
    """Return only unambiguous names for measured game Title IDs."""
    if not wanted:
        return {}
    file = Path(path)
    if not 0 < file.stat().st_size <= MAX_AURORA_DB:
        raise ValueError('Aurora title database exceeds the inspection limit.')
    with file.open('rb') as stream:
        header = stream.read(16)
    if header != b'SQLite format 3\x00':
        raise ValueError('Aurora title database is not SQLite.')
    connection = sqlite3.connect(file.as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        connection.execute('PRAGMA trusted_schema=OFF')
        names = {}
        cursor = connection.execute('SELECT TitleId, TitleName FROM ContentItems LIMIT 10000')
        try:
            for ident, name in cursor:
                if type(ident) is not int or not isinstance(name, str):
                    continue
                key = f'{ident & 0xffffffff:08X}'
                name = name.strip()
                if key in wanted and name and len(name) <= 256 and not re.search(r'[\x00-\x1f]', name):
                    names.setdefault(key, set()).add(name)
        finally:
            cursor.close()
        return {key: next(iter(values)) for key, values in names.items() if len(values) == 1}
    finally:
        connection.close()
