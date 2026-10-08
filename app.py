import os
import json
import logging
import threading
import time
import re

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
SEND_QUOTES = os.getenv('SEND_QUOTES', 'true').lower() == 'true'  # Only validated prices; set false to disable

client = OpenAI(api_key=OPENAI_API_KEY, timeout=35.0, max_retries=1)
# Simulation-only in-memory queue. Run exactly one Gunicorn worker.
# For production, use a durable external queue/database and a separate worker.
lock = threading.RLock()
histories = {}
customer_context = {}
seen = {}
phone_locks = {}
pending = {}  # phone -> [(message_id, body, monotonic_arrival)]
processing = set()
worker_thread = None
worker_pid = None
worker_start_lock = threading.Lock()
BATCH_SECONDS = float(os.getenv('MESSAGE_BATCH_SECONDS', '7'))
TYPING_MIN = float(os.getenv('TYPING_MIN_SECONDS', '2'))
TYPING_MAX = float(os.getenv('TYPING_MAX_SECONDS', '8'))


def load_conversation(phone):
    with lock:
        return list(histories.get(phone, [])), dict(customer_context.get(phone, {}))


def save_conversation(phone, history, context):
    with lock:
        histories[phone] = history[-36:]
        customer_context[phone] = context


def queue_message(phone, body, message_id):
    with lock:
        if message_id in seen:
            return
        seen[message_id] = time.monotonic()
        if len(seen) > 4000:
            for mid, _ in sorted(seen.items(), key=lambda item: item[1])[:2000]:
                seen.pop(mid, None)
        pending.setdefault(phone, []).append((message_id, body, time.monotonic()))
        app.logger.info("QUEUE_ADDED phone_suffix=%s pending=%s", phone[-4:], len(pending[phone]))


def next_batch():
    with lock:
        now = time.monotonic()
        for phone, messages in list(pending.items()):
            if phone in processing or not messages or now - messages[-1][2] < BATCH_SECONDS:
                continue
            processing.add(phone)
            app.logger.info("BATCH_READY phone_suffix=%s count=%s", phone[-4:], len(messages))
            return phone, list(messages)
    return None


def has_new_messages(phone, batch_rows=None):
    with lock:
        messages = pending.get(phone, [])
        if batch_rows is None:
            return bool(messages)
        original_ids = {r[0] for r in batch_rows}
        return any(mid not in original_ids for mid, _, _ in messages)


def finish_batch(phone, rows, success=True):
    with lock:
        if success:
            done = {r[0] for r in rows}
            pending[phone] = [r for r in pending.get(phone, []) if r[0] not in done]
            if not pending[phone]:
                pending.pop(phone, None)
        else:
            # Avoid a hot loop after a transient API failure; keep for retry.
            pending[phone] = [(mid, body, time.monotonic()) if mid in {r[0] for r in rows}
                              else (mid, body, arrived)
                              for mid, body, arrived in pending.get(phone, [])]
        processing.discard(phone)

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
 'חצי הרמוניקה + חצי קבוע + דלת': {'ציר קיר זכוכית':2,'ציר זכוכית זכוכית':2,'ציר הרמוניקה':2,'ידית כפתור':2,'ידית מגבת':1,'מגנט פינתי':1,'אטם בלון':2,'אטם כיסא':1,'מגב רצפה':1},
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
GLASS_TYPES_TEXT = ', '.join(GLASS_COSTS.keys())


