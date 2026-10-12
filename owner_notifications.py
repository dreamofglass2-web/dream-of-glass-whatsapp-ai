"""Owner-only template alerts; durable claim prevents duplicate/ambiguous retries."""
import os
import re
from handoff_store import phone_lock, read_state, write_state


def alert_configuration():
    phone = os.getenv('OWNER_ALERT_PHONE', '')
    template = os.getenv('OWNER_ALERT_TEMPLATE', '')
    language = os.getenv('OWNER_ALERT_LANGUAGE', 'he')
    if os.getenv('OWNER_ALERT_ENABLED') != 'true':
        return None
    if not re.fullmatch(r'9725\d{8}', phone) or not re.fullmatch(r'[a-z0-9_]{1,100}', template):
        return None
    if not re.fullmatch(r'[a-z]{2}(?:_[A-Z]{2})?', language):
        return None
    return phone, template, language


def dispatch_owner_alerts(connect, http, token, number_id, logger):
    config = alert_configuration()
    if not config or not token:
        return
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT phone FROM yossi_handoffs
                WHERE state->'escalation'->>'active'='true'
                AND state->'escalation'->>'notificationStatus'='not_configured'
                ORDER BY state->'escalation'->>'requestedAt' LIMIT 10""")
            phones = [r[0] for r in cur.fetchall()]
    for phone in phones:
        with connect() as conn:
            with conn.cursor() as cur:
                phone_lock(cur, phone)
                state = read_state(cur, phone)
                alert = state.get('escalation') or {}
                if not alert.get('active') or alert.get('notificationStatus') != 'not_configured':
                    continue
                # Commit claim before provider call. Timeouts are never retried blindly.
                alert['notificationStatus'] = 'sending'
                write_state(cur, phone, state)
                identity, reason = alert['id'], alert['reason']
        recipient, template, language = config
        link = 'https://yossi-david-crm-demo.abloompetal2.chatgpt.site/?attention=' + identity
        payload = {'messaging_product':'whatsapp','to':recipient,'type':'template',
            'template':{'name':template,'language':{'code':language},'components':[
                {'type':'body','parameters':[{'type':'text','text':v} for v in (phone,reason,link)]}]}}
        status = 'uncertain'
        try:
            response = http.post('https://graph.facebook.com/v26.0/' + str(number_id) + '/messages',
                headers={'Authorization':'Bearer ' + token}, json=payload, timeout=15)
            status = 'accepted' if response.ok else 'failed'
        except Exception:
            logger.warning('OWNER_ALERT_PROVIDER_UNCERTAIN')
        with connect() as conn:
            with conn.cursor() as cur:
                phone_lock(cur, phone)
                state = read_state(cur, phone)
                if (state.get('escalation') or {}).get('id') == identity:
                    state['escalation']['notificationStatus'] = status
                    write_state(cur, phone, state)
