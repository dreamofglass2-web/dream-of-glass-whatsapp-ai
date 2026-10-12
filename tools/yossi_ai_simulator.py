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
  [
    "hello",
    [
      "היי",
      "רוצה להתייעץ על מקלחון",
      "לא יודע איזה סוג מתאים",
      "זה לחדר רחצה קטן"
    ]
  ],
  [
    "price_only",
    [
      "כמה עולה מקלחון?",
      "משהו רגיל",
      "נראה לי פינתי",
      "אני משווה מחירים"
    ]
  ],
  [
    "full_quote",
    [
      "רוצה פינתי 100 על 100 שתי דלתות גובה 200 זכוכית שקופה פרזול שחור. כמה עולה?",
      "דלתות ישר על הקירות",
      "ידיות כפתור",
      "כולל התקנה ומע״מ?"
    ]
  ],
  [
    "objection",
    [
      "אפשר הצעה?",
      "מקלחון פינתי מטר על מטר",
      "קיבלתי הצעה זולה יותר",
      "הוא אומר שזה אותו מפרט",
      "אז למה לבחור בכם?"
    ]
  ],
  [
    "closing",
    [
      "שלום אני רוצה מקלחון",
      "פינתי מטר על מטר",
      "גובה 200 שתי דלתות",
      "שקוף ופרזול שחור, אפשר מחיר?",
      "איך ממשיכים?",
      "אני מאשר, הריצוף הסתיים"
    ]
  ],
  [
    "renovation",
    [
      "אנחנו לפני ריצוף",
      "אין לי מידות כרגע",
      "רק רוצה להבין אפשרויות",
      "מתי מודדים?"
    ]
  ],
  [
    "call_tomorrow",
    [
      "היי תתקשרו אליי מחר",
      "בשעה 10",
      "תודה"
    ]
  ],
  [
    "call_unspecified",
    [
      "אני מעדיף לדבר עם אלירן",
      "מחר יהיה טוב",
      "בערב",
      "תודה"
    ]
  ],
  [
    "corner_sliding",
    [
      "צריך מקלחון חדש",
      "פינתי",
      "אני רוצה דלתות הזזה",
      "בערך 90 על 90",
      "כמה עולה?",
      "מי נותן לי מחיר?"
    ]
  ],
  [
    "confused",
    [
      "צריך משהו זכוכית לאמבטיה",
      "לא הבנתי מה זאת תצורה",
      "יש שני קירות בפינה",
      "אני לא יודע מה ההבדל"
    ]
  ],
  [
    "competitor_exit",
    [
      "אפשר הצעה למקלחון",
      "פינתי",
      "עזוב החלטתי ללכת עם ספק אחר",
      "תודה"
    ]
  ],
  [
    "competitor_proof",
    [
      "אמרו לי שאתם יקרים",
      "יש לי הצעה אחרת",
      "הוא מציע אחריות דומה",
      "אתה יכול להבטיח שאתם טובים יותר?"
    ]
  ],
  [
    "warranty",
    [
      "איזו אחריות על המקלחונים?",
      "ומה אם יש תקלה?",
      "מפחד שלא יהיה שירות אחרי התשלום"
    ]
  ],
  [
    "finish",
    [
      "צריך מקלחון",
      "פינתי",
      "איזה סוגי פרזול יש?",
      "אני אוהב גוון בהיר"
    ]
  ],
  [
    "mirror",
    [
      "כמה עולה מראה?",
      "לחדר רחצה",
      "רוחב מטר גובה 80",
      "עם תאורה",
      "ואם בלי תאורה?"
    ]
  ],
  [
    "kitchen",
    [
      "עושים חיפוי זכוכית למטבח?",
      "מאחורי הכיריים",
      "עוד לא מדדתי",
      "אפשר מחיר בלי מידות?"
    ]
  ],
  [
    "partition",
    [
      "מחיצת זכוכית למשרד",
      "חלל קטן",
      "חשובה פרטיות",
      "מה כדאי?"
    ]
  ],
  [
    "out_of_area",
    [
      "מגיעים לחיפה?",
      "אני צריך מקלחון",
      "אם לא אז תגיד"
    ]
  ],
  [
    "greeting_only",
    [
      "שלום",
      "יש לי שאלה",
      "עושים גם דלתות זכוכית?",
      "עוד אין מידות"
    ]
  ],
  [
    "correction",
    [
      "היי צריך מקלחון",
      "בעצם חזיתי לא פינתי",
      "אין לי מדידות",
      "אפשר לשלוח בהמשך"
    ]
  ],
  [
    "unreadable_media",
    [
      "מחפש מקלחון",
      "[נשלחה תמונה שלא נותחה]",
      "רק רציתי לדעת אם אפשר משהו כזה"
    ]
  ],
  [
    "identity",
    [
      "מי אתה?",
      "אתה בן אדם או בוט?",
      "אפשר הצעה?",
      "מקלחון"
    ]
  ],
  [
    "no_pressure",
    [
      "אני רק מתעניין",
      "לא רוצה שתתקשרו אליי",
      "רוצה רק לדעת מה חשוב לבחור",
      "תודה"
    ]
  ],
  [
    "meta_partial",
    [
      "שלום השארתי פרטים בפייסבוק",
      "כן עדיין מתעניין",
      "אין לי מידות"
    ]
  ],
  [
    "meta_full",
    [
      "היי בקשר לפנייה שמילאתי",
      "יש לי שאלה על האחריות",
      "מה כלול?"
    ]
  ],
  [
    "meta_new_questions",
    [
      "חזרתי מהטופס",
      "כן מדובר בזכוכית למשרד",
      "מה האפשרויות?",
      "עוד לא החלטנו"
    ]
  ]
]

