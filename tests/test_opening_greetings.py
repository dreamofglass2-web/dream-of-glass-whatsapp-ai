import unittest
from datetime import datetime
from unittest.mock import Mock,patch
import opening_greetings as g
import form_outreach as f
class GreetingTests(unittest.TestCase):
 def test_actual_israel_time_and_boundaries_including_utc_offset(self):
  for time,label in [('2026-11-05T11:59:59+02:00','morning'),('2026-11-05T12:00:00+02:00','afternoon'),('2026-11-05T16:59:59+02:00','afternoon'),('2026-11-05T17:00:00+02:00','evening'),('2026-07-05T09:00:00Z','afternoon')]:
   self.assertEqual(g.selected(datetime.fromisoformat(time)),g.VARIANTS[label])
 def test_exact_approved_name_language_and_body_required(self):
  name,identity,body=g.VARIANTS['morning'];http=Mock()
  item={'name':name,'status':'APPROVED','language':'he','components':[{'type':'BODY','text':body}]}
  http.get.return_value.json.return_value=item
  self.assertTrue(f.template_approved(http,'offline',g.VARIANTS['morning']))
  self.assertTrue(http.get.call_args.args[0].endswith(identity))
  for changed in [dict(item,status='PENDING'),dict(item,name='other'),dict(item,language='en'),dict(item,components=[{'type':'BODY','text':'wrong greeting'}])]:
   http.get.return_value.json.return_value=changed
   self.assertFalse(f.template_approved(http,'offline',g.VARIANTS['morning']))
 def test_pending_slot_does_not_poison_other_slot_cache(self):
  f._approval_retry_after.clear()
  with patch.object(f,'template_approved',side_effect=[False,True]) as approved:
   self.assertFalse(f.approval_ready(Mock(),'offline',Mock(),g.VARIANTS['morning']))
   self.assertTrue(f.approval_ready(Mock(),'offline',Mock(),g.VARIANTS['evening']))
   self.assertEqual(approved.call_count,2)
  f._approval_retry_after.clear()
