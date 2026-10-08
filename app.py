import os
import json
import logging
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import Flask, request
from openai import OpenAI

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

VERIFY_TOKEN = os.getenv('VERIFY_TOKEN', 'dream_of_glass_verify')
WHATSAPP_TOKEN = os.getenv('whatsapp_token') or os.getenv('WHATSAPP_TOKEN', '')
PHONE_NUMBER_ID = os.getenv('PHONE_NUMBER_ID', '1280310741842089')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
MODEL = os.getenv('OPENAI_MODEL', 'gpt-5-mini')
SEND_QUOTES = os.getenv('SEND_QUOTES', 'false').lower() == 'true'

client = OpenAI(api_key=OPENAI_API_KEY, timeout=35.0, max_retries=1)
executor = ThreadPoolExecutor(max_workers=2)
lock = threading.RLock()
histories = {}
seen = {}
phone_locks = {}

GLASS_COSTS = {'שקופה':150,'אקסטרה קליר':220,'אנטיסן אפור':220,'פיפיטה':220,'חלבי':220,'אסיד':220,'אנטיסן ברונזה':240,'גלינה קליר':380,'אסיד קליר':380}
HARDWARE_COSTS = {'ציר קיר זכוכית':50,'ציר זכוכית זכוכית':75,'ידית כפתור':30,'ידית מגבת':80,'מוט חיזוק':65,'זווית קיר זכוכית':25,'זווית זכוכית זכוכית':30,'מגנט פינתי':30,'מגנט חזית':30,'אטם בלון':8,'מגב רצפה':8,'אטם כיסא':8,'ציר הרמוניקה':85,'ציר פרימה':100,'ציר סיכורית':150,'פרופיל אלומיניום':50,'ידית 19.2':80}
FINISH_MULTIPLIERS = {'ניקל':1.0,'שחור':1.1,'ניקל מוברש':1.1,'גרפיט':1.1,'ברונזה':1.1,'זהב':1.1,'לבן':1.1}
BOM = {
 'פינתי 2 קבועים + 2 דלתות': {'ציר זכוכית זכוכית':4,'זווית קיר זכוכית':4,'אטם בלון':2,'מגב רצפה':1,'מגנט פינתי':1,'ידית כפתור':2},
 'חזית קבוע + דלת': {'ציר קיר זכוכית':2,'זווית קיר זכוכית':2,'מגנט חזית':1,'אטם בלון':1,'מגב רצפה':1,'ידית כפתור':1},
 'פינתי הרמוניקה': {'ציר הרמוניקה':4,'ציר קיר זכוכית':4,'ידית כפתור':4,'מגנט פינתי':1,'אטם בלון':2,'אטם כיסא':2,'מגב רצפה':1},
 'חזית 2 דלתות': {'ציר קיר זכוכית':4,'ידית כפתור':2,'מגנט חזית':1,'אטם בלון':2,'מגב רצפה':1},
 'פינתי 2 דלתות': {'ציר קיר זכוכית':4,'ידית כפתור':2,'מגנט פינתי':1,'אטם בלון':2,'מגב רצפה':1},
 'פינתי קבוע + דלת': {'ציר קיר זכוכית':2,'זווית קיר זכוכית':2,'ידית כפתור':1,'אטם בלון':1,'מגב רצפה':1,'מגנט פינתי':1},
 'פינתי 2 קבועים + דלת': {'זווית קיר זכוכית':4,'ציר זכוכית זכוכית':2,'ידית כפתור':1,'אטם בלון':1,'מגנט פינתי':1,'מגב רצפה':1},
 'חצי הרמוניקה + חצי קבוע + דלת': {'ציר קיר זכוכית':2,'ציר זכוכית זכוכית':2,'ציר הרמוניקה':2,'ידית כפתור':2,'ידית ראשית':1,'מגנט פינתי':1,'אטם בלון':2,'אטם כיסא':1,'מגב רצפה':1},
 'קבוע בלבד': {'זווית קיר זכוכית':2,'מוט חיזוק':1},
 'אמבטיון קבוע + דלת': {'ציר זכוכית זכוכית':2,'זווית קיר זכוכית':2,'ידית כפתור':1,'אטם בלון':1,'מגב רצפה':1},
 'אמבטיון 2 קבועים + דלת': {'ציר זכוכית זכוכית':2,'זווית קיר זכוכית':4,'מגנט חזית':1,'מגב רצפה':1,'אטם בלון':1,'ידית כפתור':1},
 'אמבטיון קבוע + 2 דלתות': {'ציר קיר זכוכית':2,'ציר זכוכית זכוכית':2,'זווית קיר זכוכית':2,'מגנט חזית':1,'מגב רצפה':1,'אטם בלון':2,'ידית כפתור':2},
}
SLIDING = {'הזזה קבוע + דלת':600,'הזזה 2 קבועים + 2 דלתות':1200}

