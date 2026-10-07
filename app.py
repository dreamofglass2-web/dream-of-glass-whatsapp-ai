import os
import logging
import json

import requests
from openai import OpenAI
from flask import Flask, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "dream_of_glass_verify")
WHATSAPP_TOKEN = os.environ.get("whatsapp_token", "")
PHONE_NUMBER_ID = "1280310741842089"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)
conversation_history = {}
GLASS_COSTS = {
    "שקופה": 150,
    "אקסטרה קליר": 220,
    "אנטיסן אפור": 220,
    "פיפיטה": 220,
    "חלבי": 220,
    "אסיד": 220,
    "ברונזה": 240,
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
def calculate_hardware_cost(
    configuration,
    finish="ניקל",
    handle_type=None,
):
    bom = SHOWER_BOM.get(configuration)

    if not bom:
        return None

    multiplier = FINISH_MULTIPLIERS.get(finish)

    if multiplier is None:
        return None

    total = 0

    for item, quantity in bom.items():
        if item in ("ידית כפתור", "ידית ראשית"):
            if item == "ידית ראשית" and handle_type is None:
                return None

            if item == "ידית כפתור" and handle_type is None:
                return None

            if handle_type not in ("ידית כפתור", "ידית מגבת"):
                return None

            if item == "ידית ראשית":
                total += HARDWARE_COSTS[handle_type] * quantity
            else:
                total += HARDWARE_COSTS[handle_type] * quantity

            continue

        unit_cost = HARDWARE_COSTS.get(item)

        if unit_cost is None:
            return None

        total += unit_cost * quantity

    return round(total * multiplier, 2)


def calculate_shower_price(
    configuration,
    width_cm,
    height_cm,
    glass_type="none",
    finish="none",
    second_width_cm=None,
    handle_type=None,
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
    except (TypeError, ValueError):
        return None

    if width <= 0 or height <= 0 or height > 220:
        return None

    if configuration.startswith("פינתי"):
        if second_width is None:
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

    hardware_cost = calculate_hardware_cost(
        configuration,
        finish,
        handle_type,
    )

    if hardware_cost is None:
        return None

    glass_area = glass_width * height / 10000
    glass_cost = glass_area * GLASS_COSTS[glass_type]

    price_before_vat = glass_cost + hardware_cost + 1500 + 150

    if price_before_vat < 2000:
        return None

    return int((price_before_vat + 5) // 10 * 10)


@app.route("/test-price", methods=["GET"])
def test_price():
    price = calculate_shower_price(
        configuration="פינתי 2 קבועים + 2 דלתות",
        width_cm=90,
        second_width_cm=90,
        height_cm=200,
        glass_type="שקופה",
        finish="ניקל",
        handle_type="ידית כפתור",
    )

    return {
        "configuration": "פינתי 2 קבועים + 2 דלתות",
        "price_before_vat": price,
        "status": "internal_test_only",
    }, 200
@app.route("/", methods=["GET"])
def home():
    return "Dream of Glass WhatsApp AI is running", 200
@app.route("/test-extraction", methods=["GET"])
def test_extraction():
    test_history = [
        {
            "role": "user",
            "content": (
                "אני רוצה מקלחון פינתי 150 על 150, "
                "גובה 200, שני קבועים ושתי דלתות, "
                "זכוכית שקופה, פרזול ניקל "
                "וידיות כפתור."
                        ),
        }
    ]

    details = extract_shower_details(test_history)

    required_fields = [
        "configuration",
        "width_cm",
        "height_cm",
        "glass_type",
        "finish",
    ]

    missing = [
        field for field in required_fields
        if details.get(field) is None
    ]

    if missing:
        price = None
        status = "missing_details"
    else:
        price = calculate_shower_price(
            configuration=details["configuration"],
            width_cm=details["width_cm"],
            second_width_cm=details.get("second_width_cm"),
            height_cm=details["height_cm"],
            glass_type=details["glass_type"],
            finish=details["finish"],
            handle_type=details.get("handle_type"),
        )

        status = "calculated" if price is not None else "needs_review"

    return {
        "details": details,
        "price_before_vat": price,
        "status": status,
    }, 200


def extract_shower_details(history):
    response = client.responses.create(
        model="gpt-5-mini",
        instructions=(
            "חלץ מתוך השיחה פרטים על המקלחון. "
            "Return a valid json object only. "
            "אל תנחש פרטים חסרים. השתמש ב-null. "
            "סוג התצורה חייב להתאים בדיוק לאחת האפשרויות הבאות: "
            + ", ".join(SHOWER_BOM.keys())
            + ". סוג זכוכית חייב להתאים לאחת האפשרויות: "
            + ", ".join(GLASS_COSTS.keys())
            + ". גוון פרזול חייב להתאים לאחת האפשרויות: "
            + ", ".join(FINISH_MULTIPLIERS.keys())
            + ". המידות הן בסנטימטרים. "
            "החזר את השדות: "
            "configuration, width_cm, second_width_cm, "
            "height_cm, glass_type, finish, handle_type. "
            "handle_type יכול להיות רק ידית כפתור, ידית מגבת או null. "
            "אם הלקוח לא בחר במפורש, החזר null."
        ),
        input=[
            {
                "role": "system",
                "content": "Return a valid json object only.",
            },
            *history,
        ],
        text={"format": {"type": "json_object"}},
    )

    return json.loads(response.output_text)


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge or "", 200

        return "Verification failed", 403
    app.logger.info(
        "WEBHOOK POST RECEIVED content_type=%s content_length=%s",
        request.content_type,
        request.content_length,
    )

    data = request.get_json(silent=True) or {}

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                for message in value.get("messages", []):
                    if message.get("type") != "text":
                        continue

                    customer_phone = message.get("from")
                    if not customer_phone:
                        continue

                    customer_message = (
                        message.get("text", {}).get("body", "").strip()
                    )
                    if not customer_message:
                        continue

                    if not WHATSAPP_TOKEN:
                        app.logger.error("Missing WhatsApp token")
                        continue
                    history = conversation_history.setdefault(
                        customer_phone, []
                    )

                    history.append(
                        {
                            "role": "user",
                            "content": customer_message,
                        }
                    )
                    ai_response = client.responses.create(
                        model="gpt-5-mini",
                        instructions=(
                            "אתה נציג המכירות של העסק חלומות מזכוכית בוואטסאפ. "
                            "דבר בעברית טבעית, שירותית, מקצועית וקצרה. "
                            "אל תמציא מידע, מחירים, מידות, מוצרים או מפרטים. "
                            "זכור את כל הפרטים שהלקוח כבר מסר ואל תשאל אותם שוב. "
                            "שאל רק שאלה אחת בכל הודעה. "
                            "השתמש בפסיקים ובמשפטים טבעיים. "
                            "אל תשתמש במקפים כמפרידים בין חלקי משפט. "
                            "אל תמליץ על תצורה, מוצר או פתרון טכני אלא אם ההמלצה "
                            "מוגדרת במפורש בהוראות שקיבלת. "
                            "אם אינך בטוח מה מתאים ללקוח, שאל שאלה נוספת או העבר לבעל העסק. "

                            "אם הלקוח מעוניין במקלחון, אסוף לפי הצורך: "
                            "סוג המקלחון: פינתי, חזית או הזזה; "
                            "מידות; גובה; תצורה כגון קבוע ודלת או שני קבועים ושתי דלתות; "
                            "סוג זכוכית; וגוון פרזול. "
                            "אל תשאל פרט שכבר ניתן בשיחה. "

                            "אם הלקוח לא יודע לבחור תצורה או סוג, עזור לו בקצרה "
                            "ואל תעמיס עליו שאלות. "
                            "אם תמונה של המקום תעזור להבין את העבודה, בקש תמונה. "

                            "העבודה מתבצעת עם זכוכית מחוסמת ופרזול איכותי. "
                            "במקלחונים סטנדרטיים הזכוכית היא 8 מ״מ. "

                            "כרגע אסור לך לתת או לחשב מחיר בעצמך. "
                            "אם הלקוח מבקש מחיר, אסוף קודם את הפרטים החסרים. "
                            "מקרים חריגים, מורכבים או כאלה שאינך בטוח בהם "
                            "יש להעביר לבעל העסק ולא לנחש."
                        ),
                        input=history,
                    )
                    try:
                        details = extract_shower_details(history)

                        price = calculate_shower_price(
                            configuration=details.get("configuration"),
                            width_cm=details.get("width_cm"),
                            second_width_cm=details.get("second_width_cm"),
                            height_cm=details.get("height_cm"),
                            glass_type=details.get("glass_type"),
                            finish=details.get("finish"),
                            handle_type=details.get("handle_type"),
                        )

                        app.logger.info(
                            "Internal pricing status: %s",
                            "calculated" if price is not None else "not_ready",
                        )

                    except Exception:
                        app.logger.exception(
                            "Internal pricing check failed"
                        )
                    
                    reply_text = ai_response.output_text
                    history.append(
                        {
                            "role": "assistant",
                            "content": reply_text,
                        }
                    )

                    send_whatsapp_message(
                        customer_phone,
                        reply_text,
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
        "text": {"body": message_text},
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
    print("META RESPONSE:", response.status_code, response.text, flush=True)
    response.raise_for_status()


@app.route("/privacy", methods=["GET"])
def privacy():
    return (
        "<h1>Privacy Policy</h1>"
        "<p>Contact: dream.of.glass2@gmail.com</p>"
    ), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
