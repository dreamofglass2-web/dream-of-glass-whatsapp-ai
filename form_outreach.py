"""Single approved-template opening for consent-verified forms in a finite pilot."""
import json
import os
import re
from contextlib import closing
from datetime import datetime, timezone, timedelta
import business_pilot
from handoff_store import phone_lock, read_state
from handoff_state import automatic_reply_allowed

TEMPLATE = 'yossi_lead_opening_he_v1'
TEMPLATE_ID = '1112015734808257'
BUSINESS_NUMBER_ID = '456765487527572'
BUSINESS_PAGE_ID = '478369542034629'
BODY = ('היי, כאן יוסי מחלומות מזכוכית.\n'
        'קיבלתי את הפנייה שהשארת ואשמח לעזור לך להתאים פתרון והצעת מחיר.\n'
        'נוח לך שנמשיך כאן בוואטסאפ?')


def configuration(env=None):
    env = os.environ if env is None else env
    if env.get('FORM_OUTREACH_ENABLED', '').lower() != 'true':
        return None
    pilot = business_pilot.configuration(env)
    forms = [s.strip() for s in env.get('FORM_OUTREACH_FORM_IDS', '').split(',') if s.strip()]
    if not pilot or not forms or not (forms == ['*'] or all(re.fullmatch(r'\d+', f) for f in forms)):
        raise ValueError('Finite pilot and consent-verified form IDs required')
    return pilot, forms


def ensure_tables(cur):
    cur.execute('ALTER TABLE yossi_pilot_members ALTER COLUMN first_inbound_at DROP NOT NULL')
    cur.execute('ALTER TABLE yossi_pilot_members ADD COLUMN IF NOT EXISTS first_form_at TIMESTAMPTZ')
    cur.execute('''CREATE TABLE IF NOT EXISTS yossi_form_outreach (
        campaign_id TEXT NOT NULL REFERENCES yossi_pilot_campaigns(id),
        phone TEXT NOT NULL, lead_id TEXT NOT NULL, form_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', revision INTEGER NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ, message_id TEXT, reason TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(campaign_id,phone))''')


def pristine(cur, phone, start, revision=None):
    cur.execute('SELECT created_at,context,last_inbound_at,conversation FROM glass_leads WHERE phone=%s', (phone,))
    row = cur.fetchone()
    if not row or row[0] < start or row[3]:
        return None
    # A weekend can outlast the free-form window before the first answer.
    # Reopen only this unanswered, verified form with the approved template.
    if row[2] and row[2] + timedelta(hours=24) > datetime.now(timezone.utc):
        return None
    context = row[1] or {}
    if context.get('simulation_recipient_id') or str(context.get('no_followups', '')).lower() == 'true':
        return None
    state = read_state(cur, phone)
    if state['messages'] or not automatic_reply_allowed(state, datetime.now(timezone.utc).isoformat()):
        return None
    if revision is not None and state['revision'] != revision:
        return None
    return state


def enqueue(cur, cfg, lead_id, phone):
    pilot, forms = cfg
    campaign, start, limit = pilot
    excluded = set(os.getenv('BUSINESS_REPLY_TEST_SENDERS', '').split(',')) | set(os.getenv('SIMULATION_ALLOWED_SENDERS', '').split(','))
    if phone in excluded or not re.fullmatch(r'9725\d{8}', str(phone or '')):
        return False
    cur.execute('''SELECT form_id,received_at,meta_created_time,page_id FROM meta_leadgen_events
        WHERE lead_id=%s AND state='details_saved' ''', (lead_id,))
    event = cur.fetchone()
    if not event or event[3] != BUSINESS_PAGE_ID or (forms != ['*'] and event[0] not in forms) or event[1] < start or not event[2]:
        return False
    if datetime.fromtimestamp(event[2], timezone.utc) < start:
        return False
    phone_lock(cur, phone)
    state = pristine(cur, phone, start)
    if state is None:
        return False
    cur.execute('SELECT context FROM glass_leads WHERE phone=%s', (phone,))
    form = ((cur.fetchone()[0] or {}).get('meta_leads') or {}).get(lead_id) or {}
    if form.get('source') != 'meta_instant_form':
        return False
    business_pilot.configure(cur, pilot)
    if not business_pilot.allows(cur, pilot, phone):
        cur.execute('SELECT count(*) FROM yossi_pilot_members WHERE campaign_id=%s', (campaign,))
        used = cur.fetchone()[0]
        if used >= limit:
            return False
        cur.execute('''INSERT INTO yossi_pilot_members(campaign_id,phone,ordinal,first_form_at)
            VALUES(%s,%s,%s,%s)''', (campaign, phone, used + 1, event[1]))
    cur.execute('''INSERT INTO yossi_form_outreach(campaign_id,phone,lead_id,form_id,revision)
        VALUES(%s,%s,%s,%s,%s) ON CONFLICT(campaign_id,phone) DO NOTHING''',
        (campaign, phone, lead_id, event[0], state['revision']))
    return cur.rowcount == 1


