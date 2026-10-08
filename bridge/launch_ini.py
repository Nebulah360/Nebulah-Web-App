"""DashLaunch 3.21 launch.ini selection, observed through its exported state."""
import re
import socket
import base64
import binascii
import hashlib
import secrets
import tempfile
import time
from pathlib import Path

from companion import CompanionError
from hash_registry import RegistryError, verify_digest
from xbdm import exact as _exact, line


# Versioned DashLaunch 3.21 drive indices from dll/launch_constants.h.
# These are not a substitute for the bridge's discovered storage roots.
DRIVES = (
    ('Usb0:\\', '\\Device\\Mass0\\'),
    ('Usb1:\\', '\\Device\\Mass1\\'),
    ('Usb2:\\', '\\Device\\Mass2\\'),
    ('Hdd:\\', '\\Device\\Harddisk0\\Partition1\\'),
    ('NandMu:\\', '\\Device\\BuiltInMuSfc\\'),
    ('SlimMu:\\', '\\Device\\BuiltInMuUsb\\Storage\\'),
    ('MmcMu:\\', '\\Device\\BuiltInMuMmc\\Storage\\'),
    ('Flash:\\', '\\SystemRoot\\'),
)


def read_dashlaunch_state(host, address):
    """Read only signature, version and iniPathSel. No paths/options enter logs."""
    if not isinstance(host, str) or not 1 <= len(host) <= 253 or not re.fullmatch(r'[A-Za-z0-9_.-]+', host):
        raise ValueError('Console host unavailable.')
    if type(address) is not int or not 0x80000000 <= address <= 0xFFFFFFFF-556:
        raise ValueError('DashLaunch export unavailable.')
    with socket.create_connection((host, 730), timeout=3) as stream:
        stream.settimeout(3)
        if not line(stream, 160).startswith(b'201-'):
            raise ValueError('XBDM did not accept the connection.')
        values = []
        for offset in (0, 528, 552):
            stream.sendall(f'getmemex addr=0x{address+offset:08X} length=0x00000004\r\n'.encode('ascii'))
            if not line(stream, 160).startswith(b'203-'):
                raise ValueError('DashLaunch memory read unavailable.')
            values.append(_exact(stream, 6)[2:])  # XBDM prefixes each binary chunk with two status bytes.
    if values[0] != b'DL30':
        raise ValueError('DashLaunch data signature did not match.')
    version = tuple(int.from_bytes(values[1][i:i+2], 'big') for i in (0, 2))
    if version != (3, 21):
        raise ValueError('DashLaunch version is not supported for active-file detection.')
    selector = int.from_bytes(values[2], 'big')
    if selector >= len(DRIVES):
        raise ValueError('DashLaunch did not identify a supported active root.')
    return selector


def discover(bridge):
    if bridge.target is None:
        raise ValueError('Connect a console first.')
    try:
        export = bridge.adapter('launch-ini-export')
        address = int(export['address'], 16)
        selector = read_dashlaunch_state(export['target'], address)
        active_root = DRIVES[selector][0]
        roots = {root.casefold(): root for root in bridge.drives}
        if active_root.casefold() not in roots:
            raise ValueError('The active DashLaunch root is not in discovered storage.')
        active_root = roots[active_root.casefold()]
        candidates = []
        for root in bridge.drives:
            if root.casefold() not in {item[0].casefold() for item in DRIVES}:
                continue
            try:
                files = bridge.dispatch('browse', {'path': root})['files']
                found = next((item for item in files if item['name'].casefold() == 'launch.ini' and not item['directory']), None)
                if not found:
                    continue
                path = root + found['name']
                measurement = bridge.adapter('launch-ini-hash', path=path)
                if not re.fullmatch(r'[0-9a-f]{64}', measurement.get('sha256', '')):
                    continue
                candidates.append({'path': path, 'sha256': measurement['sha256'], 'size': measurement['size'],
                                   'active': root.casefold() == active_root.casefold()})
            except (ValueError, OSError, KeyError, TypeError):
                continue
        if not any(item['active'] for item in candidates):
            raise ValueError('The selected active launch.ini could not be read.')
        return {'state': 'verified', 'active_path': next(item['path'] for item in candidates if item['active']),
                'candidates': candidates, 'scope': 'runtime-only',
                'note': 'DashLaunch may choose another copy at boot. Runtime switching does not reload plugin slots.'}
    except (ValueError, OSError, KeyError, TypeError) as error:
        reason = str(error)[:200] if isinstance(error, ValueError) else 'DashLaunch source check unavailable. Check Neighborhood and XBDM.'
        return {'state': 'unverified', 'active_path': None, 'candidates': [], 'reason': reason}


