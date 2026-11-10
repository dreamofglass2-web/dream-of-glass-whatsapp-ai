"""Separate generated lead-form question labels from customer action requests."""
import re

POLICY = ('הטופס הוא הודעה אוטומטית. אל תצטט את פרטיו ואל תשתמש בהם להמלצה. '
          'אם צורפה בקשה במילות הלקוח, ענה עליה אחרי ברכה קצרה. אחרת פתח: היי, מה קורה? איך אוכל לעזור? '
          'אל תציע דוגמאות או תמונות בלי בקשה אמיתית. את היתרון של המדידה וההתקנה בידי אלירן שמור לשלב ההצעה או להתנגדות.')


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


def concise_first_opening(reply, body, history, data, draft=None):
    """Open a plain form lead in the customer's own words."""
    if (not is_form_payload(body) or data.get('needs_human')
            or any(m.get('role') == 'user' or (m.get('role') == 'assistant'
                   and 'נוח לך שנמשיך כאן בוואטסאפ' not in str(m.get('content') or ''))
                   for m in history[:-1])):
        return reply
    for line in str(body).splitlines():
        line = line.strip()
        if not line:
            continue
        if re.fullmatch(r'(?:Full name|Phone number|City|שם מלא|מספר טלפון|עיר|מה הכי חשוב לכם בפרויקט\?|יש לכם תמונות / תוכניות / מידות של הפרויקט\?|באיזה שלב נמצא הפרויקט\?|אילו עבודות אתם מחפשים\?|מהו סוג הנכס שלכם\?)\s*:.*', line, re.I):
            continue
        if re.search(r'השלמתי את הטופס שלך|(?:completed|filled out) your form', line, re.I):
            continue
        return reply
    return 'היי, מה קורה? איך אוכל לעזור?'
