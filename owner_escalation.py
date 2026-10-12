"""Conservative escalation triggers; no model call or message delivery."""
import re


def escalation_reason(customer, data=None, reply=None, history=()):
    text = str(customer or '')
    if re.search(r'נציג אנושי|לדבר עם בן אדם|רוצה לדבר עם (?:אלירן|בעל העסק)|אתה לא מבין|לא הבנת אותי|חוזר על עצמך|כבר אמרתי לך', text):
        return 'הלקוח ביקש אדם או דיווח שהשיחה אינה מתקדמת'
    if re.search(r'מעקה|קונסטרוקצי|חישוב עומס|אישור מהנדס|\bCNC\b|חיתוך מיוחד|זכוכית קונסטרוקטיבית', text, re.I):
        return 'נדרשת בדיקה מקצועית של בעל העסק'
    if data is None:
        return None
    if data.get('needs_human') is True:
        return 'יוסי סימן שאין לו תשובה בטוחה'
    answer = str(reply or '').strip()
    if not answer:
        return 'יוסי לא הפיק תשובה תקינה'
    if re.search(r'אין לי (?:מידע|תשובה|נתונים|תנאי אחריות).*מאומת|לא יודע|איני יודע|צריך לבדוק את (?:תנאי|הכיסוי)|אין לי כרגע תנאי אחריות', answer):
        return 'חסר מידע מאומת לתשובת הלקוח'
    previous = [str(m.get('content') or '').strip() for m in history if m.get('role') == 'assistant']
    if len(previous) >= 2 and answer == previous[-1] == previous[-2]:
        return 'השיחה נכנסה לחזרה ללא התקדמות'
    return None
