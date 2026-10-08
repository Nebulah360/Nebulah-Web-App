"""Atomic, human-readable snapshot of local game data; never a trust catalog."""
from database import open_database
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time

_LOCK = threading.RLock()


def write_game_data(folder, workspace='companion.sqlite3', shortcuts='games.sqlite3'):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        data = {'schema_version': 1, 'updated_at': int(time.time()),
                'trust': 'Local saved data only; candidates are not reviewed baselines.'}
        for filename, tables in ((workspace, ('profiles', 'favorites', 'recent', 'library', 'library_inspections', 'library_labels', 'titles', 'candidates')),
                                 (shortcuts, ('games',))):
            path = folder / filename
            if not path.exists():
                for table in tables: data[table] = []
                continue
            with open_database(path) as db:
                db.row_factory = sqlite3.Row
                existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table in tables:
                    data[table] = []
                    if table not in existing: continue
                    for row in db.execute('SELECT * FROM ' + table):
                        item = dict(row)
                        if table in ('titles', 'candidates', 'library_inspections'):
                            item['data'] = json.loads(item['data'])
                        data[table].append(item)
        destination = folder / 'game-data.json'
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=folder,
                                             prefix='.game-data-', suffix='.tmp', delete=False) as out:
                temporary = Path(out.name)
                json.dump(data, out, indent=2, ensure_ascii=False)
                out.write('\n')
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary is not None and temporary.exists(): temporary.unlink()
        return destination