def switch(bridge, data):
    if set(data) != {'path', 'sha256', 'confirmed'} or data.get('confirmed') is not True:
        raise ValueError('Confirm a measured launch.ini selection.')
    before = discover(bridge)
    if before['state'] != 'verified':
        raise ValueError('Active launch.ini could not be verified. No switch sent.')
    candidate = next((item for item in before['candidates'] if item['path'] == data['path']
                      and item['sha256'] == data['sha256']), None)
    if candidate is None:
        raise ValueError('Selected launch.ini changed or is not a discovered root file. Refresh first.')
    if candidate['active']:
        return before
    root = candidate['path'].rsplit('\\', 1)[0] + '\\'
    device = next((device for name, device in DRIVES if name.casefold() == root.casefold()), None)
    if device is None:
        raise ValueError('Selected root has no verified DashLaunch device mapping.')
    bridge.adapter('launch-ini-apply', device_path=device)
    after = discover(bridge)
    active = next((item for item in after['candidates'] if item['active']), None)
    if (after['state'] != 'verified' or after['active_path'].casefold() != candidate['path'].casefold()
            or active is None or active['sha256'] != candidate['sha256']):
        raise ValueError('DashLaunch did not confirm the selected launch.ini. Refresh before any retry.')
    return after


_SECTION = re.compile(r'^\s*\[([^\]\r\n]+)\]\s*(?:[;#].*)?$', re.I)
_SLOT = re.compile(r'^(\s*plugin([1-5])\s*=\s*)([^\r\n;#]*?)(\s*(?:[;#].*)?)$', re.I)
_PATH = re.compile(r'^[A-Za-z0-9_]+:\\[^"<>|?*:/\x00-\x1f]+\.xex$', re.I)
_PREVIEW_TTL = 90


def _parse(raw):
    """Keep byte-for-byte text outside plugin values, including line endings."""
    if not 1 <= len(raw) <= 131072 or b'\x00' in raw:
        raise CompanionError('Active launch.ini is outside supported text limits.')
    lines = raw.decode('latin1').splitlines(keepends=True)
    section = None
    sections = 0
    slots = [None] * 5
    positions = [None] * 5
    insert_at = None
    for index, line in enumerate(lines):
        content = line.rstrip('\r\n')
        match = _SECTION.fullmatch(content)
        if match:
            if section == 'plugins' and insert_at is None:
                insert_at = index
            section = match.group(1).strip().casefold()
            if section == 'plugins':
                sections += 1
                if sections > 1:
                    raise CompanionError('launch.ini has multiple [Plugins] sections; edit it manually.')
            continue
        if section != 'plugins':
            continue
        match = _SLOT.fullmatch(content)
        if not match:
            if re.match(r'^\s*plugin[1-5]\s*=', content, re.I):
                raise CompanionError('A plugin slot has unsupported syntax; edit launch.ini manually.')
            continue
        slot = int(match.group(2)) - 1
        if positions[slot] is not None:
            raise CompanionError('launch.ini repeats a plugin slot; edit it manually.')
        value = match.group(3).strip()
        if value and (len(value) > 512 or not value.isascii() or not _PATH.fullmatch(value)):
            raise CompanionError('A configured plugin path has unsupported syntax; edit launch.ini manually.')
        slots[slot] = value
        positions[slot] = (index, match.group(1), match.group(4), line[len(content):])
    if sections != 1:
        raise CompanionError('No [Plugins] section found in active launch.ini.')
    if insert_at is None:
        insert_at = len(lines)
    return lines, [value or '' for value in slots], positions, insert_at


