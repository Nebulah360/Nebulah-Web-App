"""Local-only Nebulah Link bridge. Python 3.10+, Windows Neighborhood/XDevkit."""
import argparse, math, hashlib, hmac, ipaddress, json, os, re, secrets, struct, subprocess, tempfile, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from hash_registry import load_catalog, public_build, verify_digest, RegistryError
ROOT = Path(__file__).resolve().parents[1]
MAX_XEX = 64 * 1024 * 1024

def validate_xex(data):
    if len(data) < 24 or len(data) > MAX_XEX or data[:4] != b'XEX2':
        raise ValueError('Not an inspectable XEX2 file (24 bytes–64 MiB required).')
    flags, pe, reserved, security, count = struct.unpack('>5I', data[4:24])
    end = 24 + count * 8
    if count > 4096 or end > len(data) or not end <= security < pe < len(data):
        raise ValueError('Invalid XEX header bounds.')
    if security + 4 > pe:
        raise ValueError('Truncated security header.')
    security_size = struct.unpack_from('>I', data, security)[0]
    if security_size < 0x180 or security + security_size > pe:
        raise ValueError('Invalid security header size.')
    keys = set()
    for i in range(count):
        key, value = struct.unpack_from('>II', data, 24 + i*8)
        if key in keys:
            raise ValueError('Duplicate optional header.')
        keys.add(key)
        size = key & 255
        if size in (0, 1):
            continue
        if value < end or value + 4 > pe:
            raise ValueError('Optional header outside header region.')
        length = struct.unpack_from('>I', data, value)[0] if size == 255 else size * 4
        if length < 4 or value + length > pe:
            raise ValueError('Invalid optional header length.')
    if not flags & 1:
        raise ValueError('XEX does not declare an executable module.')
    return {'valid':True, 'plugin':bool(flags & 8), 'hash':hashlib.sha256(data).hexdigest(),
            'size':len(data), 'checks':['XEX2 magic and executable flag','Header and security bounds','Optional-header bounds']}

def safe_path(path, drives):
    if not isinstance(path, str) or len(path)>512 or not re.fullmatch(r'[A-Za-z0-9_]+:\\[^\x00-\x1f"<>|?*:/]*',path):
        raise ValueError('Use an absolute console path on a discovered storage root.')
    if any(s in ('.','..') for s in path.split('\\')):
        raise ValueError('Relative path segments are not allowed.')
    if not any(path.lower().startswith(d.lower()) for d in drives):
        raise ValueError('Storage root has not been discovered on this console.')
    return path

def sanitize_telemetry(s):
    """Field-by-field projection; never forward raw plugin/COM objects."""
    raw=s.get('temperatures')
    if not isinstance(raw,dict):raw={}
    temperatures={}
    for key in ('cpu','gpu','edram','motherboard'):
        v=raw.get(key)
        temperatures[key]=v if type(v) in (int,float) and math.isfinite(v) and 0<v<=125 else None
    title=s.get('current_title')
    if not isinstance(title,dict):title={}
    executable=title.get('executable')
    if not isinstance(executable,str) or len(executable)>512 or re.search(r'[\x00-\x1f]',executable):executable=None
    title_id=title.get('title_id')
    if not isinstance(title_id,str) or not re.fullmatch(r'[0-9A-Fa-f]{8}',title_id):title_id=None
    return {'temperatures':temperatures,'current_title':{'executable':executable or None,'title_id':title_id.upper() if title_id else None}}

