"""Historical library observations. Grouping never grants trust or authorizes deletion."""
import hashlib
import re
import time
from collections import Counter
from component_catalog import classify_component, library_collection, load_components


HEX_FIELDS = ('title_id', 'media_id', 'version', 'base_version')
CATEGORIES = ('uncategorized', 'games', 'homebrew', 'emulators', 'apps', 'plugins', 'stealth')
SUPPORT_FOLDERS = frozenset(('backup', 'backups', 'cache', 'data', 'assets', 'dlc', 'saves',
                             'updates', 'update', 'titleupdates', 'title updates',
                             '$systemupdate', 'systemupdate'))
COLLECTION_FOLDERS = frozenset(('games', 'game', 'homebrew', 'emulators', 'apps',
                                'applications', 'dashboards', 'plugins', 'plugin'))


def library_alias_roots(drives):
    """Exclude alternate and service-created namespaces from physical installs."""
    roots = {root.lower() for root in drives}
    if len(roots) < 2:
        return set()
    aliases = {'game:\\'} & roots  # Current-title mount, not an install drive.
    if 'usb:\\' in roots and any(re.fullmatch(r'usb[0-9]+:\\', root) for root in roots):
        aliases.add('usb:\\')
    # Known stealth services can expose title mirrors as separate drive roots.
    for component in load_components()[0]['components']:
        if component['category'] == 'stealth':
            aliases.add(component['id'].lower() + ':\\')
            aliases.add(component['id'].lower() + 'data:\\')
    return aliases & roots


def library_path_excluded(path, directory=False):
    """Display/discovery policy only. An explicit local label can include an entry."""
    parts = path.rstrip('\\').lower().split('\\')
    folders = parts[1:] if directory else parts[1:-1]
    return any(part in SUPPORT_FOLDERS or part.startswith('.') or part.endswith('.data')
               for part in folders) or (not directory and parts[-1].startswith('.'))


def disc_folder(path):
    return bool(re.fullmatch(r'(?:disc|disk)[ _-]*[1-9][0-9]*', path.rstrip('\\').rsplit('\\', 1)[-1], re.I))


def install_folder(path):
    """A root or a named collection may have its own launcher and other installs."""
    parts = path.rstrip('\\').lower().split('\\')
    return len(parts) > 1 and parts[-1] not in COLLECTION_FOLDERS


def folder_category(path):
    hints = {'games': 'games', 'game': 'games', 'homebrew': 'homebrew', 'dashboards': 'homebrew',
             'emulators': 'emulators', 'apps': 'apps', 'applications': 'apps'}
    for folder in reversed(path.lower().split('\\')[1:-1]):
        if folder in hints:
            return hints[folder]
    return 'uncategorized'


def explicit_entry(item):
    label = item.get('label') or {}
    return bool(label.get('name') or label.get('mode') or label.get('favorite')
                or label.get('category', 'uncategorized') != 'uncategorized')


def display_name(path):
    """A folder hint is useful display text, never measured title identity."""
    parts = path.split('\\')
    filename = parts[-1]
    folders = [part for part in parts[1:-1] if part and part.lower() not in
               ('games', 'game', 'content', '00007000', '0000000000000000')
               and not re.fullmatch('[0-9A-Fa-f]{8,44}', part)]
    if filename.lower().endswith('.xex') and folders:
        return folders[-1]
    if filename.lower().endswith(('.iso', '.xex')):
        return filename.rsplit('.', 1)[0]
    return 'GOD candidate' if file_format(path) == 'god' else filename


def file_format(path):
    lower = path.lower()
    if lower.endswith('.xex'):
        return 'xex'
    if lower.endswith('.iso'):
        return 'iso'
    parts = lower.split('\\')
    if len(parts) >= 2 and parts[-2] == '00007000' and re.fullmatch('[0-9a-f]{40,44}', parts[-1]):
        return 'god'
    return 'unknown'


def inspection_snapshot(value):
    """Allowlist an actual server inspection; never persist review/launch status."""
    if (value.get('valid') is not True or type(value.get('plugin')) is not bool
            or type(value.get('size')) is not int or not 24 <= value['size'] <= 64 * 1024 * 1024
            or not isinstance(value.get('hash'), str) or not re.fullmatch('[0-9a-f]{64}', value['hash'])):
        raise ValueError('A measured XEX inspection is required.')
    source = value.get('metadata') if isinstance(value.get('metadata'), dict) else {}
    metadata = {}
    for key in HEX_FIELDS:
        item = source.get(key)
        if isinstance(item, str) and re.fullmatch('[0-9A-Fa-f]{8}', item):
            metadata[key] = item.upper()
    for key in ('disc', 'disc_count'):
        item = source.get(key)
        if type(item) is int and 0 <= item <= 255:
            metadata[key] = item
    return {'metadata': metadata, 'sha256': value['hash'], 'size': value['size'],
            'plugin': value['plugin'], 'inspected_at': time.time()}


