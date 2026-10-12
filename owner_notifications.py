"""Owner-only Telegram or WhatsApp alerts; durable claim prevents duplicate/ambiguous retries."""
import os
import re
from handoff_store import phone_lock, read_state, write_state


def alert_configuration():
    if os.getenv('OWNER_ALERT_CHANNEL', 'whatsapp') == 'telegram':
        token = os.getenv('OWNER_TELEGRAM_BOT_TOKEN', '')
        chat_id = os.getenv('OWNER_TELEGRAM_CHAT_ID', '')
        if (os.getenv('OWNER_ALERT_ENABLED') == 'true'
                and re.fullmatch(r'[0-9]{5,20}:[A-Za-z0-9_-]{30,200}', token)
                and re.fullmatch(r'[1-9][0-9]{0,19}', chat_id)):
            return 'telegram', token, chat_id
        return None
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
    telegram = bool(config and config[0] == 'telegram')
    if not config or (not telegram and not token):
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
                customer_text = str(alert.get('customerText') or '')[:500]
                alert['notificationChannel'] = 'telegram' if telegram else 'whatsapp'
                write_state(cur, phone, state)
        recipient, template, language = config
        link = 'https://yossi-david-crm-demo.abloompetal2.chatgpt.site/?attention=' + identity
        payload = {'messaging_product':'whatsapp','to':recipient,'type':'template',
            'template':{'name':template,'language':{'code':language},'components':[
                {'type':'body','parameters':[{'type':'text','text':v} for v in (phone,reason,link)]}]}}
        status = 'uncertain'
        try:
            if telegram:
                bot_token, chat_id = template, language
                payload = {'chat_id':chat_id,
                    'text':'יוסי עצר — נדרשת עזרתך\nלקוח: ' + phone + '\nסיבה: ' + reason
                           + '\nהודעת הלקוח: ' + customer_text
                           + '\nיוסי נשאר עצור עד שתחזיר אותו דרך ה־CRM.',
                    'link_preview_options':{'is_disabled':True},
                    'reply_markup':{'inline_keyboard':[
                        [{'text':'פתיחת הפנייה ב־CRM','url':link}],
                        [{'text':'כניסה לשיחה בוואטסאפ','url':'https://wa.me/' + phone.lstrip('+')}]]}}
                response = http.post('https://api.telegram.org/bot' + bot_token + '/sendMessage',
                                     json=payload, timeout=15)
                result = response.json() if response.ok else {}
                message = result.get('result') or {}
                accepted = (result.get('ok') is True and type(message.get('message_id')) is int
                            and str((message.get('chat') or {}).get('id')) == chat_id)
                status = 'accepted' if accepted else 'failed'
            else:
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
