import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from server import validate_xex
from test_bridge import Fake
from game_catalog import verify_game, load_games

def game_fixture():
    b=bytearray(600)
    b[:4]=b'XEX2'
    struct.pack_into('>5I',b,4,1,512,0,64,1)
    struct.pack_into('>2I',b,24,0x00040006,32)
    struct.pack_into('>4I4BI',b,32,0x12345678,1,1,0x415608C3,2,0,1,1,0)
    struct.pack_into('>I',b,64,0x180)
    return bytes(b)

class GameCatalog(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'games.json'
        self.v=validate_xex(game_fixture())
        self.b={**self.v['metadata'],'id':'sample','title':'Test game','filename':'default_mp.xex','sha256':self.v['hash'],'size':self.v['size'],'state':'reviewed','unmodified':True,'provenance':'Unit-test fixture, not a retail reference','review':{'reviewer':'test','date':'2026-10-01','evidence':'fixture','hardware_test':'test-only fixture'}}
        self.write()
    def write(self):self.path.write_text(json.dumps({'schema_version':1,'builds':[self.b]}))
    def verify(self,v=None,name='default_mp.xex'):return verify_game(v or self.v,name,self.path)
    def test_metadata_allowlist(self):
        self.assertEqual(self.v['metadata'],{'title_id':'415608C3','media_id':'12345678','version':'00000001','base_version':'00000001','disc':1,'disc_count':1})
        bad=bytearray(game_fixture());struct.pack_into('>I',bad,28,510)
        with self.assertRaises(ValueError):validate_xex(bad)
    def test_green_only_reviewed_unmodified_exact_file(self):
        self.assertEqual(self.verify()['status'],'verified')
        self.assertEqual(self.verify(name='default.xex')['status'],'unknown')
        self.b['state']='candidate';self.write()
        self.assertEqual(self.verify()['status'],'unknown')
        self.b['state']='reviewed';self.b['unmodified']=False;self.write()
        with self.assertRaises(ValueError):load_games(self.path)
    def test_red_mismatch_and_unknown_variants(self):
        changed=validate_xex(game_fixture()[:-1]+b'X')
        self.assertEqual(self.verify(changed)['status'],'mismatch')
        changed['metadata']['media_id']='FFFFFFFF'
        self.assertEqual(self.verify(changed)['status'],'unknown')
        changed['metadata']['media_id']='12345678';changed['metadata']['version']='00000002'
        self.assertEqual(self.verify(changed)['status'],'unknown')
    def test_revocation_and_launch_recheck(self):
        b=Fake();b.content=game_fixture()
        with patch('server.verify_game',lambda v,n:verify_game(v,n,self.path)):
            ticket=b.dispatch('validate',{'path':'Test:\\default_mp.xex'})['ticket']
            self.assertTrue(ticket)
            self.b['state']='revoked';self.b['revocation_reason']='Test revocation';self.write()
            with self.assertRaises(ValueError):b.dispatch('launch',{'ticket':ticket})
            self.assertFalse(b.launched)
            self.assertIsNone(b.dispatch('validate',{'path':'Test:\\default_mp.xex'})['ticket'])
    def test_mismatch_never_gets_launch_ticket(self):
        b=Fake();b.content=game_fixture()[:-1]+b'X'
        with patch('server.verify_game',lambda v,n:verify_game(v,n,self.path)):
            result=b.dispatch('validate',{'path':'Test:\\default_mp.xex'})
            self.assertIsNone(result['ticket'])
            self.assertEqual(result['game_verification']['status'],'mismatch')
    def test_unreviewed_missing_evidence_and_remote_art_rejected(self):
        del self.b['review']['evidence'];self.write()
        with self.assertRaises(ValueError):load_games(self.path)
        self.b['state']='candidate';self.b['cover']='https://example.com/cover.jpg';self.write()
        with self.assertRaises(ValueError):load_games(self.path)
