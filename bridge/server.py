"""Local-only Nebulah Link bridge. Python 3.10+, Windows Neighborhood/XDevkit."""
import webbrowser
import argparse, base64, sys, math, hashlib, hmac, ipaddress, json, os, re, secrets, selectors, struct, subprocess, tempfile, threading, time
from collections import deque
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from repositories import Repositories
from diagnostics import BridgeDiagnostic, ERRORS, STAGES, MODULE_PHASES
from game_paths import GamePaths
from browser_sessions import BrowserSessions
from companion import Companion, CompanionError
from game_catalog import verify_game, capabilities, candidate_from_inspection
from hash_registry import load_catalog, public_build, verify_digest, RegistryError
from component_catalog import classify_component
from runtime_paths import ROOT
SESSION_HANDOFF_PATH = ROOT / '.local' / 'browser-session-handoff.json'
BRIDGE_UPTIME_LOG = ROOT / '.local' / 'bridge-uptime.log'
MAX_XEX = 64 * 1024 * 1024
ADAPTER_VERSION = 10
GAME_INSPECTION_TTL = 600
MAX_GAME_INSPECTIONS = 32
# COM gets 180 seconds; allow startup and graceful adapter cleanup before killing.
BULK_PROCESS_TIMEOUT = 210
TRANSFER_ACTIONS = {'upload-file', 'upload-empty', 'verify-upload', 'download-file', 'rename-transfer', 'delete-file'}
BETA_GATED_ACTIONS = frozenset({'plugins/unload', 'plugins/force-release', 'console/launch-ini/plugins/preview',
                                'console/launch-ini/plugins/save', 'rte/poke-preview',
                                'rte/poke-apply'})
_TERMINAL_EVENTS = {'READY', 'ALIVE', 'BROWSER_OPENED', 'BROWSER_OPEN_FAILED', 'ADAPTER_FAILED',
                    'REQUEST_FAILED', 'REQUEST_SUCCEEDED', 'BROWSER_DISCONNECTED', 'STOPPED', 'FATAL',
                    'MODULE_LOADED', 'MODULE_UNLOADED'}
_TERMINAL_GROUPS = {'bridge', 'idle', 'adapter', 'connect', 'status', 'storage', 'console',
                    'plugins', 'transfer', 'games', 'library', 'session', 'stream360', 'rte',
                    'repos', 'registry', 'browse', 'launch', 'scan', 'metadata', 'discord',
                    'profiles', 'favorites', 'discover', 'usb', 'recovery', 'browser', 'launcher', 'settings', 'other'}
_TERMINAL_CODES = set(ERRORS) | {'VALIDATION','TIMEOUT','INTERNAL_ERROR','REQUEST_INTERRUPTED',
                                 'REQUEST_INCOMPLETE','RESPONSE_INTERRUPTED','BIND_FAILED',
                                 'BRIDGE_ALREADY_RUNNING',
                                 'SERVER_EXIT','NORMAL','INTERRUPTED','UNEXPECTED',
                                 'ACCESS_DENIED','SESSION_CONFLICT','RATE_LIMIT'}
# Route names only; never log request bodies, console paths, hashes, PINs or keys.
_TERMINAL_ACTIONS = set('''connect status browse validate launch
    storage/discover storage/capacity storage/health
    games/addons games/title-update games/install-plan games/inspect games/propose
    games/list games/cover games/remove games/save
    library/list library/label library/clear library/prune-uninspected
    metadata/lookup profiles/list profiles/save profiles/remove
    favorites/list favorites/save favorites/remove scan/start scan/step scan/cancel
    transfer/start transfer/chunk transfer/approve transfer/finish transfer/cancel
    transfer/status transfer/cleanup recovery/status
    plugins/capabilities plugins/library plugins/inspect plugins/forget plugins/load
    plugins/unload plugins/force-release plugins/list plugins/register plugins/remove
    registry/list registry/check repos/list repos/save repos/remove repos/check
    console/launch-ini console/launch-ini-switch console/launch-ini/plugins
    console/launch-ini/plugins/preview console/launch-ini/plugins/save
    console/notify console/power console/screenshot console/storage-compare controller/capabilities controller/pulse rte/status rte/build rte/read rte/poke-preview rte/poke-apply
    discord/status discord/start discord/stop launcher/settings launcher/save settings/read settings/save settings/admin discover/status discover/filters discover/suggest discover/search discover/detail usb/inventory
    stream360/start stream360/frame stream360/audio stream360/audio-enable stream360/status stream360/prepare-unload
    stream360/stop session/pair session/phone-pair session/phone-pin
    session/resume session/logout'''.split())
_TERMINAL_FREQUENT_ACTIONS = {'status','recovery/status','session/resume',
    'stream360/frame','stream360/audio','stream360/status','rte/status','rte/read','discord/status',
    'transfer/chunk','transfer/status','scan/step'}
_terminal_last = {}
_terminal_recent = deque(maxlen=8)
_terminal_lock = threading.Lock()


def operation_group(action):
    """A fixed label for terminal diagnostics; never print route or request data."""
    if not isinstance(action, str):return 'other'
    if action.startswith('launch-ini-'):return 'console'
    if action=='validate':return 'launch'
    if action in TRANSFER_ACTIONS or action=='receive':return 'transfer'
    if action.startswith('plugin-') or action=='plugins':return 'plugins'
    group=action.split('/',1)[0]
    return group if group in _TERMINAL_GROUPS else 'other'


def terminal_status(event, *, group='bridge', code=None, http=None, stage=None, pid=None,
                    hresult=None, architecture=None, phase=None, module_status=None, path_mode=None,
                    module=None, action=None):
    """Allowlisted terminal line with no paths, tokens or raw errors."""
    if event not in _TERMINAL_EVENTS:raise ValueError('Unknown terminal status event.')
    group=group if group in _TERMINAL_GROUPS else 'other'
    code=code if isinstance(code,str) and code in _TERMINAL_CODES else None
    stage=stage if isinstance(stage,str) and stage in STAGES | {'request','response'} else None
    http=http if type(http) is int and 100<=http<=599 else None
    pid=pid if type(pid) is int and pid>0 else None
    hresult=hresult if isinstance(hresult,str) and re.fullmatch(r'0x[0-9A-Fa-f]{8}',hresult) else None
    architecture=architecture if architecture in ('x86','x64') else None
    phase=phase if phase in MODULE_PHASES else None
    status_phase=phase=='module-result' or (code=='MODULE_UNLOAD_FAILED' and phase=='module-inventory')
    module_status=module_status if status_phase and isinstance(module_status,str) and re.fullmatch(r'0x[0-9A-Fa-f]{8}',module_status) else None
    path_mode=path_mode if path_mode in ('selected-path','verified-usb-alias') else None
    module=module if event in ('MODULE_LOADED','MODULE_UNLOADED') and isinstance(module,str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}\.xex',module,re.I) else None
    action=action if isinstance(action,str) and action in _TERMINAL_ACTIONS and event in ('REQUEST_FAILED','REQUEST_SUCCEEDED') else None
    key=(event,group,code,http,stage,hresult,architecture,phase,module_status,path_mode,module,action)
    now=time.monotonic()
    with _terminal_lock:
        previous=_terminal_last.get(key)
        immediate=event in ('MODULE_LOADED','MODULE_UNLOADED') or (event=='REQUEST_SUCCEEDED' and action not in _TERMINAL_FREQUENT_ACTIONS)
        if not immediate and previous and now-previous[0]<60:
            _terminal_last[key]=(previous[0],previous[1]+1)
            return
        repeat=f' repeats={previous[1]}' if previous and previous[1] else ''
        _terminal_last[key]=(now,0)
        details=[f'group={group}']
        if action:details.append(f'action={action}')
        if module:details.append(f'module={module}')
        if code:details.append(f'code={code}')
        if stage:details.append(f'stage={stage}')
        if phase:details.append(f'phase={phase}')
        if path_mode:details.append(f'path_mode={path_mode}')
        if module_status:details.append(f'module_status={module_status}')
        if http:details.append(f'http={http}')
        if pid:details.append(f'pid={pid}')
        if architecture:details.append(f'arch={architecture}')
        if hresult:details.append(f'hresult={hresult}')
        line=f'[{time.strftime("%H:%M:%S")}] {event} '+ ' '.join(details)+repeat
        if event!='ALIVE' and not (event=='REQUEST_SUCCEEDED' and action in _TERMINAL_FREQUENT_ACTIONS):
            _terminal_recent.append(line)
        print(line,flush=True)


def terminal_module_success(action, result):
    """Print only console-confirmed module actions, never request-supplied paths."""
    expected={'plugins/load':('loaded','MODULE_LOADED'),
              'plugins/unload':('unloaded','MODULE_UNLOADED'),
              'plugins/force-release':('unloaded','MODULE_UNLOADED')}.get(action)
    if expected and isinstance(result,dict) and result.get('state')==expected[0]:
        terminal_status(expected[1],group='plugins',module=result.get('name'))


