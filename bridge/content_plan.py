"""Read-only placement preview for a selected local add-on file."""
import re

from diagnostics import BridgeDiagnostic


FOLDERS = {'mods': 'Mods', 'mod_menus': 'Mod Menus', 'trainers': 'Trainers'}


def plan_content(bridge, game_path, kind, name, size):
    if not isinstance(kind, str) or kind not in FOLDERS:
        raise ValueError('Choose mods, mod menus or trainers.')
    if not isinstance(name, str) or not name or len(name) > 255 or name in ('.', '..') or re.search(r'[\\/\x00-\x1f"<>|?*:]|[. ]$', name):
        raise ValueError('Choose a plain file name without path separators.')
    if type(size) is not int or not 0 < size <= 2**53 - 1:
        raise ValueError('Choose a nonempty local file with a measured size.')
    install = game_path.rsplit('\\', 1)[0] + '\\'
    root = next((root for root in bridge.drives if game_path.lower().startswith(root.lower())), None)
    if root is None:
        raise ValueError('Game storage is no longer discovered.')
    listing = bridge.dispatch('browse', {'path': install})
    if any((listing.get('listing') or {}).get(key) for key in ('truncated', 'rejected')):
        raise ValueError('Game folder listing is incomplete. Cannot preview conflicts.')
    folder_name = FOLDERS[kind]
    existing = next((item for item in listing['files'] if item['name'].lower() == folder_name.lower()), None)
    if existing and not existing['directory']:
        raise ValueError('The destination folder name is already a file.')
    folder_exists = existing is not None
    folder = install + (existing['name'] if existing else folder_name) + '\\'
    conflict = False
    if folder_exists:
        children = bridge.dispatch('browse', {'path': folder})
        if any((children.get('listing') or {}).get(key) for key in ('truncated', 'rejected')):
            raise ValueError('Destination listing is incomplete. Cannot preview conflicts.')
        conflict = any(item['name'].lower() == name.lower() for item in children['files'])
    free = None
    try:
        capacity = bridge.adapter('capacity', path=root)
        total = capacity.get('total')
        value = capacity.get('free')
        if type(total) is int and type(value) is int and 0 <= value <= total <= 2**53 - 1 and total > 0:
            free = value
    except BridgeDiagnostic:
        pass
    return {'destination': folder + name, 'root': root, 'size': size,
            'folder_exists': folder_exists, 'conflict': conflict, 'free': free,
            'enough_space': None if free is None else free >= size,
            'note': 'Preview only. No file was transferred, inspected, installed or activated. Compatibility is unknown.'}
