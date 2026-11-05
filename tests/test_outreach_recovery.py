import unittest
from unittest.mock import MagicMock,patch
import outreach_recovery as r
import form_outreach
from handoff_state import new_state

class RecoveryTests(unittest.TestCase):
 def test_exact_configuration_bounded_and_unique(self):
  self.assertEqual(r.configuration({}),[])
  self.assertEqual(r.configuration({'FORM_OUTREACH_RECOVERIES':'old:972501234567'}),[('old','972501234567')])
  for value in ('bad','old:972501234567,old:972501234567',','.join('x'+str(i)+':97250123456'+str(i) for i in range(4))):
   with self.assertRaises(ValueError):r.configuration({'FORM_OUTREACH_RECOVERIES':value})
 def test_only_untouched_unconfirmed_template_can_recover(self):
  row=['wamid.old',[{'role':'assistant','content':form_outreach.BODY}],None,{},False]
  cur=MagicMock();cur.fetchone.return_value=row
  with patch.object(r,'read_state',return_value=new_state()):
   self.assertEqual(r.eligible(cur,'old','972501234567'),('wamid.old',0))
   for i,value in [(1,[]),(1,[{'role':'assistant','content':'different'}]),(2,'2026-11-05'),(3,{'no_followups':True}),(4,True)]:
    changed=list(row);changed[i]=value;cur.fetchone.return_value=changed
    self.assertIsNone(r.eligible(cur,'old','972501234567'))
  for state in [dict(new_state(),owner='operator'),dict(new_state(),messages=[{'role':'operator'}]),dict(new_state(),revision=2)]:
   with patch.object(r,'read_state',return_value=state):
    self.assertIsNone(r.eligible(cur,'old','972501234567',revision=0))
 def test_disabled_hours_or_channel_never_send(self):
  http=MagicMock()
  for env,number,hours in [({},form_outreach.BUSINESS_NUMBER_ID,True),({'FORM_OUTREACH_RECOVERIES':'old:972501234567'},'wrong',True),({'FORM_OUTREACH_RECOVERIES':'old:972501234567'},form_outreach.BUSINESS_NUMBER_ID,False)]:
   r.dispatch(MagicMock(),http,'token',number,lambda:hours,MagicMock(),env=env)
  http.post.assert_not_called()
