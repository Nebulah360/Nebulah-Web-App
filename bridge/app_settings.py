"""PC-owned console preferences. Admin is a bridge-session switch, not stored here."""
import ipaddress
import json
import os
import tempfile
from pathlib import Path
from runtime_paths import ROOT

SETTINGS_PATH = ROOT / '.local' / 'app-settings.json'
DEFAULTS = {'default_console_ip': '', 'allow_writes': True}
CONSOLE_WRITES = frozenset({
    'launch', 'plugins/load', 'plugins/unload', 'plugins/force-release', 'plugins/install',
    'console/launch-ini-switch', 'console/launch-ini/plugins/save', 'console/notify',
    'console/power', 'controller/pulse', 'rte/poke-apply', 'stream360/start',
    'stream360/audio-enable', 'transfer/cleanup',
})


def validate(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError('Choose a default console and write access before saving.')
    address = value['default_console_ip']
    if not isinstance(address, str):
        raise ValueError('Use a private console IPv4 address or leave it blank for Neighborhood.')
    if address:
        try:
            ip = ipaddress.IPv4Address(address)
        except ipaddress.AddressValueError as error:
            raise ValueError('Use a private console IPv4 address or leave it blank for Neighborhood.') from error
        if not ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            raise ValueError('Use a private console IPv4 address or leave it blank for Neighborhood.')
    if type(value['allow_writes']) is not bool:
        raise ValueError('Write access must be on or off.')
    return dict(value)


def load(path=SETTINGS_PATH):
    if not path.exists():
        return dict(DEFAULTS)
    if path.stat().st_size > 4096:
        raise ValueError('App settings file is too large.')
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('App settings file could not be read.') from error
    if not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1:
        raise ValueError('App settings version is unsupported.')
    if set(value) != {'schema', *DEFAULTS}:
        raise ValueError('App settings contain unsupported fields.')
    return validate({key: value[key] for key in DEFAULTS})


def save(value, path=SETTINGS_PATH):
    settings = validate(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', newline='\n',
                                         dir=path.parent, prefix='.app-settings-', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({'schema': 1, **settings}, stream, separators=(',', ':'))
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return settings


def requires_write(action, data, bridge):
    if action in CONSOLE_WRITES or action == 'transfer/start' and data.get('direction') == 'upload':
        return True
    if action in ('transfer/chunk', 'transfer/approve', 'transfer/finish'):
        job = getattr(getattr(bridge, 'companion', None), 'transfer', None)
        return isinstance(job, dict) and job.get('direction') == 'upload'
    return False
