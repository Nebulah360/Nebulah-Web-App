import json,sys,tempfile,unittest,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bridge'))
from repositories import Repositories,repo_name
class Repos(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.store=Repositories(Path(self.tmp.name)/'test.sqlite3');self.sha='a'*40
    def tearDown(self):self.tmp.cleanup()
    def fetch(self,path):
        if '/releases/' in path:raise urllib.error.HTTPError('',404,'',{},None)
        if '/commits/' in path:return {'sha':self.sha,'commit':{'committer':{'date':'2026-10-01T00:00:00Z'}}}
        return {'default_branch':'main','owner':{'login':'Nebulah360'},'stargazers_count':2,'pushed_at':'2026-10-01T00:00:00Z','updated_at':'2026-10-01T00:00:00Z'}
    def test_save_remove_persist_and_presets(self):
        self.store.save('https://github.com/example/plugin.git');self.assertEqual(len(self.store.list()),3)
        self.store.remove('example/plugin');self.store.remove('Nebulah360/Nebulah-Dash');self.assertEqual(len(self.store.list()),2)
    def test_first_unchanged_changed(self):
        name='Nebulah360/Nebulah-Web-App';self.assertEqual(self.store.check(name,self.fetch)['status'],'first-check');self.assertEqual(self.store.check(name,self.fetch)['status'],'unchanged');self.sha='b'*40;self.assertEqual(self.store.check(name,self.fetch)['status'],'changed')
    def test_failure_preserves_baseline(self):
        name='Nebulah360/Nebulah-Web-App';self.store.check(name,self.fetch)
        def fail(path):raise TimeoutError()
        r=self.store.check(name,fail);self.assertEqual(r['status'],'unavailable');self.assertEqual(r['last_success']['revision'],'a'*40)
    def test_plugin_registration_not_execution(self):
        self.store.register_plugin('Test','v1','example/plugin');self.assertFalse(self.store.user_plugins()[0]['loaded']);self.store.remove_plugin('Test');self.assertEqual(self.store.user_plugins(),[])
    def test_reject_arbitrary_urls_and_traversal(self):
        for value in ('http://127.0.0.1/x','https://evil.example/x/y','x/..','x/y?token=secret','x/y/z'):
            with self.assertRaises(ValueError):repo_name(value)
