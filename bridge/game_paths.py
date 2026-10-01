"""Local game shortcuts, scoped to the selected Neighborhood target."""
import re
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / '.local' / 'games.sqlite3'

class GamePaths:
    def __init__(self, path=None):
        self.path = Path(path or DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS games (id INTEGER PRIMARY KEY, target TEXT NOT NULL, name TEXT NOT NULL, folder TEXT NOT NULL, executable TEXT NOT NULL, UNIQUE(target, folder, executable))')

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def list(self, target):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT id,name,folder,executable FROM games WHERE target=? ORDER BY name COLLATE NOCASE', (target.lower(),))]

    def save(self, target, name, folder, executable):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or re.search(r'[\x00-\x1f]', name):
            raise ValueError('A shortcut name of 1–80 characters is required.')
        with self.connect() as db:
            db.execute('INSERT INTO games(target,name,folder,executable) VALUES(?,?,?,?) ON CONFLICT(target,folder,executable) DO UPDATE SET name=excluded.name', (target.lower(), name.strip(), folder, executable))
        return {'saved': True}

    def remove(self, target, shortcut_id):
        if type(shortcut_id) is not int:
            raise ValueError('Shortcut ID required.')
        with self.connect() as db:
            db.execute('DELETE FROM games WHERE target=? AND id=?', (target.lower(), shortcut_id))
        return {'removed': True}
