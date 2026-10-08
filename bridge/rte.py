"""Bounded inspection and opt-in four-byte edits of the running title module."""
import re
import secrets
import time
from xbdm import exact as _exact, line as _line, session as _session


MAX_MODULE_SIZE = 256 * 1024 * 1024
READ_LENGTHS = (4, 8, 16, 32)
POKE_TTL = 60


def _module(stream, executable):
    name = executable.replace('/', '\\').rsplit('\\', 1)[-1]
    if not re.fullmatch(r'[^\\/\x00-\x1f"]{1,128}\.xex', name, re.I):
        raise ValueError('Running XEX name unavailable.')
    stream.sendall(b'modules\r\n')
    if not _line(stream).startswith(b'202-'):
        raise ValueError('XBDM module list unavailable.')
    matches = []
    complete = False
    for _ in range(512):
        line = _line(stream)
        if line == b'.\r\n':
            complete = True
            break
        text = line.decode('ascii', 'replace')
        fields = {key.lower(): value for key, value in
                  re.findall(r'\b(name|base|size)=("[^"\r\n]*"|0x[0-9A-Fa-f]{1,8})', text, re.I)}
        if fields.get('name', '').strip('"').casefold() != name.casefold():
            continue
        try:
            base = int(fields['base'], 16)
            size = int(fields['size'], 16)
        except (KeyError, ValueError):
            raise ValueError('Running XEX module bounds unavailable.') from None
        if not 0x80000000 <= base <= 0xFFFFFFFF or not 0 < size <= MAX_MODULE_SIZE or base + size > 0x100000000:
            raise ValueError('Running XEX module bounds invalid.')
        matches.append({'name': name, 'base': base, 'size': size})
    if not complete:
        raise ValueError('XBDM module list was incomplete.')
    if len(matches) != 1:
        raise ValueError('Running XEX module could not be identified uniquely.')
    return matches[0]


def _snapshot(bridge):
    current = bridge.status()['current_title']
    title_id = current.get('title_id')
    executable = current.get('executable')
    if not isinstance(title_id, str) or not re.fullmatch(r'[0-9A-F]{8}', title_id) or title_id == '00000000' or not isinstance(executable, str):
        raise ValueError('Start a game with a reported Title ID before inspecting memory.')
    with _session(bridge.target) as stream:
        module = _module(stream, executable)
    return {'title_id': title_id, 'executable': executable, 'module': module}


def status(bridge, data):
    if data:
        raise ValueError('RTE status takes no options.')
    snapshot = _snapshot(bridge)
    module = snapshot['module']
    return {'state': 'ready', 'title_id': snapshot['title_id'], 'executable': snapshot['executable'],
            'module': {'name': module['name'], 'base': f'0x{module["base"]:08X}', 'size': module['size']},
            'read_lengths': list(READ_LENGTHS), 'source': 'xbdm'}


def _build_path(bridge, executable):
    from server import safe_path
    if not executable.casefold().startswith('\\device\\'):
        return safe_path(executable, bridge.drives), 'reported-storage-path'
    from launch_ini import DRIVES, read_dashlaunch_state
    matches = [(root, device) for root, device in DRIVES if executable.casefold().startswith(device.casefold())]
    if len(matches) != 1:
        raise ValueError('The process device path has no supported storage-root mapping.')
    export = bridge.adapter('launch-ini-export')
    if export.get('target') != bridge.target:
        raise ValueError('DashLaunch source does not match the connected console.')
    read_dashlaunch_state(export['target'], int(export['address'], 16))  # Validates the versioned drive map.
    root, device = matches[0]
    discovered = next((value for value in bridge.drives if value.casefold() == root.casefold()), None)
    if discovered is None:
        raise ValueError('Process device root was not discovered on this console.')
    return safe_path(discovered + executable[len(device):], bridge.drives), 'dashlaunch-3.21-device-alias'


def build(bridge, data):
    if data:
        raise ValueError('RTE build inspection takes no options.')
    before = _snapshot(bridge)
    path, path_resolution = _build_path(bridge, before['executable'])
    measured = bridge.inspect(path)
    if _snapshot(bridge) != before:
        raise ValueError('The running title changed during file inspection. No build report returned.')
    metadata = measured['metadata']
    if measured['plugin'] or not metadata or metadata['title_id'] != before['title_id']:
        raise ValueError('On-disk XEX Title ID does not match the running title.')
    return {'title_id': before['title_id'], 'module': before['module']['name'],
            'process_path': before['executable'], 'path_resolution': path_resolution,
            'file': {'path': path, 'sha256': measured['hash'], 'size': measured['size'],
                     'media_id': metadata['media_id'], 'version': metadata['version'],
                     'base_version': metadata['base_version']},
            'scope': 'on-disk-xex-only'}


