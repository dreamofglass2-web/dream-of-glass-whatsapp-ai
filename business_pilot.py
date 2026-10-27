"""Durable, transaction-serialized admission for a finite owner-approved pilot."""
import os
import re
from datetime import datetime, timezone


def configuration(environ=None):
    env=os.environ if environ is None else environ
    identity=env.get('BUSINESS_PILOT_ID','').strip()
    if not identity:
        return None
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',identity):
        raise ValueError('Invalid pilot identity')
    limit=int(env.get('BUSINESS_PILOT_LIMIT','0'))
    start=datetime.fromisoformat(env.get('BUSINESS_PILOT_START_AT','').replace('Z','+00:00'))
    if not 1<=limit<=3 or start.tzinfo is None:
        raise ValueError('Invalid finite pilot configuration')
    return identity,start.astimezone(timezone.utc),limit


def ensure_tables(cur):
    cur.execute('''CREATE TABLE IF NOT EXISTS yossi_pilot_campaigns (
        id TEXT PRIMARY KEY, started_at TIMESTAMPTZ NOT NULL,
        max_leads INTEGER NOT NULL CHECK(max_leads BETWEEN 1 AND 3),
        configured_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    cur.execute('''CREATE TABLE IF NOT EXISTS yossi_pilot_members (
        campaign_id TEXT NOT NULL REFERENCES yossi_pilot_campaigns(id),
        phone TEXT NOT NULL, ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 3),
        first_inbound_at TIMESTAMPTZ NOT NULL, admitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY(campaign_id,phone), UNIQUE(campaign_id,ordinal))''')


def configure(cur,config):
    identity,start,limit=config
    cur.execute('INSERT INTO yossi_pilot_campaigns(id,started_at,max_leads) VALUES(%s,%s,%s) ON CONFLICT(id) DO NOTHING',(identity,start,limit))
    cur.execute('SELECT started_at,max_leads FROM yossi_pilot_campaigns WHERE id=%s FOR UPDATE',(identity,))
    row=cur.fetchone()
    if not row or row[0]!=start or row[1]!=limit:
        raise ValueError('Pilot identity cannot be reused with different limits or cutoff')


def allows(cur,config,phone):
    identity,start,limit=config
    cur.execute('''SELECT EXISTS(SELECT 1 FROM yossi_pilot_members m
        JOIN yossi_pilot_campaigns c ON c.id=m.campaign_id
        WHERE m.campaign_id=%s AND m.phone=%s AND c.started_at=%s AND c.max_leads=%s)''',(identity,phone,start,limit))
    return bool(cur.fetchone()[0])


def admit(cur,config,phone,timestamp):
    if not re.fullmatch(r'9725\d{8}',str(phone or '')):
        return False
    if not isinstance(timestamp,str) or not timestamp.isdigit() or len(timestamp)>12:
        return False
    try:
        inbound=datetime.fromtimestamp(int(timestamp),timezone.utc)
    except (ValueError,OverflowError,OSError):
        return False
    identity,start,limit=config
    if inbound<start:
        return False
    configure(cur,config)  # Campaign row lock serializes all concurrent admissions.
    if allows(cur,config,phone):
        return True
    cur.execute('SELECT created_at,context FROM glass_leads WHERE phone=%s',(phone,))
    row=cur.fetchone()
    if not row or row[0]<start or not isinstance(row[1],dict):
        return False
    context=row[1]
    forms=context.get('meta_leads') or {}
    verified=(isinstance(forms,dict) and any(isinstance(v,dict) and v.get('source')=='meta_instant_form' for v in forms.values())) or (context.get('whatsapp_referral') or {}).get('source') in ('meta_click_to_whatsapp_ad','meta_whatsapp_direct_inbound')
    if not verified or context.get('simulation_recipient_id') or str(context.get('no_followups','false')).lower()=='true':
        return False
    cur.execute('SELECT count(*) FROM yossi_pilot_members WHERE campaign_id=%s',(identity,))
    used=cur.fetchone()[0]
    if used>=limit:
        return False
    cur.execute('INSERT INTO yossi_pilot_members(campaign_id,phone,ordinal,first_inbound_at) VALUES(%s,%s,%s,%s)',(identity,phone,used+1,inbound))
    return True
