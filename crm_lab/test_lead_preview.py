from datetime import datetime,timezone
import ast
from pathlib import Path
import unittest
from crm_lab.lead_preview import preview_leads,LeadPreviewError

def fixture(**changes):
    result=dict(phone='0000000001',name='לקוח לדוגמה',product='מקלחון',status='חדש',
                callback_time='',notes='הערה פנימית לדוגמה',updated_at='2026-10-11T23:00:00+03:00')
    result.update(changes);return result

class LeadPreviewTests(unittest.TestCase):
    def test_legacy_status_never_creates_delivery_or_approval(self):
        for status,stage in [('חדש',0),('בטיפול',1),('ממתין לחזרה',1),('ממתין לתמונה',1),
                             ('ממתין לתמחור',1),('הצעה ניתנה',2),('נסגר',None),('אחר',None)]:
            c=preview_leads([fixture(status=status)])['customers'][0]
            self.assertEqual(c['stage'],stage);self.assertEqual(c['quote_versions'],[])
            self.assertFalse(c['verified_delivery']);self.assertFalse(c['verified_approval'])
            self.assertEqual(c['tasks_created'],0)
    def test_archived_lead_is_not_a_new_or_installed_customer(self):
        c=preview_leads([fixture(status='לא רלוונטי')])['customers'][0]
        self.assertTrue(c['archived']);self.assertIsNone(c['stage'])
    def test_missing_fields_and_callback_are_explicitly_incomplete(self):
        c=preview_leads([fixture(name='',product='',callback_time='מחר אחרי הצהריים')])['customers'][0]
        self.assertEqual(len(c['review_reasons']),3);self.assertEqual(c['callback_text'],'מחר אחרי הצהריים')
        self.assertEqual(c['tasks_created'],0)
    def test_stable_identity_timestamp_and_input_are_preserved(self):
        row=fixture();before=row.copy();a=preview_leads([row])['customers'][0]
        b=preview_leads([fixture(name='שם חדש')])['customers'][0]
        self.assertEqual(a['id'],b['id']);self.assertEqual(row,before)
        self.assertEqual(a['source_updated_at'],'2026-10-11T20:00:00+00:00')
        self.assertEqual(preview_leads([fixture(updated_at=datetime.now(timezone.utc))])['mode'],'synthetic_read_only_preview')
    def test_real_numbers_duplicate_records_and_invalid_shapes_are_rejected(self):
        for rows in ([fixture(phone='972501234567')],[fixture(),fixture()],None,
                     [fixture(updated_at='2026-10-11T23:00:00')],[fixture(notes='x'*3001)]):
            with self.assertRaises(LeadPreviewError):preview_leads(rows)
    def test_partial_batch_is_not_represented_as_complete(self):
        result=preview_leads([fixture()],has_more=True)
        self.assertTrue(result['has_more']);self.assertFalse(result['live_connection_enabled'])
        with self.assertRaises(LeadPreviewError):preview_leads([fixture()]*301)
    def test_production_app_does_not_import_crm_lab(self):
        tree=ast.parse((Path(__file__).resolve().parent.parent/'app.py').read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):self.assertFalse((node.module or '').startswith('crm_lab'))
            if isinstance(node,ast.Import):self.assertFalse(any(a.name.startswith('crm_lab') for a in node.names))
    def test_followup_times_preserve_source_generation_and_require_timezone(self):
        c=preview_leads([fixture(last_inbound_at='2026-10-10T21:00:00+03:00',manual_followup_completed_at='2026-10-11T18:01:00Z')])['customers'][0]
        self.assertEqual(c['last_inbound_at'],'2026-10-10T18:00:00+00:00')
        self.assertEqual(c['manual_followup_completed_at'],'2026-10-11T18:01:00+00:00')
        self.assertIsNone(preview_leads([fixture()])['customers'][0]['last_inbound_at'])
        with self.assertRaises(LeadPreviewError):preview_leads([fixture(last_inbound_at='2026-10-10T18:00:00')])
