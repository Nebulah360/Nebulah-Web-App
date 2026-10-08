"""Hash actual XEX bytes, propose review candidates, or gate a staged install."""
import argparse, json, sys, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bridge'))
from server import validate_xex, MAX_XEX
from hash_registry import DEFAULT_CATALOG, load_catalog, verify_digest

def inspect_file(path):
    path=Path(path)
    if path.suffix.lower()!='.xex' or path.stat().st_size>MAX_XEX:raise ValueError('Use an XEX up to 64 MiB.')
    data=path.read_bytes();v=validate_xex(data)
    return v,len(data)

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    check=sub.add_parser('verify');check.add_argument('file');check.add_argument('--build',required=True);check.add_argument('--catalog',default=str(DEFAULT_CATALOG))
    propose=sub.add_parser('propose');propose.add_argument('file')
    for key in ('id','project','version','repository','commit'):propose.add_argument('--'+key,required=True)
    lint=sub.add_parser('lint');lint.add_argument('--catalog',default=str(DEFAULT_CATALOG))
    args=p.parse_args()
    try:
        if args.command=='lint':
            c,r=load_catalog(args.catalog);print(json.dumps({'builds':len(c['builds']),'catalog_revision':r}));return 0
        v,size=inspect_file(args.file)
        if args.command=='propose':
            candidate={k:getattr(args,k) for k in ('id','project','version','repository','commit')}
            candidate.update(filename=Path(args.file).name,sha256=v['hash'],size=size,state='candidate')
            with tempfile.TemporaryDirectory() as tmp:
                manifest=Path(tmp)/'catalog.json';manifest.write_text(json.dumps({'schema_version':1,'builds':[candidate]}))
                load_catalog(manifest)
            print(json.dumps(candidate,indent=2));return 0
        result=verify_digest(v['hash'],size,args.build,args.catalog)
        result['measurement']='local-file-bytes';result['structural_checks']=v['checks'];result['plugin']=v['plugin']
        print(json.dumps(result,indent=2));return 0 if result['eligible_for_install'] else 2
    except (ValueError,OSError) as e:
        print(json.dumps({'status':'verification-error','error':str(e),'eligible_for_install':False}));return 2
if __name__=='__main__':sys.exit(main())