class Bridge:
    def __init__(self, powershell):
        self.powershell=powershell; self.target=None; self.drives=[]; self.tickets={}; self.private_tickets={}
    def adapter(self, action, **kwargs):
        p=subprocess.run([self.powershell,'-NoProfile','-NonInteractive','-File',str(ROOT/'bridge/neighborhood.ps1')],
             input=json.dumps({'action':action,'target':self.target or '',**kwargs}),text=True,capture_output=True,timeout=40)
        if p.returncode:
            raise ValueError('Neighborhood operation failed. Check the console connection and XDevkit COM installation.')
        try:return json.loads(p.stdout.lstrip('\ufeff'))
        except (ValueError,TypeError):raise ValueError('Neighborhood returned an unsupported response.')
    def status(self):
        s=self.adapter('status')
        self.drives=[d for d in s.get('drives',[]) if isinstance(d,str) and re.fullmatch(r'[A-Za-z0-9_]+:\\',d)]
        # Only explicit status fields leave the bridge. No raw adapter payloads.
        return {'type':str(s.get('type','Unavailable'))[:64], 'kernel':str(s.get('kernel','Unavailable'))[:64], 'drives':self.drives, **sanitize_telemetry(s)}
    def inspect(self,path):
        if not path.lower().endswith('.xex'):raise ValueError('Only XEX files may be inspected.')
        with tempfile.TemporaryDirectory(prefix='nebulah-') as folder:
            dest=Path(folder)/'inspect.xex';self.adapter('receive',path=path,local=str(dest))
            if dest.stat().st_size>MAX_XEX:raise ValueError('XEX exceeds inspection size limit.')
            return validate_xex(dest.read_bytes())
    def dispatch(self,action,data):
        if action=='registry/list':
            catalog,revision=load_catalog()
            return {'builds':[public_build(b) for b in catalog['builds']],'catalog_revision':revision}
        if action=='registry/check':
            result=verify_digest(data.get('sha256'),data.get('size'),data.get('build_id'))
            result['measurement']='caller-supplied-digest'
            # This endpoint does not read bytes or authorize installation.
            result['eligible_for_install']=False
            return result
        if action=='connect':
            target=data.get('target','')
            if not isinstance(target,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{0,253}',target):raise ValueError('Invalid console name or local IP.')
            self.target=target; self.drives=[]; self.tickets={}; self.private_tickets={}
            return self.status()
        if self.target is None:raise ValueError('Connect a console first.')
        if action=='status':return self.status()
        if action=='cpu-key/prepare':
            # Preparing consent never queries the console or reads private data.
            now=time.monotonic()
            self.private_tickets={k:v for k,v in self.private_tickets.items() if v>now}
            if len(self.private_tickets)>=32:raise ValueError('Too many pending confirmations.')
            ticket=secrets.token_urlsafe(32)
            self.private_tickets[ticket]=now+60
            return {'confirmation_ticket':ticket,'expires_in':60}
        if action=='cpu-key/reveal':
            if data.get('confirmed') is not True:raise ValueError('Explicit confirmation required.')
            ticket=data.get('confirmation_ticket')
            if not isinstance(ticket,str):raise ValueError('Confirmation ticket required.')
            expires=self.private_tickets.pop(ticket,None)
            if expires is None or expires<time.monotonic():raise ValueError('Confirmation expired.')
            result=self.adapter('cpu-key')
            key=result.get('cpu_key')
            if not isinstance(key,str) or not re.fullmatch(r'[0-9A-Fa-f]{32}',key) or key=='0'*32:
                raise ValueError('CPU key unavailable.')
            return {'cpu_key':key.upper()}

        if action=='browse':
            path=safe_path(data.get('path'),self.drives)
            files=self.adapter('browse',path=path).get('files',[])
            return {'files':[{'name':f['name'],'directory':bool(f.get('directory')),'size':max(0,int(f.get('size',0)))} for f in files
                if isinstance(f.get('name'),str) and re.fullmatch(r'[^\\/\x00-\x1f:]+',f['name']) and f['name'] not in ('.','..')][:10000]}
        if action=='validate':
            path=safe_path(data.get('path'),self.drives);v=self.inspect(path)
            try:verification=verify_digest(v['hash'],v['size'],data.get('build_id'))
            except RegistryError:verification={'status':'registry-error','eligible_for_install':False,'discrepancies':['Catalog unavailable or malformed.']}
            verification['measurement']='console-file-bytes'
            blocked=verification['status'] in ('revoked','mismatch','unknown-build','registry-error')
            self.tickets={k:t for k,t in self.tickets.items() if t['expires']>time.monotonic()}
            ticket=secrets.token_urlsafe(24)
            if not v['plugin'] and not blocked:
                self.tickets[ticket]={'path':path,'hash':v['hash'],'expires':time.monotonic()+120,'build_id':data.get('build_id')}
            return {**v,'verification':verification,'ticket':None if blocked or v['plugin'] else ticket}
        if action=='launch':
            ticket=data.get('ticket')
            if not isinstance(ticket,str):raise ValueError('A validation ticket is required.')
            t=self.tickets.pop(ticket,None)
            if not t or t['expires']<time.monotonic():raise ValueError('Inspection expired. Inspect the XEX again.')
            v=self.inspect(t['path'])
            if v['plugin'] or not hmac.compare_digest(v['hash'],t['hash']):raise ValueError('File changed. Inspect it again before launching.')
            # Reload catalog so revocation after inspection invalidates the launch.
            verification=verify_digest(v['hash'],v['size'],t.get('build_id'))
            if verification['status'] in ('revoked','mismatch','unknown-build'):raise ValueError('Build verification rejected launch.')
            self.adapter('launch',path=t['path'])
            return {'accepted':True}
        raise ValueError('Capability not available in this base adapter.')

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,status,body,kind='application/json'):
        raw=json.dumps(body).encode() if kind=='application/json' else body
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers();self.wfile.write(raw)
    def host_ok(self):return self.headers.get('Host') in self.server.allowed_hosts
    def do_GET(self):
        if not self.host_ok():return self.reply(403,{'error':'Host not allowed.'})
        files={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript'),'/theme.js':('theme.js','text/javascript'),'/style.css':('style.css','text/css')}
        if self.path not in files:return self.reply(404,{'error':'Not found.'})
        name,kind=files[self.path];self.reply(200,(ROOT/'dist'/name).read_bytes(),kind)
    def do_POST(self):
        if not self.host_ok() or self.headers.get('Origin')!='http://'+self.headers.get('Host',''):
            return self.reply(403,{'error':'Same-origin browser request required.'})
        auth=self.headers.get('Authorization','')
        if not hmac.compare_digest(auth,'Bearer '+self.server.token):return self.reply(401,{'error':'Pairing token is incorrect.'})
        try:
            if self.headers.get('Content-Type')!='application/json':raise ValueError('JSON required.')
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=4096:raise ValueError('Invalid request size.')
            body=json.loads(self.rfile.read(n))
            if not isinstance(body,dict):raise ValueError('Object required.')
            if not self.path.startswith('/api/'):raise ValueError('Unknown route.')
            self.reply(200,self.server.bridge.dispatch(self.path[5:],body))
        except (ValueError,KeyError,TypeError):self.reply(400,{'error':'Request failed validation or Neighborhood could not complete it. Check the connection, path, and XEX; inspect again before launching.'})
        except subprocess.TimeoutExpired:self.reply(504,{'error':'Neighborhood timed out. Verify console reachability before retrying.'})
        except Exception:self.reply(502,{'error':'Local adapter unavailable. Check Windows, Python and Neighborhood installation.'})
    def setup(self):
        super().setup();self.connection.settimeout(50)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--host',default='127.0.0.1',help='Bind a specific private PC IPv4 address for phone access.');p.add_argument('--port',type=int,default=8765);p.add_argument('--powershell',default=os.path.join(os.environ.get('WINDIR','C:\\Windows'),'SysWOW64','WindowsPowerShell','v1.0','powershell.exe'))
    a=p.parse_args();ip=ipaddress.ip_address(a.host)
    if ip.version!=4 or not (ip.is_loopback or ip in ipaddress.ip_network('10.0.0.0/8') or ip in ipaddress.ip_network('172.16.0.0/12') or ip in ipaddress.ip_network('192.168.0.0/16')):p.error('Choose loopback or a specific private LAN IPv4 address.')
    server=HTTPServer((a.host,a.port),Handler);server.allowed_hosts={f'{a.host}:{a.port}'}
    if ip.is_loopback:server.allowed_hosts.add(f'localhost:{a.port}')
    server.token=secrets.token_urlsafe(32);server.bridge=Bridge(a.powershell)
    print(f'\nNebulah Link: http://{a.host}:{a.port}\nPairing token: {server.token}\nKeep this window open. Ctrl+C stops the bridge.\n')
    if not ip.is_loopback:print('LAN mode: trusted private Wi-Fi only. HTTP is not encrypted. Do not forward this port.\n')
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
if __name__=='__main__':main()