def terminal_request_success(action, result):
    """Report completed API actions; repeated polling is condensed."""
    if isinstance(action,str) and action.startswith('cpu-key/'):
        return  # The private read and its consent flow never enter terminal status.
    if action in ('plugins/load','plugins/unload','plugins/force-release'):
        terminal_module_success(action,result)
    else:
        terminal_status('REQUEST_SUCCEEDED',group=operation_group(action),action=action,http=200)


def render_heartbeat(server, number):
    active=getattr(server.bridge,'active_adapter',None)
    group=active if active in _TERMINAL_GROUPS else 'idle'
    port=server.server_address[1]
    header=f'Nebulah Link | heartbeat #{number} | pid={os.getpid()} | port={port} | adapter={group}'
    sessions=getattr(getattr(server,'browser_sessions',None),'sessions',())
    with _terminal_lock:
        if sys.stdout.isatty() and sessions:
            os.system('cls' if os.name=='nt' else 'clear')
            print(header)
            print('Recent status (newest last):')
            for line in _terminal_recent:print(line)
            print('Ctrl+C stops the bridge.',flush=True)
        elif sys.stdout.isatty():
            print(header+' | waiting for PC pairing; startup token remains above',flush=True)
        else:
            print(f'[{time.strftime("%H:%M:%S")}] {header}',flush=True)


def record_bridge_uptime(server, event, number=0):
    started=getattr(server,'bridge_started',None)
    if started is None:return
    try:
        BRIDGE_UPTIME_LOG.parent.mkdir(parents=True,exist_ok=True)
        if BRIDGE_UPTIME_LOG.exists() and BRIDGE_UPTIME_LOG.stat().st_size>1048576:
            BRIDGE_UPTIME_LOG.replace(BRIDGE_UPTIME_LOG.with_name('bridge-uptime.previous.log'))
        with BRIDGE_UPTIME_LOG.open('a',encoding='ascii') as log:
            log.write(f'{time.strftime("%Y-%m-%dT%H:%M:%S")} event={event} pid={os.getpid()} uptime_s={int(time.monotonic()-started)} heartbeat={number}\n')
    except OSError:
        pass  # Diagnostics must not interrupt console service.

def bridge_heartbeat(server, stop):
    number=0
    while not stop.wait(30):
        number+=1
        render_heartbeat(server,number)
        record_bridge_uptime(server,'HEARTBEAT',number)
        if getattr(server,'phone_host',False):
            try:server.browser_sessions.save_handoff(SESSION_HANDOFF_PATH,server.bridge.target)
            except OSError:pass

def validate_xex(data, allow_module=False):
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
    metadata = {}
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
        if key == 0x00040006:
            media, version, base_version, title = struct.unpack_from('>4I', data, value)
            metadata = {'title_id':f'{title:08X}', 'media_id':f'{media:08X}', 'version':f'{version:08X}', 'base_version':f'{base_version:08X}', 'disc':data[value+18], 'disc_count':data[value+19]}
    if not flags & 1 and not (allow_module and flags & 8):
        raise ValueError('XEX does not declare an executable module.')
    return {'valid':True, 'plugin':bool(flags & 8), 'hash':hashlib.sha256(data).hexdigest(),
            'size':len(data), 'metadata':metadata, 'checks':['XEX2 magic and title/module flag','Header and security bounds','Optional-header bounds']}

def safe_path(path, drives):
    if not isinstance(path, str) or len(path)>512 or not re.fullmatch(r'[A-Za-z0-9_]+:\\[^\x00-\x1f"<>|?*:/]*',path):
        raise ValueError('Use an absolute console path on a discovered storage root.')
    if any(s in ('.','..') for s in path.split('\\')):
        raise ValueError('Relative path segments are not allowed.')
    if not any(path.lower().startswith(d.lower()) for d in drives):
        raise ValueError('Storage root has not been discovered on this console.')
    return path

def normalize_directory_entries(raw, directory):
    """Accept leaf names or exact direct-child paths; never flatten other paths."""
    if not isinstance(raw,list):
        raise BridgeDiagnostic('STORAGE_LIST_INVALID', 'storage')
    prefix=directory.rstrip('\\')+'\\'
    entries=[]; rejected=0
    for entry in raw[:10000]:
        if not isinstance(entry,dict) or not isinstance(entry.get('name'),str):
            rejected+=1;continue
        name=entry['name']
        # SDK versions can return the full console path in IXboxFile.Name.
        if name.lower().startswith(prefix.lower()):name=name[len(prefix):]
        if entry.get('directory') is True:name=name.rstrip('\\')
        if not re.fullmatch(r'[^\\/\x00-\x1f:"<>|?*]+',name) or name in ('.','..'):
            rejected+=1;continue
        try:size=max(0,int(entry.get('size',0)))
        except (ValueError,TypeError,OverflowError):rejected+=1;continue
        entries.append({'name':name,'directory':bool(entry.get('directory')),'size':size})
    if raw and not entries:
        raise BridgeDiagnostic('STORAGE_LIST_INVALID','storage')
    return {'files':entries,'listing':{'received':len(raw),'shown':len(entries),'rejected':rejected,'truncated':len(raw)>10000}}

def normalize_drives(raw):
    """Accept SDK BSTR or adapter list; validate each discovered root separately."""
    if isinstance(raw,str):raw=[raw]
    if not isinstance(raw,list):return []
    roots=[]
    for item in raw:
        if not isinstance(item,str):continue
        for part in item.split(';'):
            match=re.fullmatch(r'([A-Za-z0-9_]+)(?::\\?)?',part.strip())
            if match:
                root=match[1]+':\\'
                if root.lower() not in [r.lower() for r in roots]:roots.append(root)
    return roots

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
    fields={}
    reported=s.get('telemetry_fields')
    if not isinstance(reported,dict):reported={}
    for field in ('type','kernel','motherboard','cpu','gpu','edram','board_temperature','executable','title_id'):
        entry=reported.get(field)
        if not isinstance(entry,dict):entry={}
        state=entry.get('state');source=entry.get('source')
        fields[field]={
            'state':state if state in ('OK','UNAVAILABLE','CHANNEL_FAILED','COMMAND_FAILED','COMMAND_REJECTED','INVALID_RESPONSE','OUT_OF_RANGE','COM_BINDING_FAILED') else 'UNAVAILABLE',
            'source':source if source in ('xdevkit','xbdm','jrpc') else 'none'}
    support=s.get('plugin_support')
    if not isinstance(support,dict):support={}
    observed=support.get('observed')
    if not isinstance(observed,list):observed=[]
    support={'observed':[name for name in ('jrpc.xex','jrpc2.xex','rpc.xex','xrpc.xex') if name in observed],
             'module_scan':'ok' if support.get('module_scan')=='ok' else 'unavailable',
             'jrpc':support.get('jrpc') if support.get('jrpc') in ('responding','rejected','failed') else 'unavailable'}
    board=s.get('motherboard')
    boards={v.lower():v for v in ('Xenon','Zephyr','Falcon','Opus','Jasper','Trinity','Corona','Winchester')}
    board=boards.get(board.lower(),'Unavailable') if isinstance(board,str) else 'Unavailable'
    return {'temperatures':temperatures,'current_title':{'executable':executable or None,'title_id':title_id.upper() if title_id else None},
            'motherboard':board,'telemetry_fields':fields,'plugin_support':support}