def _render(raw, desired):
    lines, _, positions, insert_at = _parse(raw)
    line_ending = '\r\n' if b'\r\n' in raw else '\n'
    missing = []
    for i, value in enumerate(desired):
        position = positions[i]
        if position is None:
            missing.append(f'plugin{i+1} = {value}{line_ending}')
        else:
            line_index, prefix, suffix, ending = position
            lines[line_index] = prefix + value + suffix + ending
    if missing:
        if insert_at > 0 and not lines[insert_at-1].endswith(('\r', '\n')):
            missing.insert(0, line_ending)
        lines[insert_at:insert_at] = missing
    return ''.join(lines).encode('latin1')


def _active_bytes(bridge):
    selection = discover(bridge)
    if selection['state'] != 'verified':
        raise CompanionError('Active launch.ini could not be verified. Refresh the Console tab.')
    active = next(item for item in selection['candidates'] if item['active'])
    snapshot = bridge.adapter('launch-ini-read', path=active['path'])
    try:
        raw = base64.b64decode(snapshot['data'], validate=True)
        measured = hashlib.sha256(raw).hexdigest()
        if measured != active['sha256'] or measured != snapshot['sha256'] or len(raw) != snapshot['size']:
            raise ValueError()
    except (ValueError, KeyError, TypeError, binascii.Error):
        raise CompanionError('Active launch.ini changed during read. Refresh and retry.') from None
    return active, raw


def _observed(bridge):
    try:
        listing = bridge.adapter('plugins')
        if listing.get('state') != 'observed' or not isinstance(listing.get('modules'), list):
            return None
        names = set()
        for item in listing['modules']:
            if isinstance(item, dict) and isinstance(item.get('name'), str):
                names.add(item['name'].casefold())
        return names
    except (ValueError, OSError):
        return None


def plugins(bridge):
    active, raw = _active_bytes(bridge)
    slots = _parse(raw)[1]
    observed = _observed(bridge)
    return {'state': 'verified', 'active_path': active['path'], 'sha256': active['sha256'],
            'slots': [{'number': i + 1, 'path': value,
                       'module_observation': ('unavailable' if observed is None else
                                              'name-observed' if value and value.rsplit('\\', 1)[-1].casefold() in observed else
                                              'not-observed')}
                      for i, value in enumerate(slots)],
            'note': 'A module-name match does not prove the loaded bytes came from this path. Slot edits take effect on the next boot.'}


def preview_plugins(bridge, data):
    if set(data) != {'slots'} or not isinstance(data['slots'], list) or len(data['slots']) != 5:
        raise CompanionError('Provide all five DashLaunch plugin slots.')
    active, raw = _active_bytes(bridge)
    current = _parse(raw)[1]
    desired = []
    inspections = []
    for i, value in enumerate(data['slots']):
        if not isinstance(value, str) or len(value) > 512:
            raise CompanionError('Plugin slots must be XEX paths or empty.')
        value = value.strip()
        if value == current[i]:
            desired.append(value)
            continue
        if not value:
            desired.append('')
            continue
        if not value.isascii() or not _PATH.fullmatch(value) or re.search(r'(?:^|\\)\.\.?\\', value):
            raise CompanionError('Choose a valid ASCII console XEX path for the changed slot.')
        from server import safe_path
        path = safe_path(value, bridge.drives)
        inspection = bridge.inspect(path, allow_module=True)
        if inspection.get('valid') is not True or inspection.get('plugin') is not True:
            raise CompanionError(f'Plugin {i+1} is not structurally marked as a DLL/plugin.')
        try:
            review = verify_digest(inspection['hash'], inspection['size'])
        except (RegistryError, OSError):
            raise CompanionError('Build registry unavailable; plugin slot editing paused.') from None
        if review['status'] in ('mismatch', 'revoked', 'unknown-build'):
            raise CompanionError(f'Plugin {i+1} differs from a reviewed build or is revoked.')
        if path.casefold().startswith('usb0:\\'):
            resolved = bridge.adapter('launch-ini-resolve-plugin', path=path,
                                      sha256=inspection['hash'], size=inspection['size'])
            if resolved.get('path_mode') != 'verified-usb-alias' or resolved.get('runtime_path') != 'Usb:' + path[5:]:
                raise CompanionError('Usb0: could not be verified as DashLaunch Usb:. Choose another path.')
            value = resolved['runtime_path']
        desired.append(value)
        inspections.append({'slot': i+1, 'path': value, 'source_path': path, 'sha256': inspection['hash'],
                            'review_status': review['status']})
    if desired == current:
        raise CompanionError('No plugin slot changes to save.')
    if active['path'].casefold().startswith('flash:\\'):
        raise CompanionError('Editing a Flash launch.ini is disabled. Use a writable storage-root copy.')
    replacement = _render(raw, desired)
    if len(replacement) > 131072:
        raise CompanionError('Updated launch.ini exceeds size limit.')
    token = secrets.token_urlsafe(24)
    bridge.launch_ini_edit_hold = {'token': token, 'target': bridge.target,
                                   'path': active['path'], 'source_sha256': active['sha256'],
                                   'new_sha256': hashlib.sha256(replacement).hexdigest(),
                                   'bytes': replacement, 'slots': desired, 'inspections': inspections,
                                   'expires': time.monotonic()+_PREVIEW_TTL}
    return {'state': 'ready', 'preview': token, 'active_path': active['path'],
            'source_sha256': active['sha256'], 'new_sha256': bridge.launch_ini_edit_hold['new_sha256'],
            'changes': [{'slot': i+1, 'before': current[i], 'after': desired[i]} for i in range(5) if current[i] != desired[i]],
            'inspections': [{key: item[key] for key in ('slot', 'path', 'sha256', 'review_status')}
                            for item in inspections], 'expires_in': _PREVIEW_TTL,
            'effect': 'Saved slots apply on the next boot. Loaded modules do not change now.'}


