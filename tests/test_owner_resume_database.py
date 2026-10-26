"""Disposable PostgreSQL owner-return delivery jobs. All external sends are mocked."""
import hashlib
import json
import os
import types
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
import psycopg2
os.environ.setdefault('OPENAI_API_KEY','sk-offline-test-only')
import app as yossi
from handoff_state import new_state, HandoffError
from handoff_store import owner_action, write_state


def connect():
    return psycopg2.connect(os.environ['DATABASE_URL'],sslmode='disable',connect_timeout=5)


class OwnerReturnPostgres(unittest.TestCase):
    def setUp(self):
        self.phone='TEST_FOLLOWUP_OWNER_RESUME'
        self.patches=[patch.object(yossi,'db_connection',side_effect=connect),
                      patch.object(yossi,'HANDOFF_ENABLED',True),
                      patch.object(yossi,'business_auto_reply_allowed',return_value=True),
                      patch.object(yossi,'verified_business_lead',return_value=True),
                      patch.object(yossi,'customer_freeform_send_allowed',return_value=True),
                      patch.object(yossi,'schedule_followup_dry_run'),
                      patch.object(yossi.requests,'post',side_effect=AssertionError('External sends forbidden in PG tests'))]
        for p in self.patches:p.start()
        self.addCleanup(lambda:[p.stop() for p in reversed(self.patches)])
        yossi.ensure_db();yossi.ensure_followup_table();yossi.ensure_inbound_queue_table();yossi.ensure_outbound_attempts_table()
        self.history=[{'role':'user','content':'כפתור יש לך דוגמאות?', 'at':'2026-10-19T10:00:00Z'}]
        with connect() as db:
            with db.cursor() as cur:
                yossi.ensure_handoff_tables(cur)
                cur.execute("INSERT INTO glass_leads(phone,conversation,context,last_inbound_at) VALUES(%s,%s::jsonb,%s::jsonb,now())",
                            (self.phone,json.dumps(self.history),json.dumps({'product':'מקלחון','handles':['ידית כפתור']})))
                write_state(cur,self.phone,dict(new_state(),owner='operator',revision=3,handoff_generation=1,
                    summary='הלקוח בחר כפתור',instructions='שלח דוגמאות של כפתור ומגבת'))
        self.addCleanup(self.cleanup)

    def cleanup(self):
        with connect() as db:
            with db.cursor() as cur:
                for table in ('yossi_handoffs','yossi_inbound_queue','yossi_outbound_attempts','yossi_followup_jobs'):
                    cur.execute('DELETE FROM '+table+' WHERE phone=%s',(self.phone,))
                cur.execute('DELETE FROM glass_leads WHERE phone=%s',(self.phone,))
        yossi._delivery_scope.current=None

    def enqueue(self,resume_at=None):
        with connect() as db:
            with db.cursor() as cur:
                state=owner_action(cur,self.phone,3,{'type':'returnToYossi','resume_at':resume_at},datetime.now(timezone.utc).isoformat())
                cur.execute('SELECT id,status FROM yossi_resume_jobs WHERE phone=%s',(self.phone,))
                self.job_id,status=cur.fetchone()
        self.assertEqual(status,'pending')
        return state

    def status(self):
        with connect() as db:
            with db.cursor() as cur:
                cur.execute('SELECT status FROM yossi_resume_jobs WHERE id=%s',(self.job_id,))
                return cur.fetchone()[0]

    def test_return_is_atomic_single_job_and_revision_replay_is_rejected(self):
        self.enqueue()
        with connect() as db:
            with db.cursor() as cur:
                with self.assertRaises(HandoffError):
                    owner_action(cur,self.phone,3,{'type':'returnToYossi'},datetime.now(timezone.utc).isoformat())
                cur.execute('SELECT count(*) FROM yossi_resume_jobs WHERE phone=%s',(self.phone,))
                self.assertEqual(cur.fetchone()[0],1)

    def test_restart_recovery_dispatches_both_examples_once_without_new_inbound(self):
        self.enqueue()
        data={'reply':'הנה שתי הדוגמאות. איזו ידית מתאימה לך?', 'product':'מקלחון','needs_human':False,
              'handles':['ידית כפתור','ידית מגבת'],'send_handle_images':True}
        catalog=[dict(url='https://example.test/button',handle='כפתור'),dict(url='https://example.test/towel',handle='מגבת')]
        with connect() as db:
            with db.cursor() as cur:
                cur.execute('SELECT last_inbound_at FROM glass_leads WHERE phone=%s',(self.phone,));before=cur.fetchone()[0]
        with patch.object(yossi.client.responses,'create',return_value=types.SimpleNamespace(output_text=json.dumps(data))) as model, \
             patch.object(yossi,'PHOTO_CATALOG',catalog),patch.object(yossi,'send_whatsapp') as send:
            # The durable job is discovered without any in-memory inbound queue entry.
            self.assertTrue(yossi.process_next_owner_resume())
            self.assertFalse(yossi.process_next_owner_resume())
        self.assertEqual(self.status(),'done');self.assertEqual(send.call_count,3);model.assert_called_once()
        with connect() as db:
            with db.cursor() as cur:
                cur.execute('SELECT conversation,last_inbound_at FROM glass_leads WHERE phone=%s',(self.phone,))
                history,after=cur.fetchone()
        self.assertEqual(before,after)
        self.assertEqual([m for m in history if m['role']=='user'],self.history)
        self.assertEqual(history[-1]['role'],'assistant')

    def test_new_customer_message_cancels_the_resume_job(self):
        self.enqueue()
        yossi.persist_inbound_message(self.phone,'בחרתי מגבת','TEST_OWNER_NEW_CUSTOMER')
        with patch.object(yossi,'process_owner_continuation') as continuation:
            self.assertFalse(yossi.process_next_owner_resume())
        continuation.assert_not_called();self.assertEqual(self.status(),'canceled')

    def test_owner_takeover_cancels_pending_work(self):
        self.enqueue()
        with connect() as db:
            with db.cursor() as cur:
                owner_action(cur,self.phone,4,{'type':'takeover'},datetime.now(timezone.utc).isoformat())
        self.assertEqual(self.status(),'canceled')
        with patch.object(yossi,'process_owner_continuation') as continuation:
            self.assertFalse(yossi.process_next_owner_resume())
        continuation.assert_not_called()

    def test_scheduled_return_is_not_dispatched_early(self):
        self.enqueue((datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
        with patch.object(yossi,'process_owner_continuation') as continuation:
            self.assertFalse(yossi.process_next_owner_resume())
        continuation.assert_not_called();self.assertEqual(self.status(),'pending')

    def test_prior_ambiguous_attempt_is_not_replayed(self):
        self.enqueue()
        fingerprint=hashlib.sha256(('owner-resume:'+self.job_id).encode()).hexdigest()
        yossi.reserve_outbound_attempt('TEST_OWNER_PRIOR_ATTEMPT',self.phone,fingerprint)
        with patch.object(yossi,'process_owner_continuation') as continuation:
            self.assertTrue(yossi.process_next_owner_resume())
        continuation.assert_not_called();self.assertEqual(self.status(),'needs_review')
        with connect() as db:
            with db.cursor() as cur:
                self.assertEqual(yossi.read_handoff_state(cur,self.phone)['owner'],'operator')

    def test_expired_window_reports_to_owner_without_fabricated_customer_text(self):
        self.enqueue()
        with patch.object(yossi,'customer_freeform_send_allowed',return_value=False), \
             patch.object(yossi,'send_whatsapp') as send:
            self.assertTrue(yossi.process_next_owner_resume())
        send.assert_not_called();self.assertEqual(self.status(),'blocked')
        with connect() as db:
            with db.cursor() as cur:
                cur.execute('SELECT conversation FROM glass_leads WHERE phone=%s',(self.phone,))
                self.assertEqual(cur.fetchone()[0],self.history)
                self.assertEqual(yossi.read_handoff_state(cur,self.phone)['owner'],'operator')

    def test_takeover_after_first_photo_stops_remaining_delivery(self):
        self.enqueue()
        data={'reply':'הנה דוגמאות', 'needs_human':False,'handles':['ידית כפתור','ידית מגבת'],'send_handle_images':True}
        catalog=[dict(url='https://example.test/button',handle='כפתור'),dict(url='https://example.test/towel',handle='מגבת')]
        provider=MagicMock(status_code=200)
        real_send=yossi.send_whatsapp
        def send_then_takeover(*args,**kwargs):
            real_send(*args,**kwargs)
            with connect() as db:
                with db.cursor() as cur:
                    owner_action(cur,self.phone,4,{'type':'takeover'},datetime.now(timezone.utc).isoformat())
        with patch.object(yossi.client.responses,'create',return_value=types.SimpleNamespace(output_text=json.dumps(data))), \
             patch.object(yossi,'PHOTO_CATALOG',catalog),patch.object(yossi,'send_whatsapp',side_effect=send_then_takeover), \
             patch.object(yossi.requests,'post',return_value=provider) as post:
            self.assertTrue(yossi.process_next_owner_resume())
        self.assertEqual(post.call_count,1)
        self.assertEqual(self.status(),'canceled')

    def test_customer_reply_between_photos_stops_without_re_escalating(self):
        self.enqueue()
        data={'reply':'הנה דוגמאות', 'needs_human':False,'handles':['ידית כפתור','ידית מגבת'],'send_handle_images':True}
        catalog=[dict(url='https://example.test/button',handle='כפתור'),dict(url='https://example.test/towel',handle='מגבת')]
        provider=MagicMock(status_code=200)
        real_send=yossi.send_whatsapp
        def send_then_inbound(*args,**kwargs):
            real_send(*args,**kwargs)
            yossi.persist_inbound_message(self.phone,'בעצם אל תשלח עוד תמונות','TEST_OWNER_DURING_SEND')
        with patch.object(yossi.client.responses,'create',return_value=types.SimpleNamespace(output_text=json.dumps(data))), \
             patch.object(yossi,'PHOTO_CATALOG',catalog),patch.object(yossi,'send_whatsapp',side_effect=send_then_inbound), \
             patch.object(yossi.requests,'post',return_value=provider) as post, \
             patch.object(yossi,'escalate_to_owner') as escalation:
            self.assertTrue(yossi.process_next_owner_resume())
        self.assertEqual(post.call_count,1)
        self.assertEqual(self.status(),'canceled')
        escalation.assert_not_called()


    def test_reset_clears_private_context_and_cancels_queued_continuation(self):
        previous=self.enqueue()
        yossi._delivery_scope.current={'handoff_revision':previous['revision']}
        self.assertTrue(yossi.reset_conversation_for_phone(self.phone))
        self.assertEqual(self.status(),'canceled')
        with connect() as db:
            with db.cursor() as cur:
                fresh=yossi.read_handoff_state(cur,self.phone)
                cur.execute('SELECT conversation FROM glass_leads WHERE phone=%s',(self.phone,))
                self.assertEqual(cur.fetchone()[0],[])
        self.assertEqual(fresh['owner'],'yossi')
        self.assertEqual(fresh['revision'],previous['revision']+1)
        self.assertEqual(fresh['handoff_generation'],previous['handoff_generation']+1)
        self.assertEqual(fresh['summary'],'')
        self.assertEqual(fresh['instructions'],'')
        self.assertEqual(fresh['messages'],[])
        self.assertNotIn('escalation',fresh)
        self.assertEqual(yossi._delivery_scope.current['handoff_revision'],fresh['revision'])
        with yossi.authorized_send(connect,self.phone,fresh['revision']):
            pass
        with self.assertRaises(HandoffError):
            with yossi.authorized_send(connect,self.phone,previous['revision']):
                self.fail('Old generation was authorized')

    def test_reset_never_releases_operator_ownership(self):
        self.assertTrue(yossi.reset_conversation_for_phone(self.phone))
        with connect() as db:
            with db.cursor() as cur:
                fresh=yossi.read_handoff_state(cur,self.phone)
        self.assertEqual(fresh['owner'],'operator')
        self.assertEqual(fresh['revision'],4)
        self.assertEqual(fresh['summary'],'')
        with self.assertRaises(HandoffError):
            with yossi.authorized_send(connect,self.phone,4):
                self.fail('Reset released an operator-owned chat')

    def test_stale_reset_rolls_back_dialogue_and_owner_notes(self):
        yossi._delivery_scope.current={'handoff_revision':2}
        self.assertFalse(yossi.reset_conversation_for_phone(self.phone))
        with connect() as db:
            with db.cursor() as cur:
                fresh=yossi.read_handoff_state(cur,self.phone)
                cur.execute('SELECT conversation FROM glass_leads WHERE phone=%s',(self.phone,))
                self.assertEqual(cur.fetchone()[0],self.history)
        self.assertEqual(fresh['revision'],3)
        self.assertEqual(fresh['summary'],'הלקוח בחר כפתור')


    def test_crm_reset_return_clears_old_persona_before_restart_safe_greeting(self):
        protected={'meta_leads':{'lead-1':{'source':'meta_instant_form'}},'no_phone_calls':True}
        with connect() as db:
            with db.cursor() as cur:
                cur.execute('UPDATE glass_leads SET context=%s::jsonb WHERE phone=%s',
                            (json.dumps(dict(protected,customer_name='מיכאל',handles=['ידית כפתור'],width_cm=166)),self.phone))
                original=yossi.read_handoff_state(cur,self.phone)
                original.update(summary='התחל שיחה חדשה',instructions='התחל שיחה חדשה')
                write_state(cur,self.phone,original)
                cur.execute('SELECT last_inbound_at FROM glass_leads WHERE phone=%s',(self.phone,))
                inbound=cur.fetchone()[0]
        returned=self.enqueue()
        with connect() as db:
            with db.cursor() as cur:
                cur.execute('SELECT conversation,context,last_inbound_at FROM glass_leads WHERE phone=%s',(self.phone,))
                history,context,current_inbound=cur.fetchone()
                cur.execute('SELECT reason,expected_revision FROM yossi_resume_jobs WHERE id=%s',(self.job_id,))
                self.assertEqual(cur.fetchone(),('conversation_reset',returned['revision']))
        self.assertEqual(history,[]);self.assertEqual(context,protected)
        self.assertEqual(current_inbound,inbound)
        self.assertEqual(returned['summary'],'');self.assertEqual(returned['instructions'],'')
        self.assertEqual(returned['messages'],[])
        yossi.histories[self.phone]=[{'role':'user','content':'מיכאל'}]
        yossi.customer_context[self.phone]={'customer_name':'מיכאל'}
        with patch.object(yossi.client.responses,'create') as model,patch.object(yossi,'send_whatsapp') as send:
            self.assertTrue(yossi.process_next_owner_resume())
            self.assertFalse(yossi.process_next_owner_resume())
        model.assert_not_called();send.assert_called_once()
        reply=send.call_args.kwargs['body']
        self.assertIn('מתחילים מחדש',reply);self.assertNotIn('מיכאל',reply)
        self.assertEqual(self.status(),'done')
        with connect() as db:
            with db.cursor() as cur:
                cur.execute('SELECT conversation,context FROM glass_leads WHERE phone=%s',(self.phone,))
                history,context=cur.fetchone()
        self.assertEqual(len(history),1);self.assertEqual(history[0]['role'],'assistant')
        self.assertEqual(context,protected)

    def test_paused_whatsapp_reset_is_applied_only_on_owner_return(self):
        # The command is recorded while paused, without releasing the operator.
        with patch.object(yossi,'send_whatsapp') as send:
            self.assertTrue(yossi.process_message(self.phone,'התחל שיחה חדשה'))
        send.assert_not_called()
        with connect() as db:
            with db.cursor() as cur:
                held=yossi.read_handoff_state(cur,self.phone)
                self.assertEqual(held['owner'],'operator')
                self.assertEqual(held['messages'][-1]['text'],'התחל שיחה חדשה')
                returned=owner_action(cur,self.phone,held['revision'],{'type':'returnToYossi'},datetime.now(timezone.utc).isoformat())
                cur.execute('SELECT conversation FROM glass_leads WHERE phone=%s',(self.phone,))
                self.assertEqual(cur.fetchone()[0],[])
        self.assertEqual(returned['owner'],'yossi');self.assertEqual(returned['summary'],'')
        with patch.object(yossi.client.responses,'create') as model,patch.object(yossi,'send_whatsapp') as send:
            self.assertTrue(yossi.process_next_owner_resume())
        model.assert_not_called();self.assertIn('מתחילים מחדש',send.call_args.kwargs['body'])

    def test_negated_owner_reset_instruction_preserves_sales_history(self):
        with connect() as db:
            with db.cursor() as cur:
                original=yossi.read_handoff_state(cur,self.phone)
                original['instructions']='אל תתחיל שיחה חדשה'
                write_state(cur,self.phone,original)
        returned=self.enqueue()
        with connect() as db:
            with db.cursor() as cur:
                cur.execute('SELECT conversation FROM glass_leads WHERE phone=%s',(self.phone,))
                self.assertEqual(cur.fetchone()[0],self.history)
        self.assertEqual(returned['summary'],'הלקוח בחר כפתור')


    def test_unpriced_reply_creates_real_owner_request_even_without_model_human_flag(self):
        with connect() as db:
            with db.cursor() as cur:
                write_state(cur,self.phone,dict(new_state(),revision=3))
                cur.execute('UPDATE glass_leads SET context=%s::jsonb WHERE phone=%s',
                            (json.dumps({'product':'מראה','customer_name':'מיכאל'}),self.phone))
        response={'reply':'מיכאל, הפרטים להכנת ההצעה קיימים, אבל עדיין אין לי מחיר מחושב ולכן קובץ ההצעה עוד לא מוכן.',
                  'product':'מראה','needs_human':False}
        with patch.object(yossi.client.responses,'create',return_value=types.SimpleNamespace(output_text=json.dumps(response))), \
             patch.object(yossi,'send_whatsapp') as send,patch.object(yossi,'has_new_messages',return_value=False):
            self.assertTrue(yossi.process_message(self.phone,'תודה מחכה להצעה'))
        send.assert_called_once()
        self.assertEqual(send.call_args.kwargs['body'],'אוקי, אני מכין לך הצעת מחיר.')
        with connect() as db:
            with db.cursor() as cur:
                held=yossi.read_handoff_state(cur,self.phone)
        self.assertEqual(held['owner'],'operator')
        self.assertTrue(held['escalation']['active'])
        self.assertIn('מחיר',held['escalation']['reason'])
        self.assertIn('תודה מחכה להצעה',held['escalation']['customerText'])
        self.assertIn('תודה מחכה להצעה',held['summary'])
        self.assertEqual(held['escalation']['notificationStatus'],'not_configured')

    def test_callback_time_is_saved_with_owner_task_summary_and_alert(self):
        with connect() as db:
            with db.cursor() as cur:
                write_state(cur,self.phone,dict(new_state(),revision=3))
                cur.execute("UPDATE glass_leads SET conversation='[]'::jsonb,context='{}'::jsonb WHERE phone=%s",(self.phone,))
        with patch.object(yossi.client.responses,'create') as ai, patch.object(yossi,'send_whatsapp') as send, patch.object(yossi,'has_new_messages',return_value=False):
            self.assertTrue(yossi.process_message(self.phone,'היי תתקשרו אליי בבקשה'))
            self.assertIn('מתי נוח',send.call_args.kwargs['body'])
            self.assertTrue(yossi.process_message(self.phone,'מחר בשעה 10'))
            ai.assert_not_called()
        with connect() as db:
            with db.cursor() as cur:
                state=yossi.read_handoff_state(cur,self.phone)
                cur.execute('SELECT status,callback_time,callback_request_id FROM glass_leads WHERE phone=%s',(self.phone,))
                status,preferred,identity=cur.fetchone()
        self.assertEqual(status,'ממתין לחזרה')
        self.assertIn('10:00',preferred)
        self.assertTrue(identity)
        self.assertEqual(state['owner'],'operator')
        self.assertIn('10:00',state['summary'])
        self.assertEqual(state['escalation']['notificationStatus'],'not_configured')
