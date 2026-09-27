import sys, struct, unittest, threading, http.client, json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bridge'))
from server import validate_xex, safe_path, sanitize_telemetry, Bridge, Handler, HTTPServer

def fixture(flags=1):
    b=bytearray(1024);b[:4]=b'XEX2';struct.pack_into('>5I',b,4,flags,512,0,32,0);struct.pack_into('>I',b,32,384);return bytes(b)
class Validation(unittest.TestCase):
    def test_valid_and_plugin(self):
        self.assertTrue(validate_xex(fixture())['valid']);self.assertTrue(validate_xex(fixture(9))['plugin'])
    def test_corrupt(self):
        for b in (b'XEX2',b'bad'+fixture(),fixture()[:40],fixture(0)):
            with self.assertRaises(ValueError):validate_xex(b)
    def test_bounds(self):
        b=bytearray(fixture());struct.pack_into('>I',b,20,4097)
        with self.assertRaises(ValueError):validate_xex(b)
    def test_path(self):
        self.assertEqual(safe_path('Usb9:\\Games\\default.xex',['Usb9:\\']),'Usb9:\\Games\\default.xex')
        for p in ('Usb0:\\x.xex','Usb9:\\..\\x.xex','Usb9:\\x.xex\r\nmagicboot','Usb9:\\a".xex'):
            with self.assertRaises(ValueError):safe_path(p,['Usb9:\\'])
class Fake(Bridge):
    def __init__(self):super().__init__('unused');self.target='demo';self.drives=['Test:\\'];self.content=fixture();self.launched=False
    def inspect(self,path):return validate_xex(self.content)
    def adapter(self,action,**kwargs):self.launched=action=='launch';return {}
class Tickets(unittest.TestCase):
    def test_launch_and_replay(self):
        b=Fake();v=b.dispatch('validate',{'path':'Test:\\a.xex'});b.dispatch('launch',{'ticket':v['ticket']});self.assertTrue(b.launched)
        with self.assertRaises(ValueError):b.dispatch('launch',{'ticket':v['ticket']})
    def test_changed_file(self):
        b=Fake();v=b.dispatch('validate',{'path':'Test:\\a.xex'});b.content=b.content[:-1]+b'a'
        with self.assertRaises(ValueError):b.dispatch('launch',{'ticket':v['ticket']})
        self.assertFalse(b.launched)
    def test_plugin_and_expiry(self):
        b=Fake();b.content=fixture(9);v=b.dispatch('validate',{'path':'Test:\\p.xex'})
        with self.assertRaises(ValueError):b.dispatch('launch',{'ticket':v['ticket']})
        b.content=fixture();v=b.dispatch('validate',{'path':'Test:\\a.xex'});b.tickets[v['ticket']]['expires']=0
        with self.assertRaises(ValueError):b.dispatch('launch',{'ticket':v['ticket']})
class HTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=HTTPServer(('127.0.0.1',0),Handler);cls.host='127.0.0.1:'+str(cls.server.server_port);cls.server.allowed_hosts={cls.host};cls.server.token='test-token';cls.server.bridge=Fake();cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def req(self,token='test-token',origin=None,host=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port);headers={'Host':host or self.host,'Origin':origin or 'http://'+self.host,'Authorization':'Bearer '+token,'Content-Type':'application/json'};c.request('POST','/api/validate',json.dumps({'path':'Test:\\a.xex'}),headers);r=c.getresponse();body=r.read();status=r.status;c.close();return status,body
    def test_auth_and_origin(self):
        self.assertEqual(self.req(token='wrong')[0],401);self.assertEqual(self.req(origin='http://evil.example')[0],403);self.assertEqual(self.req(host='evil.example')[0],403)
    def test_valid_request(self):self.assertEqual(self.req()[0],200)
class Telemetry(unittest.TestCase):
    def test_projection_and_partial_sensors(self):
        s=sanitize_telemetry({'temperatures':{'cpu':58,'gpu':61.5,'edram':None,'motherboard':36,'cpu_key':'secret'},'current_title':{'executable':'Usb9:\\Apps\\default.xex','title_id':'abcdef12','serial':'secret'},'keyvault':'secret'})
        self.assertEqual(s['temperatures'],{'cpu':58,'gpu':61.5,'edram':None,'motherboard':36})
        self.assertEqual(s['current_title']['title_id'],'ABCDEF12')
        self.assertNotIn('secret',json.dumps(s))
    def test_bad_values_and_missing_plugin(self):
        for value in [None,True,'58',float('nan'),float('inf'),-1,0,126]:
            self.assertIsNone(sanitize_telemetry({'temperatures':{'cpu':value}})['temperatures']['cpu'])
        self.assertEqual(sanitize_telemetry({})['current_title'],{'executable':None,'title_id':None})
        self.assertIsNone(sanitize_telemetry({'current_title':{'executable':'bad\npath','title_id':'invalid'}})['current_title']['executable'])
    def test_status_includes_only_allowlist(self):
        b=Bridge('unused');b.adapter=lambda action:{'type':'Retail','kernel':'Unavailable','drives':['Usb9:\\'],'temperatures':{'cpu':50},'serial':'secret'}
        s=b.status();self.assertEqual(s['temperatures']['cpu'],50);self.assertNotIn('serial',s)

if __name__=='__main__':unittest.main()
