import os
from flask import Flask, request

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "dream_of_glass_verify")


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
            return challenge, 200

        return "Verification failed", 403

    data = request.get_json(silent=True)
    print(data)

    return "EVENT_RECEIVED", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
@app.route("/privacy")
def privacy():
    return """
    <html>
    <head>
        <title>Privacy Policy - Dream of Glass</title>
    </head>
    <body>
        <h1>Privacy Policy</h1>
        <p>Dream of Glass uses customer information only for responding to inquiries, providing quotations, coordinating measurements, installations, and customer service.</p>
        <p>Information may include name, phone number, messages, photos, measurements, and details voluntarily provided by customers through WhatsApp.</p>
        <p>We do not sell customer personal information.</p>
        <p>Information is used only as necessary to provide our services and operate our customer communication system.</p>
        <p>Customers may contact Dream of Glass to request information regarding their personal data or request its deletion.</p>
        <p>Contact: dream.of.glass2@gmail.com</p>
    </body>
    </html>
    """, 200
