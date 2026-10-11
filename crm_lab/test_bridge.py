import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote
from crm_lab.bridge import LeadBridge,ReplayStore,BridgeError,request_signature,verify_response,wsgi_application
from crm_lab.read_source import ReadOnlyLeadSource
from crm_lab.lead_preview import LeadPreviewError

KEY=b'explicit-test-key-with-at-least-32-bytes'
class Source:
    def __init__(self):self.calls=[]
    def page(self,*,limit,after):
        self.calls.append((limit,after))
        return {'customers':[],'next_after':'000000001' if not after else None}
class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.path=Path(self.directory.name)/'replays.sqlite';self.now=1800000000
        self.source=Source();self.bridge=self.new_bridge()
    def new_bridge(self,scope='fixture'):
        return LeadBridge(self.source,key=KEY,scope=scope,replay_store=ReplayStore(self.path),clock=lambda:self.now)
    def request(self,target='/v1/leads?limit=2',nonce='a'*32,stamp=None,method='GET',body=b'',bridge=None):
        stamp=str(self.now if stamp is None else stamp)
        headers={'X-CRM-Timestamp':stamp,'X-CRM-Nonce':nonce,'X-CRM-Signature':request_signature(KEY,method,target,stamp,nonce,body)}
        return (bridge or self.bridge).handle(method,target,headers,body)
    def test_signed_response_and_bounded_cursor(self):
        status,headers,raw=self.request();self.assertEqual(status,200);self.assertEqual(headers['Cache-Control'],'no-store')
        result=verify_response(KEY,'a'*32,headers['X-CRM-Response-Signature'],raw,scope='fixture')
        target='/v1/leads?limit=2&cursor='+quote(result['next_cursor'])
        self.assertEqual(self.request(target,nonce='b'*32)[0],200)
        self.assertEqual(self.source.calls,[(2,''),(2,'000000001')])
    def test_replay_survives_new_bridge(self):
        self.assertEqual(self.request()[0],200)
        self.assertEqual(self.request(bridge=self.new_bridge())[0],401);self.assertEqual(len(self.source.calls),1)
    def test_stale_and_future_requests_rejected(self):
        for stamp in (self.now-301,self.now+301):self.assertEqual(self.request(stamp=stamp)[0],401)
        self.assertEqual(self.source.calls,[])
    def test_wrong_key_and_tampered_target(self):
        headers={'X-CRM-Timestamp':str(self.now),'X-CRM-Nonce':'a'*32,'X-CRM-Signature':request_signature(KEY,'GET','/v1/leads',self.now,'a'*32)}
        self.assertEqual(self.bridge.handle('GET','/v1/leads?limit=1',headers)[0],401)
        headers['X-CRM-Signature']=request_signature(b'x'*32,'GET','/v1/leads',self.now,'a'*32)
        self.assertEqual(self.bridge.handle('GET','/v1/leads',headers)[0],401);self.assertEqual(self.source.calls,[])
    def test_invalid_routes_queries_and_body(self):
        for target in ('/v1/leads?limit=0','/v1/leads?limit=301','/v1/leads?limit=1&limit=2','/v1/leads?account=x','/v1/leads?cursor=broken'):
            self.assertEqual(self.request(target)[0],400)
        self.assertEqual(self.request('/other')[0],404)
        self.assertEqual(self.request(method='POST')[0],405)
        self.assertEqual(self.request(body=b'payload')[0],401);self.assertEqual(self.source.calls,[])
    def test_cursor_scope_signature_and_expiry(self):
        cursor=self.bridge._cursor('000000001',self.now+1)
        self.assertEqual(self.request('/v1/leads?cursor='+quote(cursor),bridge=self.new_bridge('other'))[0],400)
        self.assertEqual(self.request('/v1/leads?cursor='+quote(cursor+'x'))[0],400)
        self.now+=2;self.assertEqual(self.request('/v1/leads?cursor='+quote(cursor))[0],400)
        self.assertEqual(self.source.calls,[])
    def test_response_tamper_nonce_scope(self):
        _,headers,raw=self.request();sig=headers['X-CRM-Response-Signature']
        for nonce,scope,data in [('a'*32,'fixture',raw+b' '),('b'*32,'fixture',raw),('a'*32,'other',raw)]:
            with self.assertRaises(BridgeError):verify_response(KEY,nonce,sig,data,scope=scope)
    def test_failure_is_redacted_and_nonce_consumed(self):
        def broken(**kwargs):raise RuntimeError('secret-password')
        self.source.page=broken
        status,_,raw=self.request();self.assertEqual(status,503);self.assertNotIn(b'secret',raw)
        self.assertEqual(self.request()[0],401)
    def test_replay_failure_is_closed(self):
        self.bridge.replay.claim=lambda *args:(_ for _ in ()).throw(RuntimeError('private-path'))
        status,_,raw=self.request();self.assertEqual(status,503);self.assertNotIn(b'private',raw);self.assertEqual(self.source.calls,[])
    def test_live_reader_disabled_without_connecting(self):
        with self.assertRaises(LeadPreviewError):ReadOnlyLeadSource().page(limit=1)
        with self.assertRaises(LeadPreviewError):ReadOnlyLeadSource(live_enabled=True)
    def test_wsgi_rejects_chunked_body(self):
        environ={'REQUEST_METHOD':'GET','PATH_INFO':'/v1/leads','HTTP_TRANSFER_ENCODING':'chunked','HTTP_X_CRM_TIMESTAMP':str(self.now),'HTTP_X_CRM_NONCE':'a'*32,'HTTP_X_CRM_SIGNATURE':request_signature(KEY,'GET','/v1/leads',self.now,'a'*32)}
        statuses=[];wsgi_application(self.bridge)(environ,lambda status,headers:statuses.append(status))
        self.assertEqual(statuses,['401 Unauthorized']);self.assertEqual(self.source.calls,[])

    def test_customer_detail_is_signed_scoped_and_replay_protected(self):
        self.source.detail=lambda **kwargs:{'customer':{'phone':kwargs['phone']},'read_only':True}
        target='/v1/customer?phone=000000001'
        status,headers,raw=self.request(target);self.assertEqual(status,200)
        result=verify_response(KEY,'a'*32,headers['X-CRM-Response-Signature'],raw,scope='fixture')
        self.assertEqual(result['customer']['phone'],'000000001')
        self.assertEqual(self.request(target)[0],401)
        self.assertEqual(self.request('/v1/customer?phone=000000001&account=other',nonce='b'*32)[0],400)
