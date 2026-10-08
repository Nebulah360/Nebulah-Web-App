"""Small, local-only preferences consumed by the Windows bridge launcher."""
import json
import os
import tempfile
from pathlib import Path
from runtime_paths import ROOT

SETTINGS_PATH = ROOT / '.local' / 'launcher-settings.json'
DEFAULTS = {'phone_access': True, 'browser': 'default', 'open_browser': True}


def validate(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError('Choose all launcher settings before saving.')
    if type(value['phone_access']) is not bool or type(value['open_browser']) is not bool:
        raise ValueError('Launcher switches must be on or off.')
    if value['browser'] not in ('default', 'chrome'):
        raise ValueError('Choose Default or Chrome for the PC browser.')
    return dict(value)


def load(path=SETTINGS_PATH):
    if not path.exists():
        return dict(DEFAULTS)
    if path.stat().st_size > 4096:
        raise ValueError('Launcher settings file is too large.')
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('Launcher settings file could not be read.') from error
    if not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1:
        raise ValueError('Launcher settings version is unsupported.')
    if set(value) != {'schema', *DEFAULTS}:
        raise ValueError('Launcher settings contain unsupported fields.')
    return validate({key: value[key] for key in DEFAULTS})


def save(value, path=SETTINGS_PATH):
    settings = validate(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({'schema': 1, **settings}, separators=(',', ':')) + '\n'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', newline='\n',
                                         dir=path.parent, prefix='.launcher-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return settings
