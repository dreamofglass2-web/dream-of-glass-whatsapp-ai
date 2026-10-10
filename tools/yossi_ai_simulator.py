"""Opt-in real-model sales tests; NEVER contacts WhatsApp, Render Postgres or customers.

Usage (in a secure environment with OPENAI_API_KEY configured):
  RUN_LIVE_YOSSI_TESTS=1 python tools/yossi_ai_simulator.py
Requires explicit opt-in and existing API account; consumes paid model tokens.
"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

if os.getenv("RUN_LIVE_YOSSI_TESTS") != "1":
    raise SystemExit("Refusing to run without RUN_LIVE_YOSSI_TESTS=1")
if not os.getenv("OPENAI_API_KEY"):
    raise SystemExit("OPENAI_API_KEY must be set in the secure runtime; do not put it in source code")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as yossi


SCENARIOS = [
    ("first_quote", [
        "אהלן, אני צריך מקלחון פינתי 100 על 100, שתי דלתות שנפתחות, זכוכית שקופה ופרזול שחור. כמה עולה דבר כזה בערך? אני בודק בעוד מקומות.",
        "הדלתות ישר על הקירות, אין קבועים. גובה 200.",
        "ידיות רגילות, כפתור. כמה זה ייצא?",
        "זה יותר ממה שתכננתי. קיבלתי הצעה זולה ב-700 שקל.",
    ]),
    ("closing", [
        "אני רוצה מקלחון פינתי 100 על 100 שתי דלתות גובה 200 זכוכית שקופה פרזול שחור. כמה עולה?",
        "ישר לקירות. ידיות כפתור.",
        "נשמע סביר, איך סוגרים?",
        "אני מאשר את ההצעה, הריצוף כבר הסתיים.",
    ]),
    ("early_renovation", [
        "אנחנו בתחילת שיפוץ, רוצים מקלחון יפה, לא יודע עדיין מידות. מה כדאי?",
        "אני לא רוצה להזמין מודד עכשיו, עוד לא סיימנו ריצוף.",
    ]),
    ("competitor", [
        "יש לי הצעה אחרת ב-700 שקל פחות. למה כדאי לי אצלכם?",
        "אם הם עושים אותו מפרט, אתה יכול להבטיח לי שאתם יותר טובים?",
    ]),
]


def main():
    memory, reports = {}, []
    def load(phone):
        hist, ctx = memory.get(phone, ([], {}))
        return list(hist), dict(ctx)
    def save(phone, hist, ctx):
        memory[phone] = (list(hist), dict(ctx))
    def reset(phone):
        memory[phone] = ([], {})
        return True
    def send(phone, body=None, image_url=None, caption=None):
        if image_url:
            raise AssertionError("Unrequested media was sent during a simulation")
        reports[-1]["reply"] = body

    # Crucial: do not mock the real model. Only external customer I/O and persistence.
    with patch.object(yossi, "load_conversation", side_effect=load), \
         patch.object(yossi, "save_conversation", side_effect=save), \
         patch.object(yossi, "reset_conversation_for_phone", side_effect=reset), \
         patch.object(yossi, "send_whatsapp", side_effect=send), \
         patch.object(yossi, "has_new_messages", return_value=False), \
         patch.object(yossi, "save_callback", return_value=True), \
         patch.object(yossi.time, "sleep", return_value=None):
        for scenario, turns in SCENARIOS:
            phone = "OFFLINE_AI_TEST_" + scenario
            for turn, customer in enumerate(turns, start=1):
                reports.append({"scenario": scenario, "turn": turn, "customer": customer, "reply": None})
                success = yossi.process_message(phone, customer)
                if not success or not reports[-1]["reply"]:
                    raise AssertionError("No reply for %s turn %s" % (scenario, turn))
                answer = reports[-1]["reply"]
                if turn == 1 and scenario in ("first_quote", "closing"):
                    if not answer.startswith(("היי", "אהלן", "שלום")):
                        raise AssertionError("Missing warm greeting")
                if any(term in answer for term in ("הצעת המחיר נשלחה", "החשבונית נשלחה")):
                    raise AssertionError("Claimed to send an unsent document")

    out = Path("yossi_ai_test_report.json")
    out.write_text(json.dumps({"model": yossi.MODEL, "scenarios": reports}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Completed", len(reports), "real-model turns across", len(SCENARIOS), "scenarios.")
    print("Report:", out)
    print("Review responses manually for tone, claims and sales quality before approval.")


if __name__ == "__main__":
    main()
