"""Owner-defined minimum opening width for recommending or quoting sliding doors."""
import math
MIN_SLIDING_WIDTH_CM=140
POLICY='מקלחון הזזה אפשר להציע ולתמחר רק ברוחב פתח של 140 ס״מ ומעלה. מתחת ל־140 לא להציע הזזה גם אם יש אסלה קרובה. לבקש צילום ומרווחים כדי לבחון פתרון אחר, בלי להבטיח מפתח כניסה או התאמת צירים. רוחב לא ידוע מחייב בירור לפני המלצה. 140 הוא סף כניסה לבדיקה ולא הבטחת התאמה. אם אין ללקוח תמונה, לא לבקש אותה שוב: לברר מה נמצא ליד הפתח, מיקום המכשול שהלקוח ציין ובהמשך מרווח, שאלה אחת בכל פעם. תיאור אינו אישור התאמה מקצועית.'

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
            'אפשר לשלוח צילום של הפתח והאזור שסביבו? כך נוכל לבדוק מה עלול להפריע לפתיחה ולבחון פתרון אחר.')


def no_customer_photo(text):
    import re
    return bool(re.search(r'אין\s+(?:לי\s+)?(?:כרגע\s+)?(?:תמונה|צילום)|לא\s+(?:יכול|יכולה|מצליח|מצליחה)\s+לצלם',str(text or '')))

def capture_obstacle(state, customer):
    """Keep explicitly stated fixtures; a question is not a site fact."""
    import re
    text=str(customer or '').split('[לקוח צירף',1)[0]
    text=re.split(r'[?？]',text)[-1]
    for noun in ('אסלה','ארון'):
        if re.search(r'(?:אין|בלי)\s+(?:לי\s+|שם\s+)?'+noun,text) and state.get('obstacle_type')==noun:
            state.pop('obstacle_type',None)
        if re.search(r'(?:יש\s+(?:לי\s+|שם\s+)?ה?'+noun+r'|'+noun+r'\s+(?:ממש\s+)?(?:קרוב|צמוד)|נתקע[ת]?\s+ב'+noun+r')',text):
            state['obstacle_type']=noun
    return state


def verbal_clearance_question(specs):
    obstacle=specs.get('obstacle_type')
    if not obstacle:
        return 'יש ליד פתח המקלחת ארון או אסלה שעלולים להפריע לפתיחת דלת?'
    if specs.get('obstacle_side') and specs.get('obstacle_clearance_cm') is not None:
        if specs.get('shower_depth_cm') is not None:
            return FIT_REVIEW_REPLY
        return 'מה העומק המשוער של המקלחת מהפתח עד הקיר שמולו?'
    if specs.get('obstacle_side'):
        return f'כמה מרווח בערך יש בין ה{obstacle} לפתח המקלחת? גם הערכה גסה תעזור להבין מה עוד צריך לבדוק.'
    verb='נמצאת' if obstacle=='אסלה' else 'נמצא'
    return f'אין בעיה, אפשר להתחיל מתיאור. ה{obstacle} {verb} מימין או משמאל לפתח המקלחת כשעומדים מולו?'


def respect_missing_customer_photo(reply, specs, customer):
    """Do not demand the same unavailable input; it never proves fit or a price."""
    import re
    if (specs.get('customer_photo_unavailable') and
            (no_customer_photo(customer) or spatial_answer(customer, specs.get('_previous_spatial_question','')) or (specs.get('obstacle_side') and str(customer).strip().rstrip('.!?') in ('מימין','משמאל')) or re.search(r'תשלח.{0,25}(?:תמונה|צילום)|שלוח.{0,25}(?:צילום|תמונה)|אפשר.{0,20}צילום|אפשר.{0,20}תמונה|לצלם',reply))):
        return verbal_clearance_question(specs)
    return reply

FIT_REVIEW_REPLY='כדי לא לאשר פתיחה שעלולה להתנגש במכשול ליד הפתח, נדרשת בדיקת התאמה של אלירן לפי התיאור והמרווחים שמסרת.'

def spatial_answer(customer, previous):
    import re
    match=re.fullmatch(r'\s*(?:בערך\s+)?(\d{1,3}(?:\.\d+)?)\s*(?:בערך|ס[״\"]?מ)?\s*[.!]?\s*',str(customer or ''))
    if not match or not 0<float(match[1])<=500:
        return None
    if 'כמה מרווח' in previous and re.search(r'אסלה|ארון',previous):
        return ('obstacle_clearance_cm',float(match[1]))
    if re.search(r'מה העומק|עומק.{0,25}מהפתח',previous):
        return ('shower_depth_cm',float(match[1]))
    return None

def capture_spatial_answer(state, customer, previous):
    state=capture_obstacle(state,customer)
    if (any(noun in previous for noun in ('האסלה','הארון')) and 'מימין או משמאל' in previous
            and str(customer).strip().rstrip('.!?') in ('מימין','משמאל')):
        state['obstacle_side']=str(customer).strip().rstrip('.!?')
        state['obstacle_type']='ארון' if 'הארון' in previous else 'אסלה'
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


def spatial_measurement_field(previous):
    import re
    text=str(previous or '')
    if re.search(r'מרווח|מרחק',text) and re.search(r'אסלה|ארון',text):
        return 'obstacle_clearance_cm'
    if 'עומק' in text and re.search(r'מקלחת|מהפתח|קיר',text):
        return 'shower_depth_cm'
    return None


def bind_spatial_measurement(state, data, customer, previous):
    """Interpret a natural answer only in the measurement question's context."""
    import re
    written=str(customer or '').split('[לקוח צירף',1)[0].strip()
    field=spatial_measurement_field(previous)
    if not field or not written or re.fullmatch(r'(?:לא יודע|לא יודעת|אין לי מושג|לא מדדתי)[.! ]*',written):
        return state
    value=data.get(field)
    if type(value) not in (int,float) or not math.isfinite(value) or value<0 or value>500:
        return state
    if field=='shower_depth_cm' and value==0:
        return state
    return dict(state,**{field:value})