class Bridge:
    def __init__(self, powershell, platform_supported=None):
        # Tests can inject a synthetic adapter on any host. The real launcher
        # passes platform_supported explicitly.
        self.recovery_hold=None; self.launch_ini_edit_hold=None; self.companion=None; self.stream360=None; self.discord_presence=None; self.igdb=None; self.rte_pokes={}; self.last_title={}; self.powershell=powershell; self.platform_supported=True if platform_supported is None else platform_supported; self.target=None; self.drives=[]; self.accessible_roots=None; self.tickets={}; self.private_tickets={}; self.game_inspections={}; self.plugin_managed={}; self.plugin_unload_uncertain=set(); self.plugin_force_attempted=set(); self.plugin_unload_target=None; self.active_adapter=None; self.connection_toast=None
    def require_recovery(self, error):
        # Preserve the first failure. No keys, console identifiers or raw exceptions.
        if self.recovery_hold is None:
            self.recovery_hold=error.payload()['diagnostic']
        self.tickets.clear(); self.private_tickets.clear(); self.game_inspections.clear(); self.rte_pokes.clear()
    def recovery_error(self):
        return BridgeDiagnostic('RECOVERY_REQUIRED', 'operation')
    def toast_title(self, title):
        executable=title.get('executable')
        title_id=title.get('title_id')
        # Boot helpers can answer JRPC before the dashboard is visible.
        return executable if executable and (executable.lower().rsplit('\\',1)[-1]=='dash.xex' or
                    title_id not in (None,'F5D10000','FFFE07D1')) else None
    def adapter(self, action, **kwargs):
        if self.recovery_hold is not None:raise self.recovery_error()
        self.active_adapter=operation_group(action)
        try:
            return self._adapter(action, **kwargs)
        except BridgeDiagnostic as error:
            terminal_status('ADAPTER_FAILED',group=operation_group(action),code=error.code,
                            stage=error.stage,hresult=error.hresult,architecture=error.architecture,
                            phase=error.phase,module_status=error.module_status,path_mode=error.path_mode)
            if action in TRANSFER_ACTIONS or error.code=='ADAPTER_TIMEOUT':
                self.require_recovery(error)
            raise
        finally:
            self.active_adapter=None
    def _adapter(self, action, **kwargs):
        if not self.platform_supported:
            raise BridgeDiagnostic('PLATFORM_UNSUPPORTED')
        try:
            p=subprocess.run([self.powershell,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(ROOT/'bridge/neighborhood.ps1')],
                input=json.dumps({'action':action,'target':self.target or '',**kwargs}).encode('ascii'),capture_output=True,timeout=BULK_PROCESS_TIMEOUT if action in ('upload-file','verify-upload','download-file','receive','launch-ini-save','launch-ini-read') else 40)
        except FileNotFoundError:
            raise BridgeDiagnostic('POWERSHELL_NOT_FOUND') from None
        except subprocess.TimeoutExpired:
            raise BridgeDiagnostic('ADAPTER_TIMEOUT') from None
        except OSError:
            raise BridgeDiagnostic('POWERSHELL_START_FAILED') from None
        try: result=json.loads(p.stdout.decode('utf-8-sig'))
        except (UnicodeDecodeError,ValueError,TypeError): result=None
        if p.returncode:
            if isinstance(result,dict) and isinstance(result.get('diagnostic'),dict):
                d=result['diagnostic']
                diagnostic=BridgeDiagnostic(d.get('code'),d.get('stage'),d.get('architecture'),d.get('hresult'),d.get('phase'),d.get('module_status'),d.get('path_mode'))
                raise diagnostic
            # Detect policy failures without forwarding any process output.
            if any(marker.encode('ascii') in (p.stderr or b'') for marker in ('PSSecurityException','UnauthorizedAccess','about_Execution_Policies')):
                raise BridgeDiagnostic('POWERSHELL_POLICY')
            raise BridgeDiagnostic('ADAPTER_PROCESS_FAILED')
        if not isinstance(result,dict) or 'diagnostic' in result:
            raise BridgeDiagnostic('ADAPTER_RESPONSE_INVALID')
        return result
    def status(self):
        s=self.adapter('status')
        storage=s.get('storage') if isinstance(s.get('storage'),dict) else {}
        fields=s.get('telemetry_fields') if isinstance(s.get('telemetry_fields'),dict) else {}
        live_fields=('kernel','executable','title_id','cpu','gpu','edram','board_temperature')
        if storage.get('state')=='FAILED' and not any(
                isinstance(fields.get(name),dict) and fields[name].get('state')=='OK' for name in live_fields):
            # OpenConsole may return a COM object for an unreachable console.
            raise BridgeDiagnostic('CONSOLE_OPEN_FAILED','operation')
        if self.target=='':
            resolved=s.get('resolved_target')
            if not isinstance(resolved,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,253}',resolved):
                raise BridgeDiagnostic('DEFAULT_CONSOLE_FAILED','default-console')
            self.target=resolved
        self.drives=normalize_drives(s.get('drives',[]))
        if self.accessible_roots is not None:
            self.drives=[root for root in self.drives if root.lower() in self.accessible_roots]
        storage={'source':storage.get('source') if storage.get('source') in ('xdevkit','xbdm','none') else 'none', 'state':storage.get('state') if storage.get('state') in ('OK','EMPTY','FAILED') else 'UNAVAILABLE'}
        # Only explicit status fields leave the bridge. No raw adapter payloads.
        result={'type':str(s.get('type','Unavailable'))[:64], 'kernel':str(s.get('kernel','Unavailable'))[:64], 'drives':self.drives, 'storage':storage, 'adapter_version':ADAPTER_VERSION if s.get('adapter_version')==ADAPTER_VERSION else None, **sanitize_telemetry(s)}
        self.last_title=result['current_title']
        toast=self.connection_toast
        if toast and toast['target']==self.target and not toast['attempted']:
            executable=self.toast_title(self.last_title)
            if executable!=toast['executable']:
                toast['executable']=executable
                toast['ready_at']=time.monotonic()+5 if executable else None
            elif executable and result['plugin_support']['jrpc']=='responding' and time.monotonic()>=toast['ready_at']:
                # Count the attempt before calling JRPC so a timeout cannot spam the console.
                toast['attempted']=True
                try:
                    reply=self._adapter('notify',message='Nebulah Link connected')
                    toast['result']='accepted' if reply.get('accepted') is True else 'unconfirmed'
                except BridgeDiagnostic:
                    toast['result']='unconfirmed'
                result['connection_toast']=toast['result']
        if self.discord_presence:self.discord_presence.update(self.last_title)
        if self.companion:result['launch_tracking']=self.companion.observe(self.last_title)
        return result
    def inspect(self,path,allow_module=False):
        if not path.lower().endswith('.xex'):raise ValueError('Only XEX files may be inspected.')
        with tempfile.TemporaryDirectory(prefix='nebulah-') as folder:
            dest=Path(folder)/'inspect.xex';self.adapter('receive',path=path,local=str(dest))
            if dest.stat().st_size>MAX_XEX:raise ValueError('XEX exceeds inspection size limit.')
            return validate_xex(dest.read_bytes(),allow_module=allow_module)
    def workspace(self):
        if self.companion is None:self.companion=Companion(self)
        return self.companion
    def dispatch(self,action,data):
        # HTTPServer is intentionally single-threaded. Do not introduce concurrent
        # console calls to make blocked HTTP requests responsive.
        if action in BETA_GATED_ACTIONS and not (action == 'plugins/unload' and data.get('route') == 'component'):
            raise ValueError('This action is paused for the public beta until its console trial passes.')
        if action=='recovery/status':
            return {'recovery_required':self.recovery_hold is not None, 'failure':self.recovery_hold}
        if self.recovery_hold is not None and action not in ('connect','transfer/cancel','transfer/status','transfer/cleanup','stream360/status','stream360/prepare-unload','stream360/stop','discord/status','discord/stop'):
            raise self.recovery_error()
        if action=='transfer/cleanup' and self.recovery_hold is not None:
            if data.get('recovery_confirmed') is not True:
                raise self.recovery_error()
            self.recovery_hold=None
        if action.startswith(('profiles/','favorites/','library/','metadata/','scan/','transfer/')) or action in ('storage/capacity','storage/health','games/addons','games/title-update','games/install-plan'):
            return self.workspace().dispatch(action,data)

        if action.startswith('discord/'):
            from discord_presence import DiscordPresence
            if self.discord_presence is None:self.discord_presence=DiscordPresence()
            if action=='discord/status':
                if data:raise ValueError('Discord status takes no options.')
                return self.discord_presence.snapshot()
            if action=='discord/start':
                if self.target is None:raise ValueError('Connect a console first.')
                if set(data)!={'client_id','image_key'}:raise ValueError('Discord application and image asset required.')
                return self.discord_presence.start(data['client_id'],data['image_key'],self.last_title)
            if action=='discord/stop':
                if data:raise ValueError('Discord stop takes no options.')
                return self.discord_presence.stop()
            raise ValueError('Unknown Discord operation.')

        if action.startswith('discover/'):
            from igdb_discover import IGDB
            if self.igdb is None:self.igdb=IGDB()
            method={'discover/status':self.igdb.status,'discover/filters':self.igdb.filters,
                    'discover/suggest':self.igdb.suggest,'discover/search':self.igdb.search,
                    'discover/detail':self.igdb.detail}.get(action)
            if method is None:raise ValueError('Unknown discovery operation.')
            try:return method(data)
            except ValueError as error:raise CompanionError(str(error)) from None
            except (OSError,KeyError,TypeError,json.JSONDecodeError):raise CompanionError('IGDB is unavailable. Check the bridge PC connection and credentials.') from None
        if action=='usb/inventory':
            from usb_inventory import inventory
            try:return inventory(data)
            except (ValueError,OSError,subprocess.TimeoutExpired) as error:
                raise CompanionError(str(error) if isinstance(error,ValueError) else 'Windows USB inventory is unavailable.') from None

        if action.startswith('repos/') or action.startswith('plugins/'):
            if action in ('plugins/capabilities','plugins/library','plugins/inspect','plugins/forget','plugins/load','plugins/unload','plugins/force-release','plugins/managed-state','plugins/install','plugins/slots'):
                from plugin_adapter import NeighborhoodPluginAdapter
                return NeighborhoodPluginAdapter(self).dispatch(action,data)
            store=Repositories()
            if action=='repos/list':return {'repositories':store.list()}
            if action=='repos/save':return store.save(data.get('repository'))
            if action=='repos/remove':return store.remove(data.get('repository'))
            if action=='repos/check':return store.check(data.get('repository'))
            if action=='plugins/register':return store.register_plugin(data.get('name'),data.get('version'),data.get('repository'))
            if action=='plugins/remove':return store.remove_plugin(data.get('name'))
            if action=='plugins/list':
                from plugin_adapter import NeighborhoodPluginAdapter
                console={'state':'disconnected','items':[]}
                if self.target is not None:
                    try:
                        raw=self.adapter('plugins')
                        modules=raw.get('modules')
                        if not isinstance(modules,list):raise ValueError('Module listing unavailable.')
                        names={};rejected=0
                        for module in modules:
                            name=module.get('name') if isinstance(module,dict) else None
                            if isinstance(name,str) and 0<len(name)<=260 and not re.search(r'[\x00-\x1f]',name):names.setdefault(name.casefold(),name)
                            else:rejected+=1
                        self.plugin_unload_uncertain.intersection_update(names)
                        self.plugin_force_attempted.intersection_update(names)
                        if not self.plugin_unload_uncertain:self.plugin_unload_target=None
                        adapter_boundary=NeighborhoodPluginAdapter(self)
                        console={'state':'observed','items':[{'name':names[key],'state':'loaded-module','plugin_classification':'unverified',
                                'managed_by_bridge':key in self.plugin_managed,
                                'bridge_load_path':self.plugin_managed[key].get('runtime_path') if isinstance(self.plugin_managed.get(key),dict) else None,
                                'bridge_selected_path':self.plugin_managed[key].get('path') if isinstance(self.plugin_managed.get(key),dict) else None,
                                'unload_uncertain':key in self.plugin_unload_uncertain,
                                'force_ready':key in self.plugin_unload_uncertain and key not in self.plugin_force_attempted,
                                'unload_ready':adapter_boundary.unload_allowed(names[key])}
                                for key in sorted(names)[:512]]}
                        adapter_rejected=raw.get('rejected',0)
                        if type(adapter_rejected) is not int or not 0<=adapter_rejected<=4096:adapter_rejected=0
                        console.update(received=len(modules)+adapter_rejected,rejected=rejected+adapter_rejected,truncated=len(names)>512,source=raw.get('source') if raw.get('source') in ('xdevkit','xbdm','none') else 'xdevkit')
                        if len(names)>512 or rejected or adapter_rejected or raw.get('state')=='partial':console['state']='partial'
                        if raw.get('state')=='unavailable':console.update(state='unavailable',items=[])
                    except Exception:console={'state':'unavailable','items':[]}
                backend=[{'name':n,'state':'loaded-bundled-component','repository':'Nebulah360/Nebulah-Web-App'} for n in ('companion','diagnostics','game_catalog','game_paths','hash_registry','repositories') if n in sys.modules]
                return {'console':console,'backend':backend,'user':store.user_plugins(),'note':'Observed console modules may include titles and system modules. Only eligible DLL/plugin files may use module loading.'}
            raise ValueError('Unknown inventory operation.')

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
            previous_hold=self.recovery_hold
            if previous_hold is not None and data.get('recovery_confirmed') is not True:
                raise self.recovery_error()
            target=data.get('target','')
            if not isinstance(target,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{0,253}',target):raise ValueError('Invalid console name or local IP.')
            if not target:
                from app_settings import load
                target=load()['default_console_ip']
            if self.stream360 is not None and self.target is not None and target != self.target:
                try:self.stream360.stop()
                except ValueError as error:raise CompanionError(str(error)) from None
            # Only an explicit, confirmed connect may probe a held console.
            # Keep the failed transfer evidence until that probe succeeds.
            self.last_title={}
            if self.discord_presence:self.discord_presence.update(None)
            self.target=target; self.drives=[]; self.accessible_roots=None; self.tickets={}; self.private_tickets={}; self.game_inspections={}; self.plugin_managed={}; self.launch_ini_edit_hold=None; self.rte_pokes={}
            self.recovery_hold=None
            try:
                result=self.status()
                if self.target != self.plugin_unload_target:
                    self.plugin_unload_uncertain.clear();self.plugin_force_attempted.clear();self.plugin_unload_target=None
                if self.companion:self.companion.reset()
                if self.toast_title(self.last_title):
                    try:
                        from plugin_adapter import NeighborhoodPluginAdapter
                        result['companion_cleanup']=NeighborhoodPluginAdapter(self).cleanup_companion_runs()
                    except (BridgeDiagnostic, ValueError, OSError):
                        result['companion_cleanup']={'state':'deferred'}
                else:
                    result['companion_cleanup']={'state':'deferred'}
                support=result['plugin_support']
                if self.connection_toast is None or self.connection_toast['target']!=self.target:
                    executable=self.toast_title(result['current_title'])
                    self.connection_toast={'target':self.target,'executable':executable,
                                           'ready_at':time.monotonic()+5 if executable else None,
                                           'attempted':False,'result':'pending'}
                result['connection_toast']=('already-sent' if self.connection_toast['attempted'] else
                                            'pending' if support['jrpc']=='responding' else 'unavailable')
                return result
            except Exception:
                self.target=None;self.drives=[]
                if previous_hold is not None:self.recovery_hold=previous_hold
                raise
        if action.startswith('stream360/'):
            from stream360.receiver import Stream360Receiver
            if action=='stream360/start':
                if self.target is None:raise CompanionError('Connect a console first.')
                if set(data)!= {'console_ip'}:raise CompanionError('Enter the console LAN IPv4 address.')
                try:address=ipaddress.ip_address(data['console_ip'])
                except (ValueError,TypeError):raise CompanionError('Enter a private console LAN IPv4 address.') from None
                if address.version!=4 or not any(address in network for network in
                        (ipaddress.ip_network('10.0.0.0/8'),ipaddress.ip_network('172.16.0.0/12'),ipaddress.ip_network('192.168.0.0/16'))):
                    raise CompanionError('Enter a private console LAN IPv4 address.')
                try:target_address=ipaddress.ip_address(self.target)
                except ValueError:target_address=None
                if target_address is not None and target_address!=address:
                    raise CompanionError('Stream console IP must match the connected Neighborhood target.')
                if self.stream360 is None:self.stream360=Stream360Receiver()
                try:return self.stream360.start(str(address))
                except ValueError as error:raise CompanionError(str(error)) from None
            if action=='stream360/frame':
                if set(data)!={'after'}:raise CompanionError('Frame sequence required.')
                if self.stream360 is None:self.stream360=Stream360Receiver()
                try:sequence,jpeg,codec=self.stream360.frame(data['after'])
                except ValueError as error:raise CompanionError(str(error)) from None
                return {'sequence':sequence,'jpeg':base64.b64encode(jpeg).decode('ascii') if jpeg is not None else None,
                        'codec':codec}
            if action=='stream360/audio':
                if set(data)!={'after'}:raise CompanionError('Audio sequence required.')
                if self.stream360 is None:self.stream360=Stream360Receiver()
                try:sequence,packets=self.stream360.audio(data['after'])
                except ValueError as error:raise CompanionError(str(error)) from None
                return {'sequence':sequence,'packets':[{'rate':rate,'bits':bits,'pcm':base64.b64encode(payload).decode('ascii')}
                                                     for _,rate,bits,payload in packets]}
            if action=='stream360/audio-enable':
                if set(data)!={'enabled'}:raise CompanionError('Audio selection required.')
                if self.stream360 is None:self.stream360=Stream360Receiver()
                try:return self.stream360.set_audio(data['enabled'])
                except ValueError as error:raise CompanionError(str(error)) from None
            if data:raise CompanionError('Stream360 operation takes no options.')
            if self.stream360 is None:self.stream360=Stream360Receiver()
            try:
                if action=='stream360/status':
                    return {**self.stream360.status(),
                            'unload_uncertain':'xbox360stream.xex' in self.plugin_unload_uncertain}
                if action=='stream360/prepare-unload':return self.stream360.prepare_unload()
                if action=='stream360/stop':return self.stream360.stop()
            except ValueError as error:raise CompanionError(str(error)) from None
            raise CompanionError('Unknown Stream360 operation.')
        if self.target is None:raise ValueError('Connect a console first.')
        if action=='status':return self.status()
        if action=='controller/capabilities':
            if data:raise ValueError('Controller capability check takes no options.')
            try:
                component=self.adapter('component-probe')
                available=(component.get('protocol')==4 and
                           self.adapter('component-input-probe').get('available') is True)
            except (BridgeDiagnostic,ValueError,OSError):available=False
            return {'available':available,'reason':'Companion input ready for user 0.' if available else
                    'Load the compatible Nebulah Companion XEX to use browser controller input.'}
        if action=='controller/pulse':
            buttons={'up':0x0001,'down':0x0002,'left':0x0004,'right':0x0008,
                     'start':0x0010,'back':0x0020,'lb':0x0100,'rb':0x0200,
                     'a':0x1000,'b':0x2000,'x':0x4000,'y':0x8000}
            if set(data)!={'button'} or not isinstance(data['button'],str) or data['button'] not in buttons:
                raise ValueError('Choose one controller button.')
            if not self.dispatch('controller/capabilities',{})['available']:
                raise ValueError('Nebulah Companion controller input is unavailable.')
            try:return self.adapter('component-input-pulse',buttons=buttons[data['button']])
            except BridgeDiagnostic as error:
                if error.module_status == '0x0000B105':raise ValueError('Virtual controller binding was not confirmed on this console.') from None
                if error.module_status == '0x0000B104':raise ValueError('The running title did not read the input press.') from None
                raise
        if action=='console/screenshot':
            if data:raise ValueError('Screen capture takes no options.')
            from screenshot import capture
            try:return capture(self.target)
            except (OSError,ValueError) as error:
                raise CompanionError('Xbox screen capture is unavailable. Check the XBDM connection and current display mode.') from None
        if action=='console/storage-compare':
            if data:raise ValueError('Storage comparison takes no options.')
            from xbdm import drives as xbdm_drives
            neighborhood=self.status()['drives']
            try:direct=xbdm_drives(self.target)
            except (OSError,ValueError):return {'state':'unavailable','neighborhood':neighborhood,'xbdm':[]}
            neighborhood_names={root.casefold() for root in neighborhood}
            direct_names={root.casefold() for root in direct}
            return {'state':'compared','neighborhood':neighborhood,'xbdm':direct,
                    'only_neighborhood':[root for root in neighborhood if root.casefold() not in direct_names],
                    'only_xbdm':[root for root in direct if root.casefold() not in neighborhood_names]}
        if action=='rte/status':
            from rte import status as rte_status
            try:return rte_status(self,data)
            except (ValueError,OSError) as error:raise CompanionError(str(error) if isinstance(error,ValueError) else 'XBDM title inspection is unavailable. Check the console connection.') from None
        if action=='rte/build':
            from rte import build as rte_build
            try:return rte_build(self,data)
            except (ValueError,OSError) as error:raise CompanionError(str(error) if isinstance(error,ValueError) else 'Running title file inspection is unavailable. Check the console connection.') from None
        if action=='rte/read':
            from rte import read as rte_read
            try:return rte_read(self,data)
            except (ValueError,OSError) as error:raise CompanionError(str(error) if isinstance(error,ValueError) else 'XBDM title memory read is unavailable. Check the console connection.') from None
        if action in ('rte/poke-preview','rte/poke-apply'):
            from rte import preview_poke, apply_poke
            try:return (preview_poke if action.endswith('preview') else apply_poke)(self,data)
            except (ValueError,OSError) as error:raise CompanionError(str(error) if isinstance(error,ValueError) else 'XBDM title memory edit is unavailable. Check the console connection.') from None
        if action=='console/launch-ini':
            if data:raise ValueError('launch.ini status takes no options.')
            from launch_ini import discover
            return discover(self)
        if action=='console/launch-ini-switch':
            from launch_ini import switch
            return switch(self,data)
        if action=='console/launch-ini/plugins':
            if data:raise ValueError('Plugin slot status takes no options.')
            from launch_ini import plugins
            return plugins(self)
        if action=='console/launch-ini/plugins/preview':
            from launch_ini import preview_plugins
            return preview_plugins(self,data)
        if action=='console/launch-ini/plugins/save':
            from launch_ini import save_plugins
            return save_plugins(self,data)
        if action=='console/notify':
            message=data.get('message')
            if set(data)!={'message','confirmed'} or data.get('confirmed') is not True or not isinstance(message,str) or not re.fullmatch(r'[ -~]{1,80}',message):
                raise ValueError('Confirm a printable ASCII Xbox notification of 1–80 characters.')
            result=self.adapter('notify',message=message)
            if result.get('accepted') is not True:
                raise BridgeDiagnostic('CONSOLE_NOTIFY_FAILED','module')
            return {'accepted':True}
        if action=='console/power':
            if set(data)!={'mode','confirmed'} or data.get('confirmed') is not True or data.get('mode') not in ('warm','cold','shutdown'):
                raise ValueError('Choose and confirm a supported console power action.')
            if self.companion and self.companion.transfer and self.companion.transfer.get('state')=='running':
                raise ValueError('Finish or cancel the active transfer before changing console power.')
            mode=data['mode']
            result=self.adapter('power',mode=mode)
            if result.get('accepted') is not True or result.get('mode')!=mode:
                raise BridgeDiagnostic('CONSOLE_POWER_FAILED','power')
            if self.stream360 is not None:self.stream360.stop(force=True)
            self.target=None;self.drives=[];self.accessible_roots=None
            self.connection_toast=None
            self.tickets.clear();self.private_tickets.clear();self.game_inspections.clear();self.plugin_managed.clear();self.rte_pokes.clear()
            self.last_title={}
            if self.discord_presence:self.discord_presence.update(None)
            if self.companion:self.companion.reset()
            return {'accepted':True,'mode':mode,'connection':'reconnect-required'}
        if action=='storage/discover':
            result=self.adapter('storage')
            self.drives=normalize_drives(result.get('drives',[]))
            self.accessible_roots={root.lower() for root in self.drives}
            raw=result.get('storage') if isinstance(result.get('storage'),dict) else {}
            storage={'source':raw.get('source') if raw.get('source') in ('xdevkit','xbdm','none') else 'none',
                     'state':raw.get('state') if raw.get('state') in ('OK','EMPTY','FAILED','PARTIAL','INACCESSIBLE') else 'FAILED'}
            for key in ('checked','unavailable'):
                storage[key]=raw[key] if type(raw.get(key)) is int and 0<=raw[key]<=32 else 0
            return {'drives':self.drives,'storage':storage}

        if action.startswith('games/'):
            if action=='games/inspect':
                path=safe_path(data.get('path'),self.drives)
                v=self.inspect(path)
                filename=path.rsplit('\\',1)[-1]
                result={'file':filename, 'plugin':v['plugin'], 'verification':verify_game(v,filename), 'capabilities':capabilities()}
                self.workspace().store.record_inspection(self.target,path,v)
                now=time.monotonic()
                self.game_inspections={k:s for k,s in self.game_inspections.items() if s['expires']>now}
                try:
                    candidate_from_inspection(v,filename,'Pending user title','Pending user provenance')
                except ValueError:
                    result['candidate_unavailable']='A non-plugin XEX with complete, valid execution metadata is required.'
                else:
                    if len(self.game_inspections)>=MAX_GAME_INSPECTIONS:
                        del self.game_inspections[next(iter(self.game_inspections))]
                    inspection=secrets.token_urlsafe(24)
                    self.game_inspections[inspection]={'filename':filename, 'value':v, 'target':self.target, 'expires':now+GAME_INSPECTION_TTL}
                    result.update(inspection_id=inspection, candidate_expires_in=GAME_INSPECTION_TTL)
                return result
            if action=='games/propose':
                if set(data)-{'inspection_id','title','provenance'}:
                    raise ValueError('Only the inspection ID, title and provenance may be supplied.')
                inspection=data.get('inspection_id')
                snapshot=self.game_inspections.get(inspection) if isinstance(inspection,str) else None
                if snapshot is None or snapshot['expires']<=time.monotonic() or snapshot['target']!=self.target:
                    raise ValueError('Inspection expired or unavailable. Read the file again.')
                # Local candidate storage only; no reviewed catalog or launch authorization.
                candidate=candidate_from_inspection(snapshot['value'],snapshot['filename'],data.get('title'),data.get('provenance'))
                self.workspace().store.save_candidate(candidate)
                return {'candidate':candidate}
            store=GamePaths()
            if action=='games/list':
                entries=store.list(self.target)
                for entry in entries:
                    if entry['title_id']:
                        cached=self.workspace().store.title(entry['title_id'])
                        entry['cover']=cached.get('cover')
                return {'shortcuts':entries}
            if action=='games/cover':
                if type(data.get('id')) is not int:raise ValueError('Shortcut ID required.')
                entry=next((item for item in store.list(self.target) if item['id']==data['id']),None)
                if not entry or not entry['executable']:raise ValueError('Choose an XEX shortcut for cover lookup.')
                path=safe_path(entry['folder']+entry['executable'],self.drives)
                inspected=self.inspect(path)
                if inspected.get('plugin') or not inspected.get('valid'):raise ValueError('Choose a game XEX for cover lookup.')
                ident=inspected.get('metadata',{}).get('title_id')
                metadata=self.workspace().store.title(ident,True)
                store.set_title(self.target,entry['id'],ident)
                return {'cover':metadata.get('cover'),'title_id':ident,'title':metadata.get('title'),'artwork_state':metadata.get('artwork_state')}

            if action=='games/remove':return store.remove(self.target,data.get('id'))
            if action=='games/save':
                folder=safe_path(data.get('folder'),self.drives).rstrip('\\')+'\\'
                executable=data.get('executable','')
                if not isinstance(executable,str) or (executable and (not re.fullmatch(r'[^\\/\x00-\x1f"<>|?*:.]+\.xex',executable,re.I))):
                    raise ValueError('Choose an XEX filename within this folder.')
                # Confirm the folder can be browsed, and an optional launch file exists.
                files=self.dispatch('browse',{'path':folder})['files']
                if executable and not any(not f['directory'] and f['name'].lower()==executable.lower() for f in files):
                    raise ValueError('Selected XEX was not found in this folder.')
                return store.save(self.target,data.get('name'),folder,executable,data.get('mode',''))
            raise ValueError('Unknown games operation.')
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
            files=self.adapter('browse',path=path).get('files')
            return normalize_directory_entries(files,path)
        if action=='browse-many':
            paths=data.get('paths')
            if not isinstance(paths,list) or not 1<=len(paths)<=8:
                raise ValueError('Choose 1–8 folders to browse.')
            paths=[safe_path(path,self.drives) for path in paths]
            result=self.adapter('browse-many',paths=paths)
            listings=result.get('listings') if isinstance(result,dict) else None
            if not isinstance(listings,list) or len(listings)!=len(paths):
                raise BridgeDiagnostic('STORAGE_LIST_INVALID','storage')
            return {'listings':[{'error':True} if isinstance(item,dict) and item.get('error') is True
                    else normalize_directory_entries(item.get('files') if isinstance(item,dict) else None,path)
                    for path,item in zip(paths,listings)]}
        if action=='validate':
            path=safe_path(data.get('path'),self.drives);v=self.inspect(path)
            try:verification=verify_digest(v['hash'],v['size'],data.get('build_id'))
            except RegistryError:verification={'status':'registry-error','eligible_for_install':False,'discrepancies':['Catalog unavailable or malformed.']}
            verification['measurement']='console-file-bytes'
            try:game_verification=verify_game(v,path.rsplit('\\',1)[-1])
            except (ValueError,OSError):game_verification={'status':'catalog-error','label':'Game catalog unavailable'}
            blocked=game_verification['status'] in ('mismatch','revoked','catalog-error') or verification['status'] in ('revoked','mismatch','unknown-build','registry-error')
            component=classify_component(path,v)
            module_hint=bool(component and component['category'] in ('plugins','stealth'))
            blocked=blocked or module_hint
            self.tickets={k:t for k,t in self.tickets.items() if t['expires']>time.monotonic()}
            ticket=secrets.token_urlsafe(24)
            if not v['plugin'] and not blocked:
                self.tickets[ticket]={'path':path,'hash':v['hash'],'expires':time.monotonic()+120,'build_id':data.get('build_id')}
            return {**v,'verification':verification,'game_verification':game_verification,'component':component,
                    'launch_block_reason':'Known plugin/stealth name hint; use explicit plugin inspection.' if module_hint else None,
                    'ticket':None if blocked or v['plugin'] else ticket}
        if action=='launch':
            ticket=data.get('ticket')
            if not isinstance(ticket,str):raise ValueError('A validation ticket is required.')
            t=self.tickets.pop(ticket,None)
            if not t or t['expires']<time.monotonic():raise ValueError('Inspection expired. Inspect the XEX again.')
            v=self.inspect(t['path'])
            if v['plugin'] or not hmac.compare_digest(v['hash'],t['hash']):raise ValueError('File changed. Inspect it again before launching.')
            component=classify_component(t['path'],v)
            if component and component['category'] in ('plugins','stealth'):raise ValueError('Plugin/stealth classification rejected title launch.')
            # Reload catalog so revocation after inspection invalidates the launch.
            verification=verify_digest(v['hash'],v['size'],t.get('build_id'))
            if verification['status'] in ('revoked','mismatch','unknown-build'):raise ValueError('Build verification rejected launch.')
            game_verification=verify_game(v,t['path'].rsplit('\\',1)[-1])
            if game_verification['status'] in ('mismatch','revoked'):raise ValueError('Game baseline rejected launch.')
            self.adapter('launch',path=t['path'])
            self.workspace().launch_accepted(t['path'],v.get('metadata',{}),self.last_title)
            return {'accepted':True,'tracking':'accepted'}
        raise ValueError('Capability not available in this base adapter.')

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,status,body,kind='application/json'):
        raw=json.dumps(body).encode() if kind=='application/json' else body
        try:
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data: https://images.igdb.com; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if getattr(self,'session_cookie',None):self.send_header('Set-Cookie',self.session_cookie)
            self.end_headers();self.wfile.write(raw)
        except (ConnectionError,TimeoutError):
            # The request may already have changed the console. Never replay it,
            # or send an adapter-error response through the same closed socket.
            self.close_connection=True
            terminal_status('BROWSER_DISCONNECTED',group=getattr(self,'_operation','browser'),
                            code='RESPONSE_INTERRUPTED',stage='response',http=status)
            return False
        return True
    def host_ok(self):return self.headers.get('Host') in self.server.allowed_hosts
    def local_client(self):
        try:
            client = ipaddress.ip_address(self.client_address[0])
            host = ipaddress.ip_address(self.server.server_address[0])
            return client.is_loopback or client == host
        except (AttributeError, IndexError, ValueError):
            return False
    def do_GET(self):
        if not self.host_ok():return self.reply(403,{'error':'Host not allowed.'})
        files={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript'),'/controller.js':('controller.js','text/javascript'),'/session.js':('session.js','text/javascript'),'/theme.js':('theme.js','text/javascript'),'/companion.js':('companion.js','text/javascript'),'/stream360.js':('stream360.js','text/javascript'),'/rte.js':('rte.js','text/javascript'),'/iso.js':('iso.js','text/javascript'),'/discord.js':('discord.js','text/javascript'),'/launcher.js':('launcher.js','text/javascript'),'/discover.js':('discover.js','text/javascript'),'/usb.js':('usb.js','text/javascript'),'/nebulah-n.png':('nebulah-n.png','image/png'),'/style.css':('style.css','text/css')}
        if self.path not in files:return self.reply(404,{'error':'Not found.'})
        name,kind=files[self.path];self.reply(200,(ROOT/'dist'/name).read_bytes(),kind)
    def do_POST(self):
        self.session_cookie=None
        self._operation='browser'
        self._action=None
        if not self.host_ok() or self.headers.get('Origin')!='http://'+self.headers.get('Host',''):
            terminal_status('REQUEST_FAILED',group='browser',code='ACCESS_DENIED',http=403)
            return self.reply(403,{'error':'Same-origin browser request required.'})
        auth=self.headers.get('Authorization','')
        if not hasattr(self.server,'browser_sessions'):self.server.browser_sessions=BrowserSessions()
        sessions=self.server.browser_sessions
        cookie=self.headers.get('Cookie','')
        session=sessions.lookup(cookie)
        recovery=None
        if session is None:
            recovery=sessions.recover(cookie,getattr(self.server.bridge,'target',None))
            if recovery=='restored':session=sessions.lookup(cookie)
        paired=self.local_client() and hmac.compare_digest(auth,'Bearer '+self.server.token)
        launch=getattr(self.server,'launch_ticket',None)
        startup_pair=(self.local_client() and self.path=='/api/session/pair' and launch is not None
                      and time.monotonic()<launch['expires'] and hmac.compare_digest(auth,'Bearer '+launch['key']))
        local_pair_request=self.path=='/api/session/local-pair' and self.local_client()
        phone_pair_request=self.path=='/api/session/phone-pair'
        if not paired and not session and not startup_pair and not local_pair_request and not phone_pair_request:
            if recovery=='pending':
                return self.reply(503,{'error':'The local bridge is reconnecting to the previous console. Retry shortly.','reconnecting':True})
            terminal_status('REQUEST_FAILED',group='browser',code='ACCESS_DENIED',http=401)
            return self.reply(401,{'error':'Browser is not paired or the pairing token is incorrect.'})
        try:
            if self.headers.get('Content-Type')!='application/json':raise ValueError('JSON required.')
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=(100000 if self.path=='/api/transfer/chunk' else 4096):raise ValueError('Invalid request size.')
            try:raw_body=self.rfile.read(n)
            except (ConnectionError,TimeoutError):
                self.close_connection=True
                terminal_status('BROWSER_DISCONNECTED',group='browser',code='REQUEST_INTERRUPTED',stage='request')
                return
            if len(raw_body)!=n:
                self.close_connection=True
                terminal_status('BROWSER_DISCONNECTED',group='browser',code='REQUEST_INCOMPLETE',stage='request')
                return
            body=json.loads(raw_body)
            if not isinstance(body,dict):raise ValueError('Object required.')
            if not self.path.startswith('/api/'):raise ValueError('Unknown route.')
            action=self.path[5:]
            self._action=action
            self._operation=operation_group(action)
            if action.startswith(('discord/','launcher/','settings/')) and not self.local_client():
                terminal_status('REQUEST_FAILED',group=operation_group(action),action=action,code='ACCESS_DENIED',http=403)
                return self.reply(403,{'error':'Control PC settings on the bridge PC.'})
            if action=='session/local-pair':
                if not self.local_client() or body:
                    terminal_status('REQUEST_FAILED',group='session',action=action,code='ACCESS_DENIED',http=403)
                    return self.reply(403,{'error':'Open this page on the bridge PC to pair locally.'})
                session=session or sessions.create(waiting=True)
                self.session_cookie=BrowserSessions.cookie(session)
                terminal_request_success(action,{'awaiting_console':True})
                return self.reply(200,{'awaiting_console':True})
            if action=='session/phone-pair':
                target=getattr(self.server.bridge,'target',None)
                client=self.client_address[0]
                result=sessions.check_phone_pin(body.get('pin'),target,client)
                if result=='locked':
                    terminal_status('REQUEST_FAILED',group='session',action=action,code='RATE_LIMIT',http=429)
                    return self.reply(429,{'error':'Too many incorrect PIN attempts from this device. Try again in 15 minutes.'})
                if result!='valid' or not getattr(self.server,'phone_host',False):
                    terminal_status('REQUEST_FAILED',group='session',action=action,code='ACCESS_DENIED',http=401)
                    return self.reply(401,{'error':'Phone PIN is incorrect or unavailable.'})
                state=self.server.bridge.dispatch('status',{})
                session=session or sessions.create()
                sessions.activate(session)
                self.session_cookie=BrowserSessions.cookie(session)
                terminal_request_success(action,{'status':state})
                return self.reply(200,{'status':state})
            if action=='session/pair':
                if not startup_pair:
                    terminal_status('REQUEST_FAILED',group='session',action=action,code='ACCESS_DENIED',http=401)
                    return self.reply(401,{'error':'Startup pairing link expired. Use the token from the bridge window.'})
                self.server.launch_ticket=None
                session=sessions.create(waiting=True)
                self.session_cookie=BrowserSessions.cookie(session)
                terminal_request_success(action,{'awaiting_console':True})
                return self.reply(200,{'awaiting_console':True})
            if session in sessions.waiting and action not in ('connect','session/resume','session/logout','launcher/settings','launcher/save','settings/read','settings/save'):
                terminal_status('REQUEST_FAILED',group=self._operation,action=action,code='SESSION_CONFLICT',http=409)
                return self.reply(409,{'error':'Pairing saved. Connect a console first.'})
            if action.startswith('session/'):
                if not session:
                    terminal_status('REQUEST_FAILED',group='session',action=action,code='ACCESS_DENIED',http=401)
                    return self.reply(401,{'error':'Browser session is unavailable.'})
                if action=='session/resume':
                    result={'awaiting_console':True} if session in sessions.waiting else {'status':self.server.bridge.dispatch('status',{})}
                elif action=='session/logout':
                    sessions.logout(session)
                    if self.local_client():self.server.admin_control=False
                    self.session_cookie=BrowserSessions.cookie('')
                    result={'signed_out':True}
                elif action=='session/phone-pin':
                    if not getattr(self.server,'phone_host',False):
                        terminal_status('REQUEST_FAILED',group='session',action=action,code='VALIDATION',http=400)
                        return self.reply(400,{'error':'Enable phone access in Console > Launcher settings, then restart Nebulah Link.'})
                    if not self.local_client():
                        terminal_status('REQUEST_FAILED',group='session',action=action,code='ACCESS_DENIED',http=403)
                        return self.reply(403,{'error':'Create the phone PIN on this PC.'})
                    target=getattr(self.server.bridge,'target',None)
                    if target is None or getattr(self.server.bridge,'recovery_hold',None) is not None:
                        terminal_status('REQUEST_FAILED',group='session',action=action,code='SESSION_CONFLICT',http=409)
                        return self.reply(409,{'error':'Connect a console before creating a phone PIN.'})
                    pin=sessions.issue_phone_pin(target,session)
                    result={'pin':pin,'url':getattr(self.server,'phone_url','http://'+self.headers['Host']+'/')}
                else:raise ValueError('Unknown session action.')
            elif action.startswith('launcher/'):
                from launcher_settings import load, save
                if action=='launcher/settings':
                    if body:raise ValueError('Launcher settings takes no options.')
                    result=load()
                elif action=='launcher/save':result=save(body)
                else:raise ValueError('Unknown launcher operation.')
            elif action.startswith('settings/'):
                from app_settings import load, save
                if action=='settings/read':
                    if body:raise ValueError('Settings read takes no options.')
                    result={**load(),'admin_control':getattr(self.server,'admin_control',False)}
                elif action=='settings/save':
                    result={**save(body),'admin_control':getattr(self.server,'admin_control',False)}
                elif action=='settings/admin':
                    if set(body)!={'enabled'} or type(body['enabled']) is not bool:
                        raise ValueError('Choose whether Admin control is on or off.')
                    if self.server.bridge.target is None:raise ValueError('Connect a console before enabling Admin control.')
                    self.server.admin_control=body['enabled']
                    result={**load(),'admin_control':self.server.admin_control}
                else:raise ValueError('Unknown settings operation.')
            else:
                from app_settings import load, requires_write
                if requires_write(action,body,self.server.bridge) and not load()['allow_writes'] and not (self.local_client() and getattr(self.server,'admin_control',False)):
                    terminal_status('REQUEST_FAILED',group=self._operation,action=action,code='ACCESS_DENIED',http=403)
                    return self.reply(403,{'error':'Write commands are off. Enable them in Settings on the bridge PC.','permission_required':True})
                previous_target=getattr(self.server.bridge,'target',None) if action=='connect' else None
                result=self.server.bridge.dispatch(action,body)
                if action=='connect':
                    if previous_target!=getattr(self.server.bridge,'target',None):self.server.admin_control=False
                    session=session or sessions.create()
                    sessions.activate(session)
                    self.session_cookie=BrowserSessions.cookie(session)
            terminal_request_success(action,result)
            self.reply(200,result)
        except CompanionError as e:
            terminal_status('REQUEST_FAILED',group=self._operation,action=self._action,code='VALIDATION',http=400)
            self.reply(400,e.payload() if hasattr(e,'payload') else {'error':str(e)})
        except BridgeDiagnostic as e:
            status=423 if e.code=='RECOVERY_REQUIRED' else 504 if e.code=='ADAPTER_TIMEOUT' else 502
            terminal_status('REQUEST_FAILED',group=self._operation,action=self._action,code=e.code,stage=e.stage,http=status,
                            hresult=e.hresult,architecture=e.architecture,phase=e.phase,
                            module_status=e.module_status,path_mode=e.path_mode)
            self.reply(status,{**e.payload(),'recovery_required':self.server.bridge.recovery_hold is not None})
        except (ValueError,KeyError,TypeError) as error:
            terminal_status('REQUEST_FAILED',group=self._operation,action=self._action,code='VALIDATION',http=400)
            if (self._action or '').startswith(('launcher/','settings/')):
                message=str(error) if isinstance(error,ValueError) else 'Invalid launcher settings.'
            else:
                message='Request failed validation or Neighborhood could not complete it. Check the connection, path, and XEX; inspect again before launching.'
            self.reply(400,{'error':message})
        except subprocess.TimeoutExpired:
            terminal_status('REQUEST_FAILED',group=self._operation,action=self._action,code='TIMEOUT',http=504)
            self.reply(504,{'error':'Neighborhood timed out. Verify console reachability before retrying.'})
        except Exception:
            terminal_status('REQUEST_FAILED',group=self._operation,action=self._action,code='INTERNAL_ERROR',http=502)
            self.reply(502,{'error':'Local adapter unavailable. Check Windows, Python and Neighborhood installation.'})
    def setup(self):
        super().setup();self.connection.settimeout(50)

def startup_summary(powershell, root=ROOT):
    """Read local build/configuration only; never connect to or query the console."""
    def source(relative):
        try:return (root/relative).read_text(encoding='utf-8')
        except (OSError,UnicodeError):return ''
    def version(text, pattern):
        match=re.search(pattern,text)
        return int(match[1]) if match else None
    adapter=version(source('bridge/telemetry.ps1'),r'\badapter_version\s*=\s*(\d+)')
    frontend=version(source('dist/app.js'),r'Telemetry adapter: (\d+)')
    wrapper=source('bridge/ComDispatch.cs')
    mode='Explicit IXboxConsole dispatch' if 'console = (IConsoleAutomation)nativeObject' in wrapper else 'Numeric COM dispatch' if '[DispID=' in wrapper else 'Named COM dispatch' if wrapper else 'Missing or unreadable'
    production=bool(source('dist/companion.js')) and bool(source('dist/index.html')) and not re.search(r'Explore demo|id=[\"\']demo[\"\']',source('dist/index.html'),re.I) and not re.search(r'\bdemo\b|demoFiles|demoGames',source('dist/app.js')+source('dist/companion.js'))
    fingerprint=hashlib.sha256(wrapper.encode('utf-8')).hexdigest()[:12] if wrapper else 'unavailable'
    lines=[
        'Adapter configuration (local files; console not queried)',
        f'  Project folder: {root.resolve()}',
        f'  Server expects adapter: {ADAPTER_VERSION}',
        f'  Backend adapter file: {adapter if adapter is not None else "missing/unrecognized"}',
        f'  Frontend adapter file: {frontend if frontend is not None else "missing/unrecognized"}',
        f'  COM binding: {mode}',
        f'  Production UI: {"verified; no demo code" if production else "FAILED: old or missing frontend files"}',
        f'  Wrapper SHA-256 prefix: {fingerprint}',
        f'  PowerShell executable: {powershell}',
        f'  Host platform: {sys.platform}',
        '  PowerShell options: NoProfile, NonInteractive, ExecutionPolicy Bypass (process only)',
        '  Console selection: Neighborhood default unless specified in the browser',
        '  Telemetry: JRPC/JRPC2 with native XBDM fallbacks; XRPC RPC sensors unavailable',
        '  Private console reads: off; CPU key requires separate confirmation',
    ]
    if adapter!=ADAPTER_VERSION or frontend!=ADAPTER_VERSION or mode!='Explicit IXboxConsole dispatch' or not production:
        lines.append('  UPDATE MISMATCH: Update this project folder completely, then restart the bridge.')
    else:lines.append('  Version check: local frontend/backend versions match the server')
    return '\n'.join(lines)


def open_startup_browser(url, preference='default', environment=None):
    """Use the user's Chrome install for phone pairing when requested."""
    if preference=='chrome':
        values=os.environ if environment is None else environment
        roots=(values.get('PROGRAMFILES'),values.get('PROGRAMFILES(X86)'),values.get('LOCALAPPDATA'))
        chrome=next((candidate for root in roots if root
                     for candidate in [Path(root)/'Google'/'Chrome'/'Application'/'chrome.exe'] if candidate.is_file()),None)
        if chrome:return webbrowser.BackgroundBrowser(str(chrome)).open(url)
    return webbrowser.open(url)


@contextmanager
def bridge_instance(name='Local\\NebulahLinkBridge'):
    """Hold one Windows bridge instance across hosts and ports."""
    if os.name!='nt':
        yield True
        return
    import ctypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=(ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p)
    kernel.CreateMutexW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=(ctypes.c_void_p,)
    handle=kernel.CreateMutexW(None,False,name)
    if not handle:raise OSError(ctypes.get_last_error(),'Bridge instance lock unavailable')
    try:yield ctypes.get_last_error()!=183  # ERROR_ALREADY_EXISTS
    finally:kernel.CloseHandle(handle)


def main():
    default_powershell=os.path.join(os.environ.get('WINDIR','C:\\Windows'),'SysWOW64','WindowsPowerShell','v1.0','powershell.exe') if os.name=='nt' else None
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--host',default='127.0.0.1',help='Bind a specific private PC IPv4 address for phone access.');p.add_argument('--port',type=int,default=8765);p.add_argument('--powershell',default=default_powershell)
    p.add_argument('--open-browser',action='store_true',help='Open the local page after successfully binding; pair automatically using a single-use startup link.')
    p.add_argument('--browser',choices=('default','chrome'),default='default',help='Browser for the startup pairing page.')
    a=p.parse_args();ip=ipaddress.ip_address(a.host)
    if ip.version!=4 or not (ip.is_loopback or ip in ipaddress.ip_network('10.0.0.0/8') or ip in ipaddress.ip_network('172.16.0.0/12') or ip in ipaddress.ip_network('192.168.0.0/16')):p.error('Choose loopback or a specific private LAN IPv4 address.')
    with bridge_instance() as available:
        if not available:
            terminal_status('FATAL',code='BRIDGE_ALREADY_RUNNING')
            p.exit(17,'Nebulah Link bridge already running. Close the existing bridge before starting another.\n')
        run_bridge(a,ip,p)


def run_bridge(a,ip,p):
    server=None;local_server=None
    try:
        server=HTTPServer((a.host,a.port),Handler)
        if not ip.is_loopback:local_server=HTTPServer(('127.0.0.1',a.port),Handler)
    except OSError:
        if server:server.server_close()
        terminal_status('FATAL',code='BIND_FAILED')
        p.exit(18,'Could not start the bridge on the selected address/port. Close the old bridge, or choose another --port.\n')
    server.allowed_hosts={f'{a.host}:{a.port}'}
    if ip.is_loopback:server.allowed_hosts.add(f'localhost:{a.port}')
    server.phone_host=not ip.is_loopback
    server.browser_sessions=(BrowserSessions.load_handoff(SESSION_HANDOFF_PATH)
                             if server.phone_host else BrowserSessions())
    server.token=secrets.token_urlsafe(32);server.bridge=Bridge(a.powershell, platform_supported=os.name=='nt')
    if local_server:
        local_server.allowed_hosts={f'127.0.0.1:{a.port}',f'localhost:{a.port}'}
        local_server.phone_host=True
        local_server.phone_url=f'http://{a.host}:{a.port}/'
        local_server.browser_sessions=server.browser_sessions
        local_server.token=server.token
        local_server.bridge=server.bridge
    print(startup_summary(a.powershell), flush=True)
    print(f'\nNebulah Link: http://{a.host}:{a.port}\nKeep this window open. Ctrl+C stops the bridge.\n')
    if local_server:print(f'PC browser: http://127.0.0.1:{a.port}/\n',flush=True)
    if not ip.is_loopback:print('LAN mode: trusted private Wi-Fi only. HTTP is not encrypted. Do not forward this port.\n')
    terminal_status('READY',pid=os.getpid())
    server.bridge_started=time.monotonic()
    record_bridge_uptime(server,'READY')
    if a.open_browser:
        browser_server=local_server or server
        browser_server.launch_ticket={'key':secrets.token_urlsafe(32),'expires':time.monotonic()+120}
        try:
            browser_host='127.0.0.1' if local_server else a.host
            url=f"http://{browser_host}:{a.port}/#pair={browser_server.launch_ticket['key']}"
            if not open_startup_browser(url,a.browser):
                terminal_status('BROWSER_OPEN_FAILED',group='browser')
                print('Open the printed URL in your browser.',flush=True)
            else:terminal_status('BROWSER_OPENED',group='browser')
        except Exception:
            terminal_status('BROWSER_OPEN_FAILED',group='browser')
            print('Open the printed URL in your browser.',flush=True)
    heartbeat_stop=threading.Event()
    heartbeat=threading.Thread(target=bridge_heartbeat,args=(server,heartbeat_stop),name='bridge-heartbeat',daemon=True)
    heartbeat.start()
    reason='NORMAL'
    try:
        if local_server:
            with selectors.DefaultSelector() as ready:
                ready.register(server,selectors.EVENT_READ)
                ready.register(local_server,selectors.EVENT_READ)
                while True:
                    for key,_ in ready.select():key.fileobj._handle_request_noblock()
        else:server.serve_forever()
    except KeyboardInterrupt:reason='INTERRUPTED'
    except Exception:
        reason='UNEXPECTED'
        terminal_status('FATAL',code='SERVER_EXIT')
        record_bridge_uptime(server,'FATAL')
        raise
    finally:
        heartbeat_stop.set()
        heartbeat.join(timeout=1)
        if server.bridge.stream360 is not None:server.bridge.stream360.stop(force=True)
        if server.bridge.discord_presence is not None:server.bridge.discord_presence.stop()
        if server.phone_host:
            try:server.browser_sessions.save_handoff(SESSION_HANDOFF_PATH,server.bridge.target)
            except OSError:
                terminal_status('REQUEST_FAILED',group='session',code='INTERNAL_ERROR')
                print('Phone session handoff could not be saved; re-pair after restart.',flush=True)
        server.server_close()
        if local_server:local_server.server_close()
        terminal_status('STOPPED',code=reason)
        record_bridge_uptime(server,'STOPPED')
if __name__=='__main__':main()
