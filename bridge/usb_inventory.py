"""Read-only allowlisted Windows USB disk and volume inventory."""
import json
import re
import subprocess
from runtime_paths import ROOT

SCRIPT = ROOT / 'bridge' / 'usb_inventory.ps1'


def inventory(data, runner=subprocess.run):
    if data:
        raise ValueError('USB inventory takes no options.')
    result = runner(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(SCRIPT)],
                    capture_output=True, timeout=15, check=False)
    if result.returncode or len(result.stdout) > 256 * 1024:
        raise ValueError('Windows USB inventory is unavailable. Check local disk access.')
    try:
        rows = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        raise ValueError('Windows USB inventory was incomplete.') from None
    if not isinstance(rows, list) or len(rows) > 32:
        raise ValueError('Windows USB inventory was invalid.')
    disks = []
    for row in rows:
        if not isinstance(row, dict) or type(row.get('number')) is not int or not 0 <= row['number'] < 256:
            raise ValueError('Windows USB disk identity was invalid.')
        size = row.get('bytes')
        if type(size) is not int or not 0 <= size <= 2**60:
            raise ValueError('Windows USB disk size was invalid.')
        volumes = []
        for volume in row.get('volumes', []):
            if not isinstance(volume, dict) or not re.fullmatch(r'[A-Z]', str(volume.get('letter', '')).upper()):
                continue
            total, free = volume.get('bytes'), volume.get('free_bytes')
            if type(total) is not int or type(free) is not int or not 0 <= free <= total <= size:
                continue
            volumes.append({'letter': volume['letter'].upper() + ':',
                            'label': str(volume.get('label') or '')[:80],
                            'filesystem': str(volume.get('filesystem') or '')[:24],
                            'bytes': total, 'free_bytes': free,
                            'health': str(volume.get('health') or '')[:24]})
        disks.append({'number': row['number'], 'model': str(row.get('model') or 'USB disk')[:100],
                      'bytes': size, 'partition_style': str(row.get('partition_style') or '')[:24],
                      'operational_status': str(row.get('operational_status') or '')[:24],
                      'system': row.get('system') is True, 'boot': row.get('boot') is True,
                      'read_only': row.get('read_only') is True, 'volumes': volumes})
    return {'source': 'windows-storage', 'disks': disks}
