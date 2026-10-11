"""Explicit Gunicorn factory for the dedicated read-only CRM service.
Importing this module does not read secrets, connect, send messages or listen.
"""
import os,re
from urllib.parse import urlsplit,unquote
from crm_lab.bridge import LeadBridge,ReplayStore,wsgi_application
from crm_lab.read_source import ReadOnlyLeadSource

def configuration(env):
    if env.get('CRM_LIVE_READ_ENABLED')!='true':raise ValueError('CRM live reader is disabled')
    key=env.get('CRM_BRIDGE_KEY_HEX','')
    if not re.fullmatch(r'[0-9a-f]{64}',key):raise ValueError('Explicit 32-byte server key required')
    url=urlsplit(env.get('CRM_READER_DATABASE_URL',''))
    if (url.scheme!='postgresql' or not url.hostname or not url.path.startswith('/')
        or url.username!='yossi_crm_reader' or not url.password or url.port not in (None,5432)
        or url.query or url.fragment):raise ValueError('Dedicated reader URL required')
    replay=env.get('CRM_REPLAY_PATH','')
    if not replay.startswith('/var/data/') or '..' in replay.split('/'):raise ValueError('Persistent replay disk required')
    params={'host':url.hostname,'dbname':unquote(url.path[1:]),'user':url.username,
        'password':unquote(url.password),'sslmode':'verify-full','connect_timeout':5}
    return params,bytes.fromhex(key),replay

def create_application(env=None):
    params,key,replay=configuration(os.environ if env is None else env)
    source=ReadOnlyLeadSource(live_parameters=params,live_enabled=True)
    bridge=LeadBridge(source,key=key,scope='glass-leads-v1',replay_store=ReplayStore(replay))
    secured=wsgi_application(bridge)
    def application(environ,start_response):
        if environ.get('REQUEST_METHOD')=='GET' and environ.get('PATH_INFO')=='/healthz':
            raw=b'{"service":"crm-read-only","configured":true}'
            start_response('200 OK',[('Content-Type','application/json'),('Cache-Control','no-store')]);return [raw]
        return secured(environ,start_response)
    return application
