"""Owner-triggered continuation; isolated model and provider, no customer sends."""
import json
import os
import types
import unittest
from contextlib import nullcontext
from unittest.mock import MagicMock, patch
os.environ.setdefault('OPENAI_API_KEY','sk-offline-test-only')
import app as yossi
from handoff_state import new_state


class OwnerContinuationTests(unittest.TestCase):
    def setUp(self):
        self.phone = 'OFFLINE_OWNER_RESUME_ONLY'
        self.state = dict(new_state(), revision=8, summary='הלקוח בחר כפתור',
                          instructions='תשלח לו דוגמה של ידית כפתור ומגבת')
        self.history = [{'role':'user','content':'כפתור יש לך דוגמאות?', 'at':'2026-10-19T10:00:00Z'}]
        self.prior = {'product':'מקלחון','handles':['ידית כפתור']}
        yossi._delivery_scope.current = {'fingerprint':'test-resume', 'ordinal':0,
                                        'handoff_revision':8,'resume_job_id':'test-job'}
        self.addCleanup(lambda:setattr(yossi._delivery_scope,'current',None))

    def test_summary_executes_both_existing_photos_without_fabricated_customer_inbound(self):
        data = {'reply':'הנה דוגמאות לידית כפתור ולידית מגבת. מה דעתך?',
                'product':'מקלחון','handles':['ידית כפתור','ידית מגבת'],
                'needs_human':False,'send_handle_images':True,'send_glass_images':False}
        catalog = [dict(url='https://res.cloudinary.com/yovjswn9/image/upload/glass_010.jpeg', glass='שקופה', product='מקלחון'),
                   dict(url='https://res.cloudinary.com/yovjswn9/image/upload/glass_009.jpeg', glass='שקופה', product='מקלחון')]
        with patch.object(yossi,'load_conversation',return_value=(list(self.history),dict(self.prior))), \
             patch.object(yossi.client.responses,'create',return_value=types.SimpleNamespace(output_text=json.dumps(data))) as model, \
             patch.object(yossi,'PHOTO_CATALOG',catalog), \
             patch.object(yossi,'HANDLE_BUTTON_IMAGE_URL',''), patch.object(yossi,'HANDLE_TOWEL_IMAGE_URL',''), \
             patch.object(yossi,'send_whatsapp') as send, patch.object(yossi,'save_conversation') as save, \
             patch.object(yossi,'authorized_send',return_value=nullcontext()):
            yossi.process_owner_continuation(self.phone,self.state)
        self.assertEqual(send.call_count,3)
        self.assertTrue(send.call_args_list[0].kwargs['image_url'].endswith('glass_010.jpeg'))
        self.assertTrue(send.call_args_list[1].kwargs['image_url'].endswith('glass_009.jpeg'))
        self.assertEqual(send.call_args_list[2].kwargs['body'],data['reply'])
        request=model.call_args.kwargs
        self.assertIn(self.state['instructions'],request['input'][1]['content'])
        self.assertEqual(request['input'][2:],[{'role':'user','content':self.history[0]['content']}])
        saved=save.call_args.args[1]
        self.assertEqual([m for m in saved if m['role']=='user'],self.history)
        self.assertNotIn(self.state['instructions'],str(saved))
        self.assertEqual(self.history[0]['at'],'2026-10-19T10:00:00Z')

    def test_text_continuation_does_not_guess_a_photo_request_from_historical_summary(self):
        data={'reply':'איזה גוון פרזול מתאים לך?', 'needs_human':False, 'send_handle_images':False}
        self.state['summary']='ביקש דוגמאות של ידיות וכבר שלחתי לו אותן'
        self.state['instructions']='תמשיך לברר את גוון הפרזול'
        with patch.object(yossi,'load_conversation',return_value=(self.history,self.prior)), \
             patch.object(yossi.client.responses,'create',return_value=types.SimpleNamespace(output_text=json.dumps(data))), \
             patch.object(yossi,'send_whatsapp') as send,patch.object(yossi,'save_conversation'), \
             patch.object(yossi,'authorized_send',return_value=nullcontext()):
            yossi.process_owner_continuation(self.phone,self.state)
        send.assert_called_once_with(self.phone,body=data['reply'])

    def test_unverified_price_is_not_sent_from_owner_summary(self):
        with patch.object(yossi,'load_conversation',return_value=(self.history,self.prior)), \
             patch.object(yossi.client.responses,'create',return_value=types.SimpleNamespace(output_text=json.dumps({'reply':'המחיר 999 ₪','needs_human':False}))), \
             patch.object(yossi,'send_whatsapp') as send:
            with self.assertRaisesRegex(ValueError,'unverified price'):
                yossi.process_owner_continuation(self.phone,self.state)
        send.assert_not_called()
