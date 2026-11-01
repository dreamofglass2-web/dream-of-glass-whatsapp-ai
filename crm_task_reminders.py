"""Read the signed owner CRM task feed and notify only the existing Telegram owner."""
import hashlib,hmac,json,os,re,secrets,time
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from urllib.parse import quote
from owner_notifications import alert_configuration
SITE='https://yossi-david-crm-demo.dream-of-glass2.chatgpt.site'
TARGET='/api/task-reminders'
_ready_logged=False

def configuration():
    if os.getenv('CRM_TASK_REMINDERS_ENABLED')!='true':return None
    key=os.getenv('CRM_CONTROL_KEY_HEX','');access=os.getenv('CRM_TASK_SITE_ACCESS','')
    owner=alert_configuration()
    if not re.fullmatch(r'[a-f0-9]{64}',key) or not access or not owner or owner[0]!='telegram':return None
    return bytes.fromhex(key),access,owner[1],owner[2]

def ensure_tables(cur):
    cur.execute('SELECT pg_advisory_xact_lock(827134,33491)')
    cur.execute("""CREATE TABLE IF NOT EXISTS crm_task_notifications (
        task_key TEXT PRIMARY KEY, due_date DATE NOT NULL,status TEXT NOT NULL,
        started_at TIMESTAMPTZ NOT NULL DEFAULT now(),completed_at TIMESTAMPTZ,message_id BIGINT)""")

def read_feed(http,key,access,now=None):
    now=now or datetime.now(timezone.utc);stamp=str(int(now.timestamp()));nonce=secrets.token_hex(16)
    message='\n'.join(['GET',TARGET,stamp,nonce,hashlib.sha256(b'').hexdigest()]).encode()
    signature='sha256='+hmac.new(key,message,hashlib.sha256).hexdigest()
    response=http.get(SITE+TARGET,headers={'OAI-Sites-Authorization':'Bearer '+access,
        'X-CRM-Timestamp':stamp,'X-CRM-Nonce':nonce,'X-CRM-Signature':signature},timeout=15,allow_redirects=False)
    if response.status_code!=200:raise ValueError('Task source unavailable')
    raw=response.content
    if len(raw)>200000:raise ValueError('Task source oversized')
    expected='sha256='+hmac.new(key,b'response\n'+nonce.encode()+b'\n'+raw,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(response.headers.get('X-CRM-Response-Signature','')),expected):raise ValueError('Task source signature invalid')
    data=json.loads(raw);generated=datetime.fromisoformat(data['generated_at'].replace('Z','+00:00'))
    if (data.get('source_scope')!='crm-task-reminders-v1' or data.get('request_nonce')!=nonce
            or generated.tzinfo is None or abs((now-generated).total_seconds())>60
            or not isinstance(data.get('items'),list) or len(data['items'])>500):raise ValueError('Task source invalid')
    today=now.astimezone(ZoneInfo('Asia/Jerusalem')).date().isoformat();seen=set()
    for item in data['items']:
        if (not isinstance(item,dict) or set(item)!={'id','customerId','due'}
            or not isinstance(item['id'],str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,50}',item['id'])
            or not isinstance(item['customerId'],str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',item['customerId'])
            or not isinstance(item['due'],str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',item['due'])
            or datetime.strptime(item['due'],'%Y-%m-%d').date().isoformat()!=item['due'] or item['due']>today):raise ValueError('Task source row invalid')
        identity=hashlib.sha256((SITE+'|'+item['customerId']+'|'+item['id']+'|'+item['due']).encode()).hexdigest()
        if identity in seen:raise ValueError('Duplicate task')
        seen.add(identity);item['key']=identity
    return data['items']

def dispatch(connect,http,logger,now=None):
    global _ready_logged
    cfg=configuration();now=now or datetime.now(timezone.utc)
    if not cfg or now.astimezone(ZoneInfo('Asia/Jerusalem')).hour<8:return 0
    key,access,bot,chat=cfg
    try:items=read_feed(http,key,access,now)
    except Exception:
        logger.error('CRM_TASK_REMINDERS_SOURCE_UNAVAILABLE');return 0
    if not _ready_logged:
        logger.info('CRM_TASK_REMINDERS_READY due_count=%s',len(items));_ready_logged=True
    sent=0
    with connect() as conn,conn.cursor() as cur:
        ensure_tables(cur)
        cur.execute("UPDATE crm_task_notifications SET status='uncertain',completed_at=now() WHERE status='sending' AND started_at<now()-interval '2 minutes'")
        cur.execute('SELECT task_key FROM crm_task_notifications WHERE task_key=ANY(%s)',([i['key'] for i in items],))
        existing={r[0] for r in cur.fetchall()}
    for item in [i for i in items if i['key'] not in existing][:50]:
        with connect() as conn,conn.cursor() as cur:
            cur.execute("INSERT INTO crm_task_notifications(task_key,due_date,status) VALUES(%s,%s,'sending') ON CONFLICT(task_key) DO NOTHING",(item['key'],item['due']))
            claimed=cur.rowcount==1
        if not claimed:continue
        status='uncertain';message_id=None
        try:
            response=http.post('https://api.telegram.org/bot'+bot+'/sendMessage',json={
                'chat_id':chat,'text':'תזכורת למשימה ב־CRM לתאריך '+item['due']+'.\nפרטי המשימה וכרטיס הלקוח מחכים לך ב־CRM.',
                'link_preview_options':{'is_disabled':True},'reply_markup':{'inline_keyboard':[[{'text':'פתיחת המשימה ב־CRM','url':SITE+'/?taskCustomer='+quote(item['customerId'],safe='')}]]}},timeout=15)
            result=response.json() if response.ok else {};message=result.get('result') or {}
            if result.get('ok') is True and type(message.get('message_id')) is int and str((message.get('chat') or {}).get('id'))==chat:
                status='accepted';message_id=message['message_id'];sent+=1
            else:status='failed'
        except Exception:logger.warning('CRM_TASK_REMINDER_PROVIDER_UNCERTAIN')
        with connect() as conn,conn.cursor() as cur:
            cur.execute('UPDATE crm_task_notifications SET status=%s,message_id=%s,completed_at=now() WHERE task_key=%s',(status,message_id,item['key']))
    return sent
