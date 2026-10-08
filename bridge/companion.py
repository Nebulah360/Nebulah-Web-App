"""Local companion workspace. Display metadata never grants executable trust."""
from database import open_database
import base64, hashlib, json, re, secrets, sqlite3, time, urllib.request, urllib.error, tempfile
from collections import deque
from pathlib import Path
from repositories import NoRedirect
from diagnostics import BridgeDiagnostic
from game_paths import validate_game_mode
from game_data import write_game_data
from game_library import (CATEGORIES, file_format, inspection_snapshot, group_files,
                          library_items, library_path_excluded, library_alias_roots,
                          disc_folder, install_folder)
from component_catalog import classify_component, library_collection, load_components
from upload_checkpoint import check_staged_file
from runtime_paths import ROOT

class CompanionError(ValueError):
    """Fixed user-facing validation errors; never raw COM output."""

class TransferFailure(CompanionError):
    def __init__(self, message, diagnostic, recovery_required):
        super().__init__(message)
        self.diagnostic=diagnostic
        self.recovery_required=recovery_required
    def payload(self):
        return {'error':str(self), 'diagnostic':self.diagnostic, 'recovery_required':self.recovery_required}

DEFAULT_DB=ROOT/'.local/companion.sqlite3'
CHUNK=64*1024
MAX_TRANSFER=128*1024*1024
MAX_UPLOAD_NAME=32
MAX_TITLE_NAMES=2000
MAX_TITLE_COVERS=200

def console_upload_filename(name):
    """Keep new console filenames short and unambiguous for Neighborhood reads."""
    if not isinstance(name,str) or not name or len(name)>255 or name in ('.','..') or re.search(r'[\\/\x00-\x1f]',name):
        raise CompanionError('Choose a filename without path separators or control characters.')
    stem,dot,extension=name.rpartition('.')
    if not stem or not re.fullmatch(r'[A-Za-z0-9]{1,8}',extension):
        stem,extension=name,''
    stem=re.sub(r'[^A-Za-z0-9_-]+','_',stem).strip('_-')
    digest=hashlib.sha256(name.encode('utf-8')).hexdigest()[:6]
    if not stem:stem='file_'+digest
    suffix='.'+extension if extension else ''
    if len(stem)+len(suffix)>MAX_UPLOAD_NAME:
        stem=(stem[:MAX_UPLOAD_NAME-len(suffix)-7].rstrip('_-') or 'file')+'_'+digest
    return stem+suffix

def text(value,limit=128):
    if not isinstance(value,str) or not value.strip() or len(value)>limit or re.search(r'[\x00-\x1f]',value):raise CompanionError('Invalid text.')
    return value.strip()

def remote_bytes(path,limit):
    # Paths are constructed here from validated title IDs, never from remote URLs.
    url='https://raw.githubusercontent.com/xenia-manager/x360db/main/'+path
    request=urllib.request.Request(url,headers={'User-Agent':'Nebulah-Link'})
    with urllib.request.build_opener(NoRedirect).open(request,timeout=6) as response:
        data=response.read(limit+1)
    if len(data)>limit:raise CompanionError('Metadata response too large.')
    return data

