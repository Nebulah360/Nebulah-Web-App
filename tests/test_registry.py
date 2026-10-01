import json, tempfile, unittest, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bridge'))
from hash_registry import load_catalog,verify_digest,RegistryError
from test_bridge import fixture,Fake
from server import validate_xex

class Catalog(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'catalog.json'
        self.digest=validate_xex(fixture())['hash']
        self.build={'id':'test-1','project':'Test fixture only','version':'1','filename':'default.xex','repository':'https://github.com/example/test','commit':'a'*40,'sha256':self.digest,'size':1024,'state':'reviewed','review':{'reviewer':'Test fixture','date':'2026-10-01','evidence':'Synthetic test only','hardware_test':'Synthetic test only'}}
        self.write()
    def tearDown(self):self.tmp.cleanup()
    def write(self,extra=None):self.path.write_text(json.dumps({'schema_version':1,'builds':[self.build]+(extra or [])}))
    def verify(self,digest=None,size=1024,expected='test-1'):return verify_digest(digest or self.digest,size,expected,self.path)
    def test_reviewed_exact_match(self):
        r=self.verify();self.assertEqual(r['status'],'reviewed-match');self.assertTrue(r['eligible_for_install'])
        self.assertFalse(self.verify(expected=None)['eligible_for_install'])
    def test_hash_and_size_discrepancies(self):
        r=self.verify('b'*64,2048);self.assertEqual(r['status'],'mismatch');self.assertEqual(len(r['discrepancies']),2);self.assertFalse(r['eligible_for_install'])
    def test_unknown_is_not_safe(self):
        self.assertEqual(self.verify('b'*64,expected=None)['status'],'unknown')
        self.assertEqual(self.verify(expected='missing')['status'],'unknown-build')
    def test_candidates_never_pass_install_gate(self):
        self.build['state']='candidate';self.write();r=self.verify();self.assertEqual(r['status'],'candidate-match');self.assertFalse(r['eligible_for_install'])
    def test_revocation_overrides_matching_review(self):
        revoked={**self.build,'id':'revoked-copy','state':'revoked','revocation_reason':'Synthetic revoked fixture'}
        self.write([revoked]);self.assertEqual(self.verify()['status'],'revoked')
    def test_malformed_missing_and_duplicate_catalog(self):
        self.path.unlink()
        with self.assertRaises(RegistryError):self.verify()
        self.write([self.build])
        with self.assertRaises(RegistryError):self.verify()
        self.build['review']={};self.write()
        with self.assertRaises(RegistryError):self.verify()
    def test_wrong_selected_version_even_if_other_hash_matches(self):
        other={**self.build,'id':'test-2','sha256':'b'*64};self.write([other])
        self.assertEqual(self.verify(expected='test-2')['status'],'mismatch')
    def test_revocation_after_validation_blocks_launch(self):
        import unittest.mock as mock
        import server
        def check(digest,size,expected=None):return verify_digest(digest,size,expected,self.path)
        b=Fake()
        with mock.patch.object(server,'verify_digest',side_effect=check):
            v=b.dispatch('validate',{'path':'Test:\\a.xex','build_id':'test-1'})
            self.build['state']='revoked';self.build['revocation_reason']='Synthetic revocation';self.write()
            with self.assertRaises(ValueError):b.dispatch('launch',{'ticket':v['ticket']})
        self.assertFalse(b.launched)
    def test_mismatch_gets_no_launch_ticket(self):
        import unittest.mock as mock
        import server
        b=Fake();self.build['sha256']='b'*64;self.write()
        with mock.patch.object(server,'verify_digest',side_effect=lambda d,s,e=None:verify_digest(d,s,e,self.path)):
            r=b.dispatch('validate',{'path':'Test:\\a.xex','build_id':'test-1'})
        self.assertIsNone(r['ticket']);self.assertEqual(r['verification']['status'],'mismatch')
    def test_readonly_hash_api_does_not_authorize_install(self):
        import unittest.mock as mock
        import server
        b=Fake()
        with mock.patch.object(server,'verify_digest',side_effect=lambda d,s,e=None:verify_digest(d,s,e,self.path)):
            r=b.dispatch('registry/check',{'sha256':self.digest,'size':1024,'build_id':'test-1'})
        self.assertEqual(r['measurement'],'caller-supplied-digest');self.assertFalse(r['eligible_for_install'])

    def test_cli_measures_bytes_and_enforces_exit_gate(self):
        import subprocess
        root=Path(__file__).resolve().parents[1];artifact=Path(self.tmp.name)/'sample.xex';artifact.write_bytes(fixture())
        args=[sys.executable,str(root/'tools/xex_registry.py'),'verify',str(artifact),'--build','test-1','--catalog',str(self.path)]
        good=subprocess.run(args,capture_output=True,text=True)
        self.assertEqual(good.returncode,0);self.assertEqual(json.loads(good.stdout)['measurement'],'local-file-bytes')
        artifact.write_bytes(fixture()[:-1]+b'x')
        bad=subprocess.run(args,capture_output=True,text=True)
        self.assertEqual(bad.returncode,2);self.assertEqual(json.loads(bad.stdout)['status'],'mismatch')