# These images must be public HTTPS URLs for photos of your actual hardware.
HANDLE_BUTTON_IMAGE_URL = os.getenv('HANDLE_BUTTON_IMAGE_URL', '')
HANDLE_TOWEL_IMAGE_URL = os.getenv('HANDLE_TOWEL_IMAGE_URL', '')

SYSTEM = '''אתה יועץ מכירות בכיר של חלומות מזכוכית. אתה מדבר עם לקוח בוואטסאפ, בעברית ישראלית טבעית, קצרה וחמה. אתה איש מקצוע אמין, לא תסריט ולא שאלון.
מטרתך להבין את הצורך, לייעץ, לבנות ביטחון, לתת מענה למחיר ולסגור עסקה בקצב הלקוח. הלקוח לא אמור להוביל אותך דרך השאלות. בכל תור חשוב מה כבר ידוע, מה חסר באמת, ומה הצעד הבא הנכון. שאל לכל היותר שאלה אחת. אל תשאל שוב על נתון שכבר ניתן, אל תחזור על הסבר שכבר ניתן, ואל תשאל שאלה שלא נדרשת כעת. אין צורך להחליט מראש איזו דלת תקבל איזו ידית; את המיקום אפשר לסכם בשטח. אל תדלג להצעת תיאום לפני שסיימת לברר מפרט ולענות לבקשת מחיר. אל תמציא מחיר.
אם הלקוח מבקש מחיר, הבהר בקצרה מה דרוש להצעה, שאל את השאלה החסרה הכי חשובה, והתייחס לרצון שלו במחיר. אם יש די מידע להצעה, אל תמשיך לשאול סתם. אין להציג הצעת מחיר מחושבת אלא אם המערכת סיפקה אותה במפורש.
הבנת צורך: ברר בהדרגה אם מדובר בשיפוץ/חדש/החלפה כשזה רלוונטי, מה חשוב ללקוח, מה מגבלות המקום, איזה סגנון הוא מחפש. לא חובה לשאול כל שאלה. הסבר הבדלים בפשטות כשהלקוח מתלבט. אם המקום קטן אל תכריע אוטומטית שדלת הזזה מתאימה; צריך להבין את המבנה. תמונה יכולה לעזור אך לעולם אינה תנאי.
מקלחונים: זכוכית מחוסמת 8 מ״מ. אל תציג 200 ס״מ כגובה סטנדרטי מחייב. אל תטען שזכוכית 8 מ״מ מקלה על ניקוי או שדלת הזזה תמיד נוחה יותר לניקוי. יציאת מים מושפעת משיפועי רצפה, ניקוז ומבנה. אין הבטחת אטימות מוחלטת או אחריות על יציאת מים. אל תעלה נושא זה בלי סיבה. אל תציע ציפוי נגד אבנית בלי אישור. חיתוך מדרגה רגיל ללא תוספת; CNC מורכב מחייב הצעת מחיר נפרדת, ואל תעלה נושא חיתוכים אם לא נשאלת.
ידיות: שתי דלתות יכולות לקבל שתי ידיות כפתור, שתי מגבת או אחת מכל סוג. אם בחרו שילוב, שמור אותו ואל תבקש לבחור לאיזו דלת תוצמד כל ידית. אם הלקוח שואל מה ההבדל, הסבר שידית כפתור קטנה וידית מגבת ארוכה ואפשר לתלות עליה מגבת. אם יש תמונות זמינות, המערכת תשלח אותן בנפרד; אל תבטיח תמונות אלא אם נאמר לך שהן זמינות.
מכירה: אחרי הצעה, בדוק בעדינות אם הפתרון מתאים. אם יש התנגדות למחיר, ברר האם התקציב נמוך יותר או שיש הצעה להשוואה; אל תציע הנחה בלי אישור. כשמתאים, ברר בטבעיות אם יש עוד שותף להחלטה, בלי להניח שזו אשתו. אם צריך להתייעץ, הצע סיכום ברור; אל תלחץ. אם יש הסכמה, הצע תיאום מדידה. לעולם אל תטען שתיאמת, שלחת או העברת לבעל העסק משהו אם לא בוצע בפועל.
מוצרים נוספים: מראות, מחיצות, חיפוי מטבח, אמבטיונים, דלתות ומעקות. עבודות מיוחדות, דלתות ומעקות מחייבים בדיקה אנושית. אזור שירות נתניה עד אשקלון כולל ירושלים. הזמנת מינימום 2000 ש״ח. אל תחשוף עלויות פנימיות.
כתוב לרוב 1–3 משפטים, בלי רשימות, בלי נקודתיים ומקפים מיותרים, ובלי פתיחה חוזרת של 'מעולה'.
החזר JSON בלבד עם השדות reply, product, configuration, width_cm, second_width_cm, height_cm, glass_type, finish, handles, quote_requested, solution_agreed, needs_human, send_handle_images. השתמש ב-null לפרט לא ידוע. handles הוא מערך של 'ידית כפתור'/'ידית מגבת' לפי מספר הידיות, או null. quote_requested אמת אם ביקש מחיר במהלך השיחה ועדיין לא קיבל מענה. solution_agreed אמת רק כשהתצורה נבחרה/אושרה. send_handle_images אמת רק כשהלקוח ביקש לראות דוגמאות או הסבר חזותי על ידיות. המידות בסנטימטרים. אל תסיק תצורה ממידות בלבד. הפרטים בשדות צריכים לשקף את כל השיחה, לא רק את ההודעה האחרונה.'''

