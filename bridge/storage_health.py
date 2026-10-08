"""Read-only health and exact-byte comparison of saved console observations."""
import re

from diagnostics import BridgeDiagnostic


def storage_health(bridge, files):
    """Probe discovered roots; never treat an unavailable root as an empty one."""
    current = {root.lower(): root for root in bridge.drives}
    saved = {}
    copies = {}
    for item in files:
        path = item['path']
        match = re.match(r'^([A-Za-z0-9_]+:\\)', path)
        if not match:
            continue
        root = match.group(1)
        state = saved.setdefault(root.lower(), {'root': root, 'saved_count': 0,
                                                'last_scanned': 0})
        state['saved_count'] += 1
        state['last_scanned'] = max(state['last_scanned'], item.get('scanned') or 0)
        inspection = item.get('inspection') or {}
        digest = inspection.get('sha256')
        if (path.lower().endswith('.xex') and isinstance(digest, str)
                and re.fullmatch('[a-f0-9]{64}', digest)
                and inspection.get('size') == item.get('size')):
            copies.setdefault((digest, item['size']), []).append(path)

    roots = []
    for key in sorted(set(current) | set(saved)):
        record = saved.get(key, {'saved_count': 0, 'last_scanned': 0})
        root = current.get(key, record.get('root'))
        health = 'unavailable'
        if key in current:
            try:
                bridge.dispatch('browse', {'path': root})
            except BridgeDiagnostic as error:
                if error.code != 'STORAGE_BROWSE_FAILED':
                    raise
                health = 'unreadable'
            else:
                health = 'available'
        roots.append({'root': root, 'state': health,
                      'saved_count': record['saved_count'],
                      'last_scanned': record['last_scanned']})

    duplicates = []
    for (digest, size), paths in copies.items():
        distinct = sorted(set(paths), key=str.lower)
        if len(distinct) > 1:
            duplicates.append({'sha256': digest, 'size': size, 'paths': distinct[:16],
                               'more_paths': len(distinct) > 16})
    duplicates.sort(key=lambda item: item['paths'][0].lower())
    return {'roots': roots, 'matching_xex': duplicates[:100],
            'incomplete': len(duplicates) > 100,
            'note': 'Saved XEX hashes compare launcher bytes only. No files are removed.'}