FORM_CONTEXT = {
  "meta_partial": {
    "l1": {
      "source": "meta_instant_form",
      "fields": {
        "full_name": [
          "ליאור"
        ],
        "phone_number": [
          "0501234567"
        ],
        "אילו_עבודות_אתם_מחפשים?": [
          "מקלחון"
        ]
      }
    }
  },
  "meta_full": {
    "l2": {
      "source": "meta_instant_form",
      "fields": {
        "full_name": [
          "רוני"
        ],
        "city": [
          "יבנה"
        ],
        "אילו_עבודות_אתם_מחפשים?": [
          "מקלחון"
        ],
        "מה_הכי_חשוב_לכם_בפרויקט?": [
          "איכות ועמידות"
        ]
      }
    }
  },
  "meta_new_questions": {
    "l3": {
      "source": "meta_instant_form",
      "fields": {
        "phone_number": [
          "0501234567"
        ],
        "באיזה_חלל_תרצו_להשתמש_בזכוכית?": [
          "משרד"
        ],
        "חשוב_לנו": [
          "פרטיות"
        ]
      }
    }
  }
}

SCENARIOS += [
  ["plain_advice", ["היי", "אני מתעניין במקלחון 100/100", "סיימנו שיפוץ",
    "כן פינתי. מימין כיור ומשמאל אסלה", "יש רווח של 30 סמ",
    "לא יודע, צריך לראות, אני לא מבין בדברים האלה", "הם כבר מורכבים"]],
  ["joint_decision", ["מחפש מראה לחדר רחצה", "עגולה, 90 סנטימטר בלי תאורה",
    "חשוב לי שתהיה יפה וקלה לניקוי", "אני צריך להתייעץ עם אשתי"]],
  ["trust_after_service", ["רוצה מקלחון", "פינתי מטר על מטר",
    "בפעם הקודמת התקינו לי משהו לא טוב", "חשוב לי שיהיה למי לפנות אחרי ההתקנה",
    "אני עוד רוצה לחשוב"]],
]
selected_names = {s.strip() for s in os.getenv("YOSSI_TEST_SCENARIOS", "").split(",") if s.strip()}
if selected_names:
    unknown = selected_names - {name for name, _ in SCENARIOS}
    if unknown:
        raise SystemExit("Unknown synthetic scenarios: " + ", ".join(sorted(unknown)))
    SCENARIOS = [(name, turns) for name, turns in SCENARIOS if name in selected_names]

