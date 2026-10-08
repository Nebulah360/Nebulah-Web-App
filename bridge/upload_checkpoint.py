"""Check host-staged executable bytes before a manual console upload."""
import hashlib
from pathlib import Path

from component_catalog import classify_component
from game_catalog import verify_game
from hash_registry import verify_digest


def check_staged_file(local_path, destination, size, expected_hash, build_id=None):
    digest = hashlib.sha256()
    with open(local_path, 'rb') as staged:
        magic = staged.read(4)
        staged.seek(0)
        count = 0
        for chunk in iter(lambda: staged.read(1024 * 1024), b''):
            count += len(chunk)
            digest.update(chunk)
    if count != size or digest.hexdigest() != expected_hash:
        raise ValueError('Staged upload bytes changed; nothing will be finalized.')
    executable = destination.lower().endswith(('.xex', '.dll')) or magic == b'XEX2'
    if not executable:
        if build_id is not None:
            raise ValueError('A selected executable build requires an XEX file.')
        return None
    if size > 64 * 1024 * 1024:
        raise ValueError('Executable inspection limit is 64 MiB.')
    # Import at call time: the server owns structural XEX inspection.
    from server import validate_xex
    inspected = validate_xex(Path(local_path).read_bytes(), allow_module=True)
    if inspected['hash'] != expected_hash or inspected['size'] != size:
        raise ValueError('Staged executable bytes changed during inspection.')
    registry = verify_digest(inspected['hash'], size, build_id)
    game = verify_game(inspected, destination.rsplit('\\', 1)[-1])
    if registry['status'] in ('revoked', 'mismatch', 'unknown-build', 'registry-error'):
        raise ValueError('Executable upload blocked: ' + registry['status'] + '.')
    if game['status'] in ('revoked', 'mismatch', 'catalog-error'):
        raise ValueError('Executable upload blocked by game baseline: ' + game['status'] + '.')
    component = classify_component(destination, inspected)
    return {'sha256': inspected['hash'], 'size': size, 'plugin': inspected['plugin'],
            'component': component, 'registry': registry,
            'game_status': game['status'], 'game_catalog_revision': game['catalog_revision'],
            'note': 'Structural inspection and digest matching do not prove safety, publisher authenticity or console compatibility. Upload does not load or launch this file.'}
