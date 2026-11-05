"""Authenticated WhatsApp receipts and a single durable owner-requested probe.

No customer retries, pilot admission, ownership changes, or inferred delivery.
"""
import json
import os
import re
from contextlib import closing
from datetime import datetime, timezone
import form_outreach

STATUSES = {'sent', 'delivered', 'read', 'failed'}


def ensure_tables(cur):
    cur.execute("SELECT pg_advisory_xact_lock(751109051)")
    cur.execute("""CREATE TABLE IF NOT EXISTS yossi_message_receipts (
        message_id TEXT NOT NULL, phone TEXT NOT NULL, status TEXT NOT NULL
          CHECK(status IN ('sent','delivered','read','failed')),
        event_at TIMESTAMPTZ NOT NULL, received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        error_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
        PRIMARY KEY(message_id,status))""")
    cur.execute("CREATE INDEX IF NOT EXISTS yossi_receipts_phone ON yossi_message_receipts(phone,event_at)")
    cur.execute("""CREATE TABLE IF NOT EXISTS yossi_delivery_probes (
        id TEXT PRIMARY KEY, phone TEXT NOT NULL, state TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ,
        message_id TEXT, sender_phone TEXT, error_codes JSONB NOT NULL DEFAULT '[]'::jsonb)""")


def parse_statuses(value, number_id):
    if not isinstance(value, dict) or not isinstance(value.get('metadata'),dict) or str(value['metadata'].get('phone_number_id','')) != str(number_id):
        return []
    result = []
    items = value.get('statuses')
    if not isinstance(items, list):
        return result
    for item in items[:1000]:
        if not isinstance(item, dict):
            continue
        mid, phone, status, timestamp = (item.get(k) for k in ('id','recipient_id','status','timestamp'))
        if (not isinstance(mid,str) or not re.fullmatch(r'wamid\.[A-Za-z0-9_+/=.-]{1,506}',mid)
            or not isinstance(phone,str) or not re.fullmatch(r'[1-9]\d{7,14}',phone)
            or not isinstance(status,str) or status not in STATUSES or not isinstance(timestamp,str)
            or len(timestamp)>10 or not timestamp.isdigit() or not 946684800 <= int(timestamp) <= 4102444800):
            continue
        errors = item.get('errors')
        codes = sorted({e['code'] for e in errors[:10] if isinstance(e,dict)
                        and type(e.get('code')) is int and 0 <= e['code'] <= 999999999}) if isinstance(errors,list) else []
        result.append((mid,phone,status,datetime.fromtimestamp(int(timestamp),timezone.utc),codes))
    return result


def record(cur, events):
    for mid, phone, status, at, codes in events:
        cur.execute("""INSERT INTO yossi_message_receipts(message_id,phone,status,event_at,error_codes)
            VALUES(%s,%s,%s,%s,%s::jsonb) ON CONFLICT(message_id,status) DO UPDATE
            SET event_at=GREATEST(yossi_message_receipts.event_at,EXCLUDED.event_at),
                error_codes=CASE WHEN EXCLUDED.event_at>=yossi_message_receipts.event_at
                    AND EXCLUDED.error_codes<>'[]'::jsonb THEN EXCLUDED.error_codes
                    ELSE yossi_message_receipts.error_codes END
            WHERE yossi_message_receipts.phone=EXCLUDED.phone""",(mid,phone,status,at,json.dumps(codes)))


def outreach_status(cur, phone):
    cur.execute("""SELECT o.status,o.completed_at,o.message_id,r.status,r.event_at,r.error_codes
        FROM (SELECT status,completed_at,message_id,phone,created_at FROM yossi_form_outreach
              UNION ALL SELECT status,completed_at,message_id,phone,created_at FROM yossi_outreach_recoveries) o
        LEFT JOIN yossi_message_receipts r ON r.message_id=o.message_id AND r.phone=o.phone
        WHERE o.phone=%s ORDER BY o.created_at DESC,r.event_at DESC LIMIT 20""",(phone,))
    rows=cur.fetchall()
    if not rows:
        return None
    latest=rows[0]
    # All receipt stages retained: out-of-order sent/failed cannot erase delivery proof.
    events=[{'status':r[3],'at':r[4].isoformat(),'errorCodes':r[5]} for r in rows
            if r[2]==latest[2] and r[3]]
    known={e['status'] for e in events}
    status=next((s for s in ('read','delivered','failed','sent') if s in known),
                'accepted' if latest[0]=='accepted' else latest[0])
    return {'status':status,'attemptedAt':latest[1].isoformat() if latest[1] else None,
            'deliveryVerified':bool(known & {'read','delivered'}),'events':events}


def probe_configuration(env=None):
    env=os.environ if env is None else env
    identity=env.get('WHATSAPP_DELIVERY_PROBE_ID','')
    phone=env.get('WHATSAPP_DELIVERY_PROBE_PHONE','')
    if not identity and not phone:
        return None
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',identity) or not re.fullmatch(r'9725\d{8}',phone):
        raise ValueError('Invalid delivery probe configuration')
    if phone=='972508554415':
        raise ValueError('Probe recipient cannot be sender')
    return identity,phone


def dispatch_probe(connect,http,token,number_id,business_hours,logger,env=None):
    cfg=probe_configuration(env)
    if not cfg or str(number_id)!=form_outreach.BUSINESS_NUMBER_ID or not token or not business_hours():
        return
    identity,phone=cfg
    with closing(connect()) as conn,conn:
        with conn.cursor() as cur:
            cur.execute('SELECT 1 FROM yossi_delivery_probes WHERE id=%s',(identity,))
            if cur.fetchone():
                return
    if not form_outreach.approval_ready(http,token,logger):
        return
    # Commit the reservation BEFORE any send. A crash/timeout never triggers a duplicate.
    with closing(connect()) as conn,conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO yossi_delivery_probes(id,phone,state) VALUES(%s,%s,'reserved') ON CONFLICT(id) DO NOTHING RETURNING id",(identity,phone))
            if not cur.fetchone():
                return
    state,mid,sender,codes='uncertain',None,None,[]
    headers={'Authorization':'Bearer '+token}
    try:
        info=http.get('https://graph.facebook.com/v26.0/'+str(number_id),
                      headers=headers,params={'fields':'display_phone_number,verified_name'},timeout=20)
        if info.status_code>=400:
            state='sender_check_failed'
        else:
            sender=re.sub(r'\D','',str(info.json().get('display_phone_number','')))
            if sender!='972508554415':
                state='sender_mismatch'
            else:
                response=http.post('https://graph.facebook.com/v26.0/'+str(number_id)+'/messages',
                    headers=headers,json={'messaging_product':'whatsapp','to':phone,'type':'template',
                    'template':{'name':form_outreach.TEMPLATE,'language':{'code':'he'}}},timeout=20)
                payload=response.json()
                code=(payload.get('error') or {}).get('code')
                if type(code) is int:
                    codes=[code]
                if response.status_code>=400:
                    state='rejected'
                else:
                    messages=payload.get('messages') or []
                    mid=messages[0].get('id') if messages else None
                    if isinstance(mid,str) and mid.startswith('wamid.'):
                        state='accepted'
    except Exception:
        logger.warning('DELIVERY_PROBE_OUTCOME_UNKNOWN')
    with closing(connect()) as conn,conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE yossi_delivery_probes SET state=%s,message_id=%s,sender_phone=%s,error_codes=%s::jsonb,completed_at=now() WHERE id=%s',
                        (state,mid,sender,json.dumps(codes),identity))
    logger.info('DELIVERY_PROBE_RESULT state=%s',state)
