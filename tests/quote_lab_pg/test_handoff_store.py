import os
import unittest
from quote_lab.postgres_store import PostgresQuoteStore
from handoff_store import ensure_tables, read_state, owner_action, record_message, authorized_send
from handoff_state import HandoffError


class HandoffStoreTests(unittest.TestCase):
    def test_paused_customer_inbound_reaches_source_without_operator_or_replay_advancement(self):
        with self.store._transaction() as cursor:
            cursor.execute("UPDATE glass_leads SET last_inbound_at='2026-10-12T15:00:00Z' WHERE phone='0000000999'")
            message={'id':'wamid.customer.returned','role':'customer','text':'חזרתי לבדוק','at':'2026-10-12T16:00:00Z'}
            record_message(cursor,'0000000999',message)
            record_message(cursor,'0000000999',message)
            record_message(cursor,'0000000999',{'id':'wamid.operator.response','role':'operator','text':'שלום','at':'2026-10-12T17:00:00Z'},operator=True)
            record_message(cursor,'0000000999',{'id':'inbound-batch-old','role':'customer','text':'ישן','at':'2026-10-12T18:00:00Z'})
            cursor.execute("SELECT last_inbound_at FROM glass_leads WHERE phone='0000000999'")
            self.assertEqual(cursor.fetchone()['last_inbound_at'].isoformat(),'2026-10-12T16:00:00+00:00')

    def test_blank_notes_do_not_overwrite_the_saved_summary(self):
        with self.store._transaction() as cursor:
            state=owner_action(cursor,'0000000999',0,{'type':'notes','summary':'סיכום שמור','instructions':'המשך'},self.now)
        with self.assertRaises(HandoffError):
            with self.store._transaction() as cursor:
                owner_action(cursor,'0000000999',state['revision'],{'type':'notes','summary':'','instructions':''},self.now)
        with self.store._transaction() as cursor:
            self.assertEqual(read_state(cursor,'0000000999'),state)

    def setUp(self):
        self.store = PostgresQuoteStore(os.environ['QUOTE_LAB_TEST_DATABASE_URL'])
        self.store._parameters['options'] = '-c search_path=handoff_test_stage,public'
        with self.store._transaction() as cursor:
            cursor.execute('CREATE SCHEMA IF NOT EXISTS handoff_test_stage')
            cursor.execute("CREATE TABLE IF NOT EXISTS glass_leads(phone TEXT PRIMARY KEY,status TEXT DEFAULT 'חדש',callback_request_id TEXT,last_inbound_at TIMESTAMPTZ)")
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

    def test_takeover_ack_waits_for_started_send_and_then_blocks_new_send(self):
        import threading
        import psycopg2
        started, release, acknowledged = threading.Event(), threading.Event(), threading.Event()
        failures=[]
        connect=lambda: psycopg2.connect(**self.store._parameters)
        def sender():
            try:
                with authorized_send(connect,'0000000999',0):
                    started.set()
                    if not release.wait(3):raise RuntimeError('Test send timed out')
            except Exception as error:failures.append(error)
        def owner():
            try:
                with self.store._transaction() as cursor:
                    owner_action(cursor,'0000000999',0,{'type':'takeover'},self.now)
                acknowledged.set()
            except Exception as error:failures.append(error)
        first=threading.Thread(target=sender);second=threading.Thread(target=owner)
        first.start()
        try:
            self.assertTrue(started.wait(2));second.start()
            self.assertFalse(acknowledged.wait(.1))
        finally:
            release.set();first.join(3)
            if second.ident is not None:second.join(3)
        self.assertFalse(failures);self.assertTrue(acknowledged.is_set())
        with self.assertRaises(HandoffError):
            with authorized_send(connect,'0000000999',0):
                self.fail('Paused conversation must not start a send')
