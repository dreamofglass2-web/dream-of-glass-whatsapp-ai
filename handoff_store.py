"""Durable operator ownership and WhatsApp Business echoes, without sending."""
import json
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from handoff_state import new_state, validate, transition, append_verified_message, automatic_reply_allowed, HandoffError


def ensure_tables(cursor):
    cursor.execute('''CREATE TABLE IF NOT EXISTS yossi_handoffs (
        phone TEXT PRIMARY KEY REFERENCES glass_leads(phone), state JSONB NOT NULL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS yossi_resume_jobs (
        id TEXT PRIMARY KEY, phone TEXT NOT NULL REFERENCES glass_leads(phone) ON DELETE CASCADE,
        expected_revision INTEGER NOT NULL, available_at TIMESTAMPTZ NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', reason TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ)''')
    cursor.execute('''CREATE INDEX IF NOT EXISTS yossi_resume_jobs_pending_idx
        ON yossi_resume_jobs(available_at) WHERE status='pending' ''')
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


def reset_sales_handoff(cursor, phone, now, expected_revision=None):
    """Reset dialogue control atomically without lifting operator ownership."""
    phone_lock(cursor, phone)
    previous = read_state(cursor, phone)
    if expected_revision is not None and previous['revision'] != expected_revision:
        raise HandoffError('Conversation changed during reset')
    result = dict(new_state(), revision=previous['revision'] + 1,
                  owner=previous['owner'], resume_at=previous['resume_at'],
                  handoff_generation=previous['handoff_generation'] + 1,
                  echo_verified=previous['echo_verified'], updated_at=now,
                  conversation_started_at=now)
    capture_suppression(cursor, phone, result)
    write_state(cursor, phone, result)
    cursor.execute("UPDATE yossi_resume_jobs SET status='canceled',reason='conversation_reset',completed_at=now() WHERE phone=%s AND status='pending'", (phone,))
    return result


def owner_action(cursor, phone, revision, action, now):
    phone_lock(cursor, phone)
    cursor.execute('SELECT 1 FROM glass_leads WHERE phone=%s', (phone,))
    if not cursor.fetchone():
        raise HandoffError('Customer not found')
    result = transition(read_state(cursor, phone), revision, action, now)
    if action.get('type') == 'takeover':
        capture_suppression(cursor, phone, result)
    write_state(cursor, phone, result)
    if action.get('type') == 'returnToYossi':
        import hashlib
        identity = hashlib.sha256(('owner-resume:' + phone + ':' + str(result['revision'])).encode()).hexdigest()
        cursor.execute('''INSERT INTO yossi_resume_jobs(id,phone,expected_revision,available_at)
            VALUES(%s,%s,%s,%s::timestamptz) ON CONFLICT(id) DO NOTHING''',
            (identity, phone, result['revision'], result.get('resume_at') or now))
    elif action.get('type') in ('takeover', 'notes'):
        cursor.execute("UPDATE yossi_resume_jobs SET status='canceled',reason='owner_changed',completed_at=now() WHERE phone=%s AND status='pending'", (phone,))
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
def authorized_send(connect, phone, expected_revision, *, resume_job_id=None):
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
            if resume_job_id:
                cursor.execute("SELECT status FROM yossi_resume_jobs WHERE id=%s AND phone=%s", (resume_job_id,phone))
                job = cursor.fetchone()
                if not job or job[0] != 'pending':
                    raise HandoffError('Owner continuation canceled')
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


def escalate_to_owner(cursor, phone, reason, customer_text, now, *, record_customer=True):
    """Persist pause and owner request atomically, without customer sends."""
    import hashlib
    phone_lock(cursor, phone)
    # The triggering inbound must remain visible in the source CRM even when
    # process_message exits before its normal save_conversation call.
    if record_customer:
        cursor.execute("""UPDATE glass_leads SET conversation =
            CASE WHEN conversation->-1->>'role' = 'user'
                      AND conversation->-1->>'content' = %s
                 THEN conversation
                 ELSE COALESCE(conversation,'[]'::jsonb) ||
                      jsonb_build_array(jsonb_build_object(
                          'role','user','content',%s::text,'at',%s::text))
            END WHERE phone=%s""", (str(customer_text),str(customer_text),now,phone))
    state = read_state(cursor, phone)
    if state['owner'] == 'operator' and (state.get('escalation') or {}).get('active'):
        return state
    if state['owner'] == 'operator':
        # Preserve manual ownership, notes and generation; only create the request.
        from copy import deepcopy
        result = deepcopy(state)
        result['revision'] += 1
        result['updated_at'] = now
    else:
        result = transition(state, state['revision'], {'type':'takeover'}, now)
        capture_suppression(cursor, phone, result)
    identity = hashlib.sha256((phone + ':' + str(result['handoff_generation'])).encode()).hexdigest()[:32]
    result['escalation'] = {'id':identity, 'active':True, 'reason':reason[:300],
        'customerText':str(customer_text)[:1800], 'requestedAt':now,
        'notificationStatus':'not_configured'}
    write_state(cursor, phone, result)
    return result

