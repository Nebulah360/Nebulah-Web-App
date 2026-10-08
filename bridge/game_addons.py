"""Bounded, read-only discovery of files associated with an inspected game."""
import re

from diagnostics import BridgeDiagnostic

MAX_FOLDERS = 48
MAX_ITEMS = 120
KINDS = ('trainers', 'title_updates', 'mods', 'mod_menus')


def discover_game_addons(bridge, game_path, title_id, aurora_paths):
    """Use exact game location and Title ID folders; never infer active state."""
    roots = bridge.drives
    found = {kind: [] for kind in KINDS}
    listings = {}
    seen_files = set()
    incomplete = False

    def children(folder):
        nonlocal incomplete
        key = folder.lower()
        if key in listings:
            return listings[key]
        if len(listings) >= MAX_FOLDERS:
            incomplete = True
            return []
        try:
            result = bridge.dispatch('browse', {'path': folder})
        except BridgeDiagnostic as error:
            if error.code != 'STORAGE_BROWSE_FAILED':
                raise
            incomplete = True
            result = {'files': []}
        listing = result.get('listing') or {}
        if listing.get('truncated') or listing.get('rejected'):
            incomplete = True
        listings[key] = result['files']
        return result['files']

    def child_directory(parent, name):
        match = next((entry for entry in children(parent)
                      if entry['directory'] and entry['name'].lower() == name.lower()), None)
        return parent.rstrip('\\') + '\\' + match['name'] + '\\' if match else None

    def descend(parent, names):
        for name in names:
            parent = child_directory(parent, name)
            if parent is None:
                return None
        return parent

    def collect(kind, folder, source, depth=0):
        nonlocal incomplete
        queue = [(folder, 0)]
        while queue:
            current, level = queue.pop(0)
            for entry in children(current):
                if sum(map(len, found.values())) >= MAX_ITEMS:
                    incomplete = True
                    return
                name = entry['name']
                if name.startswith('.'):
                    continue
                path = current.rstrip('\\') + '\\' + name
                if entry['directory']:
                    if level < depth:
                        queue.append((path + '\\', level + 1))
                    continue
                if kind == 'trainers' and not name.lower().endswith('.xex'):
                    continue
                if kind == 'title_updates' and name.lower().endswith(('.txt', '.json', '.png', '.jpg')):
                    continue
                if path.lower() in seen_files:
                    continue
                seen_files.add(path.lower())
                found[kind].append({'name': name, 'path': path, 'size': entry['size'], 'source': source})

    install = game_path.rsplit('\\', 1)[0] + '\\'
    for folder_name, kind in (('Mods', 'mods'), ('Mod Menus', 'mod_menus'),
                              ('ModMenus', 'mod_menus'), ('Trainers', 'trainers'),
                              ('Title Updates', 'title_updates'), ('TitleUpdates', 'title_updates')):
        folder = child_directory(install, folder_name)
        if folder:
            collect(kind, folder, 'Game folder', 1)
    for entry in children(install):
        if entry['directory'] or not re.search(r'(?:mod[ _-]?menu|trainer)', entry['name'], re.I):
            continue
        if not entry['name'].lower().endswith(('.xex', '.dll', '.gsc', '.sco')):
            continue
        kind = 'mod_menus' if re.search(r'mod[ _-]?menu', entry['name'], re.I) else 'trainers'
        path = install + entry['name']
        if path.lower() not in seen_files and sum(map(len, found.values())) < MAX_ITEMS:
            seen_files.add(path.lower())
            found[kind].append({'name': entry['name'], 'path': path,
                                'size': entry['size'], 'source': 'Game filename hint'})

    if title_id:
        if len(aurora_paths) > 16:
            incomplete = True
        for path in aurora_paths[:16]:
            if not any(path.lower().startswith(root.lower()) for root in roots):
                continue
            base = path.rsplit('\\', 1)[0] + '\\'
            folder = descend(base, ('User', 'Trainers', title_id))
            if folder:
                collect('trainers', folder, 'Aurora trainer folder', 2)
        for root in roots:
            folder = descend(root, ('Content', '0000000000000000', title_id, '000B0000'))
            if folder:
                collect('title_updates', folder, 'Content title-update folder', 1)
            folder = descend(root, ('JTAG', title_id))
            if folder:
                collect('mods', folder, 'JTAG Title ID folder', 1)

    for entries in found.values():
        entries.sort(key=lambda entry: entry['path'].lower())
    return {'items': found, 'title_id': title_id, 'folders_checked': len(listings),
            'incomplete': incomplete}