SYSTEM = '''אתה איש המכירות והיועץ המקצועי של "חלומות מזכוכית" בוואטסאפ. מטרתך לנהל בעצמך שיחה אנושית, מועילה ומדויקת, ולא לדקלם שאלון או לדחוף למכירה. כתוב עברית ישראלית טבעית, לרוב 1–3 משפטים קצרים ושאלה אחת לכל היותר. בלי רשימות, כותרות, נקודתיים ומקפים מיותרים, ובלי לפתוח שוב ושוב ב"מעולה". אם הלקוח כתב רק "היי", ענה בברכה אנושית פשוטה ושאל איך אפשר לעזור, בלי למנות מוצרים.

כללי ניסוח מחייבים להודעות ללקוח:
אל תשתמש בכלל בסימן מקף רגיל, מקף ארוך או קו מפריד בתשובה ללקוח. נסח משפטים זורמים בעברית בלי מקפים, גם כשאתה משווה בין אפשרויות. האיסור חל על טקסט ההודעה ללקוח ולא על שמות שדות JSON פנימיים.
כשצריך לברר את גובה המקלחון, שאל בפשטות "איזה גובה תרצו?" או "איזה גובה אתם מתכננים?". אל תשאל "מה הגובה המבוקש בס״מ" ואל תשתמש בניסוחים טכניים כמו "גובה מבוקש". אם הלקוח נותן גובה בלי יחידות, ברר יחידות רק אם באמת יש ספק.
כשלקוח שואל "מה עדיף?", "מה אתה ממליץ?" או "לא יודע", התייחס קודם לבחירה או לשאלה שעליה דיברתם מיד לפני כן. תן המלצה מנומקת על בסיס הפרטים הידועים, עם הסתייגות עניינית אם חסר פרט מכריע. אל תחליף נושא לגובה או למפרט אחר שלא נשאל עליו. אל תחזיר את הבחירה ללקוח בלי לתת לו כיוון מקצועי.

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

עובדות עסקיות מחייבות: אנחנו מרמלה ואין לנו אולם תצוגה. אין כתובת לאולם, אין שעות ביקור ואין אפשרות לתאם ביקור באולם. אם בעבר אמרת בטעות שיש אולם, תקן את הטעות במפורש והתנצל בקצרה. אל תמציא כתובות, שעות, מלאי, זמינות, הבטחות לחזרה, פנייה לנציג או תיאום שבוצע. כשלא ידוע פרט עסקי, אמור שאינך יודע אותו. אל תציג מידע פנימי על קוד, מערכות או תמחור אוטומטי ללקוח.
מחירון לקוח למוצרים שאינם מקלחונים: מראה קריסטל בלגי 5 מ״מ 700 ש״ח למטר רבוע כולל התקנה, תוספת מסגרת 250 ש״ח למטר רבוע, תוספת לד 250 ש״ח למטר רבוע. מחיצת זכוכית 10 מ״מ שקופה 700 ש״ח למטר רבוע כולל מדידה הובלה והתקנה, מחיצת 5+5 1000 ש״ח למטר רבוע, דלת למחיצה תוספת 3500 ש״ח. חיפוי זכוכית למטבח 1100 ש״ח למטר רבוע, עבודות מורכבות לבדיקה. מינימום הזמנה 2000 ש״ח, ולכן מחיר מוצר יחיד לפי מטר רבוע אינו בהכרח המחיר הסופי להזמנה. אל תאמר שהזמנת מראה בודדת בגודל מטר על מטר עולה רק 700 ש״ח. הסבר בקצרה את מחיר הבסיס ואת מינימום ההזמנה בלי להטעות. מחירים אלה לפני מע״מ אלא אם העסק אישר אחרת. אל תמציא מחיר סופי בלי חישוב מאומת.
כשלקוח שואל שאלה חברתית, ענה בחום ובקלילות בלי לסיים בכל פעם בשאלת שירות. אפשר להמשיך שיחת חולין קצרה בלי ללחוץ על מכירה. אל תטען שיש לך חיים פרטיים או יום עבודה אישי. כשלקוח עובר לנושא מקצועי, עבור איתו באופן טבעי. אל תסיק שמראה מיועדת לפרויקט בנייה רק משום שהלקוח עובד בבנייה.
אל תסיים שתי הודעות רצופות באותה שאלת שירות. אל תחזור על כל המפרט בכל תשובה. כאשר לקוח מבקש מחיר, התייחס לבקשה לפני הצעות לתיאום. כשלקוח מבקש המלצה, תן המלצה רלוונטית ולא רק רשימת אפשרויות.

הבנת הודעות רצופות ותיקונים: ההודעה הנוכחית עשויה להכיל כמה הודעות וואטסאפ שחוברו יחד. התייחס אליהן כאל מחשבה אחת. הודעה מאוחרת מתקנת הודעה מוקדמת, למשל "איתן" ואז "איתם", או "100" ואז "בעצם 120". אם תיקון הגיע לאחר שכבר ענית, קרא מחדש את ההודעה המקורית לפי התיקון, הכר בטעות שלך והמשך לפי הכוונה המתוקנת. אל תתייחס למילה "איתם" כהסכמה לקנייה אצלנו אם ההקשר הוא מתחרה. כשיש ספק משמעותי שאל הבהרה קצרה, ובוודאי אל תתאם מדידה או תבקש פרטים אישיים על בסיס מסר עמום.
לקוח שאומר שהוא הולך עם מתחרה, שהמחיר יקר לו מדי או שהוא מוותר: כבד את החלטתו, אל תתאם מדידה ואל תכין הצעה ללא בקשה חדשה ומפורשת. אל תחזור על מחיר מינימום שכבר הוסבר; תן מענה להתנגדות החדשה. אם המתחרה נותן מוצר דומה כולל התקנה במחיר נמוך יותר, הודה בכנות שזה יכול להתאים יותר להזמנה בודדת. אל תמציא הנחות או פתרונות זולים שאינם קיימים.
שיחה חברתית: אפשר לענות בחום בלי שאלה בסוף. אל תדחוף "איך אפשר לעזור" בכל הודעה. כשלקוח שולח "מה קורה", "אני בסדר", "מה איתך" ו"הכל טוב" יחד, ענה פעם אחת באופן טבעי לכל ההודעות.

כללי שיחה חדשים, בעדיפות גבוהה במיוחד:
אל תסכם ללקוח מחדש פרטים שאמר בכל הודעה. שמור אותם בשדות הפנימיים בלבד. אחרי תשובה כמו "100 על 100" אל תגיד "רשמתי 100 על 100"; פשוט שאל את השאלה הבאה, אם צריך. אחרי "גובה 200" אל תחזור על הרוחב והגובה. סיכום מלא מותר רק כשמבקשים סיכום, לפני הצגת הצעת מחיר או בעת אימות פרטים הכרחי. אל תפתח ברוב ההודעות ב"מעולה", "מצוין", "הבנתי" או "רשמתי". לפעמים התשובה הנכונה היא שאלה אחת קצרה בלי הקדמה.
התייחס להודעה האחרונה כהמשך לשאלה האחרונה שלך. אם שאלת על שתי דלתות מול קבוע ודלת והלקוח אומר "מה אתה ממליץ", ענה על תצורת הדלתות ולא על גובה. כשמבקשים המלצה, תן המלצה מעשית עם נימוק ומגבלה אחת רלוונטית; אל תציג רק אפשרויות ותשאל את הלקוח לבחור מחדש.
הובל את המכירה מתוך הבעיה של הלקוח, לא מתוך רשימת שדות חסרים. אם הלקוח עדיין בשיפוץ מוקדם, אל תתעקש על גובה, ידיות ופרזול לפני שיש בסיס להתאמה. אם הוא כבר בחר תצורה ומבקש הצעת מחיר, אסוף רק את הנתונים החסרים, אחד בכל פעם, ואז התקדם למחיר מאומת. אם המחיר האוטומטי כבוי, אל תבטיח הצעה טלפונית או פנייה לנציג שלא באמת הופעלה; הסבר בקצרה שהמחיר דורש אישור.
אל תחזור על שאלה שנשאלה וטרם נענתה אם הלקוח שאל במקומה שאלה אחרת. ענה קודם לשאלתו. אם הלקוח כבר נתן פרט, אסור לבקש אותו שוב אלא אם קיימת סתירה אמיתית.

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

# Conversation guidance added after the simulation. This supplements, rather than
# replaces, the existing quote engine and WhatsApp batching.
SALES_GUIDANCE = """
עדיפות עליונה: המשך את מטרת השיחה ולא רק את המשפט האחרון. לקוח שפתח ב"קיבלתי הצעה זולה יותר" רוצה השוואה. אם עדיין לא ידוע על איזו עבודה מדובר, שאל זאת. אם אמר "מקלחון פינתי", המשך בבירור מה כללה ההצעה, ולא עבור אוטומטית לשאלון מידות. לעולם אל תניח שכבר נתנו לו הצעה משלנו.
כאשר לקוח אינו יודע תצורה, גובה או רוחב, או אומר שאין לו מידות, זו עובדה מחייבת. אסור לבקש ממנו שוב את אותם הנתונים בהמשך השיחה, אלא אם הוא הודיע שיש לו אותם כעת. במקום זאת שאל על משהו נגיש, כמו מיקום אסלה, מרווח פתיחה, תמונה של אזור המקלחת או צילום הצעת המתחרה. תמונה היא אפשרות בלבד, לא תנאי לשיחה. אם לקוח אמר שאין לו הצעה כתובה, אל תבקש אותה שוב.
אם הלקוח ביקש הערכת מחיר ללא מידות, תן תשובה שימושית: מחיר המינימום למקלחון הוא 2,000 ש״ח לפני מע״מ, לא הצעה מחושבת למקלחון שלו. המחיר בפועל תלוי במידות, תצורה, זכוכית ופרזול. אין להמציא טווח עליון או להציג 2,500 ש״ח כזול או יקר בלי מפרט. אין לשאול שוב על מידות באותה תגובה.
אם לקוח מבקש המלצה, הצע כיוון מעשי לפי הנתונים הקיימים. אסלה ליד מקלחון פינתי עשויה להגביל פתיחת דלת החוצה, אבל אינה מחייבת הזזה. אפשר לבדוק הזזה או פתרון צירים שנפתח פנימה אם מתאים; אין להבטיח התאמה בלי בדיקה. שאל שאלה אחת קלה בלבד, ורק אם מקדמת את השיחה.
אל תשתמש במילה "כבוד להחלטה" ואל תכתוב "בהצלחה עם איתם". אם הלקוח רק מזכיר מתחרה, הוא עדיין לא החליט. אם אומר בבירור שבחר במתחרה, כבד וסיים בנימוס ללא מכירה נוספת.
אל תשאל פעמיים את אותה השאלה גם בניסוח אחר. לפני כל תשובה בדוק במיוחד מה הלקוח אמר שאין לו או שאינו יודע. תשובות קצרות, חמות, מקצועיות, ללא מקפים.
"""


def conversation_constraints(history):
    """Extract explicit limits from customer messages; never infer unknown measurements."""
    customer = [str(m.get('content', '')) for m in history if m.get('role') == 'user']
    text = '\n'.join(customer)
    no_dimensions = bool(re.search(r'(אין לי|לא יודע|לא יודעת|אין לנו|לא מדדתי|לא מדדנו).{0,28}(מידות|רוחב|גובה)|בלי מידות', text))
    no_written_quote = bool(re.search(r'(אין לי|אין לנו).{0,20}(הצעה כתובה|הצעת מחיר כתובה|צילום של ההצעה)', text))
    competitor = bool(re.search(r'הצעה.{0,35}(זול|מתחרה|מישהו אחר)|(?:זול|מתחרה).{0,35}הצעה', text))
    corner = 'פינתי' in text
    toilet = 'אסלה' in text
    # Allow the user to revise their earlier statement later.
    if no_dimensions and re.search(r'(מדדתי|יש לי מידות|המידות הן|הרוחב הוא|הגובה הוא)', customer[-1] if customer else ''):
        no_dimensions = False
    return {'no_dimensions':no_dimensions,'no_written_quote':no_written_quote,
            'competitor_comparison':competitor,'corner_shower':corner,'toilet_nearby':toilet}


def avoid_repeated_dimensions(reply, facts, body):
    """Last-resort guard against the exact loop observed in the simulation."""
    if not facts['no_dimensions']:
        return reply
    if not re.search(r'(איזה|מה|כמה|תוכל|אפשר).{0,32}(רוחב|גובה|מידות)|(רוחב|גובה|מידות).{0,20}(מתכננים|שלכם|יש לכם)', reply):
        return reply
    # Preserve the useful explanation before the repeated question.
    sentences = re.split(r'(?<=[.!?])\s+', reply)
    kept = [x for x in sentences if not re.search(r'(איזה|מה|כמה|תוכל|אפשר).{0,32}(רוחב|גובה|מידות)|(רוחב|גובה|מידות).{0,20}(מתכננים|שלכם|יש לכם)', x)]
    base = ' '.join(kept).strip()
    if re.search(r'אסלה', body):
        return 'אם האסלה קרובה למקלחון, כדאי לתכנן פתיחה שלא תיתקע בה. אפשר לבדוק הזזה או דלת שנפתחת פנימה, לפי השטח. יש לך אפשרות לשלוח תמונה של אזור המקלחת?'
    if re.search(r'ממליץ|המלצה|מה עדיף', body):
        return 'במקלחון פינתי אני מעדיף דלתות ציר כשיש להן מקום להיפתח, והזזה כשצפוף. אם יש אסלה או ארון ליד המקלחון זה יכול להשפיע. יש משהו צמוד אליו?'
    if re.search(r'מחיר|בערך|כמה עולה', body):
        return 'בטח. מקלחון אצלנו מתחיל מ־2,000 ש״ח לפני מע״מ. זה מחיר מינימום ולא הצעה מדויקת למקלחון שלך, כי המחיר תלוי בתצורה ובמידות. אפשר לשלוח תמונה של האזור ואכוון אותך לפתרון מתאים.'
    return (base + ' ' if base else '') + 'אם נוח לך, אפשר לשלוח תמונה של אזור המקלחת כדי שאוכל לכוון אותך גם בלי מידות.'


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
        handle_count = bom.get('ידית כפתור', 0) + bom.get('ידית מגבת', 0)
        if handle_count and (not isinstance(handles, list) or len(handles) != handle_count):
            return None
        if any(h not in ('ידית כפתור','ידית מגבת') for h in (handles or [])):
            return None
        hardware = sum(HARDWARE_COSTS[h] for h in (handles or []))
        for name, count in bom.items():
            if name in ('ידית כפתור', 'ידית מגבת'):
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

def polish_reply(reply, history):
    """Light-touch output guard. Never remove substantive answers or quote details."""
    reply = reply.strip()
    reply = re.sub(r'^(?:(?:מעולה|מצוין|יופי)[,!،. ]+)', '', reply)
    reply = re.sub(r'^(?:רשמתי|קיבלתי)[,،. ]+', '', reply)
    # Only remove a repetitive recap if it directly precedes a simple next question.
    if history and '?' in reply:
        first, separator, rest = reply.partition('.')
        if separator and rest.strip().startswith(('איזה ', 'מה ', 'יש ', 'תרצו ', 'אתם ')):
            if any(term in first for term in ('רשמתי', 'סיכמנו', '100x100', '100×100')):
                reply = rest.strip()
    return re.sub(r'[-\u2013\u2014]', ' ', reply).strip()

def process_message(phone, body, batch_rows=None):
    with lock:
        personal_lock = phone_locks.setdefault(phone, threading.Lock())
    with personal_lock:
        history, prior = load_conversation(phone)
        history.append({'role':'user','content':body})
        facts = conversation_constraints(history)
        competitor_exit = any(phrase in body for phrase in ('אלך איתם', 'הולך איתם', 'אני אלך איתם', 'אסגור איתם', 'אני הולך איתם', 'נראה לי שאני אלך איתם'))
        short_correction = body.strip() in ('איתם', 'התכוונתי איתם', 'איתם*', '*איתם')
        if short_correction and any('איתן' in m.get('content', '') or 'איתם' in m.get('content', '') for m in history[-5:] if m.get('role') == 'user'):
            competitor_exit = True
        showroom_question = ('אולם' in body or 'תצוגה' in body) and any(w in body for w in ('יש', 'איפה', 'כתובת', 'שעות', 'לבוא', 'להגיע', 'ביקור', 'שלכם', 'האולם'))
        showroom_claimed = any('יש לנו אולם' in msg.get('content', '') or 'שעות האולם' in msg.get('content', '') for msg in history[:-1] if msg.get('role') == 'assistant')
        image_ready = bool(HANDLE_BUTTON_IMAGE_URL and HANDLE_TOWEL_IMAGE_URL)
        glass_images_ready = bool(GLASS_SAMPLE_IMAGES)
        instructions = (SYSTEM + '\n' + SALES_GUIDANCE + '\nמצב שיחה מפורש: ' + json.dumps(facts, ensure_ascii=False) + '\nסוגי הזכוכית המלאים הזמינים: ' + GLASS_TYPES_TEXT
                        + '\nתמונות זכוכית זמינות לסוגים: ' + ('، '.join(GLASS_SAMPLE_IMAGES) if glass_images_ready else 'אין עדיין')
                        + '\nתמונות ידיות זמינות לשליחה: '
                        + ('כן' if image_ready else 'לא')
                        + '\nמחירים אוטומטיים מופעלים: ' + ('כן' if SEND_QUOTES else 'לא')
                        + '\nסיכום מצב קודם, לבדיקה מול ההיסטוריה: '
                        + json.dumps(prior, ensure_ascii=False))
        try:
            app.logger.info("AI_REQUEST phone_suffix=%s", phone[-4:])
            response = client.responses.create(
                model=MODEL,
                instructions=instructions,
                input=[{'role':'developer','content':'Return a valid JSON object. Follow the JSON output contract in the instructions.'}] + history[-36:],
                text={'format':{'type':'json_object'}},
            )
            app.logger.info("AI_RESPONSE phone_suffix=%s", phone[-4:])
            data = json.loads(response.output_text)
            reply = polish_reply(str(data.get('reply') or ''), history)
            reply = avoid_repeated_dimensions(reply, facts, body)
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
            # Hard business facts override a mistaken model response.
            if showroom_question:
                reply = ('סליחה, טעיתי קודם. אנחנו מרמלה אבל אין לנו אולם תצוגה שאפשר להגיע אליו 😊' if showroom_claimed else 'אנחנו מרמלה, אבל אין לנו אולם תצוגה שאפשר להגיע אליו 😊')
            if competitor_exit:
                reply = ('אה, הבנתי אותך עכשיו, התכוונת להצעה שלהם 😊 סליחה על הבלבול. אם היא מתאימה לך יותר, אני לגמרי מבין. שיהיה בהצלחה, ואם תצטרך משהו נוסף בזכוכית אנחנו כאן.' if short_correction else 'מבין אותך. אם ההצעה שלהם מתאימה לך יותר, זה לגמרי בסדר 😊 שיהיה בהצלחה, ואם תצטרך משהו נוסף בזכוכית אנחנו כאן.')
            # Only send validated shower quotes, never an AI-invented number.
            if not showroom_question and not competitor_exit and SEND_QUOTES and data.get('quote_requested') is True and data.get('solution_agreed') is True and not data.get('needs_human'):
                price = calculate_quote(data)
                if price is not None:
                    reply = (f'לפי הפרטים שסיכמנו, המחיר המשוער הוא ₪{price:,.0f} לפני מע״מ, כולל מדידה, הובלה והתקנה. המחיר הסופי כפוף לאימות הפרטים בשטח. איך זה נשמע לך?')
            # Do not expose internal infrastructure or disabled pricing to customers.
            if not showroom_question and any(term in reply for term in ('תמחור אוטומטי', 'מערכת התמחור', 'התמחור לא פעיל')):
                reply = 'בשמחה. כדי לתת לך מחיר אמין אני צריך לוודא את הפרטים של העבודה. על איזה מוצר מדובר?'
            # If the customer sent a correction while we were composing, retry
            # with the new messages rather than sending a stale response.
            delay = min(TYPING_MAX, max(TYPING_MIN, len(reply) / 23.0))
            time.sleep(delay)
            if has_new_messages(phone, batch_rows):
                app.logger.info('New messages arrived during composition; postponing reply')
                return False
            app.logger.info("WHATSAPP_SEND_ATTEMPT phone_suffix=%s", phone[-4:])
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
            save_conversation(phone, history + [{'role':'assistant','content':reply}], {
                key: data.get(key) for key in (
                    'stage','action','next_missing_fact','product','configuration',
                    'width_cm','second_width_cm','height_cm','glass_type','finish',
                    'handles','quote_requested','solution_agreed','needs_human')
            })
            return True
        except Exception:
            app.logger.exception('Message processing failed')
            try:
                send_whatsapp(phone, body='סליחה, הייתה תקלה רגעית. תוכל לשלוח לי שוב את ההודעה?')
                return True  # Error already reported to the customer; do not send it repeatedly.
            except Exception:
                app.logger.exception('Fallback send failed')
            return False

def batch_worker():
    app.logger.info("BATCH_WORKER_STARTED pid=%s", os.getpid())
    while True:
        try:
            batch = next_batch()
            if not batch:
                time.sleep(0.25)
                continue
            phone, rows = batch
            combined = '\n'.join(r[1] for r in rows)
            success = process_message(phone, combined, rows)
            # If a correction arrived during composition, keep the entire batch
            # so it can be reinterpreted together with the correction.
            if not success and has_new_messages(phone, rows):
                with lock:
                    processing.discard(phone)
                continue
            finish_batch(phone, rows, success=success)
        except Exception:
            app.logger.exception('Batch worker failed')
            time.sleep(2)


def ensure_worker_started():
    """Start in the process that actually serves requests, not at import/preload."""
    global worker_thread, worker_pid
    with worker_start_lock:
        pid = os.getpid()
        if worker_pid != pid or worker_thread is None or not worker_thread.is_alive():
            worker_thread = threading.Thread(target=batch_worker, daemon=True,
                                             name='whatsapp-batch-worker')
            worker_pid = pid
            worker_thread.start()
            app.logger.info("WORKER_INITIALIZED pid=%s", pid)


@app.route('/', methods=['GET'])
def home():
    return 'Dream of Glass WhatsApp AI is running', 200

@app.route('/health', methods=['GET'])
def health():
    ensure_worker_started()
    with lock:
        queued = sum(len(items) for items in pending.values())
        active = len(processing)
    return {'status':'ok','quotes_enabled':SEND_QUOTES,
            'worker_alive':bool(worker_thread and worker_thread.is_alive()),
            'queued_messages':queued,'processing_chats':active}, 200

@app.route('/webhook', methods=['GET','POST'])
def webhook():
    if request.method == 'GET':
        if request.args.get('hub.mode') == 'subscribe' and request.args.get('hub.verify_token') == VERIFY_TOKEN:
            return request.args.get('hub.challenge', ''), 200
        return 'Verification failed', 403
    ensure_worker_started()
    data = request.get_json(silent=True) or {}
    received = 0
    statuses = 0
    ignored = 0
    for entry in data.get('entry', []):
        for change in entry.get('changes', []):
            value = change.get('value') or {}
            statuses += len(value.get('statuses', []))
            for message in value.get('messages', []):
                if message.get('type') != 'text':
                    ignored += 1
                    continue
                phone = message.get('from')
                body = ((message.get('text') or {}).get('body') or '').strip()
                message_id = message.get('id')
                if not phone or not body:
                    continue
                try:
                    queue_message(phone, body, message_id or f'{phone}:{time.time_ns()}')
                    received += 1
                except Exception:
                    app.logger.exception('Could not queue incoming message')
                    return 'Queue unavailable', 503
    app.logger.info('WEBHOOK_RECEIVED text_messages=%s statuses=%s ignored=%s', received, statuses, ignored)
    return 'EVENT_RECEIVED', 200

@app.route('/privacy', methods=['GET'])
def privacy():
    return '<h1>Privacy Policy</h1><p>Contact: dream.of.glass2@gmail.com</p>', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT','10000')))
