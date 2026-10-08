"""Local game shortcuts, scoped to the selected Neighborhood target."""
from database import open_database
import re
import sqlite3
from game_data import write_game_data
from pathlib import Path
from runtime_paths import ROOT

DB = ROOT / '.local' / 'games.sqlite3'

def validate_game_mode(value):
    if not isinstance(value, str) or value not in ('', 'campaign', 'multiplayer', 'zombies', 'other'):
        raise ValueError('Choose a valid game mode.')
    return value

class GamePaths:
    def __init__(self, path=None):
        self.path = Path(path or DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS games (id INTEGER PRIMARY KEY, target TEXT NOT NULL, name TEXT NOT NULL, folder TEXT NOT NULL, executable TEXT NOT NULL, UNIQUE(target, folder, executable))')

            if 'mode' not in {row[1] for row in db.execute('PRAGMA table_info(games)')}:
                db.execute("ALTER TABLE games ADD COLUMN mode TEXT NOT NULL DEFAULT ''")

            if 'title_id' not in {row[1] for row in db.execute('PRAGMA table_info(games)')}:
                db.execute("ALTER TABLE games ADD COLUMN title_id TEXT NOT NULL DEFAULT ''")
        self.sync_game_data()

    def sync_game_data(self):
        return write_game_data(self.path.parent, shortcuts=self.path.name)

    def connect(self):
        return open_database(self.path)

    def list(self, target):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT id,name,folder,executable,mode,title_id FROM games WHERE target=? ORDER BY name COLLATE NOCASE', (target.lower(),))]

    def save(self, target, name, folder, executable, mode=""):
        mode = validate_game_mode(mode)
        if mode and not executable:
            raise ValueError("Choose an XEX before assigning a game mode.")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or re.search(r'[\x00-\x1f]', name):
            raise ValueError('A shortcut name of 1–80 characters is required.')
        with self.connect() as db:
            db.execute('INSERT INTO games(target,name,folder,executable,mode) VALUES(?,?,?,?,?) ON CONFLICT(target,folder,executable) DO UPDATE SET name=excluded.name,mode=excluded.mode', (target.lower(), name.strip(), folder, executable, mode))
        self.sync_game_data()
        return {'saved': True}

    def set_title(self, target, shortcut_id, title_id):
        if not isinstance(title_id,str) or not re.fullmatch('[0-9A-F]{8}',title_id) or title_id=='00000000':
            raise ValueError('A valid Title ID is required for artwork.')
        with self.connect() as db:
            db.execute('UPDATE games SET title_id=? WHERE target=? AND id=?',(title_id,target.lower(),shortcut_id))
        self.sync_game_data()

    def remove(self, target, shortcut_id):
        if type(shortcut_id) is not int:
            raise ValueError('Shortcut ID required.')
        with self.connect() as db:
            db.execute('DELETE FROM games WHERE target=? AND id=?', (target.lower(), shortcut_id))
        self.sync_game_data()
        return {'removed': True}