def calculate_quote(data):
    configuration = data.get('configuration')
    glass_type = data.get('glass_type')
    finish = data.get('finish')
    handles = data.get('handles')
    if configuration not in BOM and configuration not in SLIDING:
        return None
    if glass_type not in GLASS_COSTS or finish not in FINISH_MULTIPLIERS:
        return None
    try:
        width = float(data['width_cm'])
        height = float(data['height_cm'])
        second = float(data['second_width_cm']) if data.get('second_width_cm') is not None else None
    except (TypeError, ValueError, KeyError):
        return None
    if width <= 0 or height <= 0 or height > 220:
        return None
    is_corner = configuration.startswith('פינתי') or configuration == 'הזזה 2 קבועים + 2 דלתות'
    if is_corner:
        if second is None or second <= 0 or width > 120 or second > 120:
            return None
        total_width = width + second
    else:
        if width > 200:
            return None
        total_width = width
    if configuration in SLIDING:
        hardware = SLIDING[configuration] * FINISH_MULTIPLIERS[finish]
    else:
        bom = BOM[configuration]
        handle_count = bom.get('ידית כפתור', 0) + bom.get('ידית ראשית', 0)
        if not isinstance(handles, list) or len(handles) != handle_count:
            return None
        if any(h not in ('ידית כפתור','ידית מגבת') for h in handles):
            return None
        hardware = sum(HARDWARE_COSTS[h] for h in handles)
        for name, count in bom.items():
            if name in ('ידית כפתור', 'ידית ראשית'):
                continue
            hardware += HARDWARE_COSTS[name] * count
        hardware *= FINISH_MULTIPLIERS[finish]
    area = total_width * height / 10000
    amount = area * GLASS_COSTS[glass_type] + hardware + 1500 + 150
    return round(max(2000, amount), 2)