def read(bridge, data):
    if set(data) != {'title_id', 'executable', 'module_base', 'module_size', 'address', 'length'}:
        raise ValueError('Refresh the running title before reading memory.')
    address_text = data.get('address')
    if not isinstance(address_text, str) or not re.fullmatch(r'0x[0-9A-Fa-f]{8}', address_text):
        raise ValueError('Enter an eight-digit hexadecimal title address.')
    address = int(address_text, 16)
    length = data.get('length')
    if type(length) is not int or length not in READ_LENGTHS or address % 4:
        raise ValueError('Choose an aligned title address and a supported read length.')
    before = _snapshot(bridge)
    module = before['module']
    if (data.get('title_id') != before['title_id'] or data.get('executable') != before['executable']
            or data.get('module_base') != f'0x{module["base"]:08X}' or data.get('module_size') != module['size']):
        raise ValueError('The running title changed. Refresh the RTE workspace.')
    if not module['base'] <= address or address + length > module['base'] + module['size']:
        raise ValueError('Address must be inside the running title XEX module.')
    with _session(bridge.target) as stream:
        raw = bytearray()
        for offset in range(0, length, 4):
            stream.sendall(f'getmemex addr=0x{address+offset:08X} length=0x00000004\r\n'.encode('ascii'))
            if not _line(stream).startswith(b'203-'):
                raise ValueError('XBDM could not read that title address.')
            raw.extend(_exact(stream, 6)[2:])
    after = _snapshot(bridge)
    if after != before:
        raise ValueError('The running title changed during the read. No bytes returned.')
    return {'title_id': before['title_id'], 'module_base': data['module_base'],
            'executable': before['executable'], 'module_size': module['size'],
            'address': f'0x{address:08X}', 'length': length, 'hex': raw.hex().upper(), 'source': 'xbdm'}


def preview_poke(bridge, data):
    if set(data) != {'title_id', 'executable', 'module_base', 'module_size', 'address', 'expected', 'replacement'}:
        raise ValueError('Read four bytes from the running title before preparing an edit.')
    expected, replacement = data['expected'], data['replacement']
    if not all(isinstance(value, str) and re.fullmatch(r'[0-9A-Fa-f]{8}', value)
               for value in (expected, replacement)) or expected.upper() == replacement.upper():
        raise ValueError('Enter exactly four changed bytes as eight hexadecimal digits.')
    if data['title_id'] == 'FFFE07D1':
        raise ValueError('Dashboard memory cannot be edited. Start a game first.')
    observed = read(bridge, {key: data[key] for key in ('title_id', 'executable', 'module_base', 'module_size', 'address')}
                    | {'length': 4})
    if observed['hex'] != expected.upper():
        raise ValueError('Memory changed since the last read. Read it again before editing.')
    ticket = secrets.token_urlsafe(24)
    bridge.rte_pokes = {ticket: {'target': bridge.target, 'expires': time.monotonic() + POKE_TTL,
                                  'title_id': observed['title_id'], 'module_base': observed['module_base'],
                                  'executable': observed['executable'], 'module_size': observed['module_size'],
                                  'address': observed['address'], 'expected': observed['hex'],
                                  'replacement': replacement.upper()}}
    return {'ticket': ticket, 'expires_in': POKE_TTL, 'title_id': observed['title_id'],
            'address': observed['address'], 'expected': observed['hex'],
            'replacement': replacement.upper()}


def apply_poke(bridge, data):
    if set(data) != {'ticket', 'confirmed'} or data.get('confirmed') is not True or not isinstance(data.get('ticket'), str):
        raise ValueError('Confirm the prepared four-byte edit.')
    pending = bridge.rte_pokes.pop(data['ticket'], None)
    if not pending or pending['expires'] <= time.monotonic() or pending['target'] != bridge.target:
        raise ValueError('Edit preview expired. Read the running title again.')
    fields = {key: pending[key] for key in ('title_id', 'executable', 'module_base', 'module_size', 'address')}
    observed = read(bridge, fields | {'length': 4})
    if (observed['hex'] != pending['expected'] or observed['executable'] != pending['executable']
            or observed['module_size'] != pending['module_size']):
        raise ValueError('Memory changed since preview. Nothing was written.')
    command = f'setmem addr={pending["address"]} data={pending["replacement"]}\r\n'.encode('ascii')
    try:
        with _session(bridge.target) as stream:
            stream.sendall(command)
            accepted = _line(stream).startswith(b'200-')
    except (OSError, ValueError):
        raise ValueError('Memory edit result is uncertain. Read the address before any retry.') from None
    if not accepted:
        raise ValueError('XBDM rejected the memory edit. Nothing was confirmed written.')
    try:
        after = read(bridge, fields | {'length': 4})
    except (OSError, ValueError):
        raise ValueError('XBDM accepted the edit, but verification failed. Read the address before any retry.') from None
    if after['hex'] != pending['replacement']:
        raise ValueError('XBDM accepted the edit, but bytes differ. Read the address before any retry.')
    result = {'state': 'verified', 'title_id': pending['title_id'], 'address': pending['address'],
              'before': pending['expected'], 'after': after['hex']}
    if not pending.get('rollback'):
        ticket = secrets.token_urlsafe(24)
        bridge.rte_pokes = {ticket: {**pending, 'expected': after['hex'],
                                      'replacement': pending['expected'], 'rollback': True,
                                      'expires': time.monotonic() + POKE_TTL}}
        result.update(rollback_ticket=ticket, rollback_expires_in=POKE_TTL)
    return result
