
import os
import json
import logging
import threading

import requests
from flask import Flask, request
from openai import OpenAI

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "dream_of_glass_verify")
WHATSAPP_TOKEN = os.environ.get("whatsapp_token", "")
PHONE_NUMBER_ID = "1280310741842089"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

SEND_QUOTES = os.environ.get("SEND_QUOTES", "false").lower() == "true"
VAT_RATE = float(os.environ.get("VAT_RATE", "0.18"))

conversation_history = {}
customer_sales_state = {}
processed_messages = set()
state_lock = threading.RLock()

GLASS_COSTS = {
    "שקופה": 150,
    "אקסטרה קליר": 220,
    "אנטיסן אפור": 220,
    "פיפיטה": 220,
    "חלבי": 220,
    "אסיד": 220,
    "אנטיסן ברונזה": 240,
    "גלינה קליר": 380,
    "אסיד קליר": 380,
}

HARDWARE_COSTS = {
    "ציר קיר זכוכית": 50,
    "ציר זכוכית זכוכית": 75,
    "ידית כפתור": 30,
    "ידית מגבת": 80,
    "מוט חיזוק": 65,
    "זווית קיר זכוכית": 25,
    "זווית זכוכית זכוכית": 30,
    "מגנט פינתי": 30,
    "מגנט חזית": 30,
    "אטם בלון": 8,
    "מגב רצפה": 8,
    "אטם כיסא": 8,
    "ציר הרמוניקה": 85,
    "ציר פרימה": 100,
    "ציר סיכורית": 150,
    "פרופיל אלומיניום": 50,
    "ידית 19.2": 80,
}

FINISH_MULTIPLIERS = {
    "ניקל": 1.00,
    "שחור": 1.10,
    "ניקל מוברש": 1.10,
    "גרפיט": 1.10,
    "ברונזה": 1.10,
    "זהב": 1.10,
    "לבן": 1.10,
}

SLIDING_SET_COSTS = {
    "קבוע + דלת": 600,
    "2 קבועים + 2 דלתות": 1200,
}

SHOWER_BOM = {
    "חצי הרמוניקה + חצי קבוע + דלת": {
        "ציר קיר זכוכית": 2,
        "ציר זכוכית זכוכית": 2,
        "ציר הרמוניקה": 2,
        "ידית כפתור": 2,
        "ידית ראשית": 1,
        "מגנט פינתי": 1,
        "אטם בלון": 2,
        "אטם כיסא": 1,
        "מגב רצפה": 1,
    },
    "פינתי 2 קבועים + 2 דלתות": {
        "ציר זכוכית זכוכית": 4,
        "זווית קיר זכוכית": 4,
        "ידית כפתור": 2,
        "מגנט פינתי": 1,
        "מגב רצפה": 1,
        "אטם בלון": 2,
    },
    "חזית קבוע + דלת": {
        "ציר קיר זכוכית": 2,
        "זווית קיר זכוכית": 2,
        "מגנט חזית": 1,
        "אטם בלון": 1,
        "מגב רצפה": 1,
        "ידית כפתור": 1,
    },
    "פינתי הרמוניקה": {
        "ציר הרמוניקה": 4,
        "ציר קיר זכוכית": 4,
        "ידית כפתור": 4,
        "מגנט פינתי": 1,
        "אטם בלון": 2,
        "אטם כיסא": 2,
        "מגב רצפה": 1,
    },
    "חזית 2 דלתות": {
        "ציר קיר זכוכית": 4,
        "ידית כפתור": 2,
        "מגנט חזית": 1,
        "אטם בלון": 2,
        "מגב רצפה": 1,
    },
    "פינתי 2 דלתות": {
        "ציר קיר זכוכית": 4,
        "ידית כפתור": 2,
        "מגנט פינתי": 1,
        "אטם בלון": 2,
        "מגב רצפה": 1,
    },
    "פינתי קבוע + דלת": {
        "ציר קיר זכוכית": 2,
        "זווית קיר זכוכית": 2,
        "ידית כפתור": 1,
        "אטם בלון": 1,
        "מגב רצפה": 1,
        "מגנט פינתי": 1,
    },
    "פינתי 2 קבועים + דלת": {
        "זווית קיר זכוכית": 4,
        "ציר זכוכית זכוכית": 2,
        "ידית כפתור": 1,
        "אטם בלון": 1,
        "מגנט פינתי": 1,
        "מגב רצפה": 1,
    },
    "קבוע בלבד": {
        "זווית קיר זכוכית": 2,
        "מוט חיזוק": 1,
    },
}

