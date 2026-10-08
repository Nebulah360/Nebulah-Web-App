"""Offline component hints. Neither filenames nor observed public hashes grant trust."""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from runtime_paths import ROOT

DEFAULT_COMPONENTS = ROOT / 'registry/components.json'
LIBRARY_FOLDERS = {'games': 'games', 'plugins': 'plugins', 'homebrew': 'homebrew',
                   'apps': 'apps', 'emulators': 'emulators'}
COMPONENT_CATEGORIES = frozenset(('homebrew', 'apps', 'emulators', 'plugins', 'stealth'))


class ComponentCatalogError(ValueError):
    pass


def source_url(value):
    if not isinstance(value, str) or len(value) > 1024 or re.search(r'[\x00-\x20]', value):
        return False
    url = urlsplit(value)
    return url.scheme == 'https' and bool(url.hostname) and not url.username and not url.password and not url.fragment


def load_components(path=DEFAULT_COMPONENTS):
    try:
        raw = Path(path).read_bytes()
        if len(raw) > 256 * 1024:
            raise ComponentCatalogError('Component catalogue too large.')
        data = json.loads(raw)
        if data.get('schema_version') != 1 or not isinstance(data.get('components'), list) or len(data['components']) > 200:
            raise ComponentCatalogError('Invalid component catalogue.')
        ids = set()
        for item in data['components']:
            ident = item.get('id')
            if not isinstance(ident, str) or not re.fullmatch('[a-z0-9][a-z0-9-]{0,79}', ident) or ident in ids:
                raise ComponentCatalogError('Invalid component ID.')
            ids.add(ident)
            if item.get('category') not in COMPONENT_CATEGORIES or not isinstance(item.get('name'), str) or not 1 <= len(item['name']) <= 128 or re.search(r'[\x00-\x1f]', item['name']):
                raise ComponentCatalogError('Invalid component display fields.')
            for field in ('filenames', 'folders', 'launchers'):
                values = item.get(field)
                if not isinstance(values, list) or len(values) > 32 or any(not isinstance(value, str) or not 1 <= len(value) <= 128 or re.search(r'[\\/:*?"<>|\x00-\x1f]', value) for value in values):
                    raise ComponentCatalogError('Invalid component aliases.')
                if field != 'folders' and any(not value.lower().endswith('.xex') for value in values):
                    raise ComponentCatalogError('Component aliases must name XEX files.')
            if not item.get('sources') or not isinstance(item['sources'], list) or any(not source_url(url) for url in item['sources']):
                raise ComponentCatalogError('Component source evidence required.')
            if 'trusted' in item or 'reviewed' in item:
                raise ComponentCatalogError('Classification entries cannot grant trust.')
        hashes = data.get('observed_hashes')
        if not isinstance(hashes, list) or len(hashes) > 1000:
            raise ComponentCatalogError('Invalid component hash observations.')
        for entry in hashes:
            if (entry.get('component_id') not in ids or not re.fullmatch('[a-f0-9]{64}', entry.get('sha256', ''))
                    or type(entry.get('size')) is not int or not 24 <= entry['size'] <= 64 * 1024 * 1024
                    or type(entry.get('plugin')) is not bool or entry.get('state') != 'observed'
                    or entry.get('reviewed') is not False or entry.get('hardware_tested') is not False
                    or not source_url(entry.get('source_url')) or not entry.get('evidence')):
                raise ComponentCatalogError('Observed hashes cannot grant trust.')
        return data, hashlib.sha256(raw).hexdigest()
    except ComponentCatalogError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise ComponentCatalogError('Component catalogue unavailable or malformed.') from error


def library_collection(path):
    parts = path.rstrip('\\').lower().split('\\')
    return LIBRARY_FOLDERS.get(parts[1]) if len(parts) > 1 else None


def classify_component(path, inspection=None, catalog=None):
    data = catalog if catalog is not None else load_components()[0]
    parts = path.rstrip('\\').split('\\')
    filename = parts[-1].lower()
    measured = inspection or {}
    digest = measured.get('sha256') or measured.get('hash')
    observed = next((entry for entry in data['observed_hashes']
                     if entry['sha256'] == digest and entry['size'] == measured.get('size')
                     and entry['plugin'] == measured.get('plugin')), None)
    match = next((item for item in data['components'] if observed and item['id'] == observed['component_id']), None)
    basis = 'observed-hash' if match else None
    if not match:
        match = next((item for item in data['components'] if filename in [alias.lower() for alias in item['filenames']]), None)
        basis = 'filename' if match else None
    if not match:
        match = next((item for item in data['components']
                      if filename in [alias.lower() for alias in item['launchers']]
                      and len(parts)>2 and parts[-2].lower() in [alias.lower() for alias in item['folders']]), None)
        basis = 'folder' if match else None
    if not match:
        return None
    category = match['category']
    if measured.get('plugin') is True and category not in ('plugins', 'stealth'):
        category = 'plugins'
    return {'id': match['id'], 'name': match['name'], 'category': category, 'basis': basis,
            'sources': match['sources'], 'observed_hash_match': bool(observed),
            'reviewed': False, 'note': 'Classification only; no reviewed trust or compatibility is established.'}
