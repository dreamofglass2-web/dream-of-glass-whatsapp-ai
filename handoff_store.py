"""Durable operator ownership and WhatsApp Business echoes, without sending."""
import json
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from handoff_state import new_state, validate, transition, append_verified_message, automatic_reply_allowed, HandoffError


def ensure_tables(cursor):
    cursor.execute('''CREATE TABLE IF NOT EXISTS yossi_handoffs (
        phone TEXT PRIMARY KEY REFERENCES glass_leads(phone), state JSONB NOT NULL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS yossi_control_nonces (
        nonce TEXT PRIMARY KEY, expires TIMESTAMPTZ NOT NULL)''')


def phone_lock(cursor, phone):
    cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,827134))', (phone,))


def read_state(cursor, phone):
    cursor.execute('SELECT state FROM yossi_handoffs WHERE phone=%s', (phone,))
    row = cursor.fetchone()
    return validate(row['state'] if isinstance(row, dict) else row[0]) if row else new_state()


def write_state(cursor, phone, state):
    validate(state)
    cursor.execute('''INSERT INTO yossi_handoffs(phone,state) VALUES(%s,%s::jsonb)
        ON CONFLICT(phone) DO UPDATE SET state=EXCLUDED.state''',
                   (phone, json.dumps(state, ensure_ascii=False)))


def owner_action(cursor, phone, revision, action, now):
    phone_lock(cursor, phone)
    cursor.execute('SELECT 1 FROM glass_leads WHERE phone=%s', (phone,))
    if not cursor.fetchone():
        raise HandoffError('Customer not found')
    result = transition(read_state(cursor, phone), revision, action, now)
    if action.get('type') == 'takeover':
        capture_suppression(cursor, phone, result)
    write_state(cursor, phone, result)
    return result


def capture_suppression(cursor, phone, state):
    cursor.execute('SELECT status,callback_request_id,last_inbound_at FROM glass_leads WHERE phone=%s', (phone,))
    row = cursor.fetchone()
    if isinstance(row, dict):
        status, callback, inbound = row['status'], row['callback_request_id'], row['last_inbound_at']
    else:
        status, callback, inbound = row
    state['silenced_callback_id'] = (callback or 'legacy') if status == 'ממתין לחזרה' else None
    state['silenced_inbound_at'] = inbound.isoformat() if inbound else None


def record_message(cursor, phone, message, *, operator=False):
    phone_lock(cursor, phone)
    state = read_state(cursor, phone)
    result = append_verified_message(state, message)
    if (result['revision'] != state['revision'] and message['role'] == 'customer'
            and not message['id'].startswith('inbound-batch-')):
        # A paused customer's original Meta timestamp must reach the source CRM.
        # Replays/operator messages never advance inbound. Queued batches already
        # recorded their inbound at admission: never use their later processing time.
        cursor.execute('''UPDATE glass_leads SET last_inbound_at=
            GREATEST(last_inbound_at,%s::timestamptz) WHERE phone=%s''', (message['at'],phone))
    if operator:
        result['echo_verified'] = True
        # A manual message itself takes ownership. Duplicate delivery must never
        # pause a conversation that the owner has subsequently returned to Yossi.
        if result['revision'] != state['revision'] and result['owner'] == 'yossi':
            result = transition(result, result['revision'], {'type': 'takeover'}, message['at'])
            capture_suppression(cursor, phone, result)
    write_state(cursor, phone, result)
    return result


@contextmanager
def authorized_send(connect, phone, expected_revision):
    """Hold the same per-phone transaction lock through the provider request.

    An accepted takeover waits for any already-started send. After its acknowledgement,
    stale model generations and queued automatic sends cannot start a provider call.
    """
    with closing(connect()) as connection, connection:
        with connection.cursor() as cursor:
            phone_lock(cursor, phone)
            state = read_state(cursor, phone)
            now = datetime.now(timezone.utc).isoformat()
            if expected_revision is None or state['revision'] != expected_revision or not automatic_reply_allowed(state, now):
                raise HandoffError('Automatic send stopped by operator handoff')
            yield


def parse_echoes(change, business_number_id):
    """Use only after authentication of the complete Meta webhook envelope."""
    if not isinstance(change, dict) or change.get('field') != 'smb_message_echoes':
        return []
    value = change.get('value') or {}
    if value.get('messaging_product') != 'whatsapp' or str((value.get('metadata') or {}).get('phone_number_id')) != str(business_number_id):
        return []
    messages = value.get('message_echoes', [])
    if not isinstance(messages, list) or len(messages) > 100:
        raise HandoffError('Invalid echo batch')
    result = []
    import re
    for message in messages:
        phone = str(message.get('to') or '')
        if not re.fullmatch(r'[1-9][0-9]{7,14}', phone):
            raise HandoffError('Invalid echo recipient')
        if message.get('type') != 'text':
            # Media/edit/revoke semantics must be implemented before claiming
            # complete coverage. Do not turn unsupported events into fake text.
            continue
        timestamp = message.get('timestamp')
        if not isinstance(timestamp, str) or not timestamp.isdigit() or len(timestamp) > 12:
            raise HandoffError('Invalid echo timestamp')
        try:
            at = datetime.fromtimestamp(int(timestamp), timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError) as exc:
            raise HandoffError('Invalid echo timestamp') from exc
        item = {'id': message.get('id'), 'role': 'operator',
                'text': (message.get('text') or {}).get('body'), 'at': at}
        append_verified_message(new_state(), item)
        result.append((phone, item))
    return result
