"""Saved repositories and metadata-only plugin inventory; no remote code loading."""
import json, re, sqlite3, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone
from pathlib import Path
PRESETS=('Nebulah360/Nebulah-Web-App','Nebulah360/Nebulah-Dash')
DEFAULT_DB=Path(__file__).resolve().parents[1]/'.local/repositories.sqlite3'
def now():return datetime.now(timezone.utc).isoformat()
def repo_name(value):
    if not isinstance(value,str):raise ValueError('Repository required.')
    value=value.strip().removeprefix('https://github.com/').removesuffix('/').removesuffix('.git')
    if len(value)>200 or not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+',value) or value.split('/')[1] in ('.','..'):raise ValueError('Use owner/repo or its HTTPS GitHub URL.')
    return value
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def github(path):
    request=urllib.request.Request('https://api.github.com/repos/'+path,headers={'Accept':'application/vnd.github+json','User-Agent':'Nebulah-Link','X-GitHub-Api-Version':'2022-11-28'})
    with urllib.request.build_opener(NoRedirect).open(request,timeout=4) as response:
        data=response.read(2*1024*1024+1)
        if len(data)>2*1024*1024:raise ValueError('GitHub response too large.')
        return json.loads(data)

class Repositories:
    def __init__(self,path=DEFAULT_DB):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS repos (name TEXT PRIMARY KEY COLLATE NOCASE, origin TEXT, snapshot TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS plugins (name TEXT PRIMARY KEY COLLATE NOCASE, version TEXT, repo TEXT)')
            for name in PRESETS:db.execute('INSERT OR IGNORE INTO repos VALUES (?, ?, NULL)',(name,'preset'))
    def db(self):return sqlite3.connect(self.path,timeout=5)
    def list(self):
        with self.db() as db:return [{'repository':n,'origin':o,'last_check':json.loads(s) if s else None} for n,o,s in db.execute('SELECT name,origin,snapshot FROM repos ORDER BY name')]
    def save(self,name):
        name=repo_name(name)
        with self.db() as db:
            if db.execute('SELECT count(*) FROM repos').fetchone()[0]>=50 and not db.execute('SELECT 1 FROM repos WHERE name=?',(name,)).fetchone():raise ValueError('Maximum 50 saved repositories.')
            db.execute('INSERT OR IGNORE INTO repos VALUES (?, ?, NULL)',(name,'saved'))
        return {'saved':name}
    def remove(self,name):
        with self.db() as db:db.execute("DELETE FROM repos WHERE name=? AND origin='saved'",(repo_name(name),))
        return {'removed_if_saved':name}
    def check(self,name,fetch=github):
        name=repo_name(name)
        with self.db() as db:row=db.execute('SELECT snapshot FROM repos WHERE name=?',(name,)).fetchone()
        if row is None:raise ValueError('Save the repository first.')
        previous=json.loads(row[0]) if row[0] else None
        result={'repository':name,'checked_at':now(),'status':'unavailable','error':None,'last_success':previous}
        try:
            meta=fetch(name);branch=meta['default_branch'];commit=fetch(name+'/commits/'+urllib.parse.quote(branch,safe=''))
            sha=commit['sha']
            if not re.fullmatch(r'[a-f0-9]{40,64}',sha):raise ValueError('Invalid revision.')
            result.update(push_changed=previous['last_push']!=meta['pushed_at'] if previous else None,revision_changed=previous['revision']!=sha if previous else None,status='first-check' if not previous else 'changed' if previous['revision']!=sha else 'unchanged',owner=meta['owner']['login'],stars=meta['stargazers_count'],last_push=meta['pushed_at'],metadata_updated=meta['updated_at'],branch=branch,revision=sha,commit_date=commit['commit']['committer']['date'],description=meta.get('description'),archived=meta.get('archived',False),forks=meta.get('forks_count'),open_issues=meta.get('open_issues_count'),license=(meta.get('license') or {}).get('spdx_id'),release=None,release_status='unavailable',previous_revision=previous['revision'] if previous else None,last_success=None)
            try:
                release=fetch(name+'/releases/latest')
                result['release']={k:release.get(k) for k in ('tag_name','name','published_at')};result['release_status']='available'
            except urllib.error.HTTPError as e:result['release_status']='none' if e.code==404 else 'unavailable'
            except Exception:pass
            with self.db() as db:db.execute('UPDATE repos SET snapshot=? WHERE name=?',(json.dumps(result),name))
        except urllib.error.HTTPError as e:result['error']='GitHub HTTP '+str(e.code)+' (check availability or API rate limit).'
        except Exception:result['error']='GitHub metadata unavailable; previous results are not current.'
        return result
    def register_plugin(self,name,version,repo):
        if any(not isinstance(v,str) or not v.strip() or len(v)>128 or re.search(r'[\x00-\x1f]',v) for v in (name,version)):raise ValueError('Plugin name and version required.')
        repo=repo_name(repo);self.save(repo)
        with self.db() as db:
            if db.execute('SELECT count(*) FROM plugins').fetchone()[0]>=100:raise ValueError('Plugin inventory full.')
            db.execute('INSERT OR REPLACE INTO plugins VALUES (?,?,?)',(name,version,repo))
        return {'registered':name,'loaded':False}
    def user_plugins(self):
        with self.db() as db:return [{'name':n,'version':v,'repository':r,'state':'registered-not-loaded','loaded':False} for n,v,r in db.execute('SELECT name,version,repo FROM plugins ORDER BY name')]
    def remove_plugin(self,name):
        if not isinstance(name,str):raise ValueError('Plugin name required.')
        with self.db() as db:db.execute('DELETE FROM plugins WHERE name=?',(name,))
        return {'removed':name}