PRODUCTS = (
    "מקלחון",
    "אמבטיון",
    "מראה",
    "מחיצת זכוכית",
    "חיפוי זכוכית למטבח",
    "דלת זכוכית",
    "מעקה זכוכית",
    "אחר",
)


def handle_slots(configuration):
    bom = SHOWER_BOM.get(configuration, {})
    return bom.get("ידית כפתור", 0) + bom.get("ידית ראשית", 0)


def calculate_hardware_cost(configuration, finish="ניקל", handles=None):
    bom = SHOWER_BOM.get(configuration)
    multiplier = FINISH_MULTIPLIERS.get(finish)

    if bom is None or multiplier is None:
        return None

    count = handle_slots(configuration)

    if not isinstance(handles, list) or len(handles) != count:
        return None

    if any(h not in ("ידית כפתור", "ידית מגבת") for h in handles):
        return None

    total = sum(HARDWARE_COSTS[h] for h in handles)

    for part, quantity in bom.items():
        if part in ("ידית כפתור", "ידית ראשית"):
            continue

        unit_cost = HARDWARE_COSTS.get(part)

        if unit_cost is None:
            return None

        total += unit_cost * quantity

    return round(total * multiplier, 2)


def calculate_shower_price(
    configuration,
    width_cm,
    height_cm,
    glass_type,
    finish,
    second_width_cm=None,
    handles=None,
):
    if glass_type not in GLASS_COSTS:
        return None

    if configuration not in SHOWER_BOM:
        return None

    try:
        width = float(width_cm)
        height = float(height_cm)
        second_width = (
            float(second_width_cm)
            if second_width_cm is not None
            else None
        )
    except (ValueError, TypeError):
        return None

    if width <= 0 or height <= 0 or height > 220:
        return None

    if configuration.startswith("פינתי"):
        if second_width is None or second_width <= 0:
            return None

        if width > 120 or second_width > 120:
            return None

        glass_width = width + second_width

    elif configuration.startswith("חזית"):
        if width > 200:
            return None

        glass_width = width

    else:
        return None

    hardware = calculate_hardware_cost(
        configuration,
        finish,
        handles,
    )

    if hardware is None:
        return None

    glass_area = glass_width * height / 10000

    before_vat = (
        glass_area * GLASS_COSTS[glass_type]
        + hardware
        + 1500
        + 150
    )

    return int((max(before_vat, 2000) + 5) // 10 * 10)


def llm_json(instructions, history):
    response = client.responses.create(
        model="gpt-5-mini",
        instructions=instructions + " Return a valid JSON object only.",
        input=[
            {
                "role": "system",
                "content": "Return a valid JSON object only.",
            },
            *history,
        ],
        text={"format": {"type": "json_object"}},
    )

    return json.loads(response.output_text)


def understand_customer_need(history):
    instructions = """
נתח את השיחה בעברית כמנהל מכירות מקצועי.

אל תמציא פרטים.

החזר JSON עם המפתחות:
product, stage, need, priority, quote_requested,
solution_agreed, step_cut, cnc_possible, needs_human.

product חייב להיות אחד מהמוצרים הבאים או null:
""" + ", ".join(PRODUCTS) + """

stage חייב להיות אחד מהבאים:
discovery, consultation, qualification, quotation,
negotiation, closing, handoff.

need מתאר למה הלקוח צריך את המוצר, או null.

priority מתאר מה חשוב ללקוח, או null.

quote_requested=true רק אם הלקוח ביקש מחיר במפורש
או אישר שהוא רוצה הצעת מחיר.

אל תסיק שהלקוח רוצה הצעת מחיר רק כי נתן מידות.

solution_agreed=true רק אם הלקוח בחר פתרון ברור
או אישר המלצה מסוימת.

step_cut=true רק אם הלקוח הזכיר מדרגה או חיתוך.

cnc_possible=true רק אם הוזכר CNC או חיתוך מורכב
שמחייב בדיקה.

needs_human=true במעקות, דלתות זכוכית,
עבודות מיוחדות, מורכבות הנדסית
או אי ודאות מהותית שלא ניתן לפתור בצ'אט.

תן עדיפות להודעות האחרונות אם הלקוח שינה פרט.
"""

    return llm_json(instructions, history)


def extract_shower_details(history):
    instructions = """
חלץ רק מידע שהלקוח אמר או אישר.
אל תנחש ואל תקבע ברירת מחדל.

החזר JSON עם המפתחות:
configuration, width_cm, second_width_cm,
height_cm, glass_type, finish, handles, cut_type.

configuration חייב להיות אחת האפשרויות:
""" + ", ".join(SHOWER_BOM.keys()) + """

או null.

glass_type חייב להיות אחת האפשרויות:
""" + ", ".join(GLASS_COSTS.keys()) + """

או null.

finish חייב להיות אחת האפשרויות:
""" + ", ".join(FINISH_MULTIPLIERS.keys()) + """

או null.

המידות בסנטימטרים.
אם הלקוח נתן מטרים, המר לסנטימטרים
רק כשהמידה ברורה.

handles היא רשימה של כל הידיות בתצורה.

כל איבר ברשימה יכול להיות רק:
ידית כפתור
ידית מגבת

אם לא ידוע סוג כל הידיות, החזר null.

אם הלקוח אמר שתי ידיות מגבת,
החזר שתי ידיות מגבת ברשימה.

אם אמר אחת מגבת ואחת כפתור,
החזר את שתיהן בנפרד.

אל תניח ששתי ידיות חייבות להיות זהות.

כאשר הלקוח אומר שני קבועים ושתי דלתות,
אל תקצר את התצורה לשתי דלתות בלבד.

cut_type יכול להיות:
רגיל, cnc, לא ידוע, null.

אל תעלה את נושא החיתוך מיוזמתך.

אם יש סתירה מהותית,
החזר null בשדה הבעייתי.
"""

    return llm_json(instructions, history)


SALES_INSTRUCTIONS = """
אתה יועץ המכירות של חלומות מזכוכית.
העסק מבצע עבודות זכוכית בהתאמה אישית.

המטרה שלך היא לעזור ללקוח לבחור נכון,
לבנות אמון ולהוביל לעסקה שמתאימה לצרכיו.

סגנון דיבור

דבר בעברית ישראלית פשוטה,
בגובה העיניים, בחום ובמקצועיות.

דבר כמו בעל מקצוע מנוסה בוואטסאפ,
לא כמו רובוט, מפרט טכני או מרצה.

כתוב בדרך כלל שניים עד ארבעה משפטים קצרים.

הימנע ממקפים ומנקודתיים.
השתמש בפסיקים ובנקודות באופן טבעי.

אל תכתוב כותרות, סעיפים או רשימות ללקוח.

אל תשתמש במונחים מקצועיים מסובכים
אלא אם הלקוח ביקש הסבר.

אל תפתח כל הודעה במעולה, מצוין או בשמחה.

שאל לכל היותר שאלה אחת בכל הודעה.

אל תציג ללקוח רשימה ארוכה של אפשרויות
כשאפשר לשאול שאלה פשוטה אחת.

ניהול שיחה

קרא את כל היסטוריית השיחה לפני כל תשובה.

זכור את כל הפרטים שהלקוח כבר מסר.

אל תשאל שוב על פרט שכבר נאמר.

זכור גם מה שכבר הסברת ללקוח.

אל תחזור על אותו הסבר בלי סיבה.

אם הלקוח כתב רק היי,
ברך אותו ושאל איך אפשר לעזור.

אל תנחש איזה מוצר הוא מחפש.

אם הלקוח כתב רק שהוא צריך מקלחון,
ברר באופן טבעי אם מדובר בשיפוץ,
חדר רחצה חדש או החלפת מקלחון קיים.

אם הלקוח כבר סיפר זאת,
אל תשאל שוב.

אם הלקוח אמר שהמקלחון פינתי,
אל תשאל בהמשך אם הוא פינתי.

אם הלקוח נתן מידות,
אל תבקש אותן שוב.

אם הלקוח משנה פרט,
השתמש בפרט החדש.

הבנת צרכים

נסה להבין למה הלקוח צריך את המוצר
ומה חשוב לו.

אל תהפוך את השיחה לשאלון.

התייחס למה שהלקוח אמר בפועל.

אל תמהר לבקש מידות אם הלקוח
עדיין מנסה להבין מה מתאים לו.

אם הלקוח מבקש מחיר מיד,
כבד את הבקשה ואסוף רק
את המידע הנחוץ להצעה.

אם הלקוח כבר בחר פתרון,
אל תכריח אותו לעבור בירור מיותר.

ייעוץ מקצועי

אל תניח מראש אם המקלחון פינתי,
חזיתי או מסוג אחר.

אל תניח כמה דלתות או חלקים קבועים יש.

קודם הבן את מבנה המקום.

אל תחליט שצריך הזזה או הרמוניקה
רק משום שהמקום קטן.

אפשר להסביר שיש כמה אפשרויות,
ושהבחירה תלויה במבנה המקום
ובנוחות השימוש.

אם תמונה תעזור להבין את המקום,
אפשר להציע ללקוח לשלוח תמונה.

תמונה היא אפשרות בלבד,
לעולם לא תנאי להמשך השיחה.

אם אין תמונה,
המשך לפי התיאור והמידות.

אפשר להסביר שההתאמה הסופית
תיבדק במדידה בשטח.

אל תחזור על ההסבר הזה בכל הודעה.

אם הלקוח רוצה הצעת מחיר,
אפשר להכין הצעה ראשונית
לפתרון שהלקוח בחר או אישר.

אל תבחר בשבילו תצורה אקראית.

אם במדידה יתברר שצריך פתרון אחר,
ייתכן שינוי במחיר.

יש לעדכן את הלקוח בהפרש
לפני אישור העבודה.

אל תמציא הפרשי מחיר.

מים ושיפועים

יציאת מים מהמקלחון תלויה במידה רבה
בשיפועי הרצפה, בכיוון הניקוז
ובמבנה המקלחון.

כשהשיפועים טובים ומובילים את המים לניקוז,
בדרך כלל לא אמורה להיות בעיה משמעותית.

אסור להבטיח אטימות מוחלטת.

אסור להבטיח שלא ייצאו מים.

אסור לומר שאנחנו נותנים אחריות
על יציאת מים או על איטום המקלחון.

אל תבטיח שדלת מסוימת
תמנע יציאת מים.

אם הלקוח לא שאל על מים,
אל תעלה את הנושא מיוזמתך.

אל תחזור על הסבר השיפועים
אחרי שכבר הסברת אותו,
אלא אם הלקוח שואל שוב.

ניקוי ותחזוקה

אל תטען שדלת הזזה בהכרח
קלה יותר לניקוי.

אל תטען שזכוכית 8 מ"מ
מקלה על הניקוי.

אל תציע ציפוי נגד אבנית
או אביזר שלא אושר במידע העסקי.

מקלחונים וידיות

מקלחון סטנדרטי עשוי זכוכית
מחוסמת בעובי 8 מ"מ.

העסק משתמש בפרזול איכותי
ומבצע התקנה מקצועית.

אפשר לבחור ידית כפתור,
ידית מגבת או שילוב ביניהן.

במקלחון עם שתי ידיות,
אפשר שתי ידיות כפתור,
שתי ידיות מגבת
או אחת מכל סוג.

שאל על סוגי הידיות
רק כשזה רלוונטי לתצורה
ונחוץ להכנת ההצעה.

אל תניח שכל הידיות זהות.

אל תשאל על ידיות
בתצורה שאינה דורשת ידית.

מדרגה וחיתוכים

אם הלקוח לא הזכיר מדרגה או חיתוך,
אל תעלה את הנושא.

חיתוך רגיל למדרגה
מתבצע ללא תוספת תשלום.

אם הלקוח שואל מה זה CNC,
הסבר שזה חיתוך או עיבוד
באמצעות מכונה ממוחשבת
לצורות מיוחדות ומורכבות.

חיתוך CNC דורש בדיקת מחיר נפרדת.

אל תמציא מחיר לחיתוך CNC.

אם לא ברור איזה חיתוך נדרש,
אפשר לבקש תמונה או תיאור נוסף.

אל תחייב את הלקוח לשלוח תמונה.

מחירים

אסור לך להמציא מחירים.

אסור לך לחשב מחיר בעצמך.

מחירים מגיעים רק ממנגנון
התמחור של המערכת.

אל תחשוף ללקוח עלויות פנימיות.

אל תחשוף נוסחאות תמחור.

אל תציע מחיר לתצורה
שהלקוח לא בחר או אישר.

אם חסר מידע,
שאל רק על הפרט החשוב הבא.

מקרים מורכבים

דלתות זכוכית ומעקות
דורשים בדיקה של בעל העסק.

גם חיתוך CNC ועבודה מיוחדת
דורשים בדיקה.

אל תמציא פתרון הנדסי.

אל תבטיח שהעברת פרטים
לבעל העסק אם לא ביצעת העברה בפועל.

אל תבטיח שתיאמת מדידה
אם לא בוצע תיאום בפועל.

חשוב מאוד

בכל תשובה התייחס להודעה האחרונה
ולהקשר של כל השיחה.

אל תחזור על שאלות שכבר נענו.

אל תחזור על הסברים שכבר נתת.

אל תנסה להישמע חכם מדי.

תהיה ברור, נעים, מקצועי וענייני.

תן ללקוח להרגיש שהוא מדבר
עם בעל מקצוע שמבין אותו.
"""


def conversation_facts(history, analysis, details):
    return {
        "customer_messages": [
            m["content"]
            for m in history
            if m["role"] == "user"
        ],
        "assistant_messages_already_sent": [
            m["content"]
            for m in history
            if m["role"] == "assistant"
        ],
        "customer_need": analysis.get("need"),
        "customer_priority": analysis.get("priority"),
        "product": analysis.get("product"),
        "shower_details": details,
    }


def draft_sales_reply(history, analysis, details):
    context = {
        "stage": analysis.get("stage"),
        "need": analysis.get("need"),
        "priority": analysis.get("priority"),
        "quote_requested": analysis.get("quote_requested"),
        "solution_agreed": analysis.get("solution_agreed"),
        "product": analysis.get("product"),
        "known_shower_details": details,
        "conversation_facts": conversation_facts(
            history,
            analysis,
            details,
        ),
    }

    response = client.responses.create(
        model="gpt-5-mini",
        instructions=(
            SALES_INSTRUCTIONS
            + "\nמידע פנימי על מצב השיחה, לא להציג ללקוח: "
            + json.dumps(context, ensure_ascii=False)
        ),
        input=history,
    )

    first_draft = response.output_text.strip()

    try:
        edited = client.responses.create(
            model="gpt-5-mini",
            instructions="""
אתה עורך הודעות וואטסאפ של איש מכירות מקצועי.

החזר רק את ההודעה המתוקנת,
בלי הסברים ובלי כותרות.

קרא את כל היסטוריית השיחה
ואת טיוטת התשובה.

בדוק שהבוט לא שואל שוב
על מידע שהלקוח כבר נתן.

אם הלקוח אמר פינתי,
אל תשאל אם הוא פינתי.

אם נתן מידות,
אל תבקש אותן שוב.

אל תחזור על הסברים שכבר ניתנו,
כולל שיפועים, ניקוז, זכוכית 8 מ"מ
וניקוי, אלא אם הלקוח שאל שוב.

אל תסיק סוג דלת רק מהמידות.

אל תמליץ על הזזה אוטומטית
רק כי המקום קטן.

אל תטען שדלת הזזה
בהכרח קלה יותר לניקוי.

אל תטען שזכוכית 8 מ"מ
מקלה על ניקוי.

אל תבטיח אטימות,
אחריות על יציאת מים,
ציפוי נגד אבנית
או בדיקת שיפועים במדידה.

אם הלקוח מתלבט,
עזור לו עם הסבר קצר
ושאלה אחת שמקדמת את השיחה.

אם אין תמונה,
אפשר להמשיך כרגיל.

השתמש בעברית פשוטה,
חמה, מקצועית וטבעית.

כתוב בדרך כלל משפט או שניים
ושאלה אחת לכל היותר.

בלי מקפים מיותרים,
בלי נקודתיים,
בלי רשימות
ובלי מונחים מסובכים.

אל תמציא מחיר,
מוצר, התחייבות או עובדה.
""",
            input=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "conversation": history,
                            "known_facts": conversation_facts(
                                history,
                                analysis,
                                details,
                            ),
                            "draft_to_edit": first_draft,
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
        )

        return edited.output_text.strip() or first_draft

    except Exception:
        app.logger.exception("Sales reply editorial pass failed")
        return first_draft


def format_quote(price):
    return (
        f"לפי הפרטים שסיכמנו, המחיר המשוער למקלחון הוא "
        f"₪{price:,.0f} לפני מע״מ, "
        "כולל מדידה, הובלה והתקנה. "
        "המחיר הסופי כפוף לאימות המידות "
        "והפרטים במדידה. "
        "אם זה מתאים לך, נוכל להתקדם לתיאום מדידה."
    )


def missing_quote_details(details):
    required = (
        "configuration",
        "width_cm",
        "height_cm",
        "glass_type",
        "finish",
    )

    missing = [
        field
        for field in required
        if details.get(field) is None
    ]

    configuration = details.get("configuration")

    if (
        configuration
        and configuration.startswith("פינתי")
        and details.get("second_width_cm") is None
    ):
        missing.append("second_width_cm")

    if configuration in SHOWER_BOM:
        count = handle_slots(configuration)

        if count and not isinstance(details.get("handles"), list):
            missing.append("handles")

    return missing


def process_customer_message(customer_phone, customer_message):
    with state_lock:
        history = conversation_history.setdefault(
            customer_phone,
            [],
        )

        history.append(
            {
                "role": "user",
                "content": customer_message,
            }
        )

        if len(history) > 50:
            del history[:-50]

        snapshot = list(history)

    try:
        analysis = understand_customer_need(snapshot)

    except Exception:
        app.logger.exception("Customer need analysis failed")

        analysis = {
            "stage": "discovery",
            "quote_requested": False,
            "product": None,
            "solution_agreed": False,
        }

    product = analysis.get("product")
    details = {}

    if product == "מקלחון":
        try:
            details = extract_shower_details(snapshot)

        except Exception:
            app.logger.exception("Shower detail extraction failed")

    with state_lock:
        customer_sales_state[customer_phone] = analysis

    try:
        reply = draft_sales_reply(
            snapshot,
            analysis,
            details,
        )

    except Exception:
        app.logger.exception("Sales response failed")

        reply = (
            "אשמח לעזור לך לבחור פתרון מתאים. "
            "מה הכי חשוב לך במוצר?"
        )

    if (
        SEND_QUOTES
        and product == "מקלחון"
        and analysis.get("quote_requested") is True
        and analysis.get("solution_agreed") is True
        and not analysis.get("needs_human")
        and not analysis.get("cnc_possible")
        and details.get("cut_type") != "cnc"
        and not missing_quote_details(details)
    ):
        price = calculate_shower_price(
            configuration=details.get("configuration"),
            width_cm=details.get("width_cm"),
            second_width_cm=details.get("second_width_cm"),
            height_cm=details.get("height_cm"),
            glass_type=details.get("glass_type"),
            finish=details.get("finish"),
            handles=details.get("handles"),
        )

        if price is not None:
            reply = format_quote(price)

            app.logger.info(
                "Approved quote calculation succeeded"
            )

        else:
            app.logger.info(
                "Quote needs manual review"
            )

    with state_lock:
        conversation_history[customer_phone].append(
            {
                "role": "assistant",
                "content": reply,
            }
        )

    return reply


@app.route("/", methods=["GET"])
def home():
    return "Dream of Glass WhatsApp AI is running", 200


@app.route("/health", methods=["GET"])
def health():
    return {
        "status": "ok",
        "quotes_enabled": SEND_QUOTES,
    }, 200


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge or "", 200

        return "Verification failed", 403

    data = request.get_json(silent=True) or {}

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                for message in value.get("messages", []):
                    if message.get("type") != "text":
                        continue

                    phone = message.get("from")
                    body = (
                        (message.get("text") or {})
                        .get("body", "")
                        .strip()
                    )
                    message_id = message.get("id")

                    if not phone or not body:
                        continue

                    if not WHATSAPP_TOKEN:
                        app.logger.error(
                            "Missing WhatsApp token"
                        )
                        continue

                    with state_lock:
                        if (
                            message_id
                            and message_id in processed_messages
                        ):
                            continue

                        if message_id:
                            processed_messages.add(message_id)

                            if len(processed_messages) > 10000:
                                processed_messages.clear()

                    reply = process_customer_message(
                        phone,
                        body,
                    )

                    send_whatsapp_message(
                        phone,
                        reply,
                    )

    except Exception:
        app.logger.exception("Webhook processing error")

    return "EVENT_RECEIVED", 200


def send_whatsapp_message(customer_phone, message_text):
    url = (
        f"https://graph.facebook.com/v26.0/"
        f"{PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": customer_phone,
        "type": "text",
        "text": {
            "body": message_text,
        },
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=15,
    )

    app.logger.info(
        "WhatsApp send status: %s",
        response.status_code,
    )

    response.raise_for_status()


@app.route("/privacy", methods=["GET"])
def privacy():
    return (
        "<h1>Privacy Policy</h1>"
        "<p>Contact: dream.of.glass2@gmail.com</p>"
    ), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(
        host="0.0.0.0",
        port=port,
    )