def copy_identity(item):
    """Require full execution identity and filename; title ID alone is insufficient."""
    snapshot = item.get('inspection')
    if item['format'] != 'xex' or not snapshot or snapshot.get('plugin') is not False:
        return None
    metadata = snapshot.get('metadata', {})
    if any(not isinstance(metadata.get(key), str) or not re.fullmatch('[0-9A-F]{8}', metadata[key]) for key in HEX_FIELDS):
        return None
    if metadata['title_id'] == '00000000' or metadata['media_id'] == '00000000':
        return None
    disc, count = metadata.get('disc'), metadata.get('disc_count')
    if type(disc) is not int or type(count) is not int or not 1 <= disc <= count <= 255:
        return None
    # default.xex and default_mp.xex can describe distinct modes of one title.
    return '|'.join([item['path'].rsplit('\\', 1)[-1].lower(),
                     *(metadata[key] for key in HEX_FIELDS), str(disc), str(count)])


def group_files(files, titles):
    groups = {}
    for item in files:
        identity = copy_identity(item)
        key = ('identity:' + identity) if identity else ('path:' + item['path'].lower())
        if key not in groups:
            metadata = (item.get('inspection') or {}).get('metadata', {})
            title_id = metadata.get('title_id')
            cached = titles.get(title_id, {}) if title_id and title_id != '00000000' else {}
            label = item.get('label') or {}
            groups[key] = {'id': hashlib.sha256(key.encode()).hexdigest(),
                           'name': label.get('name') or cached.get('title') or display_name(item['path']),
                           'name_source': 'custom' if label.get('name') else ('aurora' if cached.get('source') == 'Aurora on-console metadata' else 'community') if cached.get('title') else 'folder',
                           'metadata_available': bool(cached.get('title')),
                           'categories': [], 'favorite': False,
                           'cover_title_id': title_id if cached.get('cover') else None, 'title_id': title_id,
                           'format': item['format'], 'identity': identity, 'paths': []}
        groups[key]['paths'].append(item['path'])
        label = item.get('label') or {}
        if label.get('name') and groups[key]['name_source'] != 'custom':
            groups[key].update(name=label['name'], name_source='custom')
        category = label.get('category', 'uncategorized')
        if category not in groups[key]['categories']:
            groups[key]['categories'].append(category)
        groups[key]['favorite'] |= label.get('favorite') is True
    return list(groups.values())


def deduplicate_items(items, files):
    """Choose display paths only; known names never establish byte identity or trust."""
    by_path = {item['path'].lower(): item for item in files}

    def preference(item):
        path = item['paths'][0].lower()
        # Prefer an observed HDD path, never construct a root or infer an alias mapping.
        return (path.split('\\', 1)[0] != 'hdd:', path.count('\\'), path)

    chosen = {}
    for item in sorted(items, key=preference):
        path = item['paths'][0].lower()
        primary = by_path[path]
        component = item['component']
        key = ('path', path)
        if component:
            # Keep distinct filename variants (for example RPC.xex and XRPC.xex).
            key = ('known-file', component['id'], path.rsplit('\\', 1)[-1])
        elif item['kind'] == 'installation' and item['format'] == 'xex' and 'games' in item['categories']:
            snapshot = primary.get('inspection') or {}
            digest = snapshot.get('sha256')
            if (snapshot.get('plugin') is False and isinstance(digest, str)
                    and re.fullmatch('[a-f0-9]{64}', digest)
                    and snapshot.get('size') == primary['size']):
                key = ('game-bytes', digest, primary['size'])
        if key not in chosen:
            chosen[key] = item
    return list(chosen.values())


