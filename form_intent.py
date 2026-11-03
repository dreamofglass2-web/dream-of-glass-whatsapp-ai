"""Separate generated lead-form question labels from customer action requests."""
import re

POLICY = ('הודעת טופס היא מסירת פרטים לצורך בירור צרכים. שאלות הטופס הן תוויות, לא בקשות של הלקוח. '
          'התשובה כן, אשלח בוואטסאפ מתייחסת לחומרי הפרויקט שהלקוח ישלח אלינו; היא אינה בקשה לתמונות מהקטלוג. '
          'השתמש בשם, בעיר, בסוג העבודה ובהעדפות שכבר נמסרו בלי לשאול עליהם שוב. '
          'המשפט האוטומטי ברצוני לדעת יותר על העסק אינו בקשה לסקירה על העסק. '
          'פתח בברכה אישית קצרה, היכרות בשם יוסי, התייחסות לפרטי הפרויקט ושאלה טבעית אחת. '
          'לדוגמה: היי חן, אני יוסי מחלומות מזכוכית. ראיתי שאתה מחפש מקלחון בראשון לציון. כבר יש לך כיוון לסגנון שתרצה, או שנבדוק יחד מה מתאים למקום? '
          'זו דוגמת סגנון בלבד; אין להעתיק שם, עיר או עובדות שלא נמסרו. '
          'בפתיחה אל תפרט על רמלה, מדידה, התקנה או קבלני משנה בלי שנשאלת, ואל תשאל על מקלחון קודם שלא הוזכר. '
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


def concise_first_opening(reply, body, history, data, draft=None):
    """Repair a sales monologue only for a first, plain shower form submission."""
    if (not is_form_payload(body) or any(m.get('role')=='assistant' for m in history[:-1])
            or data.get('needs_human') or data.get('quote_requested')
            or data.get('stage') not in ('discovery',None)):
        return reply
    fields={}
    for line in str(body).splitlines():
        line=line.strip()
        if not line:continue
        field=re.fullmatch(r'([^:\n]{1,220}):\s*(.*)',line)
        if field:
            label,value=field.groups();label=label.replace('_',' ').strip()
            if not re.fullmatch(r'Full name|Phone number|City|שם מלא|מספר טלפון|עיר|מה הכי חשוב לכם בפרויקט\?|יש לכם תמונות / תוכניות / מידות של הפרויקט\?|באיזה שלב נמצא הפרויקט\?|אילו עבודות אתם מחפשים\?|מהו סוג הנכס שלכם\?',label,re.I):return reply
            fields[label.lower()]=value.strip()
        elif not re.fullmatch(r'ה[יי]{1,2}[!. ]*\s*השלמתי את הטופס שלך,?\s*וברצוני לדעת יותר על העסק שלך[!. ]*',line):
            return reply
    product=fields.get('אילו עבודות אתם מחפשים?','')
    if product!='מקלחון':return reply
    original=str(draft or reply)
    if max(len(reply),len(original))<=230 and not re.search(r'מקלחון קודם|מקלחון הקודם|מה אהבת|אנחנו מרמלה|ללא קבלני משנה',original+' '+reply):return reply
    name=(fields.get('full name') or fields.get('שם מלא') or '').split()
    first=name[0] if name and re.fullmatch(r"[א-תA-Za-z'-]{2,24}",name[0]) else ''
    city=fields.get('city') or fields.get('עיר') or ''
    city=re.sub(r'[\"״׳\x27]','',city).strip()
    if city=='ראשלצ':city='ראשון לציון'
    location=' ב'+city if re.fullmatch(r'[א-ת -]{2,40}',city) else ''
    return ('היי'+(' '+first if first else '')+', אני יוסי מחלומות מזכוכית. '
            +'ראיתי שאתה מחפש מקלחון'+location+'. '
            +'כבר יש לך כיוון לסגנון שתרצה, או שנבדוק יחד מה מתאים למקום?')
