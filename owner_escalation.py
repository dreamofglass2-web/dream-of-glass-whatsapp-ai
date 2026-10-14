"""Conservative escalation triggers; no model call or message delivery."""
import re


def simple_name_correction(text):
    """A factual name reminder is recoverable; combined complaints are not exempt."""
    return bool(re.fullmatch(
        r'\s*(?:כבר אמרתי לך(?: בהתחלה| קודם)?\s+)?(?:קוראים לי|שמי|השם שלי(?: הוא)?)\s+'
        r'[א-תA-Za-z]{2,30}(?:\s+[א-תA-Za-z]{2,30})?\s*[.!?]*\s*',str(text or '')))


def escalation_reason(customer, data=None, reply=None, history=()):
    text = str(customer or '')
    if not simple_name_correction(text) and re.search(r'נציג אנושי|לדבר עם בן אדם|רוצה לדבר עם (?:אלירן|בעל העסק)|אתה לא מבין|לא הבנת אותי|חוזר על עצמך|אתה לא עונה לעניין|את לא עונה לעניין|לא עונה לי לעניין|כבר אמרתי לך', text):
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



def planning_clarification(customer, prior, history):
    """Recover missing ordinary planning detail with one question, not an unsafe answer."""
    text=str(customer or '')
    if not text.strip() or len(text)>350 or escalation_reason(text):
        return None
    previous=next((str(m.get('content') or '') for m in reversed(history) if m.get('role')=='assistant'),'')
    # Interpret short answers in relation to the question we actually asked.
    readiness_question=bool(re.search(r'ריצוף|שיפוץ',previous) and re.search(r'גמור|מוכן|עובדים|הסתיים',previous))
    readiness_answer=bool(re.fullmatch(r'\s*(?:כן|לא|עוד לא|עדיין לא|גמור|מוכן|עוד כמה ימים יהיה מוכן|(?:עוד )?(?:כמה|\d+) ימים(?: יהיה מוכן)?|מחר(?: יהיה מוכן)?|בשבוע הבא(?: יהיה מוכן)?)\s*[.!?]*\s*',text))
    shower_context=('מקלחון' in str(prior.get('product') or '') or any(m.get('role')=='user' and 'מקלחון' in str(m.get('content') or '') for m in history))
    if shower_context and readiness_question and readiness_answer and int(prior.get('planning_clarification_count') or 0)<2:
        next_question=('איזה סוג זכוכית תרצי למקלחון?' if not prior.get('glass_type')
                       else 'איזה גוון פרזול תרצי?' if not prior.get('finish')
                       else 'אפשר בינתיים להמשיך בבחירת הפתיחה הנוחה לך.')
        return 'אפשר להמשיך בתכנון ובבחירות בזמן השיפוץ. את המדידה הסופית עושים אחרי אישור ההצעה וסיום הריצוף. ' + next_question
    if re.search(r'מחיר|כמה|אחריות|ביטול|תשלומ|אשראי|הנחה|תקן|בטיח|אטימות|עיגון|קידוח|לשבור|חשמל|קיר גבס|מחר|לתאם|תתקשר|נציג|אלירן',text):
        return None
    users=' '.join(str(m.get('content') or '') for m in history if m.get('role')=='user')
    if 'מקלחון' not in str(prior.get('product') or '') and 'מקלחון' not in users:
        return None
    if not re.search(r'קודם|צורה|דלת|פתיח|נוח|מידות|מקום|תמונה|דומה|אסלה|כיור|ארון|לא יודע|לא מדדתי',text):
        return None
    if int(prior.get('planning_clarification_count') or 0)>=2:
        return None
    if re.search(r'קודם|צורה',text):
        return 'מה היה שונה במקלחון הקודם, המבנה שלו או הדרך שבה הדלת נפתחה?'
    if re.search(r'תמונה|דומה',text):
        return 'התמונה יכולה לעזור להבין את הכיוון, אבל לא לקבוע מידות. מה ממנה היית רוצה שיהיה גם אצלך?'
    if re.search(r'לא מדדתי|מידות',text):
        return 'אפשר להתחיל מהתכנון גם בלי מידות מדויקות. מה היית רוצה לשפר במקלחון?'
    return 'כדי להבין מה יתאים לך, תוכלי לתאר איך היית רוצה להיכנס למקלחון ומה מפריע כרגע?'


def planning_explanation(customer, prior, history):
    """Explain a previously discussed folding mechanism without certifying site fit."""
    text=str(customer or '')
    if not text.strip() or len(text)>350 or escalation_reason(text):
        return None
    if re.search(r'מחיר|כמה|אחריות|ביטול|תשלומ|אשראי|הנחה|תקן|בטיח|אטימות|עיגון|קידוח|לשבור|חשמל|קיר גבס|לתאם|תתקשר|נציג|אלירן',text):
        return None
    if not re.search(r'איך.{0,35}(?:בנוי|בנו[יי]|נפתח|יפתח|פותח|אכנס|נכנס|סוגר)|תסביר.{0,25}(?:מבנה|פתיח|קיפול)|תגיד.{0,25}(?:בנוי|מבנה)',text):
        return None
    recent=' '.join(str(m.get('content') or '') for m in history[-12:])
    if 'מקלחון' not in str(prior.get('product') or '') and 'מקלחון' not in recent:
        return None
    if not re.search(r'מתקפל|מתקפלות|מתקפלת|הרמוניקה',recent):
        return None
    answer=('בדלת מתקפלת יש שני לוחות זכוכית שמתקפלים זה אל זה, במקום שדלת שלמה תיפתח בקשת רחבה. '
            'פותחים את הקיפול כדי להיכנס ופורשים את הלוחות כדי לסגור. ')
    if re.search(r'אסלה|כיור|ארון',recent):
        answer+='המיקום ליד הכלים צריך להשאיר מקום גם לקיפול וגם לכניסה. '
    answer+='זה הסבר על מנגנון הפתיחה, ואת החלוקה וכיוון הקיפול שמתאימים לחדר נבדוק בשטח.'
    return answer