def library_items(files, titles):
    """One display item per physical install, separate from the raw XEX inventory.

    Paths contain selected launch entries, never all package members. Folder/filename
    rules are hints, not proof of completeness, active use, trust or identical copies.
    """
    folders = {}
    standalone = []
    catalogue = load_components()[0]
    components = {}
    for item in files:
        plugin = (item.get('inspection') or {}).get('plugin') is True
        explicit = explicit_entry(item)
        if library_path_excluded(item['path']) and not explicit:
            continue
        component = classify_component(item['path'], item.get('inspection'), catalogue)
        if not library_collection(item['path']) and not component:
            continue
        components[item['path'].lower()] = component
        module_category = (component['category'] if component else (item.get('label') or {}).get('category')) if item['format'] == 'xex' else None
        if plugin or module_category in ('plugins', 'stealth') or item['format'] in ('iso', 'god'):
            kind = 'stealth' if module_category == 'stealth' else 'plugin' if plugin or module_category == 'plugins' else item['format']
            standalone.append((item, kind))
        elif item['format'] == 'xex':
            folder = item['path'].rsplit('\\', 1)[0].lower()
            if component and not install_folder(folder):
                standalone.append((item,'installation'))
            else:
                folders.setdefault(folder, []).append(item)

    # A container's lone helper is not an install when it holds child game folders.
    default_folders = {folder for folder, entries in folders.items()
                       if any(entry['path'].rsplit('\\', 1)[-1].lower() == 'default.xex' for entry in entries)}
    containers = set()
    for folder in default_folders:
        parts = folder.split('\\')
        containers.update('\\'.join(parts[:i]) for i in range(1, len(parts)))

    selected = []
    anchors = set()
    for folder, entries in sorted(folders.items(), key=lambda pair: (pair[0].count('\\'), pair[0])):
        chosen = [entry for entry in entries if explicit_entry(entry)]
        default = next((entry for entry in entries
                        if entry['path'].rsplit('\\', 1)[-1].lower() == 'default.xex'), None)
        parts = folder.split('\\')
        nested = any('\\'.join(parts[:i]) in anchors for i in range(1, len(parts)))
        plugin_folder = any(part in ('plugins', 'plugin') for part in parts[1:])
        if not plugin_folder and (not nested or disc_folder(folder)):
            known = next((entry for entry in entries if components.get(entry['path'].lower())), None)
            primary = default or known or (entries[0] if len(entries) == 1 and folder not in containers else None)
            if primary and primary not in chosen:
                chosen.insert(0, primary)
        if not chosen:
            continue
        # Prefer the normal launcher; explicitly selected alternates stay on the same card.
        if default in chosen:
            chosen.remove(default)
            chosen.insert(0, default)
        if install_folder(folder):
            anchors.add(folder)
        selected.append((chosen, 'installation', entries))

    selected.extend(([item], kind, [item]) for item, kind in standalone)
    result = []
    for entries, kind, members in selected:
        primary = entries[0]
        component = components.get(primary['path'].lower())
        card = group_files([primary], titles)[0]
        install = primary['path'].rsplit('\\', 1)[0]
        key = ('install:' + install.lower()) if kind == 'installation' and install_folder(install) else ('file:' + primary['path'].lower())
        card.update(id=hashlib.sha256(key.encode()).hexdigest(), kind=kind, install_path=install,
                    paths=[entry['path'] for entry in entries], auxiliary_count=len(members) - len(entries),
                    categories=[], component=component,
                    plugin_confirmed=(primary.get('inspection') or {}).get('plugin') is True,
                    favorite=any((entry.get('label') or {}).get('favorite') is True for entry in entries))
        for entry in entries:
            label = entry.get('label') or {}
            category = label.get('category', 'uncategorized')
            if category == 'uncategorized':
                category = (components.get(entry['path'].lower()) or {}).get('category') or library_collection(entry['path'])
            if category not in card['categories']:
                card['categories'].append(category)
        if component:
            label = primary.get('label') or {}
            card.update(name=label.get('name') or component['name'],
                        name_source='custom' if label.get('name') else 'known',
                        cover_title_id=None, metadata_available=True, categories=[component['category']])
        if kind in ('plugin', 'stealth'):
            label = primary.get('label') or {}
            card.update(name=label.get('name') or (component or {}).get('name') or primary['path'].rsplit('\\', 1)[-1].rsplit('.', 1)[0],
                        name_source='custom' if label.get('name') else 'known' if component else 'filename',
                        categories=['stealth' if kind == 'stealth' else 'plugins'],
                        cover_title_id=None, metadata_available=False)
        result.append(card)
    result = deduplicate_items(result, files)
    title_names = {}
    for card in result:
        title_names.setdefault(card['name'].casefold(), []).append(card)
    for cards in title_names.values():
        if len(cards) < 2:
            continue
        hints = [display_name(card['paths'][0]) for card in cards]
        hint_counts = Counter(hint.casefold() for hint in hints)
        seen_hints = set()
        for card, hint in zip(cards, hints):
            repeated = hint.casefold() in seen_hints
            seen_hints.add(hint.casefold())
            if hint_counts[hint.casefold()] > 1 and repeated:
                card['location_hint'] = card['paths'][0].split('\\', 1)[0]
            elif hint.casefold() != card['name'].casefold():
                card['location_hint'] = hint
    return sorted(result, key=lambda item: (item['name'].lower(), item['install_path'].lower(), item['id']))
