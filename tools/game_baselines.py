"""Measure a local game XEX and propose a baseline; never auto-approve it."""
import argparse
import base64
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bridge'))
from server import validate_xex, MAX_XEX
from game_catalog import load_games, candidate_from_inspection, validate_game_builds

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest='command',required=True)
    lint=subs.add_parser('lint');lint.add_argument('--catalog')
    propose=subs.add_parser('propose');propose.add_argument('file')
    for key in ('id','title','provenance'):propose.add_argument('--'+key,required=True)
    propose.add_argument('--cover',help='Optional local JPEG/PNG up to 512 KiB.')
    a=parser.parse_args()
    try:
        if a.command=='lint':
            builds,revision=load_games(a.catalog);print(json.dumps({'builds':len(builds),'revision':revision}));return 0
        path=Path(a.file)
        if path.suffix.lower()!='.xex' or path.stat().st_size>MAX_XEX:raise ValueError('Use an XEX up to 64 MiB.')
        v=validate_xex(path.read_bytes())
        b=candidate_from_inspection(v,path.name,a.title,a.provenance,build_id=a.id)
        if a.cover:
            cover=Path(a.cover)
            if cover.stat().st_size>512*1024:raise ValueError('Artwork exceeds 512 KiB.')
            raw=cover.read_bytes()
            kind='png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else 'jpeg' if raw.startswith(b'\xff\xd8\xff') else None
            if not kind:raise ValueError('Use PNG or JPEG artwork.')
            b['cover']='data:image/'+kind+';base64,'+base64.b64encode(raw).decode()
        validate_game_builds({'schema_version':1,'builds':[b]})
        print(json.dumps(b,indent=2));return 0
    except (OSError,ValueError) as e:print(str(e),file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())
