import unittest
from handoff_store import parse_echoes
from handoff_state import HandoffError


class EchoTests(unittest.TestCase):
    def sample(self):
        return {'field':'smb_message_echoes','value':{
            'messaging_product':'whatsapp','metadata':{'phone_number_id':'123456123'},
            'message_echoes':[{'from':'16315551181','to':'11234567890','id':'ABGGFlA5Fpa',
                'timestamp':'1504902988','type':'text','text':{'body':'this is a text message'}}]}}

    def test_meta_sample_has_operator_author_and_original_timestamp(self):
        result=parse_echoes(self.sample(),'123456123')
        self.assertEqual(result[0][0],'11234567890')
        self.assertEqual(result[0][1]['role'],'operator')
        self.assertEqual(result[0][1]['at'],'2017-09-08T20:36:28+00:00')

    def test_wrong_channel_and_other_webhook_field_are_not_operator_events(self):
        self.assertEqual(parse_echoes(self.sample(),'another-number'),[])
        change=self.sample();change['field']='messages'
        self.assertEqual(parse_echoes(change,'123456123'),[])

    def test_missing_id_timestamp_or_body_rejected(self):
        for field in ('id','timestamp','text'):
            change=self.sample();del change['value']['message_echoes'][0][field]
            with self.assertRaises(HandoffError):parse_echoes(change,'123456123')

    def test_unsupported_media_is_not_fabricated_as_text(self):
        change=self.sample();change['value']['message_echoes'][0]['type']='image'
        self.assertEqual(parse_echoes(change,'123456123'),[])
