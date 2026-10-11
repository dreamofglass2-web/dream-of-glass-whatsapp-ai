import unittest
from crm_lab.customer_detail import project_detail
from crm_lab.test_lead_preview import fixture
from crm_lab.lead_preview import LeadPreviewError
from crm_lab.read_source import ReadOnlyLeadSource
class CustomerDetailTests(unittest.TestCase):
    def row(self,**changes):return fixture(conversation=[{'role':'user','content':'שלום'},{'role':'assistant','content':'איך אפשר לעזור?'},{'role':'user','content':'שלום'}],**changes)
    def test_complete_order_and_repeated_messages_are_preserved_without_fabricated_time(self):
        result=project_detail(self.row());messages=result['conversation']
        self.assertEqual([m['content'] for m in messages],['שלום','איך אפשר לעזור?','שלום'])
        self.assertEqual(len({m['id'] for m in messages}),3);self.assertTrue(result['conversation_complete'])
        self.assertTrue(all(m['sent_at'] is None and not m['delivery_verified'] for m in messages))
    def test_legacy_quote_is_exact_but_not_verified_version_history(self):
        result=project_detail(self.row(legacy_quote={'issued':True,'approved':True,'amount_ils_pre_vat':2828,'configuration':'פינתי','width_cm':90}))
        self.assertEqual(result['legacy_quote']['amount_cents'],282800);self.assertIsNone(result['legacy_quote']['version'])
        self.assertFalse(result['legacy_quote']['verified_approval']);self.assertEqual(result['quote_versions'],[])
        self.assertNotIn('context',result)
    def test_callback_does_not_invent_schedule_or_persistent_request_id(self):
        result=project_detail(self.row(status='ממתין לחזרה',callback_time='מחר'))
        self.assertIsNone(result['callback']['due_at']);self.assertIsNone(result['callback']['request_id'])
        self.assertEqual(result['callback']['requested_time_text'],'מחר')
    def test_media_blocks_preserve_text_without_exporting_private_image_urls(self):
        row=self.row();row['conversation']=[{'role':'user','content':[{'type':'text','text':'תמונה'},{'type':'image_url','image_url':{'url':'private-test-url'}}]}]
        result=project_detail(row);self.assertEqual(result['conversation'][0]['attachment_count'],1)
        self.assertNotIn('private-test-url',str(result))
    def test_malformed_or_excessive_history_and_invalid_price_fail_without_truncation(self):
        for change in ({'conversation':[{'role':'system','content':'private'}]}, {'conversation':[{'role':'user','content':'x'}]*1001},
                       {'legacy_quote':{'issued':True,'amount_ils_pre_vat':True}}, {'legacy_quote':{'issued':True,'amount_ils_pre_vat':'1.001'}},
                       {'legacy_quote':{'issued':True,'amount_ils_pre_vat':'NaN'}}):
            row=self.row();row.update(change)
            with self.assertRaises(LeadPreviewError):project_detail(row)
    def test_live_detail_disabled_before_any_connection(self):
        with self.assertRaises(LeadPreviewError):ReadOnlyLeadSource().detail(phone='972501234567')