def template_approved(http, token):
    response = http.get('https://graph.facebook.com/v26.0/' + TEMPLATE_ID,
        params={'fields': 'name,status,language,components'},
        headers={'Authorization': 'Bearer ' + token}, timeout=12)
    response.raise_for_status()
    item = response.json()
    components = item.get('components') or []
    return (item.get('name') == TEMPLATE and item.get('status') == 'APPROVED'
            and item.get('language') == 'he'
            and len(components) == 1 and components[0].get('type') == 'BODY'
            and components[0].get('text') == BODY)


def deliver(connect, http, token, number_id, cfg, phone, revision, business_hours, logger):
    pilot, _ = cfg
    campaign, start, _ = pilot
    with closing(connect()) as conn, conn:
        with conn.cursor() as cur:
            phone_lock(cur, phone)
            allowed = (business_hours() and pristine(cur, phone, start, revision) is not None
                       and business_pilot.allows(cur, pilot, phone))
            if not allowed:
                cur.execute('''UPDATE yossi_form_outreach SET status='canceled',reason='conversation_changed',completed_at=now()
                    WHERE campaign_id=%s AND phone=%s''', (campaign, phone))
                return False
            status, message_id, reason = 'uncertain', None, 'provider_outcome_unknown'
            try:
                response = http.post('https://graph.facebook.com/v26.0/' + str(number_id) + '/messages',
                    headers={'Authorization': 'Bearer ' + token},
                    json={'messaging_product': 'whatsapp', 'to': phone, 'type': 'template',
                          'template': {'name': TEMPLATE, 'language': {'code': 'he'}}}, timeout=20)
                if response.status_code >= 400:
                    status, reason = 'failed', 'provider_rejected'
                else:
                    messages = response.json().get('messages') or []
                    message_id = messages[0].get('id') if messages else None
                    if isinstance(message_id, str) and message_id.startswith('wamid.'):
                        status, reason = 'accepted', ''
            except Exception:
                logger.warning('FORM_OUTREACH_PROVIDER_OUTCOME_UNKNOWN')
            cur.execute('''UPDATE yossi_form_outreach SET status=%s,message_id=%s,reason=%s,completed_at=now()
                WHERE campaign_id=%s AND phone=%s''', (status, message_id, reason, campaign, phone))
            if status == 'accepted':
                message = {'role': 'assistant', 'content': BODY, 'at': datetime.now(timezone.utc).isoformat()}
                cur.execute('''UPDATE glass_leads SET conversation=conversation || %s::jsonb,
                    context=context || %s::jsonb,updated_at=now() WHERE phone=%s''',
                    (json.dumps([message], ensure_ascii=False),
                     json.dumps({'form_outreach': {'message_id': message_id, 'template': TEMPLATE}}), phone))
            return status == 'accepted'


def dispatch(connect, http, token, number_id, business_hours, logger):
    cfg = configuration()
    if not cfg or not business_hours() or not token or str(number_id) != BUSINESS_NUMBER_ID:
        return False
    # No free-form 24-hour exception: only this exact approved template may initiate.
    if not template_approved(http, token):
        return False
    pilot, forms = cfg
    campaign, start, _ = pilot
    with closing(connect()) as conn, conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('meta_leadgen_events')")
            if not cur.fetchone()[0]:
                return False
            cur.execute('''SELECT e.lead_id,l.phone FROM meta_leadgen_events e
                JOIN glass_leads l ON l.context->'meta_leads' ? e.lead_id
                WHERE e.state='details_saved' AND e.received_at >= %s
                AND e.page_id=%s AND (%s OR e.form_id=ANY(%s))
                AND (l.last_inbound_at IS NULL OR l.last_inbound_at <= now()-interval '24 hours')
                AND l.conversation='[]'::jsonb
                ORDER BY e.received_at LIMIT 100''', (start, BUSINESS_PAGE_ID, forms == ['*'], forms))
            candidates = cur.fetchall()
    for lead_id, phone in candidates:
        with closing(connect()) as conn, conn:
            with conn.cursor() as cur:
                enqueue(cur, cfg, lead_id, phone)
    with closing(connect()) as conn, conn:
        with conn.cursor() as cur:
            cur.execute('''UPDATE yossi_form_outreach SET status='uncertain',reason='interrupted_send'
                WHERE status='sending' AND started_at < now()-interval '2 minutes' ''')
            cur.execute('''SELECT phone,revision FROM yossi_form_outreach
                WHERE campaign_id=%s AND status='pending' ORDER BY created_at
                FOR UPDATE SKIP LOCKED LIMIT 1''', (campaign,))
            job = cur.fetchone()
            if not job:
                return False
            phone, revision = job
            # Commit this claim before the provider request: ambiguous sends never retry.
            cur.execute('''UPDATE yossi_form_outreach SET status='sending',started_at=now()
                WHERE campaign_id=%s AND phone=%s''', (campaign, phone))
    return deliver(connect, http, token, number_id, cfg, phone, revision, business_hours, logger)
