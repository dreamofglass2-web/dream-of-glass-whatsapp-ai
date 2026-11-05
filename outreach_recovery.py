"""One owner-authorized resend for exact unopened historical form inquiries."""
import json,os,re
from contextlib import closing
from datetime import datetime,timezone
import form_outreach
from handoff_store import phone_lock,read_state


def configuration(env=None):
    env=os.environ if env is None else env
    items=[v.strip() for v in env.get('FORM_OUTREACH_RECOVERIES','').split(',') if v.strip()]
    if len(items)>3 or len(set(items))!=len(items):raise ValueError('At most three distinct recoveries')
    result=[]
    for item in items:
        match=re.fullmatch(r'([A-Za-z0-9_-]{1,100}):(9725\d{8})',item)
        if not match:raise ValueError('Exact source campaign and phone required')
        result.append(match.groups())
    return result


def ensure_tables(cur):
    cur.execute("SELECT pg_advisory_xact_lock(751109052)")
    cur.execute("""CREATE TABLE IF NOT EXISTS yossi_outreach_recoveries (
        campaign_id TEXT NOT NULL,phone TEXT NOT NULL,status TEXT NOT NULL,
        original_message_id TEXT, message_id TEXT,revision INTEGER NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),completed_at TIMESTAMPTZ,
        error_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
        PRIMARY KEY(campaign_id,phone))""")


def eligible(cur,campaign,phone,revision=None):
    state=read_state(cur,phone)
    if state['owner']!='yossi' or state['messages'] or (revision is not None and state['revision']!=revision):return None
    cur.execute("""SELECT o.message_id,l.conversation,l.last_inbound_at,l.context,
        EXISTS(SELECT 1 FROM yossi_message_receipts r WHERE r.message_id=o.message_id AND r.phone=o.phone AND r.status IN ('delivered','read'))
        FROM yossi_form_outreach o JOIN glass_leads l USING(phone)
        JOIN yossi_pilot_members m ON m.campaign_id=o.campaign_id AND m.phone=o.phone
        WHERE o.campaign_id=%s AND o.phone=%s AND o.status='accepted'""",(campaign,phone))
    row=cur.fetchone()
    if not row:return None
    mid,history,inbound,context,delivered=row
    if (delivered or inbound or not isinstance(history,list) or len(history)!=1
        or history[0].get('role')!='assistant' or history[0].get('content')!=form_outreach.BODY
        or not isinstance(context,dict) or context.get('simulation_recipient_id')
        or str(context.get('no_followups','')).lower()=='true'):return None
    return mid,state['revision']


def dispatch(connect,http,token,number_id,business_hours,logger,env=None):
    selected=configuration(env)
    if not selected or str(number_id)!=form_outreach.BUSINESS_NUMBER_ID or not token or not business_hours():return False
    for campaign,phone in selected:
        with closing(connect()) as db,db:
            with db.cursor() as cur:
                cur.execute('SELECT 1 FROM yossi_outreach_recoveries WHERE campaign_id=%s AND phone=%s',(campaign,phone))
                if cur.fetchone():continue
                phone_lock(cur,phone)
                target=eligible(cur,campaign,phone)
                if target is None:continue
        if not form_outreach.approval_ready(http,token,logger):return False
        with closing(connect()) as db,db:
            with db.cursor() as cur:
                phone_lock(cur,phone)
                target=eligible(cur,campaign,phone)
                if target is None:continue
                mid,revision=target
                cur.execute("""INSERT INTO yossi_outreach_recoveries(campaign_id,phone,status,original_message_id,revision)
                    VALUES(%s,%s,'reserved',%s,%s) ON CONFLICT DO NOTHING RETURNING phone""",(campaign,phone,mid,revision))
                if not cur.fetchone():continue
        # The committed reservation survives crashes. Never blind-retry uncertainty.
        with closing(connect()) as db,db:
            with db.cursor() as cur:
                phone_lock(cur,phone)
                if not business_hours() or eligible(cur,campaign,phone,revision) is None:
                    cur.execute("UPDATE yossi_outreach_recoveries SET status='canceled',completed_at=now() WHERE campaign_id=%s AND phone=%s",(campaign,phone))
                    return False
                status,new_mid,codes='uncertain',None,[]
                try:
                    response=http.post('https://graph.facebook.com/v26.0/'+str(number_id)+'/messages',
                        headers={'Authorization':'Bearer '+token},json={'messaging_product':'whatsapp','to':phone,'type':'template',
                        'template':{'name':form_outreach.TEMPLATE,'language':{'code':'he'}}},timeout=20)
                    payload=response.json()
                    if response.status_code>=400:
                        status='failed'
                        code=(payload.get('error') or {}).get('code')
                        if type(code) is int:codes=[code]
                    else:
                        messages=payload.get('messages') or []
                        new_mid=messages[0].get('id') if messages else None
                        if isinstance(new_mid,str) and new_mid.startswith('wamid.'):status='accepted'
                except Exception:logger.warning('OUTREACH_RECOVERY_OUTCOME_UNKNOWN')
                cur.execute("""UPDATE yossi_outreach_recoveries SET status=%s,message_id=%s,error_codes=%s::jsonb,completed_at=now()
                    WHERE campaign_id=%s AND phone=%s""",(status,new_mid,json.dumps(codes),campaign,phone))
                if status=='accepted':
                    at=datetime.now(timezone.utc).isoformat()
                    message={'role':'assistant','content':form_outreach.BODY,'at':at,'message_id':new_mid}
                    cur.execute("UPDATE glass_leads SET conversation=conversation || %s::jsonb,context=context || %s::jsonb,updated_at=now() WHERE phone=%s",
                        (json.dumps([message],ensure_ascii=False),json.dumps({'outreach_recovery':{'message_id':new_mid,'source_campaign':campaign,'at':at}}),phone))
                logger.info('OUTREACH_RECOVERY_RESULT status=%s phone_suffix=%s',status,phone[-4:])
                return status=='accepted'
    return False