def save_plugins(bridge, data):
    if set(data) != {'preview', 'confirmed'} or data.get('confirmed') is not True:
        raise CompanionError('Confirm the reviewed plugin slot changes.')
    hold = bridge.launch_ini_edit_hold
    bridge.launch_ini_edit_hold = None  # one use, including failed attempts
    if (not isinstance(hold, dict) or not isinstance(data.get('preview'), str)
            or not secrets.compare_digest(data['preview'], hold['token'])
            or hold['expires'] <= time.monotonic() or hold['target'] != bridge.target):
        raise CompanionError('Plugin slot preview expired. Refresh and review again.')
    active, raw = _active_bytes(bridge)
    if active['path'] != hold['path'] or active['sha256'] != hold['source_sha256']:
        raise CompanionError('Active launch.ini changed. No write sent; refresh and review again.')
    if hashlib.sha256(hold['bytes']).hexdigest() != hold['new_sha256']:
        raise CompanionError('Prepared launch.ini changed. No write sent.')
    if _parse(hold['bytes'])[1] != hold['slots']:
        raise CompanionError('Prepared plugin slots did not match preview.')
    for item in hold['inspections']:
        latest = bridge.inspect(item['source_path'], allow_module=True)
        if (latest.get('valid') is not True or latest.get('plugin') is not True
                or latest.get('hash') != item['sha256']):
            raise CompanionError(f'Plugin {item["slot"]} changed since review. No write sent.')
    with tempfile.TemporaryDirectory(prefix='nebulah-launch-ini-') as folder:
        local = Path(folder) / 'launch.ini'
        local.write_bytes(hold['bytes'])
        result = bridge.adapter('launch-ini-save', path=active['path'], expected_sha256=active['sha256'],
                                new_sha256=hold['new_sha256'], local=str(local))
    if result.get('state') != 'saved':
        return {'state': result.get('state', 'uncertain'), 'backup_path': result.get('backup_path'),
                'partial_path': result.get('partial_path'),
                'reason': 'Save not confirmed. Inspect the active file and retained recovery copy before retrying.'}
    try:
        after, updated = _active_bytes(bridge)
        verified = (after['path'] == hold['path'] and after['sha256'] == hold['new_sha256']
                    and _parse(updated)[1] == hold['slots'])
    except (ValueError, OSError):
        verified = False
    if not verified:
        return {'state': 'uncertain', 'backup_path': result.get('backup_path'),
                'reason': 'Console saved the file, but DashLaunch active state could not be verified. Check before rebooting.'}
    return {'state': 'saved', 'active_path': hold['path'], 'sha256': hold['new_sha256'],
            'backup_path': result.get('backup_path'), 'effect': 'Plugin slots will apply on the next boot.'}