def send_whatsapp(phone, body=None, image_url=None, caption=None):
    url = f'https://graph.facebook.com/v26.0/{PHONE_NUMBER_ID}/messages'
    payload = {'messaging_product':'whatsapp','to':phone}
    if image_url:
        payload.update({'type':'image','image':{'link':image_url,'caption':caption or ''}})
    else:
        payload.update({'type':'text','text':{'body':body}})
    result = requests.post(url, headers={'Authorization':f'Bearer {WHATSAPP_TOKEN}'}, json=payload, timeout=15)
    app.logger.info('WhatsApp send status: %s', result.status_code)
    result.raise_for_status()

def process_message(phone, body):
    with lock:
        personal_lock = phone_locks.setdefault(phone, threading.Lock())
    with personal_lock:
        with lock:
            history = list(histories.get(phone, []))
        history.append({'role':'user','content':body})
        image_ready = bool(HANDLE_BUTTON_IMAGE_URL and HANDLE_TOWEL_IMAGE_URL)
        instructions = SYSTEM + '\nתמונות ידיות זמינות לשליחה: ' + ('כן' if image_ready else 'לא')
        try:
            response = client.responses.create(
                model=MODEL,
                instructions=instructions,
                input=history[-36:],
                text={'format':{'type':'json_object'}},
            )
            data = json.loads(response.output_text)
            reply = str(data.get('reply') or '').strip()
            if not reply:
                raise ValueError('Empty reply')
            # Quotes are off by default; even when enabled, send only validated quotes.
            if SEND_QUOTES and data.get('quote_requested') is True and data.get('solution_agreed') is True and not data.get('needs_human'):
                price = calculate_quote(data)
                if price is not None:
                    reply = (f'לפי הפרטים שסיכמנו, המחיר המשוער הוא ₪{price:,.0f} לפני מע״מ, כולל מדידה, הובלה והתקנה. המחיר הסופי כפוף לאימות הפרטים בשטח. איך זה נשמע לך?')
            send_whatsapp(phone, body=reply)
            if image_ready and data.get('send_handle_images') is True:
                send_whatsapp(phone, image_url=HANDLE_BUTTON_IMAGE_URL, caption='ידית כפתור')
                send_whatsapp(phone, image_url=HANDLE_TOWEL_IMAGE_URL, caption='ידית מגבת')
            with lock:
                histories[phone] = (history + [{'role':'assistant','content':reply}])[-36:]
        except Exception:
            app.logger.exception('Message processing failed')
            try:
                send_whatsapp(phone, body='סליחה, הייתה תקלה רגעית. תוכל לשלוח לי שוב את ההודעה?')
            except Exception:
                app.logger.exception('Fallback send failed')

def safe_process(phone, body):
    try:
        process_message(phone, body)
    except Exception:
        app.logger.exception('Unhandled background error')

@app.route('/', methods=['GET'])
def home():
    return 'Dream of Glass WhatsApp AI is running', 200

@app.route('/health', methods=['GET'])
def health():
    return {'status':'ok','quotes_enabled':SEND_QUOTES}, 200

@app.route('/webhook', methods=['GET','POST'])
def webhook():
    if request.method == 'GET':
        if request.args.get('hub.mode') == 'subscribe' and request.args.get('hub.verify_token') == VERIFY_TOKEN:
            return request.args.get('hub.challenge', ''), 200
        return 'Verification failed', 403
    data = request.get_json(silent=True) or {}
    for entry in data.get('entry', []):
        for change in entry.get('changes', []):
            value = change.get('value') or {}
            for message in value.get('messages', []):
                if message.get('type') != 'text':
                    continue
                phone = message.get('from')
                body = ((message.get('text') or {}).get('body') or '').strip()
                message_id = message.get('id')
                if not phone or not body:
                    continue
                with lock:
                    now = time.monotonic()
                    if message_id and message_id in seen:
                        continue
                    if message_id:
                        seen[message_id] = now
                    if len(seen) > 2000:
                        old = sorted(seen, key=seen.get)[:1000]
                        for key in old:
                            seen.pop(key, None)
                try:
                    executor.submit(safe_process, phone, body)
                except RuntimeError:
                    app.logger.exception('Background executor unavailable')
    return 'EVENT_RECEIVED', 200

@app.route('/privacy', methods=['GET'])
def privacy():
    return '<h1>Privacy Policy</h1><p>Contact: dream.of.glass2@gmail.com</p>', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT','10000')))
