"""Repository update commands and plugin inventory for Nebulah Link."""
import argparse,json,sys,os,urllib.request,urllib.parse,ipaddress
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bridge'))
from repositories import Repositories,DEFAULT_DB

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',default=str(DEFAULT_DB));sub=p.add_subparsers(dest='action',required=True)
    sub.add_parser('check-updates');sub.add_parser('repos');q=sub.add_parser('plugins');q.add_argument('--bridge',help='Running bridge URL. Token is read from NEBULAH_BRIDGE_TOKEN.')
    for action in ('save-repo','remove-repo'):
        q=sub.add_parser(action);q.add_argument('repository')
    q=sub.add_parser('register-plugin');q.add_argument('name');q.add_argument('--version',required=True);q.add_argument('--repo',required=True)
    q=sub.add_parser('remove-plugin');q.add_argument('name')
    a=p.parse_args();store=Repositories(a.db)
    try:
        if a.action=='check-updates':
            with ThreadPoolExecutor(max_workers=4) as pool:result=list(pool.map(store.check,[r['repository'] for r in store.list()]))
        elif a.action=='repos':result=store.list()
        elif a.action=='save-repo':result=store.save(a.repository)
        elif a.action=='remove-repo':result=store.remove(a.repository)
        elif a.action=='register-plugin':result=store.register_plugin(a.name,a.version,a.repo)
        elif a.action=='remove-plugin':result=store.remove_plugin(a.name)
        elif a.bridge:
            url=urllib.parse.urlsplit(a.bridge)
            if url.scheme!='http' or url.username or url.password or url.query or url.fragment or url.path not in ('','/'):raise ValueError('Use the local bridge HTTP origin.')
            ip=ipaddress.ip_address(url.hostname)
            if ip.version!=4 or not (ip.is_loopback or ip in ipaddress.ip_network('10.0.0.0/8') or ip in ipaddress.ip_network('172.16.0.0/12') or ip in ipaddress.ip_network('192.168.0.0/16')):raise ValueError('Use a private LAN or loopback bridge address.')
            token=os.environ.get('NEBULAH_BRIDGE_TOKEN','')
            if not token:raise ValueError('Set NEBULAH_BRIDGE_TOKEN for the running bridge.')
            origin='http://'+url.netloc
            request=urllib.request.Request(origin+'/api/plugins/list',data=b'{}',headers={'Content-Type':'application/json','Origin':origin,'Authorization':'Bearer '+token})
            from repositories import NoRedirect
            with urllib.request.build_opener(NoRedirect).open(request,timeout=45) as response:result=json.load(response)
        else:
            result={'user':store.user_plugins(),'console':{'state':'requires-running-bridge','items':[]},'backend':{'state':'requires-running-bridge','items':[]}}
        print(json.dumps(result,indent=2));return 2 if isinstance(result,list) and any(r.get('status')=='unavailable' for r in result) else 0
    except (ValueError,OSError):print(json.dumps({'error':'Command failed. Check arguments, bridge pairing, or local/network availability.'}));return 2
if __name__=='__main__':sys.exit(main())
