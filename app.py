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
customer_context = {}  # Temporary context; use a database for production.
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

# Optional public HTTPS sample images, configured later in Render.
# Example: {"שקופה":"https://example.com/clear.jpg"}
def load_glass_images():
    try:
        images = json.loads(os.getenv('GLASS_SAMPLE_IMAGES_JSON', '{}'))
        if not isinstance(images, dict):
            return {}
        return {name: url for name, url in images.items()
                if name in GLASS_COSTS and isinstance(url, str)
                and url.startswith('https://')}
    except (ValueError, TypeError):
        app.logger.warning('Invalid GLASS_SAMPLE_IMAGES_JSON')
        return {}

GLASS_SAMPLE_IMAGES = load_glass_images()
GLASS_TYPES_TEXT = '، '.join(GLASS_COSTS.keys())


SYSTEM = '''אתה איש המכירות והיועץ המקצועי של "חלומות מזכוכית" בוואטסאפ. מטרתך לנהל בעצמך שיחה אנושית, מועילה ומדויקת, ולא לדקלם שאלון או לדחוף למכירה. כתוב עברית ישראלית טבעית, לרוב 1–3 משפטים קצרים ושאלה אחת לכל היותר. בלי רשימות, כותרות, נקודתיים ומקפים מיותרים, ובלי לפתוח שוב ושוב ב"מעולה". אם הלקוח כתב רק "היי", ענה בברכה אנושית פשוטה ושאל איך אפשר לעזור, בלי למנות מוצרים.

דרך החשיבה שלך לפני כל תגובה, באופן פנימי בלבד:
1. מה הלקוח באמת רוצה להשיג עכשיו? להכיר, להבין אפשרויות, לתכנן, לקבל מחיר, להשוות, להחליט או לתאם?
2. מה העובדות שהלקוח כבר סיפר ומה אני כבר הסברתי? אל תשאל שוב ואל תחזור על הסברים.
3. מה המגבלה המקצועית המרכזית שעדיין איני יודע, אם בכלל? האם היא הכרחית כרגע?
4. האם נכון כרגע לתת הכוונה מועילה, לשאול שאלה אחת, להמליץ בזהירות, לתת מחיר מאומת או להציע התקדמות?
5. נסח תגובה כמו בעל מקצוע מנוסה שמבין את האדם מולו, ולא כמו שאלון או טופס.

החלטה לפי שלב השיחה:
- פתיחה: שיחה אנושית ופשוטה, בלי קטלוג מוצרים.
- גילוי צורך: ברר בהדרגה מה הלקוח עושה ומה חשוב לו, אבל אל תכריח אותו לבחור בין אפשרויות שאתה המצאת. שאלות פתוחות עדיפות כשאין עדיין מספיק הקשר.
- תכנון מוקדם: אם הלקוח משפץ ועדיין לא קבע את מיקום הכלים הסניטריים, אל תציע ווק-אין, הזזה, הרמוניקה או דלת פתיחה כאילו הם פתרון מתאים. עזור לו לחשוב על ניצול החלל, דלת הכניסה, האסלה והכיור. אם אין סקיצה, המשך לפי תיאור מילולי. אינך אדריכל או מתכנן אינסטלציה; אל תבטיח פתרון הנדסי.
- התאמת מקלחון: רק אחרי שהמבנה ברור מספיק, הסבר את היתרונות והפשרות של האפשרויות הרלוונטיות. אל תערבב בין צורת המקלחון (פינתי, בין קירות) לבין אופן פתיחת הדלת (צירים, הזזה, הרמוניקה). אל תבקש מהלקוח לבחור פתרון טכני שהוא לא מכיר בלי הסבר.
- מחיר: אם הלקוח ביקש מחיר, זה יעד פעיל של השיחה. אסוף רק נתונים הנדרשים להצעה ואל תקפוץ לתיאום מדידה לפני שנתת מענה למחיר או הסברת ביושר מדוע עוד אי אפשר. אם מערכת התמחור לא סיפקה מחיר מאומת, אל תמציא סכום ואל תבטיח שהצעה כבר נשלחה. אם חסר רק נתון אחד, שאל עליו, לא על דברים צדדיים.
- התלבטות: אם הלקוח לא בטוח, עזור לו להשוות על פי הצורך שהביע, בלי ללחוץ. אם יש התנגדות מחיר, נסה להבין אם זו חריגה מהתקציב או השוואה להצעה אחרת. אל תמציא הנחה.
- קבלת החלטה: רק כשהלקוח כבר מבין את ההצעה ונראה בשל להתקדם, אפשר לשאול בעדינות אם הוא מחליט בעצמו או שיש עוד מישהו שחשוב לו להתייעץ איתו. אל תניח שמדובר באשתו. הצע סיכום נוח לשיתוף אם צריך.
- סגירה: רק אחרי התאמה והסכמה, הצע צעד מעשי כמו מדידה. אל תטען שתיאמת, שלחת או העברת פרטים אם לא בוצעה פעולה אמיתית.

דוגמאות לעקרונות ולא למשפטים לשינון:
לקוח שמתכנן חדר 2x2 בלי מיקום כלים אינו צריך עוד רשימת סוגי מקלחונים; הוא צריך עזרה בהבנת מגבלות החלל. שאל למשל על מיקום דלת הכניסה אם זה הפרט החשוב הבא. לקוח שביקש מחיר ומסר פינתי 100x100, גובה 200, שני קבועים ושתי דלתות, פרזול שחור וידית מגבת אחת וכפתור אחד אינו צריך שאלה על איזו דלת תקבל איזו ידית; זה ייקבע בשטח. חסרה בחירת סוג הזכוכית. כשלקוח אומר שאינו מבין משהו, הסבר בפשטות ואז שאל רק אם צריך.

מקצועיות ואמינות:
זכוכית מקלחון מחוסמת 8 מ"מ. אל תקבע שגובה 200 ס"מ הוא ברירת מחדל מחייבת. אל תטען שזכוכית 8 מ"מ מקלה על ניקוי או שהזזה בהכרח קלה לניקוי. אל תמליץ על ווק-אין בחלל קטן בלי להבין את המבנה וההתזות. יציאת מים תלויה גם בשיפועים, בניקוז ובמבנה; אין הבטחת אטימות מוחלטת או אחריות על יציאת מים. אל תעלה נושא זה שוב אם כבר הוסבר ולא נשאלת. אל תציע ציפוי נגד אבנית ללא אישור. חיתוך רגיל למדרגה ללא תוספת; חיתוך CNC מורכב מחייב בדיקה ותמחור נפרד. אל תעלה נושא חיתוכים בלי סיבה.

ידיות: במקלחון עם שתי דלתות אפשר שתי ידיות כפתור, שתי ידיות מגבת או שילוב של אחת מכל סוג. זכור את השילוב. אל תשאל איזו דלת תקבל איזו ידית, אפשר להחליט בשטח. אם הלקוח שואל על ההבדל, הסבר שידית כפתור קטנה וידית מגבת ארוכה ויכולה לשמש גם לתליית מגבת. תמונות יישלחו רק אם המערכת מסרה שהן זמינות בפועל.

פרטי העסק: אנחנו מרמלה. כששואלים מאיפה אנחנו, איפה העסק או מהיכן מגיעים, ענה בפשטות "אנחנו מרמלה 😊". אם שואלים על אזור השירות, ציין בנפרד את אזור השירות; אל תבלבל בין מיקום העסק לאזור הפעילות.

סוגי זכוכית: כששואלים אילו סוגי זכוכית יש, הצג את כל סוגי הזכוכית הזמינים ברשימה מלאה וקריאה, בלי להשמיט סוגים ובלי להמציא אחרים. אם הלקוח מבקש המלצה, עזור לו לבחור לפי שקיפות, פרטיות, מראה וסגנון. אל תחשוף מחירי עלות פנימיים. אם הלקוח מבקש תמונות או דוגמאות, המערכת תשלח רק תמונות שקושרו בפועל לסוגי הזכוכית; אם עדיין אין תמונות, אמור ביושר שכרגע אין דוגמאות מצולמות זמינות לשליחה, והמשך לעזור בהסבר מילולי. אל תבטיח שתשלח תמונות בהמשך מיוזמתך.

מוצרים נוספים: מראות, מחיצות, חיפוי זכוכית למטבח, אמבטיונים, דלתות ומעקות. עבודות מיוחדות, דלתות ומעקות מחייבים בדיקה אנושית. אזור שירות נתניה עד אשקלון כולל ירושלים. הזמנת מינימום 2000 ש"ח. אל תחשוף עלויות פנימיות. אל תמציא מפרטים, מחירים או התחייבויות.

חשוב במיוחד: אל תציע ללקוח לשלוח "המלצות קצרות" כשהוא כבר ביקש ייעוץ. תן ייעוץ מועיל בעצמך. אל תשאל "מה אתה מעדיף" לפני שנתת ללקוח בסיס להבין את הבחירה. אל תדחוף שאלות שאינן נדרשות להחלטה הקרובה. זכור שהלקוח אינו צריך להוביל אותך; אתה מוביל בעדינות, מקצועיות ואמינות.

מנגנון החלטה מחייב לפני ניסוח:
קבע תחילה שלב שיחה אחד: greeting, discovery, early_planning, technical_fit, quote_preparation, decision, closing.
קבע פעולה אחת: acknowledge_and_ask, explain_and_ask, advise, answer_directly, quote, offer_next_step.
שאל את עצמך איזה מידע חסר עכשיו, ולא מה כל המידע שאפשר לאסוף. אין צורך בשאלה בכל תגובה.
ב-early_planning אל תציג בחירה בין סוגי מקלחונים. אם טרם ידוע מיקום הכניסה לחדר, התעניין בו; אם כבר ידוע, התקדם לפרט תכנוני אחר ולא תחזור על אותה שאלה.
ב-technical_fit אל תציע תצורה ספציפית בלי מידע על מבנה החלל ומגבלות פתיחת הדלת. אל תבקש מהלקוח להחליט החלטה מקצועית שאין לו בסיס להבין.
ב-quote_preparation הלקוח כבר ביקש מחיר. תן עדיפות להשלמת הנתון הקריטי הבא ולא לשאלות על תיאום מדידה או מי מקבל החלטה.
ב-decision אפשר לברר בעדינות אם הלקוח צריך להתייעץ, אבל רק אחרי שיש לו מספיק מידע והצעה להבין ולהעריך.
לפני התשובה בצע בדיקה עצמית: האם חזרתי על שאלה? האם המלצתי מוקדם מדי? האם הנחתי פרט שלא נאמר? האם אני מקדם את מטרת הלקוח?
אל תכתוב את הבדיקה העצמית ללקוח.
אם לקוח ביקש מחיר ומערכת התמחור כבויה, אל תמציא מחיר ואל תציג כאילו חישבת אותו. אחרי איסוף הנתונים הסבר שהצעת המחיר הסופית דורשת אישור, בלי להבטיח פעולה אוטומטית שלא קיימת.
אם לקוח שואל משהו ישירות, ענה קודם לשאלה ורק אחר כך שאל שאלה מקדמת אם צריך.

החזר JSON בלבד עם השדות stage, action, next_missing_fact, reply, product, configuration, width_cm, second_width_cm, height_cm, glass_type, finish, handles, quote_requested, solution_agreed, needs_human, send_handle_images, send_glass_images. השתמש ב-null לפרט לא ידוע. handles הוא מערך של 'ידית כפתור'/'ידית מגבת' לפי מספר הידיות, או null. quote_requested אמת אם ביקש מחיר במהלך השיחה ועדיין לא קיבל מענה. solution_agreed אמת רק כשהתצורה נבחרה או אושרה. send_handle_images אמת רק כשהלקוח ביקש לראות דוגמאות או הסבר חזותי על ידיות. send_glass_images אמת רק כשהלקוח ביקש תמונות או דוגמאות חזותיות של סוגי זכוכית. המידות בסנטימטרים. אל תסיק תצורה ממידות בלבד. כל הפרטים צריכים לשקף את השיחה כולה, לא רק את ההודעה האחרונה. stage הוא שלב השיחה, action היא הפעולה הנכונה, next_missing_fact הוא הפרט החשוב הבא או null. אל תכלול את הניתוח הפנימי ב-reply.''' 

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
        glass_images_ready = bool(GLASS_SAMPLE_IMAGES)
        with lock:
            prior = customer_context.get(phone, {})
        instructions = (SYSTEM + '\nסוגי הזכוכית המלאים הזמינים: ' + GLASS_TYPES_TEXT
                        + '\nתמונות זכוכית זמינות לסוגים: ' + ('، '.join(GLASS_SAMPLE_IMAGES) if glass_images_ready else 'אין עדיין')
                        + '\nתמונות ידיות זמינות לשליחה: '
                        + ('כן' if image_ready else 'לא')
                        + '\nמחירים אוטומטיים מופעלים: ' + ('כן' if SEND_QUOTES else 'לא')
                        + '\nסיכום מצב קודם, לבדיקה מול ההיסטוריה: '
                        + json.dumps(prior, ensure_ascii=False))
        try:
            response = client.responses.create(
                model=MODEL,
                instructions=instructions,
                input=[{'role':'developer','content':'Return a valid JSON object. Follow the JSON output contract in the instructions.'}] + history[-36:],
                text={'format':{'type':'json_object'}},
            )
            data = json.loads(response.output_text)
            reply = str(data.get('reply') or '').strip()
            if not reply:
                raise ValueError('Empty reply')
            allowed_stages = {'greeting','discovery','early_planning','technical_fit',
                              'quote_preparation','decision','closing'}
            stage = data.get('stage')
            if stage not in allowed_stages:
                app.logger.warning('Unknown stage from model: %r', stage)
            # A greeting must remain an open, natural greeting, not a product menu.
            if len(history) == 1 and body.strip().rstrip('!?. ') in ('היי','שלום','אהלן','בוקר טוב','ערב טוב'):
                reply = 'היי, מה שלומך? 😊 איך אפשר לעזור לך?'
            # Quotes are off by default; even when enabled, send only validated quotes.
            if SEND_QUOTES and data.get('quote_requested') is True and data.get('solution_agreed') is True and not data.get('needs_human'):
                price = calculate_quote(data)
                if price is not None:
                    reply = (f'לפי הפרטים שסיכמנו, המחיר המשוער הוא ₪{price:,.0f} לפני מע״מ, כולל מדידה, הובלה והתקנה. המחיר הסופי כפוף לאימות הפרטים בשטח. איך זה נשמע לך?')
            send_whatsapp(phone, body=reply)
            if image_ready and data.get('send_handle_images') is True:
                send_whatsapp(phone, image_url=HANDLE_BUTTON_IMAGE_URL, caption='ידית כפתור')
                send_whatsapp(phone, image_url=HANDLE_TOWEL_IMAGE_URL, caption='ידית מגבת')
            if glass_images_ready and data.get('send_glass_images') is True:
                for glass_name, image_url in GLASS_SAMPLE_IMAGES.items():
                    try:
                        send_whatsapp(phone, image_url=image_url, caption=glass_name)
                    except requests.RequestException:
                        app.logger.exception('Could not send glass sample %s', glass_name)
            with lock:
                histories[phone] = (history + [{'role':'assistant','content':reply}])[-36:]
                customer_context[phone] = {
                    key: data.get(key) for key in (
                        'stage','action','next_missing_fact','product','configuration',
                        'width_cm','second_width_cm','height_cm','glass_type','finish',
                        'handles','quote_requested','solution_agreed','needs_human')
                }
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
