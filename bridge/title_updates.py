"""Bounded structural reading of a selected Xbox 360 title-update package."""
import hashlib
import tempfile
from pathlib import Path


MAX_TITLE_UPDATE = 128 * 1024 * 1024
HEADER_LEN = 0x1800


def _header_name(header, offset):
    raw = header[offset:offset + 0x80]
    end = next((index for index in range(0, len(raw), 2) if raw[index:index + 2] == b'\0\0'), len(raw))
    try:
        name = raw[:end].decode('utf-16-be')
    except UnicodeDecodeError:
        return None
    return name.strip() if name.isprintable() and name.strip() else None


def parse_title_update_header(header):
    """Read STFS fields only; this is not signature or payload validation."""
    if len(header) < HEADER_LEN or header[:4] not in (b'CON ', b'LIVE', b'PIRS'):
        raise ValueError('This file has no supported STFS header.')
    content_type = int.from_bytes(header[0x344:0x348], 'big')
    if content_type != 0x000B0000:
        raise ValueError('This STFS header is not a title update.')
    title_id = header[0x360:0x364].hex().upper()
    if title_id == '00000000':
        raise ValueError('The title-update header has no Title ID.')
    return {'magic': header[:4].decode('ascii').strip(),
            'content_type': '000B0000',
            'title_id': title_id,
            'media_id': header[0x354:0x358].hex().upper(),
            'version': header[0x358:0x35C].hex().upper(),
            'base_version': header[0x35C:0x360].hex().upper(),
            'display_name': _header_name(header, 0x411),
            'title_name': _header_name(header, 0x1691)}


def inspect_title_update(bridge, path, expected_size, game_title_id, game_media_id):
    if type(expected_size) is not int or not HEADER_LEN <= expected_size <= MAX_TITLE_UPDATE:
        raise ValueError('Title update is outside the 128 MiB inspection limit.')
    info = bridge.adapter('file-info', path=path)
    if info.get('directory') is not False or info.get('size') != expected_size:
        raise ValueError('Title-update file changed. Refresh its folder first.')
    with tempfile.TemporaryDirectory(prefix='nebulah-tu-') as folder:
        local = Path(folder) / 'package.bin'
        bridge.adapter('download-file', path=path, local=str(local), size=expected_size)
        if local.stat().st_size != expected_size:
            raise ValueError('Title-update download size changed.')
        digest = hashlib.sha256()
        with local.open('rb') as source:
            header = source.read(HEADER_LEN)
            metadata = parse_title_update_header(header)
            digest.update(header)
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
    title_id = metadata['title_id']
    media_id = metadata['media_id']
    if game_title_id and title_id != game_title_id.upper():
        assessment = 'different-title'
    elif game_title_id and game_media_id and game_media_id != '00000000' and media_id != '00000000':
        assessment = 'matching-media-id' if media_id == game_media_id.upper() else 'different-release'
    else:
        assessment = 'unknown'
    return {'path': path, 'size': expected_size, 'sha256': digest.hexdigest(),
            'header': metadata, 'assessment': assessment,
            'note': 'Structural header and Media ID comparison only; active state, signature and compatibility are unverified.'}
