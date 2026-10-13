import unittest
from crm_records import stamp_new_messages, conversation_status


class ConversationRecordTests(unittest.TestCase):
    def test_new_turns_get_times_without_fabricating_legacy_times(self):
        h=[{'role':'user','content':'old'},{'role':'user','content':'new','at':'2026-10-13T19:00:00+00:00'},{'role':'assistant','content':'reply'}]
        result=stamp_new_messages(h,1,'2026-10-13T20:00:00+00:00')
        self.assertNotIn('at',result[0])
        self.assertEqual(result[1]['at'],h[1]['at'])
        self.assertEqual(result[2]['at'],'2026-10-13T20:00:00+00:00')
        self.assertNotIn('at',h[2])

    def test_progress_uses_saved_evidence_not_model_stage(self):
        h=[{'role':'user','content':'מקלחון'},{'role':'assistant','content':'זה לבית חדש?'}]
        self.assertEqual(conversation_status(h,{'product':'מקלחון'}),'בטיפול')
        self.assertEqual(conversation_status(h,{'stage':'closed'}),'חדש')
        self.assertEqual(conversation_status(h,{'validated_quote':{'issued':True}}),'הצעה ניתנה')
