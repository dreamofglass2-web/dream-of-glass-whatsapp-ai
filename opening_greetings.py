"""Fixed Meta-reviewed opening variants selected by actual Israel send time."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo
SUFFIX=(' כאן יוסי מחלומות מזכוכית.\n'
        'קיבלתי את הפנייה שהשארת ואשמח לעזור לך להתאים פתרון והצעת מחיר.\n'
        'נוח לך שנמשיך כאן בוואטסאפ?')
VARIANTS={
 'morning':('yossi_lead_morning_he_v1','2239594036971482','בוקר טוב,'+SUFFIX),
 'afternoon':('yossi_lead_afternoon_he_v1','1183029887387820','צהריים טובים,'+SUFFIX),
 'evening':('yossi_lead_evening_he_v1','1811416656668788','ערב טוב,'+SUFFIX),
}


def selected(now=None):
    local=(now or datetime.now(ZoneInfo('Asia/Jerusalem'))).astimezone(ZoneInfo('Asia/Jerusalem'))
    return VARIANTS['morning' if local.hour<12 else 'afternoon' if local.hour<17 else 'evening']


def enabled():return os.getenv('FORM_TIME_GREETINGS_ENABLED','').lower()=='true'
