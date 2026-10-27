import os,unittest
from unittest.mock import patch
import business_pilot as p

PHONE='972501234567'
def message(phone=PHONE):
    return {'type':'text','text':{'body':'הי! השלמתי את הטופס שלך, וברצוני לדעת יותר על העסק שלך.\nFull name: Test Customer\nCity: Test City\nאילו עבודות אתם מחפשים?: מקלחון\nPhone number: +'+phone}}
class FormMessagePilotTests(unittest.TestCase):
    def test_customer_sent_form_counts_as_message_without_an_extra_hi(self):
        self.assertTrue(p.is_customer_form_message(PHONE,message()))
    def test_link_alone_another_phone_missing_fields_and_media_do_not_qualify(self):
        self.assertFalse(p.is_customer_form_message(PHONE,{'type':'text','text':{'body':'https://fb.me/example'}}))
        self.assertFalse(p.is_customer_form_message(PHONE,message('972509999999')))
        data=message();data['text']['body']=data['text']['body'].replace('Full name: Test Customer','')
        self.assertFalse(p.is_customer_form_message(PHONE,data))
        self.assertFalse(p.is_customer_form_message(PHONE,{'type':'image'}))
    def test_form_only_switch_accepts_form_payload_but_not_ordinary_direct_message(self):
        import app as yossi
        from unittest.mock import MagicMock
        env={'BUSINESS_PILOT_REQUIRE_FORM':'true','BUSINESS_PILOT_ALL_INBOUND':'false','BUSINESS_PILOT_ID':'isolated-test'}
        with patch.dict(os.environ,env),patch.object(yossi,'db_connection',return_value=MagicMock()) as db,patch.object(yossi,'ensure_db'):
            self.assertFalse(yossi.persist_verified_direct_inbound(PHONE,{'type':'text','timestamp':'1793149200','text':{'body':'שלום'}}))
            db.assert_not_called()
            data=message();data['timestamp']='1793149200'
            self.assertTrue(yossi.persist_verified_direct_inbound(PHONE,data))
            db.assert_called_once()
