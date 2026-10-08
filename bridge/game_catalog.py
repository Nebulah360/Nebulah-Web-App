"""Reviewed game-file baselines, separate from source-build provenance."""
import base64
import hashlib
import json
import re
from pathlib import Path
from runtime_paths import ROOT

CATALOG = ROOT / 'registry' / 'games.json'


def load_games(path=None):
    path = Path(path or CATALOG)
    raw = path.read_bytes()
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError('Game catalog exceeds size limit.')
    catalog = json.loads(raw)
    return validate_game_builds(catalog), hashlib.sha256(raw).hexdigest()


def validate_game_builds(catalog):
    """Validate an in-memory catalog too, so proposals use the same contract."""
    if not isinstance(catalog, dict) or catalog.get('schema_version') != 1 or not isinstance(catalog.get('builds'), list):
        raise ValueError('Invalid game catalog.')
    seen = set()
    for b in catalog['builds']:
        if not isinstance(b, dict):raise ValueError('Invalid game build.')
        for k in ('id', 'title', 'filename', 'provenance'):
            if not isinstance(b.get(k), str) or not b[k].strip() or len(b[k]) > 1024 or re.search(r'[\x00-\x1f\x7f]', b[k]):
                raise ValueError('Invalid game metadata.')
        if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,127}', b['id']) or b['id'] in seen:raise ValueError('Invalid or duplicate game build ID.')
        seen.add(b['id'])
        if not re.fullmatch(r'[^\\/:*?"<>|]+\.xex', b['filename'], re.I):raise ValueError('Invalid filename.')
        for k in ('title_id', 'media_id', 'version', 'base_version'):
            if not isinstance(b.get(k), str) or not re.fullmatch('[0-9A-F]{8}', b[k]):raise ValueError('Invalid game identity.')
        if not isinstance(b.get('sha256'), str) or not re.fullmatch('[a-f0-9]{64}', b['sha256']):raise ValueError('Invalid game hash.')
        if type(b.get('size')) is not int or not 24 <= b['size'] <= 64*1024*1024:raise ValueError('Invalid game size.')
        if b.get('state') not in ('candidate', 'reviewed', 'revoked'):raise ValueError('Invalid review state.')
        if b['state'] == 'reviewed':
            review = b.get('review', {})
            if b.get('unmodified') is not True or not isinstance(review, dict) or any(not isinstance(review.get(k),str) or not review[k].strip() for k in ('reviewer','date','evidence','hardware_test')):
                raise ValueError('Reviewed baselines require unmodified provenance and review evidence.')
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',review['date']):raise ValueError('Invalid review date.')
        if b['state'] == 'revoked' and not b.get('revocation_reason'):raise ValueError('Revocation needs a reason.')
        cover = b.get('cover')
        if cover is not None:
            if not isinstance(cover,str) or not re.fullmatch(r'data:image/(png|jpeg);base64,[A-Za-z0-9+/=]+',cover):raise ValueError('Use embedded PNG/JPEG artwork.')
            data=base64.b64decode(cover.split(',',1)[1],validate=True)
            if len(data)>512*1024 or not (data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff')):raise ValueError('Invalid artwork.')
    return catalog['builds']


def candidate_from_inspection(v, filename, title, provenance, build_id=None):
    """Export measured identity only; a hash never grants review or trust."""
    if not isinstance(v, dict) or v.get('valid') is not True or v.get('plugin') is not False:
        raise ValueError('Inspect a non-plugin XEX before proposing a game baseline.')
    metadata = v.get('metadata')
    if not isinstance(metadata, dict):
        raise ValueError('Game execution metadata is required.')
    candidate = {k:metadata.get(k) for k in ('title_id', 'media_id', 'version', 'base_version')}
    candidate.update(id='candidate', filename=filename, title=title, provenance=provenance,
                     sha256=v.get('hash'), size=v.get('size'), state='candidate', unmodified=False)
    # Validate before normalizing or deriving an ID; never invent missing fields.
    validate_game_builds({'schema_version':1, 'builds':[candidate]})
    candidate['title'] = title.strip()
    candidate['provenance'] = provenance.strip()
    identity = [filename.lower(), *[candidate[k] for k in ('title_id', 'media_id', 'version', 'base_version', 'sha256', 'size')]]
    digest = hashlib.sha256(json.dumps(identity, separators=(',', ':')).encode()).hexdigest()
    candidate['id'] = build_id if build_id is not None else 'game-' + candidate['title_id'].lower() + '-' + digest[:32]
    validate_game_builds({'schema_version':1, 'builds':[candidate]})
    return candidate


def verify_game(v, filename, path=None):
    builds, revision = load_games(path)
    identity=v.get('metadata') or {}
    keys=('title_id','media_id','version','base_version')
    same=[b for b in builds if b['filename'].lower()==filename.lower() and all(b[k]==identity.get(k) for k in keys)]
    result={'status':'unknown','label':'No reviewed baseline','actual_sha256':v['hash'],'actual_size':v['size'], 'catalog_revision':revision,'metadata':identity,'references':[], 'game':None}
    # A revoked byte hash is rejected even if the caller uses a different filename.
    if any(b['state']=='revoked' and b['sha256']==v['hash'] for b in builds):
        result.update(status='revoked',label='Revoked file');return result
    reviewed=[b for b in same if b['state']=='reviewed']
    result['references']=[{k:b[k] for k in ('id','sha256','size','provenance','review')} for b in reviewed]
    exact=[b for b in reviewed if b['sha256']==v['hash'] and b['size']==v['size']]
    if exact:
        result.update(status='verified',label='Matches reviewed unmodified build')
    elif reviewed:
        result.update(status='mismatch',label='Differs from reviewed unmodified build')
    elif same:
        result.update(label='Reference has not been reviewed')
    metadata_source=(exact or reviewed or same)
    if metadata_source:
        b=metadata_source[0]
        result['game']={'title':b['title'],'cover':b.get('cover'),'source':'Local game catalog','build_id':b['id']}
    return result


def capabilities():
    return {key:{'available':False,'reason':reason} for key,reason in {
        'trainers':'No tested trainer adapter is installed. Trainer XEX files are not launched as games.',
        'title_updates':'Title-update discovery and activation adapter is not implemented. Installed/active TU is unknown.',
        'gsc':'No tested game/version-specific GSC adapter is installed. Applicability is unknown.'
    }.items()}
