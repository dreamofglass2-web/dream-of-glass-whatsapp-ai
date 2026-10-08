import os
import json
import logging
import re
import threading
from collections import Counter

import requests
from flask import Flask, request
from openai import OpenAI

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN', 'dream_of_glass_verify')
WHATSAPP_TOKEN = os.environ.get('whatsapp_token', '')
PHONE_NUMBER_ID = '1280310741842089'
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
client = OpenAI(api_key=OPENAI_API_KEY)
# Keep this False until you approve live quotes after testing.
SEND_QUOTES = os.environ.get('SEND_QUOTES', 'false').lower() == 'true'
VAT_RATE = float(os.environ.get('VAT_RATE', '0.18'))

conversation_history = {}
customer_sales_state = {}
processed_messages = set()
state_lock = threading.RLock()

GLASS_COSTS = {
    'שקופה': 150, 'אקסטרה קליר': 220, 'אנטיסן אפור': 220,
    'פיפיטה': 220, 'חלבי': 220, 'אסיד': 220,
    'אנטיסן ברונזה': 240, 'גלינה קליר': 380, 'אסיד קליר': 380,
}
HARDWARE_COSTS = {
    'ציר קיר זכוכית': 50, 'ציר זכוכית זכוכית': 75,
    'ידית כפתור': 30, 'ידית מגבת': 80, 'מוט חיזוק': 65,
    'זווית קיר זכוכית': 25, 'זווית זכוכית זכוכית': 30,
    'מגנט פינתי': 30, 'מגנט חזית': 30, 'אטם בלון': 8,
    'מגב רצפה': 8, 'אטם כיסא': 8, 'ציר הרמוניקה': 85,
    'ציר פרימה': 100, 'ציר סיכורית': 150,
    'פרופיל אלומיניום': 50, 'ידית 19.2': 80,
}
FINISH_MULTIPLIERS = {
    'ניקל': 1.0, 'שחור': 1.1, 'ניקל מוברש': 1.1,
    'גרפיט': 1.1, 'ברונזה': 1.1, 'זהב': 1.1, 'לבן': 1.1,
}
SLIDING_SET_COSTS = {'קבוע + דלת': 600, '2 קבועים + 2 דלתות': 1200}
SHOWER_BOM = {
    'חצי הרמוניקה + חצי קבוע + דלת': {
        'ציר קיר זכוכית': 2, 'ציר זכוכית זכוכית': 2,
        'ציר הרמוניקה': 2, 'ידית כפתור': 2, 'ידית ראשית': 1,
        'מגנט פינתי': 1, 'אטם בלון': 2, 'אטם כיסא': 1,
        'מגב רצפה': 1,
    },
    'פינתי 2 קבועים + 2 דלתות': {
        'ציר זכוכית זכוכית': 4, 'זווית קיר זכוכית': 4,
        'ידית כפתור': 2, 'מגנט פינתי': 1, 'מגב רצפה': 1,
        'אטם בלון': 2,
    },
    'חזית קבוע + דלת': {
        'ציר קיר זכוכית': 2, 'זווית קיר זכוכית': 2,
        'מגנט חזית': 1, 'אטם בלון': 1, 'מגב רצפה': 1,
        'ידית כפתור': 1,
    },
    'פינתי הרמוניקה': {
        'ציר הרמוניקה': 4, 'ציר קיר זכוכית': 4,
        'ידית כפתור': 4, 'מגנט פינתי': 1, 'אטם בלון': 2,
        'אטם כיסא': 2, 'מגב רצפה': 1,
    },
    'חזית 2 דלתות': {
        'ציר קיר זכוכית': 4, 'ידית כפתור': 2,
        'מגנט חזית': 1, 'אטם בלון': 2, 'מגב רצפה': 1,
    },
    'פינתי 2 דלתות': {
        'ציר קיר זכוכית': 4, 'ידית כפתור': 2,
        'מגנט פינתי': 1, 'אטם בלון': 2, 'מגב רצפה': 1,
    },
    'פינתי קבוע + דלת': {
        'ציר קיר זכוכית': 2, 'זווית קיר זכוכית': 2,
        'ידית כפתור': 1, 'אטם בלון': 1, 'מגב רצפה': 1,
        'מגנט פינתי': 1,
    },
    'פינתי 2 קבועים + דלת': {
        'זווית קיר זכוכית': 4, 'ציר זכוכית זכוכית': 2,
        'ידית כפתור': 1, 'אטם בלון': 1,
        'מגנט פינתי': 1, 'מגב רצפה': 1,
    },
    'קבוע בלבד': {'זווית קיר זכוכית': 2, 'מוט חיזוק': 1},
}

