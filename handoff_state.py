"""Validated operator handoff records. No environment, database or send side effects.

The caller must authenticate the owner / Meta event and persist under a per-phone
transaction lock. These records are distinct from conversational model context.
"""
from copy import deepcopy
from datetime import datetime, timezone
import re


class HandoffError(ValueError):
    pass


def instant(value):
    if not isinstance(value, str) or not re.search(r'(Z|[+-]\d\d:\d\d)$', value):
        raise HandoffError('Timezone-aware timestamp required')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    except ValueError as exc:
        raise HandoffError('Invalid timestamp') from exc


def new_state():
    return {'revision': 0, 'owner': 'yossi', 'summary': '', 'instructions': '',
            'resume_at': None, 'updated_at': None, 'messages': [],
            'echo_verified': False, 'handoff_generation': 0}


def validate(state):
    if not isinstance(state, dict):
        raise HandoffError('Invalid handoff record')
    if type(state.get('revision')) is not int or state['revision'] < 0:
        raise HandoffError('Invalid revision')
    if state.get('owner') not in ('yossi', 'operator'):
        raise HandoffError('Invalid conversation owner')
    for field in ('summary', 'instructions'):
        if not isinstance(state.get(field), str) or len(state[field]) > 6000:
            raise HandoffError('Invalid operator notes')
    for field in ('resume_at', 'updated_at'):
        if state.get(field) is not None:
            instant(state[field])
    if type(state.get('echo_verified')) is not bool:
        raise HandoffError('Invalid echo capability')
    if type(state.get('handoff_generation')) is not int or state['handoff_generation'] < 0:
        raise HandoffError('Invalid handoff generation')
    messages = state.get('messages')
    if not isinstance(messages, list) or len(messages) > 500:
        raise HandoffError('Handoff history limit reached')
    seen = set()
    for message in messages:
        if not isinstance(message, dict) or message.get('role') not in ('customer', 'operator'):
            raise HandoffError('Invalid message')
        identity = message.get('id')
        if not isinstance(identity, str) or not identity or len(identity) > 200 or identity in seen:
            raise HandoffError('Invalid message identity')
        seen.add(identity)
        if not isinstance(message.get('text'), str) or len(message['text']) > 20000:
            raise HandoffError('Invalid message content')
        instant(message.get('at'))
    if sum(len(m['text'].encode('utf-8')) for m in messages) > 600000:
        raise HandoffError('Handoff history byte limit reached')
    return state


def transition(state, expected_revision, action, now):
    validate(state)
    instant(now)
    if type(expected_revision) is not int or expected_revision != state['revision']:
        raise HandoffError('Conversation changed; reload before retrying')
    next_state = deepcopy(state)
    kind = action.get('type') if isinstance(action, dict) else None
    if kind == 'takeover':
        if state['owner'] != 'yossi':
            raise HandoffError('Conversation is already assigned to operator')
        next_state['owner'] = 'operator'
        next_state['resume_at'] = None
        next_state['handoff_generation'] += 1
    elif kind == 'notes':
        if not isinstance(action.get('summary'), str) or not action['summary'].strip():
            raise HandoffError('Owner summary required before saving notes')
        next_state['summary'] = action.get('summary')
        next_state['instructions'] = action.get('instructions')
    elif kind == 'returnToYossi':
        if state['owner'] != 'operator':
            raise HandoffError('Conversation is not assigned to operator')
        if not state['summary'].strip():
            raise HandoffError('Owner summary required before returning conversation')
        # A summary is mandatory even with echoes: phone calls and commitments
        # may be absent from WhatsApp. Returning does not itself send a message.
        if action.get('resume_at') is not None:
            if instant(action['resume_at']) < instant(now):
                raise HandoffError('Resume time must not be in the past')
        next_state['resume_at'] = action.get('resume_at')
        next_state['owner'] = 'yossi'
        if next_state.get('escalation'):
            next_state['escalation']['active'] = False
    else:
        raise HandoffError('Unsupported owner action')
    next_state['updated_at'] = now
    next_state['revision'] += 1
    return validate(next_state)


def append_verified_message(state, message):
    """Only call after Meta signature, business-number and recipient validation.

    Event delivery order must not replace the original timestamps. Exact duplicate
    delivery is idempotent; conflicting reuse of a Meta message ID fails closed.
    """
    validate(state)
    existing = next((m for m in state['messages'] if m['id'] == message.get('id')), None)
    if existing is not None:
        if existing != message:
            raise HandoffError('Conflicting message identity')
        return deepcopy(state)
    result = deepcopy(state)
    result['messages'].append(deepcopy(message))
    result['messages'].sort(key=lambda m: (instant(m['at']), m['id']))
    result['revision'] += 1
    return validate(result)


def automatic_reply_allowed(state, now):
    validate(state)
    return state['owner'] == 'yossi' and (
        state['resume_at'] is None or instant(now) >= instant(state['resume_at']))


def resume_context(state):
    validate(state)
    return {'owner_summary': state['summary'], 'owner_instructions': state['instructions'],
            'manual_conversation': deepcopy(state['messages'][-36:]),
            'older_manual_messages_omitted': max(0, len(state['messages'])-36),
            'app_messages_verified': state['echo_verified'],
            'generation': state['handoff_generation']}

