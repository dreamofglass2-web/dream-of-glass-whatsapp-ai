"""Owner-defined minimum opening width for recommending or quoting sliding doors."""
import math
MIN_SLIDING_WIDTH_CM=140
POLICY='מקלחון הזזה אפשר להציע ולתמחר רק ברוחב פתח של 140 ס״מ ומעלה. מתחת ל־140 לא להציע הזזה גם אם יש אסלה קרובה. לבקש צילום ומרווחים כדי לבחון פתרון אחר, בלי להבטיח מפתח כניסה או התאמת צירים. רוחב לא ידוע מחייב בירור לפני המלצה. 140 הוא סף כניסה לבדיקה ולא הבטחת התאמה. אם אין ללקוח תמונה, לא לבקש אותה שוב: להתחיל מתיאור מיקום האסלה ובהמשך לברר מרווח, שאלה אחת בכל פעם. תיאור אינו אישור התאמה מקצועית.'

def narrow_opening(specs):
    width=specs.get('width_cm')
    return type(width) in (int,float) and math.isfinite(width) and 0 < width < MIN_SLIDING_WIDTH_CM

def disallowed_slider(specs):
    return 'הזזה' in str(specs.get('configuration') or '') and narrow_opening(specs)

def clear_disallowed_slider(specs):
    result=dict(specs)
    if disallowed_slider(result):
        result.pop('configuration',None)
        result.pop('validated_quote',None)
        result['solution_agreed']=False
    return result

def sliding_limit_reply(specs):
    width=specs.get('width_cm')
    return (f'בפתח של {width:g} ס״מ לא אמליץ על הזזה; אצלנו בוחנים הזזה רק מ־140 ס״מ ומעלה, כדי לא לצמצם מדי את הכניסה. '
            'אפשר לשלוח צילום של הפתח והאסלה ולציין בערך כמה מרווח נשאר ביניהם? כך נבדוק פתרון פתיחה אחר.')


def no_customer_photo(text):
    import re
    return bool(re.search(r'אין\s+(?:לי\s+)?(?:כרגע\s+)?(?:תמונה|צילום)|לא\s+(?:יכול|יכולה|מצליח|מצליחה)\s+לצלם',str(text or '')))

def verbal_clearance_question(specs):
    if specs.get('obstacle_side'):
        return 'כמה מרווח בערך יש בין האסלה לפתח המקלחת? גם הערכה גסה תעזור להבין מה עוד צריך לבדוק.'
    return 'אין בעיה, אפשר להתחיל מתיאור. האסלה נמצאת מימין או משמאל לפתח המקלחת כשעומדים מולו?'


def respect_missing_customer_photo(reply, specs, customer):
    """Do not demand the same unavailable input; it never proves fit or a price."""
    import re
    if (specs.get('customer_photo_unavailable') and
            (no_customer_photo(customer) or (specs.get('obstacle_side') and str(customer).strip().rstrip('.!?') in ('מימין','משמאל')) or re.search(r'תשלח.{0,25}(?:תמונה|צילום)|שלוח.{0,25}(?:צילום|תמונה)|אפשר.{0,20}צילום|אפשר.{0,20}תמונה|לצלם',reply))):
        return verbal_clearance_question(specs)
    return reply
