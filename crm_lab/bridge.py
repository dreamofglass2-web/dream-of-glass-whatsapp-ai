"""Server-to-server read-only bridge. No listener/configuration is auto-started."""
import base64
import hashlib
import hmac
import json
import re
import sqlite3
import time
from urllib.parse import parse_qsl,urlsplit

class BridgeError(ValueError):
    def __init__(self,message,status=401):super().__init__(message);self.status=status

def request_signature(key,method,target,timestamp,nonce,body=b''):
    message='\n'.join([method,target,str(timestamp),nonce,hashlib.sha256(body).hexdigest()]).encode()
    return 'sha256='+hmac.new(key,message,hashlib.sha256).hexdigest()

class ReplayStore:
    def __init__(self,path):
        if str(path)==':memory:':raise BridgeError('Persistent replay file required',400)
        self.path=str(path)
        db=sqlite3.connect(self.path)
        try:
            with db:db.execute('CREATE TABLE IF NOT EXISTS crm_bridge_nonces (nonce TEXT PRIMARY KEY,expires INTEGER NOT NULL)')
        finally:db.close()
    def claim(self,nonce,now):
        db=sqlite3.connect(self.path,timeout=5)
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('DELETE FROM crm_bridge_nonces WHERE expires<?',(now,))
                try:db.execute('INSERT INTO crm_bridge_nonces VALUES (?,?)',(nonce,now+601))
                except sqlite3.IntegrityError:raise BridgeError('Repeated request') from None
        finally:db.close()

class LeadBridge:
    def __init__(self,source,*,key,scope,replay_store,clock=time.time):
        if not isinstance(key,bytes) or len(key)<32 or not isinstance(scope,str) or not scope.strip():
            raise BridgeError('Explicit server-only key and source scope required',400)
        self.source,self.key,self.scope,self.replay,self.clock=source,key,scope,replay_store,clock
    def _cursor(self,after,expires):
        raw=json.dumps([self.scope,after,expires],separators=(',',':')).encode()
        encoded=base64.urlsafe_b64encode(raw).decode().rstrip('=')
        return encoded+'.'+hmac.new(self.key,b'cursor\n'+raw,hashlib.sha256).hexdigest()
    def _after(self,cursor,now):
        if not cursor:return ''
        try:
            if len(cursor)>500:raise ValueError
            encoded,signature=cursor.split('.')
            raw=base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4))
            expected=hmac.new(self.key,b'cursor\n'+raw,hashlib.sha256).hexdigest()
            scope,after,expires=json.loads(raw)
            if (not hmac.compare_digest(signature,expected) or scope!=self.scope
                    or type(expires) is not int or expires<now or not isinstance(after,str) or len(after)>20):raise ValueError
            return after
        except (ValueError,TypeError,UnicodeError):raise BridgeError('Invalid or expired cursor',400) from None
    def handle(self,method,target,headers,body=b''):
        nonce=''
        try:
            if not isinstance(target,str) or len(target)>2048:raise BridgeError('Invalid request target',400)
            now=int(self.clock());stamp=headers.get('X-CRM-Timestamp','');nonce=headers.get('X-CRM-Nonce','')
            signature=headers.get('X-CRM-Signature','')
            if (not isinstance(body,bytes) or body or not re.fullmatch(r'[0-9]{1,12}',stamp)
                    or abs(now-int(stamp))>300 or not re.fullmatch(r'[0-9a-f]{32}',nonce)
                    or not re.fullmatch(r'sha256=[0-9a-f]{64}',signature)):
                raise BridgeError('Invalid authentication')
            expected=request_signature(self.key,method,target,stamp,nonce,body)
            if not hmac.compare_digest(signature,expected):raise BridgeError('Invalid authentication')
            if method!='GET':raise BridgeError('Read-only method required',405)
            parsed=urlsplit(target)
            if parsed.scheme or parsed.netloc or parsed.fragment or parsed.path!='/v1/leads':raise BridgeError('Unknown route',404)
            pairs=parse_qsl(parsed.query,keep_blank_values=True,strict_parsing=True)
            if len(pairs)!=len(dict(pairs)) or set(dict(pairs))-{'limit','cursor'}:raise BridgeError('Invalid page query',400)
            query=dict(pairs);value=query.get('limit','100')
            if not re.fullmatch(r'[0-9]{1,3}',value) or not 1<=int(value)<=300:raise BridgeError('Invalid page limit',400)
            after=self._after(query.get('cursor',''),now)
            self.replay.claim(nonce,now)
            try:result=self.source.page(limit=int(value),after=after)
            except Exception:raise BridgeError('Source unavailable; no update applied',503) from None
            result=dict(result);last=result.pop('next_after',None)
            result.update(source_scope=self.scope,request_nonce=nonce,
                          next_cursor=self._cursor(last,now+300) if last else None)
            raw=json.dumps(result,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
            if len(raw)>1000000:raise BridgeError('Source page too large',413)
            sig=hmac.new(self.key,b'response\n'+nonce.encode()+b'\n'+raw,hashlib.sha256).hexdigest()
            return 200,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-CRM-Response-Signature':'sha256='+sig},raw
        except BridgeError as error:return error.status,{'Content-Type':'application/json','Cache-Control':'no-store'},json.dumps({'error':str(error)}).encode()
        except (ValueError,TypeError,KeyError):return 400,{'Content-Type':'application/json','Cache-Control':'no-store'},b'{"error":"Malformed request"}'
        except Exception:return 503,{'Content-Type':'application/json','Cache-Control':'no-store'},b'{"error":"Bridge unavailable"}'

def verify_response(key,nonce,signature,raw,*,scope):
    if not isinstance(raw,bytes) or len(raw)>1000000:raise BridgeError('Invalid source response size')
    expected='sha256='+hmac.new(key,b'response\n'+nonce.encode()+b'\n'+raw,hashlib.sha256).hexdigest()
    if not isinstance(signature,str) or not hmac.compare_digest(signature,expected):raise BridgeError('Invalid source response signature')
    result=json.loads(raw)
    if not isinstance(result,dict):raise BridgeError('Invalid source response')
    if result.get('request_nonce')!=nonce or result.get('source_scope')!=scope:raise BridgeError('Wrong response scope')
    return result

def wsgi_application(bridge):
    def application(environ,start_response):
        target=environ.get('PATH_INFO','')
        if environ.get('QUERY_STRING'):target+='?'+environ['QUERY_STRING']
        headers={name:environ.get('HTTP_'+name.upper().replace('-','_'),'') for name in ('X-CRM-Timestamp','X-CRM-Nonce','X-CRM-Signature')}
        # GET bodies are prohibited. Never read an unbounded stream.
        length=environ.get('CONTENT_LENGTH','')
        body=b'body-not-allowed' if length not in ('','0') or environ.get('HTTP_TRANSFER_ENCODING') else b''
        status,response_headers,raw=bridge.handle(environ.get('REQUEST_METHOD',''),target,headers,body)
        labels={200:'OK',400:'Bad Request',401:'Unauthorized',404:'Not Found',405:'Method Not Allowed',413:'Payload Too Large',503:'Service Unavailable'}
        start_response(f'{status} {labels.get(status,"Error")}',list(response_headers.items()))
        return [raw]
    return application
