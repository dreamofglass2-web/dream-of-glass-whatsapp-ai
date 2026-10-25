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
    if specs.get('obstacle_side') and specs.get('obstacle_clearance_cm') is not None:
        if specs.get('shower_depth_cm') is not None:
            return FIT_REVIEW_REPLY
        return 'מה העומק המשוער של המקלחת מהפתח עד הקיר שמולו?'
    if specs.get('obstacle_side'):
        return 'כמה מרווח בערך יש בין האסלה לפתח המקלחת? גם הערכה גסה תעזור להבין מה עוד צריך לבדוק.'
    return 'אין בעיה, אפשר להתחיל מתיאור. האסלה נמצאת מימין או משמאל לפתח המקלחת כשעומדים מולו?'


def respect_missing_customer_photo(reply, specs, customer):
    """Do not demand the same unavailable input; it never proves fit or a price."""
    import re
    if (specs.get('customer_photo_unavailable') and
            (no_customer_photo(customer) or spatial_answer(customer, specs.get('_previous_spatial_question','')) or (specs.get('obstacle_side') and str(customer).strip().rstrip('.!?') in ('מימין','משמאל')) or re.search(r'תשלח.{0,25}(?:תמונה|צילום)|שלוח.{0,25}(?:צילום|תמונה)|אפשר.{0,20}צילום|אפשר.{0,20}תמונה|לצלם',reply))):
        return verbal_clearance_question(specs)
    return reply

FIT_REVIEW_REPLY='כדי לא לאשר פתיחה שעלולה להפריע לאסלה, נדרשת בדיקת התאמה של אלירן לפי התיאור והמרווחים שמסרת.'

def spatial_answer(customer, previous):
    import re
    match=re.fullmatch(r'\s*(?:בערך\s+)?(\d{1,3}(?:\.\d+)?)\s*(?:בערך|ס[״\"]?מ)?\s*[.!]?\s*',str(customer or ''))
    if not match or not 0<float(match[1])<=500:
        return None
    if 'כמה מרווח' in previous and 'אסלה' in previous:
        return ('obstacle_clearance_cm',float(match[1]))
    if re.search(r'מה העומק|עומק.{0,25}מהפתח',previous):
        return ('shower_depth_cm',float(match[1]))
    return None

def capture_spatial_answer(state, customer, previous):
    if ('האסלה' in previous and 'מימין או משמאל' in previous
            and str(customer).strip().rstrip('.!?') in ('מימין','משמאל')):
        state['obstacle_side']=str(customer).strip().rstrip('.!?')
    answer=spatial_answer(customer,previous)
    if answer:state[answer[0]]=answer[1]
    return state


def unknown_width_slider_reply(reply, specs):
    """An unknown width permits explanation, not a sliding recommendation."""
    import re
    width=specs.get('width_cm')
    if type(width) in (int,float) and math.isfinite(width) and width>0:
        return reply
    if not str(specs.get('product') or '').startswith(('מקלחון','אמבטיון')):
        return reply
    parts=re.split(r'(?<=[.!?])\s+|\n+',str(reply or ''))
    def recommends(part):
        return ('הזזה' in part and not re.search(r'לא (?:כדאי|מתאי[םמה]|ממליץ)',part)
                and re.search(r'ממליץ|כדאי|כיוון|מתאי[םמה]|חלוקת ההזזה|לבחור',part))
    if not any(recommends(part) for part in parts):
        return reply
    caveat=('לפני המלצה על הזזה צריך לדעת את רוחב הפתח. אצלנו בוחנים הזזה רק מ־140 ס״מ ומעלה, '
            'וגם אז ההתאמה תלויה במרווחים בשטח.')
    rest=' '.join(part for part in parts if not recommends(part))
    return caveat+(' '+rest if rest else '')