class Workspace:
    def __init__(self,path=None):
        self.path=Path(path or DEFAULT_DB);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY,name TEXT NOT NULL,target TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS favorites (target TEXT,path TEXT,name TEXT,directory INTEGER,PRIMARY KEY(target,path));
            CREATE TABLE IF NOT EXISTS recent (target TEXT,path TEXT,launched REAL,state TEXT,PRIMARY KEY(target,path));
            CREATE TABLE IF NOT EXISTS library (target TEXT,path TEXT,size INTEGER,scanned REAL,PRIMARY KEY(target,path));
            CREATE INDEX IF NOT EXISTS library_case_path ON library(target,path COLLATE NOCASE);
            CREATE TABLE IF NOT EXISTS library_inspections (target TEXT,path TEXT COLLATE NOCASE,size INTEGER,data TEXT,PRIMARY KEY(target,path));
            CREATE TABLE IF NOT EXISTS library_labels (target TEXT,path TEXT COLLATE NOCASE,name TEXT,category TEXT,mode TEXT,favorite INTEGER,PRIMARY KEY(target,path));
            CREATE TABLE IF NOT EXISTS titles (id TEXT PRIMARY KEY,data TEXT,updated REAL);
            CREATE TABLE IF NOT EXISTS candidates (id TEXT PRIMARY KEY,data TEXT,updated REAL);
            CREATE TABLE IF NOT EXISTS companion_runs (target TEXT,path TEXT COLLATE NOCASE,sha256 TEXT,size INTEGER,PRIMARY KEY(target,path));
            ''')
            if 'mode' not in {row[1] for row in db.execute('PRAGMA table_info(favorites)')}:
                db.execute("ALTER TABLE favorites ADD COLUMN mode TEXT NOT NULL DEFAULT ''")
        self.sync_game_data()
    def sync_game_data(self):
        return write_game_data(self.path.parent, workspace=self.path.name)
    def save_candidate(self,candidate):
        from game_catalog import validate_game_builds
        validate_game_builds({'schema_version':1,'builds':[candidate]})
        if candidate.get('state')!='candidate' or candidate.get('unmodified') is not False:
            raise CompanionError('Only unreviewed candidates may be saved here.')
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO candidates VALUES(?,?,?)',(candidate['id'],json.dumps(candidate),time.time()))
        self.sync_game_data()
    def db(self):
        return open_database(self.path)
    def companion_run_add(self,target,path,sha256,size):
        if (not isinstance(target,str) or not target or not re.fullmatch(r'[A-Za-z0-9_.-]{1,253}',target) or
                not isinstance(path,str) or not re.search(r'\\NebulahCompanion-[0-9a-f]{16}\.xex$',path,re.I) or
                not re.fullmatch(r'[0-9a-f]{64}',sha256) or not 24<=size<=64*1024*1024):
            raise ValueError('Invalid temporary Companion file identity.')
        with self.db() as db:db.execute('INSERT INTO companion_runs VALUES(?,?,?,?)',(target.lower(),path,sha256,size))
    def companion_runs(self,target):
        with self.db() as db:return [dict(row) for row in db.execute('SELECT path,sha256,size FROM companion_runs WHERE target=?',(target.lower(),))]
    def companion_run_remove(self,target,path):
        with self.db() as db:db.execute('DELETE FROM companion_runs WHERE target=? AND path=?',(target.lower(),path))
    def profiles(self):
        with self.db() as db:return [dict(r) for r in db.execute('SELECT * FROM profiles ORDER BY name COLLATE NOCASE')]
    def profile_save(self,data):
        name=text(data.get('name'),80);target=data.get('target')
        if not isinstance(target,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,253}',target):raise CompanionError('Profiles require an explicit console name or IP.')
        ident=data.get('id') or secrets.token_hex(12)
        if not re.fullmatch('[a-f0-9]{24}',ident):raise CompanionError('Invalid profile.')
        with self.db() as db:
            if db.execute('SELECT count(*) FROM profiles').fetchone()[0]>=32 and not db.execute('SELECT 1 FROM profiles WHERE id=?',(ident,)).fetchone():raise CompanionError('Profile limit reached.')
            db.execute('INSERT OR REPLACE INTO profiles VALUES(?,?,?)',(ident,name,target))
        self.sync_game_data()
        return {'saved':True}
    def profile_remove(self,ident):
        with self.db() as db:db.execute('DELETE FROM profiles WHERE id=?',(text(ident),))
        self.sync_game_data()
        return {'removed':True}
    def list(self,table,target):
        if table not in ('favorites','recent','library'):raise CompanionError('Invalid collection.')
        order={'favorites':'name COLLATE NOCASE','recent':'launched DESC','library':'path COLLATE NOCASE'}[table]
        with self.db() as db:return [dict(r) for r in db.execute(f'SELECT * FROM {table} WHERE target=? ORDER BY {order} LIMIT 2000',(target.lower(),))]
    def favorite(self,target,path,name,directory,mode=""):
        mode=validate_game_mode(mode)
        if mode and (directory or not path.lower().endswith(".xex")):raise CompanionError("Choose an XEX before assigning a game mode.")
        with self.db() as db:
            existing=db.execute('SELECT 1 FROM favorites WHERE target=? AND path=? COLLATE NOCASE',(target.lower(),path)).fetchone()
            if not existing and db.execute('SELECT count(*) FROM favorites WHERE target=?',(target.lower(),)).fetchone()[0]>=200:raise CompanionError('Favorite limit reached.')
            db.execute('DELETE FROM favorites WHERE target=? AND path=? COLLATE NOCASE',(target.lower(),path))
            db.execute('INSERT OR REPLACE INTO favorites(target,path,name,directory,mode) VALUES(?,?,?,?,?)',(target.lower(),path,text(name,128),int(directory),mode))
        self.sync_game_data()
        return {'saved':True}
    def remove_favorite(self,target,path):
        with self.db() as db:db.execute('DELETE FROM favorites WHERE target=? AND path=? COLLATE NOCASE',(target.lower(),path))
        self.sync_game_data()
        return {'removed':True}
    def record_launch(self,target,path,state='accepted'):
        with self.db() as db:
            db.execute('DELETE FROM recent WHERE target=? AND path=? COLLATE NOCASE',(target.lower(),path))
            db.execute('INSERT INTO recent VALUES(?,?,?,?)',(target.lower(),path,time.time(),state))
            db.execute('DELETE FROM recent WHERE target=? AND path NOT IN (SELECT path FROM recent WHERE target=? ORDER BY launched DESC LIMIT 30)',(target.lower(),target.lower()))
        self.sync_game_data()
    def update_launch(self,target,path,state):
        with self.db() as db:db.execute('UPDATE recent SET state=? WHERE target=? AND path=? COLLATE NOCASE',(state,target.lower(),path))
        self.sync_game_data()
    def record_file(self,target,path,size):
        self.record_files(target,[(path,size)])
    def record_files(self,target,files):
        if not files:return
        scanned=time.time()
        rows=[(target.lower(),path,size,scanned) for path,size in files]
        with self.db() as db:
            # Neighborhood paths are case-insensitive. Preserve a matching observation
            # across rescans, but invalidate it if the listed size changes.
            for row in rows:
                db.execute('DELETE FROM library WHERE target=? AND path=? COLLATE NOCASE',row[:2])
                db.execute('INSERT INTO library(target,path,size,scanned) VALUES(?,?,?,?)',row)
            self.trim_library(db,target.lower())
        self.sync_game_data()
    def trim_library(self,db,target):
        db.execute('DELETE FROM library WHERE target=? AND path NOT IN (SELECT path FROM library WHERE target=? ORDER BY scanned DESC, rowid DESC LIMIT 2000)',(target,target))
        db.execute('DELETE FROM library_inspections WHERE target=? AND NOT EXISTS (SELECT 1 FROM library WHERE library.target=library_inspections.target AND library.path=library_inspections.path COLLATE NOCASE AND library.size=library_inspections.size)',(target,))
        db.execute('DELETE FROM library_labels WHERE target=? AND NOT EXISTS (SELECT 1 FROM library WHERE library.target=library_labels.target AND library.path=library_labels.path COLLATE NOCASE)',(target,))
    def record_inspection(self,target,path,value):
        if file_format(path)!='xex':raise CompanionError('Only XEX inspection metadata may be saved.')
        snapshot=inspection_snapshot(value)
        target=target.lower()
        with self.db() as db:
            db.execute('DELETE FROM library WHERE target=? AND path=? COLLATE NOCASE',(target,path))
            db.execute('INSERT INTO library(target,path,size,scanned) VALUES(?,?,?,?)',(target,path,snapshot['size'],snapshot['inspected_at']))
            db.execute('INSERT OR REPLACE INTO library_inspections VALUES(?,?,?,?)',(target,path,snapshot['size'],json.dumps(snapshot)))
            self.trim_library(db,target)
        self.sync_game_data()
    def remove_inspected_plugin(self,target,path,sha256):
        # Remove only the saved card; no Neighborhood operation is involved.
        target=target.lower()
        with self.db() as db:
            row=db.execute('SELECT i.data FROM library_inspections i JOIN library l ON l.target=i.target AND l.path=i.path COLLATE NOCASE AND l.size=i.size WHERE i.target=? AND i.path=? COLLATE NOCASE',(target,path)).fetchone()
            snapshot=json.loads(row['data']) if row else None
            if not snapshot or snapshot.get('plugin') is not True or snapshot.get('sha256')!=sha256:
                raise CompanionError('Inspected plugin entry changed. Refresh and try again.')
            db.execute('DELETE FROM library WHERE target=? AND path=? COLLATE NOCASE',(target,path))
            db.execute('DELETE FROM library_inspections WHERE target=? AND path=? COLLATE NOCASE',(target,path))
            db.execute('DELETE FROM library_labels WHERE target=? AND path=? COLLATE NOCASE',(target,path))
        self.sync_game_data()
        return {'removed':True}
    def library(self,target,view='files',root=None,excluded_roots=()):
        # Saved data only: listing never probes the console or fetches online art.
        if view not in ('files','installs'):raise CompanionError('Choose file inventory or physical installs.')
        if root is not None and (not isinstance(root,str) or not re.fullmatch(r'[A-Za-z0-9_]+:\\',root)):
            raise CompanionError('Choose a storage root for the library.')
        with self.db() as db:
            rows=db.execute('SELECT l.*,i.data AS inspection FROM library l LEFT JOIN library_inspections i ON l.target=i.target AND l.path=i.path COLLATE NOCASE AND l.size=i.size WHERE l.target=? ORDER BY l.scanned DESC,l.rowid DESC LIMIT 2000',(target.lower(),)).fetchall()
            titles={row['id']:json.loads(row['data']) for row in db.execute('SELECT id,data FROM titles')}
            labels={row['path'].lower():dict(row) for row in db.execute('SELECT path,name,category,mode,favorite FROM library_labels WHERE target=?',(target.lower(),))}
            recent={row['path'].lower():dict(row) for row in db.execute('SELECT path,launched,state FROM recent WHERE target=?',(target.lower(),))}
        files=[];seen=set()
        for row in rows:
            item=dict(row);key=item['path'].lower()
            if root is not None and not key.startswith(root.lower()):continue
            if view=='installs' and any(key.startswith(alias) for alias in excluded_roots):continue
            if key in seen:continue
            seen.add(key)
            item['format']=file_format(item['path'])
            item['inspection']=json.loads(item['inspection']) if item['inspection'] else None
            if key in labels:
                label=labels[key]
                item['label']={field:label[field] for field in ('name','category','mode')}|{'favorite':bool(label['favorite'])}
            if key in recent:item['last_launch']={field:recent[key][field] for field in ('launched','state')}
            files.append(item)
        files.sort(key=lambda item:item['path'].lower())
        items=library_items(files,titles)
        if view=='installs':
            selected={path.lower() for item in items for path in item['paths']}
            result={'files':[item for item in files if item['path'].lower() in selected],
                    'items':items,'inventory_count':len(files)}
            groups=items
        else:
            groups=group_files(files,titles)
            result={'files':files,'groups':groups,'items':items}
        covers={group['cover_title_id']:titles[group['cover_title_id']]['cover'] for group in groups if group['cover_title_id']}
        if covers:result['covers']=covers
        return result
    def label_file(self,target,path,data):
        if set(data)-{'path','name','category','mode','favorite'}:
            raise CompanionError('Only a display name, category, mode and favorite may be saved.')
        name=data.get('name','')
        if not isinstance(name,str) or len(name)>128 or re.search(r'[\x00-\x1f]',name):raise CompanionError('Invalid library name.')
        category=data.get('category','uncategorized')
        if category not in CATEGORIES:raise CompanionError('Choose a library category.')
        mode=validate_game_mode(data.get('mode',''))
        component=classify_component(path)
        if mode and (category in ('plugins','stealth') or component and component['category'] in ('plugins','stealth')):
            raise CompanionError('Plugins and stealth services cannot have a title-launch mode.')
        if mode and file_format(path)!='xex':raise CompanionError('Only XEX files may have a launch-mode label.')
        favorite=data.get('favorite',False)
        if type(favorite) is not bool:raise CompanionError('Favorite must be true or false.')
        with self.db() as db:
            if not db.execute('SELECT 1 FROM library WHERE target=? AND path=? COLLATE NOCASE',(target.lower(),path)).fetchone():
                raise CompanionError('Scan or inspect this file before organizing it.')
            snapshot=db.execute('SELECT data FROM library_inspections WHERE target=? AND path=? COLLATE NOCASE',(target.lower(),path)).fetchone()
            if mode and snapshot and json.loads(snapshot['data']).get('plugin') is True:
                raise CompanionError('DLL/plugin files cannot have a title-launch mode.')
            db.execute('INSERT OR REPLACE INTO library_labels VALUES(?,?,?,?,?,?)',(target.lower(),path,name.strip(),category,mode,int(favorite)))
        self.sync_game_data()
        return {'saved':True}
    def clear_library(self,target):
        with self.db() as db:
            db.execute('DELETE FROM library WHERE target=?',(target.lower(),))
            db.execute('DELETE FROM library_inspections WHERE target=?',(target.lower(),))
            db.execute('DELETE FROM library_labels WHERE target=?',(target.lower(),))
        self.sync_game_data()
        return {'cleared':True}
    def prune_uninspected_games(self,target,root=None,confirmed=False,expected_count=None,excluded_roots=()):
        listing=self.library(target,'installs',root,excluded_roots)
        files={item['path'].lower():item for item in listing['files']}
        paths={path for item in listing['items'] if item['kind']=='installation' and 'games' in item['categories']
               for path in item['paths'] if path.lower() in files and files[path.lower()]['inspection'] is None}
        if not confirmed:return {'count':len(paths)}
        if expected_count is not None and expected_count!=len(paths):raise CompanionError('Library changed. Preview unread games again.')
        with self.db() as db:
            for path in paths:
                db.execute('DELETE FROM library WHERE target=? AND path=? COLLATE NOCASE',(target.lower(),path))
                db.execute('DELETE FROM library_inspections WHERE target=? AND path=? COLLATE NOCASE',(target.lower(),path))
                db.execute('DELETE FROM library_labels WHERE target=? AND path=? COLLATE NOCASE',(target.lower(),path))
        if paths:self.sync_game_data()
        return {'removed':len(paths)}
    def title(self,ident,online=False):
        if not isinstance(ident,str) or not re.fullmatch('[0-9A-Fa-f]{8}',ident) or ident=='00000000':raise CompanionError('A nonzero Title ID is required.')
        ident=ident.upper()
        with self.db() as db:row=db.execute('SELECT data FROM titles WHERE id=?',(ident,)).fetchone()
        if row and not online:return json.loads(row[0])|{'cached':True}
        if not online:return {'title_id':ident,'state':'not-cached'}
        try:
            raw=json.loads(remote_bytes('titles/'+ident+'/info.json',256*1024))
        except urllib.error.HTTPError as error:
            if error.code==404:raise CompanionError('Title ID was not found in the community archive.') from None
            raise CompanionError('Community title lookup is unavailable. Retry later; cached metadata is preserved.') from None
        except (OSError,ValueError):raise CompanionError('Community title lookup failed or returned invalid data. Cached metadata is preserved.') from None
        if not isinstance(raw,dict) or not isinstance(raw.get('id'),str) or raw['id'].upper()!=ident:raise CompanionError('Title identity mismatch.')
        if not isinstance(raw.get('title'),dict):raise CompanionError('Community title metadata is invalid.')
        result={'title_id':ident,'title':text(raw.get('title',{}).get('full'),256),'source':'x360db community metadata','state':'available','cover':None,'cached':False,'fetched_at':int(time.time()),'artwork_state':'unavailable'}
        for field in ('developer','publisher','release_date'):
            value=raw.get(field)
            if isinstance(value,str) and len(value)<=256:result[field]=value
        try:
            cover=remote_bytes('titles/'+ident+'/artwork/boxart.jpg',512*1024)
            if cover.startswith(b'\xff\xd8\xff'):
                result['cover']='data:image/jpeg;base64,'+base64.b64encode(cover).decode();result['artwork_state']='available'
        except Exception:pass # Useful title metadata survives missing artwork.
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO titles VALUES(?,?,?)',(ident,json.dumps(result),time.time()))
            # Keep lightweight names for the whole bounded library. Evicting artwork
            # must not turn an already identified title back into a folder hint.
            db.execute('DELETE FROM titles WHERE id NOT IN (SELECT id FROM titles ORDER BY updated DESC LIMIT ?)',(MAX_TITLE_NAMES,))
            for old in db.execute('SELECT id,data FROM titles ORDER BY updated DESC LIMIT -1 OFFSET ?',(MAX_TITLE_COVERS,)).fetchall():
                cached=json.loads(old['data'])
                if cached.get('cover'):
                    cached.update(cover=None,artwork_state='evicted')
                    db.execute('UPDATE titles SET data=? WHERE id=?',(json.dumps(cached),old['id']))
        self.sync_game_data()
        return result

    def missing_game_titles(self,target,excluded_roots=()):
        listing=self.library(target,'installs',excluded_roots=excluded_roots)
        return {item['title_id'] for item in listing['items']
                if 'games' in item['categories'] and item.get('title_id') and item['title_id']!='00000000'
                and not item['metadata_available']}

    def save_aurora_titles(self,names):
        saved=0
        with self.db() as db:
            for ident,name in names.items():
                if db.execute('SELECT 1 FROM titles WHERE id=?',(ident,)).fetchone():continue
                result={'title_id':ident,'title':text(name,256),'source':'Aurora on-console metadata',
                        'state':'available','cover':None,'artwork_state':'unavailable','fetched_at':int(time.time())}
                db.execute('INSERT INTO titles VALUES(?,?,?)',(ident,json.dumps(result),time.time()))
                saved+=1
            if saved:
                db.execute('DELETE FROM titles WHERE id NOT IN (SELECT id FROM titles ORDER BY updated DESC LIMIT ?)',(MAX_TITLE_NAMES,))
        if saved:self.sync_game_data()
        return saved

class Companion:
    def __init__(self,bridge,path=None):
        self.bridge=bridge;self.store=Workspace(path);self.scan=None;self.transfer=None;self.launch=None
    def clean_transfer(self):
        if self.transfer and self.transfer.get('local_stage'):
            self.transfer.pop('local_stage').cleanup()
    def reset(self):
        self.clean_transfer()
        self.scan=None;self.transfer=None;self.launch=None
    def launch_accepted(self,path,metadata,previous):
        self.launch={'path':path,'title_id':metadata.get('title_id'),'previous':previous or {},'started':time.monotonic(),'state':'accepted'}
        self.store.record_launch(self.bridge.target,path)
    def observe(self,title):
        job=self.launch
        if not job:return None
        if job['state']=='accepted':
            path=(title.get('executable') or '').lower();expected=job['path'].lower();old=(job['previous'].get('executable') or '').lower()
            tid=title.get('title_id');oldid=job['previous'].get('title_id')
            name=path.replace('/','\\').rsplit('\\',1)[-1]
            expected_name=expected.replace('/','\\').rsplit('\\',1)[-1]
            old_name=old.replace('/','\\').rsplit('\\',1)[-1]
            if path==expected and old!=expected:job['state']='confirmed-path'
            elif tid and tid==job['title_id'] and old and name==expected_name and name!=old_name:job['state']='confirmed-executable-name'
            elif tid and tid==job['title_id'] and tid!=oldid:job['state']='confirmed-title-id'
            elif time.monotonic()-job['started']>60:job['state']='unconfirmed'
            if job['state']!='accepted':self.store.update_launch(self.bridge.target,job['path'],job['state'])
        return {'state':job['state'],'elapsed':int(time.monotonic()-job['started'])}
    def saved_game_library(self,path,target):
        drives=self.bridge.drives
        root=next((drive for drive in drives if path.lower().startswith(drive.lower())),None)
        library=self.store.library(target,'installs',root)
        if not any(item['kind']=='installation' and 'games' in item['categories']
                   and path.lower() in [candidate.lower() for candidate in item['paths']]
                   for item in library['items']):
            raise CompanionError('Choose a saved game launcher.')
        return library
    def dispatch(self,action,data):
        b=self.bridge
        # Import lazily to preserve the existing standalone server entrypoint.
        from server import safe_path
        target=b.target or ''
        if action=='profiles/list':return {'profiles':self.store.profiles()}
        if action=='profiles/save':return self.store.profile_save(data)
        if action=='profiles/remove':return self.store.profile_remove(data.get('id'))
        if action in ('transfer/cancel','transfer/status','transfer/cleanup'):return self.transfer_action(action,data)
        if b.target is None:raise CompanionError('Connect a console first.')
        if action=='favorites/list':return {'favorites':self.store.list('favorites',target),'recent':self.store.list('recent',target)}
        if action=='favorites/save':
            path=safe_path(data.get('path'),b.drives)
            directory=data.get('directory') is True
            if directory:b.dispatch('browse',{'path':path})
            else:
                info=b.adapter('file-info',path=path)
                if info.get('directory') is not False:raise CompanionError('Select a file.')
            return self.store.favorite(target,path,data.get('name'),directory,data.get('mode',''))
        if action=='favorites/remove':return self.store.remove_favorite(target,text(data.get('path'),512))
        if action in ('library/list','library/prune-uninspected'):
            if action=='library/prune-uninspected' and set(data)-{'root','confirmed','expected_count'}:
                raise CompanionError('Invalid library cleanup request.')
            root=data.get('root')
            if root is not None:
                root=safe_path(root,b.drives)
                if root.lower() not in [drive.lower() for drive in b.drives]:raise CompanionError('Choose a discovered storage root.')
            if action=='library/list':
                view=data.get('view','files')
                return self.store.library(target,view,root,library_alias_roots(b.drives) if view=='installs' else ())
            if 'confirmed' in data and type(data['confirmed']) is not bool:raise CompanionError('Confirm local library cleanup.')
            if data.get('confirmed') is True and (type(data.get('expected_count')) is not int or not 0<=data['expected_count']<=2000):
                raise CompanionError('Preview unread games before cleanup.')
            return self.store.prune_uninspected_games(target,root,data.get('confirmed') is True,
                                                     data.get('expected_count'),library_alias_roots(b.drives))
        if action=='games/addons':
            if set(data) != {'path'}:raise CompanionError('Choose a saved game launcher.')
            path=safe_path(data.get('path'),b.drives)
            library=self.saved_game_library(path,target)
            file=next(item for item in library['files'] if item['path'].lower()==path.lower())
            metadata=(file.get('inspection') or {}).get('metadata') or {}
            title_id=metadata.get('title_id')
            if not isinstance(title_id,str) or not re.fullmatch('[0-9A-Fa-f]{8}',title_id) or title_id=='00000000':title_id=None
            aurora=[];catalog=load_components()[0]
            for saved in self.store.library(target)['files']:
                candidate=saved['path']
                if candidate.lower().endswith('.xex') and any(candidate.lower().startswith(drive.lower()) for drive in b.drives):
                    hint=classify_component(candidate,catalog=catalog)
                    if hint and hint['id']=='aurora':aurora.append(candidate)
            from game_addons import discover_game_addons
            return discover_game_addons(b,path,title_id,aurora)
        if action=='games/title-update':
            if set(data) != {'game_path','path'}:
                raise CompanionError('Choose a game and its title-update candidate.')
            game_path=safe_path(data.get('game_path'),b.drives)
            path=safe_path(data.get('path'),b.drives)
            discovered=self.dispatch('games/addons',{'path':game_path})
            candidate=next((item for item in discovered['items']['title_updates']
                            if item['path'].lower()==path.lower()),None)
            if candidate is None:
                raise CompanionError('Choose a discovered title-update file for this game.')
            game=next(item for item in self.store.library(target)['files']
                      if item['path'].lower()==game_path.lower())
            game_media=((game.get('inspection') or {}).get('metadata') or {}).get('media_id')
            from title_updates import MAX_TITLE_UPDATE, inspect_title_update
            if type(candidate['size']) is int and candidate['size'] > MAX_TITLE_UPDATE:
                raise CompanionError('Title update exceeds the 128 MiB inspection limit. No console file was read.')
            return inspect_title_update(b,path,candidate['size'],discovered['title_id'],game_media)
        if action=='games/install-plan':
            if set(data) != {'game_path','kind','name','size'}:
                raise CompanionError('Choose a game, content type and local file.')
            game_path=safe_path(data.get('game_path'),b.drives)
            self.saved_game_library(game_path,target)
            from content_plan import plan_content
            return plan_content(b,game_path,data.get('kind'),data.get('name'),data.get('size'))
        if action=='library/label':return self.store.label_file(target,safe_path(data.get('path'),b.drives),data)
        if action=='library/clear':return self.store.clear_library(target)
        if action=='metadata/lookup':return self.store.title(data.get('title_id'),data.get('online') is True)
        if action=='metadata/aurora-import':
            if data:raise CompanionError('Aurora title import takes no options.')
            from aurora_metadata import MAX_AURORA_DB, title_names
            wanted=self.store.missing_game_titles(target,library_alias_roots(b.drives))
            if not wanted:return {'imported':0,'missing':0,'source':'Aurora on-console metadata'}
            aliases=library_alias_roots(b.drives)
            catalog=load_components()[0]
            candidates=[]
            for item in self.store.library(target)['files']:
                path=item['path']
                if (path.lower().endswith('\\aurora\\aurora.xex')
                        and not any(path.lower().startswith(alias) for alias in aliases)
                        and any(path.lower().startswith(root.lower()) for root in b.drives)):
                    component=classify_component(path,catalog=catalog)
                    if component and component['id']=='aurora':
                        candidates.append(path.rsplit('\\',1)[0]+'\\Data\\Databases\\content.db')
            for path in candidates[:4]:
                try:
                    info=b.adapter('file-info',path=path)
                except BridgeDiagnostic:
                    continue
                size=info.get('size')
                if info.get('directory') is not False or type(size) is not int or not 0<size<=MAX_AURORA_DB:continue
                with tempfile.TemporaryDirectory() as directory:
                    local=Path(directory)/'aurora.db'
                    b.adapter('download-file',path=path,local=str(local),size=size)
                    try:names=title_names(local,wanted)
                    except (OSError,ValueError,sqlite3.DatabaseError):
                        return {'imported':0,'missing':len(wanted),'source':'Aurora database unreadable'}
                saved=self.store.save_aurora_titles(names)
                return {'imported':saved,'missing':len(wanted)-saved,'source':'Aurora on-console metadata'}
            return {'imported':0,'missing':len(wanted),'source':'Aurora unavailable'}
        if action=='storage/capacity':
            root=safe_path(data.get('root'),b.drives)
            if root.lower() not in [x.lower() for x in b.drives]:raise CompanionError('Choose a storage root.')
            info=b.adapter('capacity',path=root)
            total=info.get('total');free=info.get('free')
            if type(total) is not int or type(free) is not int or not 0<=free<=total<=2**53-1 or total==0:raise CompanionError('Capacity unavailable.')
            return {'root':root,'total':total,'free':free,'used':total-free}
        if action=='storage/health':
            if data:raise CompanionError('Storage health takes no path or options.')
            from storage_health import storage_health
            return storage_health(b,self.store.library(target)['files'])
        if action=='scan/start':
            formats=data.get('formats','xex')
            if formats not in ('xex','iso-god'):raise CompanionError('Choose XEX or ISO/GOD discovery.')
            view=data.get('view','files')
            if view not in ('files','installs') or (view=='installs' and formats!='xex'):
                raise CompanionError('Choose file discovery or XEX install discovery.')
            if formats=='iso-god' and data.get('disclaimer_accepted') is not True:
                raise CompanionError('Accept the ISO/GOD discovery disclaimer first.')
            if 'paths' in data:
                if 'path' in data or not isinstance(data['paths'],list) or not 1<=len(data['paths'])<=32:
                    raise CompanionError('Choose 1–32 discovered scan folders.')
                roots=[safe_path(path,b.drives).rstrip('\\')+'\\' for path in data['paths']]
            else:roots=[safe_path(data.get('path'),b.drives).rstrip('\\')+'\\']
            unique_roots={}
            for root in roots:unique_roots.setdefault(root.lower(),root)
            roots=list(unique_roots.values())
            if view=='installs':
                aliases=library_alias_roots(b.drives)
                roots=[root for root in roots if not any(root.lower().startswith(alias) for alias in aliases)]
                if not roots:raise CompanionError('Choose the numbered USB storage root for this library scan.')
            depth=data.get('depth',6)
            if type(depth) is not int or not 0<=depth<=12:raise CompanionError('Depth must be 0–12.')
            if self.transfer and self.transfer['state']=='running':raise CompanionError('Finish or cancel the active transfer before scanning.')
            self.scan={'id':secrets.token_hex(16),'queue':deque((root,0) for root in roots),'seen':set(),'queued':{root.lower() for root in roots},'visited':0,'found':0,'errors':0,'depth':depth,'state':'running','started':time.monotonic()}
            self.scan['formats']=formats
            self.scan['view']=view
            if view=='installs':self.scan['components']=load_components()[0]
            return self.scan_status()
        if action.startswith('scan/'):
            job=self.scan
            if not job or data.get('id')!=job['id']:raise CompanionError('Scan expired.')
            if action=='scan/cancel':job['state']='cancelled';job['queue'].clear();return self.scan_status()
            if action!='scan/step':raise CompanionError('Unknown scan action.')
            if job['state']!='running':return self.scan_status()
            if time.monotonic()-job['started']>1800 or job['visited']>=1000 or job['found']>=2000:
                job['state']='limited';return self.scan_status()
            folders=[job['queue'].popleft() for _ in range(min(8,len(job['queue']),1000-job['visited']))]
            if len(folders)>1:
                try:listings=b.dispatch('browse-many',{'paths':[folder for folder,_ in folders]})['listings']
                except Exception:
                    job['visited']+=len(folders);job['errors']+=len(folders)
                    if not job['queue']:job['state']='completed'
                    return self.scan_status()
            else:
                try:listings=[b.dispatch('browse',{'path':folders[0][0]})]
                except Exception:listings=[{'error':True}]
            for (folder,depth),result in zip(folders,listings):
                job['visited']+=1;job['seen'].add(folder.lower())
                if result.get('error') is True:
                    job['errors']+=1;continue
                try:
                    if result.get('listing',{}).get('truncated') or result.get('listing',{}).get('rejected'):job['errors']+=1
                    found=[]
                    installs=job.get('view')=='installs'
                    hints={f['name']:classify_component(folder+f['name'],catalog=job['components'])
                           for f in result['files'] if not f['directory']} if installs else {}
                    has_default=installs and any(not f['directory'] and f['name'].lower()=='default.xex'
                                                and (library_collection(folder+f['name']) or hints.get(f['name'])) for f in result['files'])
                    has_app=any(hint and hint['category'] in ('homebrew','apps','emulators') for hint in hints.values())
                    anchored=(has_default or has_app) and install_folder(folder)
                    for f in result['files']:
                        path=folder+f['name']
                        component=hints.get(f['name'])
                        if installs and not f['directory'] and not library_collection(path) and not component:continue
                        if installs and (library_path_excluded(path,f['directory']) or
                                         (f['directory'] and anchored and not disc_folder(path))):continue
                        if has_default and not f['directory'] and f['name'].lower()!='default.xex' and not component:continue
                        if f['directory'] and depth<job['depth'] and path.lower()+'\\' not in job['queued'] and len(job['queue'])<1000:
                            job['queue'].append((path+'\\',depth+1))
                            job['queued'].add(path.lower()+'\\')
                        elif f['directory'] and depth<job['depth'] and len(job['queue'])>=1000:job['errors']+=1
                        elif not f['directory'] and self.scan_candidate(path,job.get('formats','xex')) and job['found']+len(found)<2000:
                            found.append((path,f['size']))
                    self.store.record_files(target,found)
                    job['found']+=len(found)
                except Exception:job['errors']+=1
            if job['found']>=2000:job['state']='limited'
            elif not job['queue']:job['state']='completed'
            return self.scan_status()
        if action.startswith('transfer/'):return self.transfer_action(action,data)
        raise CompanionError('Unknown companion action.')
    def scan_status(self):
        return {k:self.scan[k] for k in ('id','visited','found','errors','state')}|{'remaining':len(self.scan['queue'])}
    @staticmethod
    def scan_candidate(path,formats):
        # Layout evidence only, not a GOD header/integrity determination.
        return file_format(path)=='xex' if formats=='xex' else file_format(path) in ('iso','god')
    def receive_download(self,job):
        self.bridge.adapter('download-file',path=job['path'],local=job['local_path'],size=job['size'])
        if Path(job['local_path']).stat().st_size!=job['size']:
            raise CompanionError('Downloaded file size changed.')
    def transfer_action(self,action,data):
        from server import safe_path
        b=self.bridge
        if action=='transfer/start':
            if self.transfer and self.transfer['state']=='running':raise CompanionError('Finish or cancel the active transfer.')
            direction=data.get('direction');requested_path=data.get('path')
            if direction=='upload':
                if not isinstance(requested_path,str) or '\\' not in requested_path:raise CompanionError('Choose a console folder and filename.')
                folder,name=requested_path.rsplit('\\',1)
                folder=safe_path(folder+'\\',b.drives)
                path=safe_path(folder+console_upload_filename(name),b.drives)
            else:path=safe_path(requested_path,b.drives)
            if path.endswith('\\'):raise CompanionError('Choose a file path.')
            if direction not in ('upload','download'):raise CompanionError('Invalid direction.')
            job={'id':secrets.token_hex(16),'direction':direction,'path':path,'offset':0,'state':'running','hash':hashlib.sha256(),'started':time.monotonic()}
            if direction=='download':
                info=b.adapter('file-info',path=path);size=info.get('size')
                if info.get('directory') is not False:raise CompanionError('Not a file.')
            else:
                if data.get('upload_protocol')!=2:raise CompanionError('Upload protocol changed. Hard-refresh the browser (Ctrl+F5) before uploading.')
                if data.get('confirmed') is not True:raise CompanionError('Confirm the destination before upload.')
                size=data.get('size');expected=data.get('sha256')
                if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected):raise CompanionError('Upload SHA-256 required.')
                job['expected']=expected
                build_id=data.get('build_id')
                if build_id is not None and (not isinstance(build_id,str) or not re.fullmatch('[a-z0-9][a-z0-9._-]{0,127}',build_id)):
                    raise CompanionError('Invalid expected build id.')
                job['build_id']=build_id
                self.require_new_destination(path)
                job['temporary']=path.rsplit('\\',1)[0]+'\\nb-'+job['id'][:24]+'.part'
            if type(size) is not int or not 0<=size<=MAX_TRANSFER:raise CompanionError('Transfer limit is 128 MiB per file.')
            self.clean_transfer()
            job['size']=size
            job['local_stage']=tempfile.TemporaryDirectory(prefix='nebulah-transfer-')
            job['local_path']=str(Path(job['local_stage'].name)/'transfer.bin')
            Path(job['local_path']).touch()
            job['phase']='staging' if direction=='upload' else 'receiving'
            self.transfer=job
            return self.transfer_status()
        job=self.transfer
        if not job or data.get('id')!=job['id']:raise CompanionError('Transfer expired.')
        if action=='transfer/status':return self.transfer_status()
        if action=='transfer/cancel':
            if job['state']=='running':job['state']='cancelled'
            self.clean_transfer()
            return self.transfer_status()
        if action=='transfer/cleanup':
            if job['direction']!='upload' or not job.get('remote_attempted') or job['state'] not in ('cancelled','failed'):
                raise CompanionError('No failed remote upload partial is available.')
            if data.get('id')!=job['id'] or data.get('confirmed') is not True:
                raise CompanionError('Confirm cleanup for this failed upload.')
            if data.get('path') not in (None, job.get('temporary')):
                raise CompanionError('Partial path does not match this transfer.')
            b.adapter('delete-file',path=job['temporary'])
            job['partial_cleaned']=True
            return self.transfer_status()
        if job['state']!='running':raise CompanionError('Transfer is not active.')
        if time.monotonic()-job['started']>3600:
            job['state']='expired';self.clean_transfer();raise CompanionError('Transfer expired.')
        if action=='transfer/approve':
            consent=job.pop('consent',None)
            if (job['direction']!='upload' or job['phase']!='checked' or not consent
                    or data.get('confirmed') is not True or not isinstance(data.get('consent'),str)
                    or not secrets.compare_digest(consent,data['consent']) or time.monotonic()>job['consent_expires']):
                job['state']='failed';self.clean_transfer()
                raise CompanionError('Executable upload confirmation expired or invalid. Stage the file again.')
            job['phase']='approved'
            return self.transfer_status()
        if action=='transfer/finish':
            if job['offset']!=job['size']:raise CompanionError('Transfer incomplete.')
            try:
                if job['direction']=='download':
                    # Empty files skip chunk requests but still require a real receive.
                    if job['phase']=='receiving':
                        self.receive_download(job)
                    job['state']='completed';self.clean_transfer();return self.transfer_status()
                if job['phase']=='staging':
                    if job['hash'].hexdigest()!=job['expected']:raise CompanionError('Staged upload digest mismatch; nothing sent to console.')
                    report=self.upload_report(job)
                    if report:
                        job['checkpoint']=report;job['phase']='checked'
                        job['consent']=secrets.token_urlsafe(32);job['consent_expires']=time.monotonic()+120
                        return self.transfer_status()
                    self.send_staged_upload(job)
                elif job['phase']=='approved':
                    if time.monotonic()>job['consent_expires']:raise CompanionError('Executable upload confirmation expired. Stage the file again.')
                    self.recheck_upload(job)
                    self.send_staged_upload(job)
                elif job['phase']=='checked':
                    raise CompanionError('Confirm the staged executable report before uploading.')
                elif job['phase']=='sent':
                    job['phase']='verifying'
                    result=b.adapter('verify-upload',path=job['temporary'],size=job['size'])
                    if result.get('sha256')!=job['expected']:raise CompanionError('Full-file read-back hash mismatch; partial retained, destination not finalized.')
                    job['phase']='verified'
                elif job['phase']=='verified':
                    if job.get('checkpoint'):self.recheck_upload(job)
                    self.require_new_destination(job['path'])
                    job['phase']='finalizing'
                    b.adapter('rename-transfer',path=job['temporary'],destination=job['path'])
                    job['phase']='finalized';job['state']='completed';self.clean_transfer()
                return self.transfer_status()
            except BridgeDiagnostic as error:
                job['state']='failed';self.clean_transfer()
                raise self.transfer_failure(job,error) from None
            except Exception:
                job['state']='failed';self.clean_transfer();raise
        if action!='transfer/chunk' or data.get('offset')!=job['offset']:raise CompanionError('Unexpected transfer offset.')
        try:
            remaining=job['size']-job['offset'];count=min(CHUNK,remaining)
            if count<=0:raise CompanionError('No bytes remaining.')
            if job['direction']=='download':
                if job['phase']=='receiving':
                    self.receive_download(job)
                    job['phase']='streaming'
                with open(job['local_path'],'rb') as received:
                    received.seek(job['offset']);chunk=received.read(count)
                content=base64.b64encode(chunk).decode()
            else:
                content=data.get('content');chunk=base64.b64decode(content,validate=True)
                if len(chunk)!=count:raise CompanionError('Incorrect chunk size.')
                if job['phase']!='staging':raise CompanionError('Upload is no longer staging.')
                with open(job['local_path'],'ab') as staged:
                    if staged.tell()!=job['offset']:raise CompanionError('Staged file size changed.')
                    staged.write(chunk)
            if len(chunk)!=count:raise CompanionError('File changed or short read.')
            job['hash'].update(chunk);job['offset']+=len(chunk)
            response=self.transfer_status()
            if job['direction']=='download':response['content']=content
            return response
        except BridgeDiagnostic as error:
            job['state']='failed';self.clean_transfer()
            raise self.transfer_failure(job,error) from None
        except CompanionError:
            job['state']='failed';self.clean_transfer();raise
        except Exception:
            job['state']='failed';self.clean_transfer();raise CompanionError('Transfer response could not be decoded; any remote partial file is retained.') from None
    def transfer_failure(self,job,error):
        self.bridge.require_recovery(error)
        diagnostic={**error.payload()['diagnostic'], 'phase':job['phase'], 'offset':job['offset']}
        job['failure']=diagnostic
        suffix=' Console operations paused; confirm console recovery before reconnecting.' if self.bridge.recovery_hold is not None else ''
        return TransferFailure(f'{error.reason} [{error.code}; HRESULT {error.hresult or "unavailable"}; phase {job["phase"]}; byte offset {job["offset"]}].'+suffix,
                               diagnostic,self.bridge.recovery_hold is not None)
    def require_new_destination(self,path):
        folder,name=path.rsplit('\\',1)
        result=self.bridge.dispatch('browse',{'path':folder+'\\'})
        if result.get('listing',{}).get('truncated') or result.get('listing',{}).get('rejected'):raise CompanionError('Cannot establish destination absence from incomplete listing.')
        if any(f['name'].lower()==name.lower() for f in result['files']):raise CompanionError('Destination exists. Choose a new filename; overwrite is disabled.')
    def transfer_status(self):
        job=self.transfer
        result={k:job[k] for k in ('id','direction','path','size','offset','state')}
        result['chunk_size']=CHUNK
        if job['direction']=='upload':
            result['temporary']=job['temporary'];result['phase']=job['phase']
            if job.get('checkpoint'):result['checkpoint']=job['checkpoint']
            if job['phase']=='checked' and job['state']=='running' and job.get('consent'):
                result['consent']=job['consent'];result['consent_expires_in']=max(0,int(job['consent_expires']-time.monotonic()))
        result['remote_partial_possible']=job.get('remote_attempted',False)
        result['partial_cleaned']=job.get('partial_cleaned',False)
        if job.get('failure'):result['failure']=job['failure']
        if job['state']=='completed':result['sha256']=job['hash'].hexdigest()
        return result
    def recheck_upload(self,job):
        report=self.upload_report(job)
        previous=job['checkpoint']
        if (not report or report['registry']['catalog_revision']!=previous['registry']['catalog_revision']
                or report['game_catalog_revision']!=previous['game_catalog_revision']):
            raise CompanionError('Executable review catalog changed. Stage and confirm the file again.')
    def upload_report(self,job):
        try:return check_staged_file(job['local_path'],job['path'],job['size'],job['expected'],job.get('build_id'))
        except ValueError as error:raise CompanionError('Upload checkpoint rejected: '+str(error)) from None
        except OSError:raise CompanionError('Staged file or review catalog unavailable. Upload blocked.') from None
    def send_staged_upload(self,job):
        self.require_new_destination(job['path'])
        job['phase']='sending';job['remote_attempted']=True
        self.bridge.adapter('upload-empty' if job['size']==0 else 'upload-file',path=job['temporary'],local=job['local_path'],size=job['size'])
        job['phase']='sent'
