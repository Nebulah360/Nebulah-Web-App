"""Offline reviewed-build catalog. Digest identity is not a safety guarantee."""
import hashlib, json, re
from pathlib import Path
from runtime_paths import ROOT

DEFAULT_CATALOG=ROOT/'registry/catalog.json'
class RegistryError(ValueError):pass

def text(value,limit=512):
    return isinstance(value,str) and 0<len(value)<=limit and not re.search(r'[\x00-\x1f]',value)

def load_catalog(path=DEFAULT_CATALOG):
    try:
        path=Path(path)
        if path.stat().st_size>4*1024*1024:raise RegistryError('Catalog too large.')
        raw=path.read_bytes();catalog=json.loads(raw)
        if not isinstance(catalog,dict) or catalog.get('schema_version')!=1 or not isinstance(catalog.get('builds'),list):raise RegistryError('Invalid catalog format.')
        if len(catalog['builds'])>10000:raise RegistryError('Catalog entry limit exceeded.')
        seen=set()
        for b in catalog['builds']:
            if not isinstance(b,dict):raise RegistryError('Invalid build.')
            for key in ('id','project','version','filename','repository','commit','sha256','state'):
                if not text(b.get(key)):raise RegistryError('Missing or invalid build field: '+key)
            if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,127}',b['id']) or b['id'] in seen:raise RegistryError('Invalid or duplicate build id.')
            seen.add(b['id'])
            if not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',b['repository']):raise RegistryError('Use a canonical GitHub repository URL.')
            if not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}',b['commit']):raise RegistryError('Source must be pinned to a full commit.')
            if not re.fullmatch(r'[a-f0-9]{64}',b['sha256']):raise RegistryError('Invalid SHA-256.')
            if not re.fullmatch(r'[^\\/:*?"<>|]+\.xex',b['filename'],re.I):raise RegistryError('Invalid XEX filename.')
            if type(b.get('size')) is not int or not 24<=b['size']<=64*1024*1024:raise RegistryError('Invalid executable size.')
            if b['state'] not in ('candidate','reviewed','revoked'):raise RegistryError('Invalid review state.')
            review=b.get('review')
            if b['state']=='reviewed':
                if not isinstance(review,dict) or any(not text(review.get(k),2048) for k in ('reviewer','date','evidence','hardware_test')):raise RegistryError('Reviewed builds require review and hardware evidence.')
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',review['date']):raise RegistryError('Invalid review date.')
            if b['state']=='revoked' and not text(b.get('revocation_reason'),2048):raise RegistryError('Revocation requires a reason.')
        return catalog,hashlib.sha256(raw).hexdigest()
    except RegistryError:raise
    except (OSError,ValueError,TypeError,KeyError) as e:raise RegistryError('Catalog unavailable or malformed.') from e

def public_build(b):
    keys=('id','project','version','filename','repository','commit','sha256','size','state','review','revocation_reason')
    return {k:b[k] for k in keys if k in b}

def verify_digest(digest,size,expected_id=None,path=DEFAULT_CATALOG):
    if not isinstance(digest,str) or not re.fullmatch(r'[a-fA-F0-9]{64}',digest):raise ValueError('A SHA-256 digest is required.')
    if type(size) is not int or size<0:raise ValueError('A byte size is required.')
    if expected_id is not None and (not isinstance(expected_id,str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,127}',expected_id)):raise ValueError('Invalid expected build id.')
    digest=digest.lower();catalog,revision=load_catalog(path);builds=catalog['builds']
    same_hash=[b for b in builds if b['sha256']==digest]
    expected=next((b for b in builds if b['id']==expected_id),None)
    result={'status':'unknown','actual_sha256':digest,'actual_size':size,'expected':public_build(expected) if expected else None,
            'matches':[public_build(b) for b in same_hash],'discrepancies':[],'catalog_revision':revision,'eligible_for_install':False}
    revoked=[b for b in same_hash if b['state']=='revoked']
    if revoked:
        result['status']='revoked';result['discrepancies']=[b['revocation_reason'] for b in revoked];return result
    if expected_id is not None and expected is None:
        result['status']='unknown-build';result['discrepancies']=['Requested build id is not in this catalog.'];return result
    if expected:
        if expected['state']=='revoked':result['status']='revoked';result['discrepancies']=[expected['revocation_reason']];return result
        if expected['sha256']!=digest:result['discrepancies'].append('SHA-256 differs from the selected build.')
        if expected['size']!=size:result['discrepancies'].append('File size differs from the selected build.')
        if result['discrepancies']:result['status']='mismatch';return result
        candidates=[expected]
    else:candidates=[b for b in same_hash if b['size']==size]
    if candidates:
        reviewed=any(b['state']=='reviewed' for b in candidates)
        result['status']='reviewed-match' if reviewed else 'candidate-match'
        # Repository installs must select an explicit release/build, not just any matching binary.
        result['eligible_for_install']=reviewed and expected is not None
    elif same_hash:
        result['status']='mismatch';result['discrepancies']=['Reported size differs from catalog entries.']
    return result
