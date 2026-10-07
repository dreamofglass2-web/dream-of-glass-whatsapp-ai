import os
import logging

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
        "זווית זכוכית זכוכית": 4,
        "אטם בלון": 2,
        "מגב רצפה": 1,
        "מגנט פינתי": 1,
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
    "קבוע + דלת": 600,
    "2 קבועים + 2 דלתות": 1200,
}
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
@app.route("/", methods=["GET"])
def home():
    return "Dream of Glass WhatsApp AI is running", 200


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
