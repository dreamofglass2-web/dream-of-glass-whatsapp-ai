import unittest
from datetime import datetime
from active_sales_hours import active_session

def msg(role,at):return {'role':role,'at':at,'content':'בדיקה'}
class ActiveHoursTests(unittest.TestCase):
 def test_conversation_continues_across_close_and_idle_closes(self):
  history=[msg('user','2026-11-05T19:50:00+02:00'),msg('assistant','2026-11-05T19:51:00+02:00')]
  self.assertTrue(active_session(history,{},datetime.fromisoformat('2026-11-05T20:10:00+02:00')))
  self.assertFalse(active_session(history,{},datetime.fromisoformat('2026-11-05T20:52:00+02:00')))
 def test_continuous_conversation_can_continue_for_hours_but_not_new_night_session(self):
  history=[msg('user','2026-11-05T19:40:00+02:00'),msg('assistant','2026-11-05T19:41:00+02:00')]
  for hour in [20,21,22]:history.extend([msg('user',f'2026-11-05T{hour}:10:00+02:00'),msg('assistant',f'2026-11-05T{hour}:11:00+02:00')])
  self.assertTrue(active_session(history,{},datetime.fromisoformat('2026-11-05T22:30:00+02:00')))
  self.assertFalse(active_session([msg('user','2026-11-05T22:10:00+02:00'),msg('assistant','2026-11-05T22:11:00+02:00')],{},datetime.fromisoformat('2026-11-05T22:30:00+02:00')))
 def test_template_alone_unknown_time_and_closed_state_do_not_extend(self):
  now=datetime.fromisoformat('2026-11-05T20:05:00+02:00')
  self.assertFalse(active_session([msg('assistant','2026-11-05T19:50:00+02:00')],{},now))
  self.assertFalse(active_session([{'role':'assistant'}],{},now))
  history=[msg('user','2026-11-05T19:50:00+02:00'),msg('assistant','2026-11-05T19:51:00+02:00')]
  for ctx in [{'needs_human':True},{'stage':'closed'},{'no_followups':True}]:self.assertFalse(active_session(history,ctx,now))

class WorkerHoursTests(unittest.TestCase):
 def test_batch_gate_continues_only_an_authorized_active_chat(self):
  import app as yossi
  from unittest.mock import patch
  import time
  phone='972501234567';rows=[('test-mid',{'text':{'body':'כן'}},time.monotonic()-60)]
  with patch.object(yossi,'pending',{phone:rows}),patch.object(yossi,'processing',set()),patch.object(yossi,'business_auto_reply_allowed',return_value=True),patch.object(yossi,'is_simulation_contact',return_value=False),patch.object(yossi,'active_sales_reply_allowed',return_value=True):
   self.assertEqual(yossi.next_batch()[0],phone)
  with patch.object(yossi,'pending',{phone:rows}),patch.object(yossi,'processing',set()),patch.object(yossi,'business_auto_reply_allowed',return_value=True),patch.object(yossi,'is_simulation_contact',return_value=False),patch.object(yossi,'active_sales_reply_allowed',return_value=False):
   self.assertIsNone(yossi.next_batch())
  with patch.object(yossi,'pending',{phone:rows}),patch.object(yossi,'processing',set()),patch.object(yossi,'business_auto_reply_allowed',return_value=False),patch.object(yossi,'is_simulation_contact',return_value=False),patch.object(yossi,'active_sales_reply_allowed',return_value=True):
   self.assertIsNone(yossi.next_batch())
 def test_database_failure_does_not_enable_after_hours(self):
  import app as yossi
  from unittest.mock import patch
  yossi._after_hours_snapshots.clear()
  with patch.object(yossi,'is_yossi_business_hours',return_value=False),patch.object(yossi,'db_connection',side_effect=RuntimeError('offline')):
   self.assertFalse(yossi.active_sales_reply_allowed('972501234567'))