def main():
    memory, reports = {}, []
    out = Path('yossi_ai_test_report.json')
    def write_report(status='running'):
        calls = [c for row in reports for c in row.get('api_calls', [])]
        costs = [c.get('estimated_usd') for c in calls]
        estimate = round(sum(costs), 8) if costs and all(c is not None for c in costs) else None
        out.write_text(json.dumps({'model': yossi.MODEL, 'status': status,
            'estimated_usd': estimate, 'api_call_count': len(calls),
            'scenarios': reports}, ensure_ascii=False, indent=2), encoding='utf-8')
    max_calls = int(os.getenv('YOSSI_TEST_MAX_CALLS', '90'))
    max_budget = float(os.getenv('YOSSI_TEST_MAX_USD', '5'))
    spent_upper = 0.0
    call_count = 0
    real_create = yossi.client.responses.create
    def measured_create(**kwargs):
        nonlocal spent_upper, call_count
        if call_count >= max_calls or spent_upper >= max_budget:
            write_report('budget_stopped')
            raise RuntimeError('Synthetic AI test budget reached')
        call_count += 1
        response = real_create(**kwargs)
        metrics = yossi.api_usage_metrics(response)
        reports[-1].setdefault('api_calls', []).append(metrics)
        input_tokens, output_tokens = metrics['input_tokens'], metrics['output_tokens']
        if isinstance(input_tokens, int) and isinstance(output_tokens, int):
            spent_upper += (input_tokens * 12.5 + output_tokens * 50) / 1_000_000
        else:
            spent_upper = max_budget
        write_report()
        return response
    callbacks = {}
    def record_callback(phone, when=None):
        callbacks[phone] = when or 'ממתין לתיאום'
        return True
    def waiting_callback(phone):
        return callbacks.get(phone) == 'ממתין לתיאום'
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
    with patch.object(yossi.client.responses, "create", side_effect=measured_create), \
         patch.object(yossi, "load_conversation", side_effect=load), \
         patch.object(yossi, "save_conversation", side_effect=save), \
         patch.object(yossi, "reset_conversation_for_phone", side_effect=reset), \
         patch.object(yossi, "send_whatsapp", side_effect=send), \
         patch.object(yossi, "has_new_messages", return_value=False), \
         patch.object(yossi, "save_callback", side_effect=record_callback), \
         patch.object(yossi, "waiting_for_callback_time", side_effect=waiting_callback), \
         patch.object(yossi, "save_custom_quote_lead", return_value=True), \
         patch.object(yossi.time, "sleep", return_value=None):
        for scenario, turns in SCENARIOS:
            phone = "OFFLINE_AI_TEST_" + scenario
            if scenario in FORM_CONTEXT:
                memory[phone] = ([], {'meta_leads': FORM_CONTEXT[scenario]})
            for turn, customer in enumerate(turns, start=1):
                reports.append({"scenario": scenario, "turn": turn, "customer": customer, "reply": None})
                success = yossi.process_message(phone, customer)
                if not success or not reports[-1]["reply"]:
                    raise AssertionError("No reply for %s turn %s" % (scenario, turn))
                answer = reports[-1]["reply"]
                print(json.dumps(reports[-1], ensure_ascii=False), flush=True)
                write_report()
                if "הייתה תקלה רגעית" in answer:
                    write_report("failed")
                    raise AssertionError("AI request failed or budget reached; inspect synthetic transcript")
                if turn == 1 and scenario in ("full_quote", "closing"):
                    if not answer.startswith(("היי", "אהלן", "שלום")):
                        raise AssertionError("Missing warm greeting")
                if any(term in answer for term in ("הצעת המחיר נשלחה", "החשבונית נשלחה")):
                    raise AssertionError("Claimed to send an unsent document")

    write_report("completed")
    costs = [call.get("estimated_usd") for row in reports for call in row.get("api_calls", [])]
    total_cost = round(sum(costs), 8) if costs and all(c is not None for c in costs) else None
    out = Path("yossi_ai_test_report.json")
    write_report("completed")
    print('Callbacks:', len(callbacks))
    print("Completed", len(reports), "real-model turns across", len(SCENARIOS), "scenarios.")
    print("Report:", out)
    print("Review responses manually for tone, claims and sales quality before approval. Scripted customer turns are not adaptive.")


if __name__ == "__main__":
    main()
