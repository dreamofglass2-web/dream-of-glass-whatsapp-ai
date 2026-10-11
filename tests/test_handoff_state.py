import unittest
from handoff_state import (new_state, transition, append_verified_message,
                           automatic_reply_allowed, resume_context, HandoffError)

NOW = '2026-10-11T23:00:00Z'


class HandoffTests(unittest.TestCase):
    def test_takeover_blocks_reply_and_followup_until_explicit_return(self):
        state = transition(new_state(), 0, {'type': 'takeover'}, NOW)
        self.assertFalse(automatic_reply_allowed(state, NOW))
        with self.assertRaises(HandoffError):
            transition(state, 1, {'type': 'returnToYossi'}, NOW)
        state = transition(state, 1, {'type': 'notes', 'summary': 'סיכמנו התקנה ביום ראשון',
                                    'instructions': 'לחזור רק לאישור שעה'}, NOW)
        state = transition(state, 2, {'type': 'returnToYossi',
                                     'resume_at': '2026-10-12T09:00:00+03:00'}, NOW)
        self.assertFalse(automatic_reply_allowed(state, NOW))
        self.assertTrue(automatic_reply_allowed(state, '2026-10-12T06:00:00Z'))
        self.assertIn('התקנה', resume_context(state)['owner_summary'])

    def test_echo_is_idempotent_and_preserves_chronology_and_sender(self):
        state = new_state()
        operator = {'id': 'wamid.owner', 'role': 'operator', 'text': 'קבענו למחר',
                    'at': '2026-10-11T23:01:00Z'}
        customer = {'id': 'wamid.customer', 'role': 'customer', 'text': 'מתי מגיעים?',
                    'at': NOW}
        state = append_verified_message(state, operator)
        state = append_verified_message(state, customer)
        self.assertEqual(state, append_verified_message(state, operator))
        self.assertEqual([m['role'] for m in state['messages']], ['customer', 'operator'])
        with self.assertRaises(HandoffError):
            append_verified_message(state, {**operator, 'text': 'changed'})
        self.assertFalse(resume_context(state)['app_messages_verified'])

    def test_stale_device_unknown_action_and_invalid_notes_fail_closed(self):
        state = transition(new_state(), 0, {'type': 'takeover'}, NOW)
        for revision, action in [(0, {'type': 'returnToYossi'}),
                                 (1, {'type': 'send'}),
                                 (1, {'type': 'notes', 'summary': 'x' * 6001,
                                      'instructions': ''})]:
            with self.assertRaises(HandoffError):
                transition(state, revision, action, NOW)
        self.assertEqual(state['revision'], 1)
        self.assertEqual(state['owner'], 'operator')


if __name__ == '__main__':
    unittest.main()
