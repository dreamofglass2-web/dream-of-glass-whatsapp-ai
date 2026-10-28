"""Separate generated lead-form question labels from customer action requests."""
import re

POLICY = ('הודעת טופס היא מסירת פרטים לצורך בירור צרכים. שאלות הטופס הן תוויות, לא בקשות של הלקוח. '
          'התשובה כן, אשלח בוואטסאפ מתייחסת לחומרי הפרויקט שהלקוח ישלח אלינו; היא אינה בקשה לתמונות מהקטלוג. '
          'השתמש בשם, בעיר, בסוג העבודה ובהעדפות שכבר נמסרו בלי לשאול עליהם שוב. '
          'התחל בהכרה קצרה בפנייה ובשאלה רלוונטית אחת על פרט חסר. '
          'אל תשלח דוגמאות או תכתוב שמצורפות תמונות בלי בקשה ממשית של הלקוח לראות אותן.')


def is_form_payload(text):
    text=str(text or '')
    return bool(re.search(r'השלמתי\s+את\s+הטופס|(?:completed|filled out)\s+your\s+form',text,re.I)
                and re.search(r'(?:Full name|שם מלא)\s*:',text,re.I)
                and re.search(r'(?:Phone number|מספר טלפון)\s*:',text,re.I))


def request_text(text):
    """Retain real free text and field answers; form-upload labels never request media.

    The complete original form remains in conversation/model history as facts.
    This view is used only for deterministic action/intent detection.
    """
    text=str(text or '')
    if not is_form_payload(text):
        return text
    result=[]
    for line in text.splitlines():
        field=re.match(r'^\s*([^:\n]{1,220}):\s*(.*)$',line)
        if not field:
            result.append(line)
            continue
        label,value=field.groups()
        label=label.replace('_',' ')
        if re.search(r'יש\s+לכם|יש\s+לך|(?:do you|have you)',label,re.I) and re.search(r'תמונ|תוכני|מידות|photos?|pictures?|plans?',label,re.I):
            continue
        result.append(value)
    return '\n'.join(result)