PRODUCTS = ('מקלחון', 'אמבטיון', 'מראה', 'מחיצת זכוכית',
            'חיפוי זכוכית למטבח', 'דלת זכוכית', 'מעקה זכוכית', 'אחר')


def handle_slots(configuration):
    bom = SHOWER_BOM.get(configuration, {})
    return bom.get('ידית כפתור', 0) + bom.get('ידית ראשית', 0)


def calculate_hardware_cost(configuration, finish='ניקל', handles=None):
    bom = SHOWER_BOM.get(configuration)
    multiplier = FINISH_MULTIPLIERS.get(finish)
    if bom is None or multiplier is None:
        return None
    count = handle_slots(configuration)
    if not isinstance(handles, list) or len(handles) != count:
        return None
    if any(h not in ('ידית כפתור', 'ידית מגבת') for h in handles):
        return None
    total = sum(HARDWARE_COSTS[h] for h in handles)
    for part, quantity in bom.items():
        if part in ('ידית כפתור', 'ידית ראשית'):
            continue
        unit_cost = HARDWARE_COSTS.get(part)
        if unit_cost is None:
            return None
        total += unit_cost * quantity
    return round(total * multiplier, 2)


def calculate_shower_price(configuration, width_cm, height_cm, glass_type,
                           finish, second_width_cm=None, handles=None):
    if glass_type not in GLASS_COSTS or configuration not in SHOWER_BOM:
        return None
    try:
        width = float(width_cm)
        height = float(height_cm)
        second_width = float(second_width_cm) if second_width_cm is not None else None
    except (ValueError, TypeError):
        return None
    if width <= 0 or height <= 0 or height > 220:
        return None
    if configuration.startswith('פינתי'):
        if second_width is None or second_width <= 0 or width > 120 or second_width > 120:
            return None
        glass_width = width + second_width
    elif configuration.startswith('חזית'):
        if width > 200:
            return None
        glass_width = width
    else:
        # Fixed-only, accordion variants and sliding systems need approved BOM/geometry.
        return None
    hardware = calculate_hardware_cost(configuration, finish, handles)
    if hardware is None:
        return None
    glass_area = glass_width * height / 10000
    before_vat = glass_area * GLASS_COSTS[glass_type] + hardware + 1500 + 150
    # Minimum job is NIS 2,000 before VAT. Never silently reject smaller quotes.
    return int((max(before_vat, 2000) + 5) // 10 * 10)


def llm_json(instructions, history):
    response = client.responses.create(
        model='gpt-5-mini',
        instructions=instructions + ' Return a valid JSON object only.',
        input=[{'role': 'system', 'content': 'Return a valid JSON object only.'}, *history],
        text={'format': {'type': 'json_object'}},
    )
    return json.loads(response.output_text)


def understand_customer_need(history):
    return llm_json(
        '''נתח את השיחה בעברית כמנהל מכירות מקצועי. אל תמציא פרטים.
        החזר JSON עם המפתחות: product, stage, need, priority, quote_requested,
        solution_agreed, step_cut, cnc_possible, needs_human.
        product חייב להיות אחד מ: ''' + ', '.join(PRODUCTS) + ''' או null.
        stage חייב להיות discovery, consultation, qualification, quotation,
        negotiation, closing או handoff.
        need: למה הלקוח צריך את המוצר, או null.
        priority: מה חשוב ללקוח (נוחות, ניקיון, עיצוב, מחיר וכדומה), או null.
        quote_requested=true רק אם הלקוח ביקש מחיר/הצעת מחיר במפורש בשיחה
        או אישר במפורש שהוא רוצה הצעת מחיר. אל תסיק זאת ממידות בלבד.
        solution_agreed=true רק אם הלקוח כבר בחר פתרון ברור או אישר המלצה.
        step_cut=true רק אם הלקוח הזכיר מדרגה או חיתוך.
        cnc_possible=true רק אם הוזכר CNC או חיתוך מורכב שמחייב בדיקה.
        needs_human=true במעקה, דלת זכוכית, עבודת הדפסה מיוחדת, מורכבות
        הנדסית או אי ודאות מהותית שלא ניתן לפתור בצ'אט.
        תן עדיפות להודעות האחרונות במקרה של שינוי פרטים.''', history)


def extract_shower_details(history):
    return llm_json(
        '''חלץ רק מידע שהלקוח אמר או אישר, אל תנחש ואל תקבע ברירת מחדל.
        החזר JSON עם: configuration, width_cm, second_width_cm, height_cm,
        glass_type, finish, handles, cut_type.
        configuration אחת מהאפשרויות: ''' + ', '.join(SHOWER_BOM.keys()) + ''' או null.
        glass_type אחת מהאפשרויות: ''' + ', '.join(GLASS_COSTS.keys()) + ''' או null.
        finish אחת מהאפשרויות: ''' + ', '.join(FINISH_MULTIPLIERS.keys()) + ''' או null.
        מידות בסנטימטרים, המר מטרים לסנטימטרים רק כשהמידה ברורה.
        handles היא רשימה לפי כל הידיות בתצורה, כל איבר בדיוק
        'ידית כפתור' או 'ידית מגבת'. אם לא ידוע מהי כל ידית, החזר null.
        אם הלקוח אמר שתי ידיות מגבת, רשום פעמיים 'ידית מגבת'.
        אם אמר אחת מגבת ואחת כפתור, רשום את שתיהן בנפרד.
        אין להניח ששתי ידיות זהות. אין להמציא ידיות.
        כאשר נאמר שני קבועים ושתי דלתות, אל תקצר לשתי דלתות בלבד.
        cut_type: 'רגיל', 'cnc', 'לא ידוע' או null. אל תעלה חיתוך מיוזמתך.
        אם יש סתירה מהותית, החזר null לשדה הבעייתי.''', history)


SALES_INSTRUCTIONS = """אתה יועץ המכירות של 'חלומות מזכוכית', עסק לעבודות זכוכית בהתאמה אישית.

סגנון דיבור מחייב:
דבר בעברית ישראלית פשוטה, בגובה העיניים, בחום, במקצועיות ובביטחון שקט.
כמו בעל מקצוע מנוסה שמדבר בוואטסאפ, לא כמו רובוט, מפרט טכני או פרסומת.
כתוב בדרך כלל שניים עד ארבעה משפטים קצרים, בלי רשימות ארוכות ובלי הרצאות.
הימנע ממקפים, מקפים ארוכים ונקודתיים בתשובות ללקוח.
השתמש במשפטים רגילים עם פסיקים ונקודות, כמו בשיחת וואטסאפ טבעית.
אל תכתוב כותרות, סעיפים, תבליטים או ניסוח אקדמי.
אל תשתמש בסוגריים אלא אם אין דרך טבעית יותר להסביר.
שאל לכל היותר שאלה אחת בכל הודעה. אל תשלב כמה שאלות באותו משפט.
אל תציג תפריט של ארבע אפשרויות אם אפשר לשאול שאלה טבעית אחת.
אל תפתח כל תשובה ב'מעולה', 'מצוין' או 'בשמחה'.
אל תשתמש במונחים כמו פריימלס, סמי-פריימלס, פיבוט, תצורה, אטימה הרמטית
או מונחים מקצועיים אחרים אלא אם הלקוח משתמש בהם או מבקש הסבר.
אם יש צורך במושג מקצועי, הסבר אותו במשפט פשוט.

ניהול שיחת מכירה:
קרא את כל ההיסטוריה וזכור פרטים שהלקוח כבר מסר. אל תשאל אותם שוב.
בהתחלה הבן למה הלקוח צריך את המוצר ומה חשוב לו, בדרך טבעית ולא כשאלון.
אחר כך תן ייעוץ שמתייחס בדיוק למה שאמר, ורק בהמשך אסוף נתונים להצעה.
אם הלקוח מבקש מחיר כבר בהתחלה, כבד זאת ואסוף את המינימום הדרוש.
אם הלקוח כבר החליט על פתרון, אל תכריח אותו לעבור בירור מיותר.
אל תמהר לשאול מידות כשהלקוח עדיין מנסה להבין מה מתאים לו.
אם לא ברור איזה פתרון יתאים, הצג בקצרה אפשרויות בלי לקבוע עובדות נחרצות.
אל תמציא מוצרים, תכונות, ציפויים, מבצעים, זמני אספקה או התחייבויות.
אל תציע ציפוי נגד אבנית, סף מיוחד או אביזר אחר שלא אושר במידע העסקי.

ייעוץ על מקום צפוף:
אפשר להסביר שבחלק מהמקרים דלת הזזה או הרמוניקה יכולה להתאים,
אך הבחירה תלויה במבנה המקום ובנוחות השימוש. אל תבטיח פתרון בלי לראות.
אם תמונה באמת תעזור, הצע ללקוח לשלוח תמונה כאפשרות בלבד, לא כחובה.
אין להתנות התקדמות בשיחה או הצעה בקבלת תמונה.
אפשר לומר: 'אם נוח לך, אפשר לשלוח תמונה כדי שאבין טוב יותר את השטח'.
אפשר להסביר שההתאמה הסופית תיבדק במדידה בשטח.
לעולם אל תניח מראש אם המקלחון פינתי, חזיתי או אחר, ואל תניח
כמה חלקים קבועים או דלתות יש בו. קודם הבן את מבנה המקום לפי
תיאור הלקוח או תמונה אם בחר לשלוח.
אם הלקוח מעוניין במחיר, אפשר להכין הצעה ראשונית רק עבור פתרון
שמתאים למידע הקיים ושהלקוח בחר או אישר במפורש.
אל תציע כדוגמת ברירת מחדל מקלחון פינתי עם שני קבועים ושתי דלתות.
אם עדיין לא ברור מה מבנה המקלחון, שאל שאלה פשוטה אחת על השטח
לפני שאתה מציע תצורה או מחיר.
אם במדידה יידרש פתרון אחר, כגון הרמוניקה, ייתכן הפרש מחיר;
מסבירים שההפרש ייבדק ויוצג ללקוח לפני אישור העבודה.
אל תמציא הפרש מחיר ואל תבטיח שפתרון מסוים מתאים בוודאות.

מים ואיטום — מידע מקצועי מחייב:
יציאת מים מהמקלחון תלויה במידה רבה בשיפועי הרצפה, כיוון הניקוז
ובמבנה המקלחון. כשהשיפועים טובים ומובילים את המים לניקוז,
בדרך כלל לא אמורה להיות בעיה משמעותית של יציאת מים.
אסור להבטיח אטימות מוחלטת או להבטיח שלא ייצאו מים.
אסור לומר שאנחנו נותנים אחריות על יציאת מים או על איטום המקלחון.
אל תבטיח שדלת מתקפלת או דלת ציר 'שומרת על אטימות'.
אם הלקוח לא שאל על מים או איטום, אל תעלה את הנושא מיוזמתך.

מקלחונים וידיות:
מקלחון סטנדרטי עשוי זכוכית מחוסמת 8 מ״מ עם פרזול איכותי והתקנה מקצועית.
כאשר נדרשות ידיות, אפשר ידית כפתור, ידית מגבת או שילוב ביניהן.
במקלחון עם שתי ידיות שאל על השילוב רק כשהמידע נחוץ להצעת מחיר.
אל תניח ששתי ידיות חייבות להיות זהות; אל תשאל על ידיות כשאין צורך.

מדרגה וחיתוך:
אם הלקוח לא הזכיר מדרגה או חיתוך, אל תעלה את הנושא ואל תבקש תמונה.
חיתוך רגיל למדרגה נעשה ללא תוספת תשלום.
CNC הוא חיתוך או עיבוד מדויק באמצעות מכונה ממוחשבת לצורות מורכבות;
אם נדרש CNC, המחיר ייבדק בנפרד. אל תמציא עלות ואל תכריע ללא מידע.
אם הלקוח לא שולח תמונה, המשך לפי התיאור ככל שניתן.
אל תבקש תמונה אם אין סיבה מקצועית ברורה לכך.

מחירים וגבולות סמכות:
אל תחשב מחירים בעצמך ואל תמציא סכומים. מחיר יינתן רק ממנגנון החישוב.
אל תציע הצעת מחיר לתצורה שלא אומתה עם הלקוח, גם לא כהערכה.
אל תחשוף עלויות פנימיות או נוסחאות.
מקרים מורכבים, עבודות מיוחדות, דלתות זכוכית ומעקות — לבדיקה אנושית.
אל תאמר שהעברת פרטים או תיאמת מדידה אם לא ביצעת פעולה כזו בפועל.
כשאין נתונים מספיקים, שאל שאלה אחת על הפרט החשוב הבא בלבד.
"""

def draft_sales_reply(history, analysis, details):
    context = {
        'stage': analysis.get('stage'),
        'need': analysis.get('need'),
        'priority': analysis.get('priority'),
        'quote_requested': analysis.get('quote_requested'),
        'solution_agreed': analysis.get('solution_agreed'),
        'product': analysis.get('product'),
        'known_shower_details': details,
    }
    response = client.responses.create(
        model='gpt-5-mini',
        instructions=SALES_INSTRUCTIONS + '\nמידע פנימי על מצב השיחה (לא להציג ללקוח): ' +
                     json.dumps(context, ensure_ascii=False),
        input=history,
    )
    return response.output_text.strip()


def format_quote(price):
    return (f'לפי הפרטים שסיכמנו, המחיר המשוער למקלחון הוא ₪{price:,.0f} '
            'לפני מע״מ, כולל מדידה, הובלה והתקנה. '
            'המחיר הסופי כפוף לאימות המידות והפרטים במדידה. '
            'אם זה מתאים לך, נוכל להתקדם לתיאום מדידה.')


def missing_quote_details(details):
    required = ('configuration', 'width_cm', 'height_cm', 'glass_type', 'finish')
    missing = [field for field in required if details.get(field) is None]
    config = details.get('configuration')
    if config and config.startswith('פינתי') and details.get('second_width_cm') is None:
        missing.append('second_width_cm')
    if config in SHOWER_BOM and handle_slots(config) and not isinstance(details.get('handles'), list):
        missing.append('handles')
    return missing


def process_customer_message(customer_phone, customer_message):
    with state_lock:
        history = conversation_history.setdefault(customer_phone, [])
        history.append({'role': 'user', 'content': customer_message})
        # Limit context to control costs. This remains in-memory until DB is added.
        if len(history) > 50:
            del history[:-50]
        snapshot = list(history)
    try:
        analysis = understand_customer_need(snapshot)
    except Exception:
        app.logger.exception('Customer need analysis failed')
        analysis = {'stage': 'discovery', 'quote_requested': False,
                    'product': None, 'solution_agreed': False}
    product = analysis.get('product')
    details = {}
    if product == 'מקלחון':
        try:
            details = extract_shower_details(snapshot)
        except Exception:
            app.logger.exception('Shower detail extraction failed')

    with state_lock:
        customer_sales_state[customer_phone] = analysis

    try:
        reply = draft_sales_reply(snapshot, analysis, details)
    except Exception:
        app.logger.exception('Sales response failed')
        reply = 'אשמח לעזור לך לבחור פתרון מתאים. מה הכי חשוב לך במוצר?'

    # Hard gate: model never controls the actual amount or timing of a quote.
    # In test mode the assistant continues the consultation without revealing prices.
    if (SEND_QUOTES and product == 'מקלחון' and
            analysis.get('quote_requested') is True and
            analysis.get('solution_agreed') is True and
            not analysis.get('needs_human') and
            not analysis.get('cnc_possible') and
            details.get('cut_type') != 'cnc' and
            not missing_quote_details(details)):
        price = calculate_shower_price(
            configuration=details.get('configuration'),
            width_cm=details.get('width_cm'),
            second_width_cm=details.get('second_width_cm'),
            height_cm=details.get('height_cm'),
            glass_type=details.get('glass_type'),
            finish=details.get('finish'),
            handles=details.get('handles'),
        )
        if price is not None:
            reply = format_quote(price)
            app.logger.info('Approved quote calculation succeeded')
        else:
            app.logger.info('Quote needs manual review')

    with state_lock:
        conversation_history[customer_phone].append({'role': 'assistant', 'content': reply})
    return reply


@app.route('/', methods=['GET'])
def home():
    return 'Dream of Glass WhatsApp AI is running', 200


@app.route('/health', methods=['GET'])
def health():
    return {'status': 'ok', 'quotes_enabled': SEND_QUOTES}, 200


@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        if mode == 'subscribe' and token == VERIFY_TOKEN:
            return challenge or '', 200
        return 'Verification failed', 403

    data = request.get_json(silent=True) or {}
    try:
        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                for message in value.get('messages', []):
                    if message.get('type') != 'text':
                        continue
                    phone = message.get('from')
                    body = (message.get('text') or {}).get('body', '').strip()
                    message_id = message.get('id')
                    if not phone or not body:
                        continue
                    if not WHATSAPP_TOKEN:
                        app.logger.error('Missing WhatsApp token')
                        continue
                    with state_lock:
                        if message_id and message_id in processed_messages:
                            continue
                        if message_id:
                            processed_messages.add(message_id)
                            if len(processed_messages) > 10000:
                                processed_messages.clear()
                    reply = process_customer_message(phone, body)
                    send_whatsapp_message(phone, reply)
    except Exception:
        app.logger.exception('Webhook processing error')
    return 'EVENT_RECEIVED', 200


def send_whatsapp_message(customer_phone, message_text):
    url = f'https://graph.facebook.com/v26.0/{PHONE_NUMBER_ID}/messages'
    headers = {'Authorization': f'Bearer {WHATSAPP_TOKEN}',
               'Content-Type': 'application/json'}
    payload = {'messaging_product': 'whatsapp', 'to': customer_phone,
               'type': 'text', 'text': {'body': message_text}}
    response = requests.post(url, headers=headers, json=payload, timeout=15)
    app.logger.info('WhatsApp send status: %s', response.status_code)
    response.raise_for_status()


@app.route('/privacy', methods=['GET'])
def privacy():
    return ('<h1>Privacy Policy</h1>'
            '<p>Contact: dream.of.glass2@gmail.com</p>'), 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '10000'))
    app.run(host='0.0.0.0', port=port)
