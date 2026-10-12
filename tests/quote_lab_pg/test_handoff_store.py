import os
import unittest
from quote_lab.postgres_store import PostgresQuoteStore
from handoff_store import ensure_tables, read_state, owner_action, record_message, authorized_send
from handoff_state import HandoffError


class HandoffStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = PostgresQuoteStore(os.environ['QUOTE_LAB_TEST_DATABASE_URL'])
        self.store._parameters['options'] = '-c search_path=handoff_test_stage,public'
        with self.store._transaction() as cursor:
            cursor.execute('CREATE SCHEMA IF NOT EXISTS handoff_test_stage')
            cursor.execute('CREATE TABLE IF NOT EXISTS glass_leads(phone TEXT PRIMARY KEY)')
            ensure_tables(cursor)
            cursor.execute('DELETE FROM yossi_handoffs')
            cursor.execute("INSERT INTO glass_leads(phone) VALUES('0000000999') ON CONFLICT DO NOTHING")
        self.now = '2026-10-12T15:00:00Z'

    def test_durable_summary_echo_and_duplicate_do_not_retake_returned_conversation(self):
        message = {'id':'wamid.test.operator', 'role':'operator', 'text':'קבענו למחר', 'at':self.now}
        with self.store._transaction() as cursor:
            state = record_message(cursor, '0000000999', message, operator=True)
            self.assertEqual(state['owner'], 'operator')
            state = owner_action(cursor, '0000000999', state['revision'],
                {'type':'notes', 'summary':'נקבע ביקור', 'instructions':'לאשר שעה'}, self.now)
            state = owner_action(cursor, '0000000999', state['revision'],
                {'type':'returnToYossi'}, self.now)
        with self.store._transaction() as cursor:
            self.assertEqual(state, record_message(cursor, '0000000999', message, operator=True))
            self.assertEqual(read_state(cursor, '0000000999')['owner'], 'yossi')

    def test_takeover_rejects_stale_send_and_failed_action_rolls_back(self):
        with self.store._transaction() as cursor:
            state = owner_action(cursor, '0000000999', 0, {'type':'takeover'}, self.now)
        import psycopg2
        connect = lambda: psycopg2.connect(**self.store._parameters)
        with self.assertRaises(HandoffError):
            with authorized_send(connect, '0000000999', 0):
                self.fail('Provider call must never be reached')
        with self.assertRaises(HandoffError):
            with self.store._transaction() as cursor:
                owner_action(cursor, '0000000999', state['revision'], {'type':'returnToYossi'}, self.now)
        with self.store._transaction() as cursor:
            self.assertEqual(read_state(cursor, '0000000999'), state)
