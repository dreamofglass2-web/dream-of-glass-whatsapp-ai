"""Plain-language discovery when the customer cannot choose a shower layout."""
import re

POLICY = '''כשהלקוח לא יודע איזו תצורה לבחור ומבקש המלצה, תפקידך לייעץ: אל תבקש ממנו לחלק זכוכיות ודלתות בעצמו. ברר תחילה אם סוגרים צד אחד בין קירות או שני צדדים בפינה, או בקש תמונה. שאל שאלה פשוטה אחת בכל פעם. אחרי הבנת החלל ברר מידות ומכשולים לפני המלצה על פתיחה. המלצה אינה אישור מפרט או מחיר. בקשת המלצה רגילה אינה סיבה להעביר לבעל העסק; מגבלה מקצועית אמיתית עדיין מחייבת העברה.'''

def layout_advice_request(text):
    return bool(re.search(r'אין לי מושג|לא (?:כל כך )?(?:יודע|יודעת|מבין|מבינה)|מה (?:אתה |את |היית )?ממליץ|מה כדאי|תמליץ', str(text or '')))

def layout_consultation_reply(text, specs, previous=''):
    if not layout_advice_request(text) or specs.get('configuration'):
        return None
    if str(specs.get('product') or '').startswith('אמבטיון'):
        return 'אעזור לך לבחור לפי האמבטיה. אפשר לשלוח תמונה שלה כדי לראות איזה צד צריך לסגור ומה נמצא לידו?'
    if 'איך מחולקות' in previous or 'תצורת המקלחון' in previous:
        return 'אעזור לך לבחור לפי המקום. אפשר לשלוח תמונה של אזור המקלחת? כך אוכל לראות איפה הקירות ומה עלול להפריע לפתיחת הדלת.'
    return 'אעזור לך לבחור לפי המקום. צריך לסגור צד אחד בין שני קירות, או שני צדדים שנפגשים בפינה?'


def capture_layout_geometry(state, customer):
    """A shape is not a bill-of-materials configuration or customer approval."""
    text=str(customer or '').strip().rstrip('.!?').strip()
    if re.fullmatch(r'(?:זה |הוא |המקלחון )?(?:בפינה|פינתי|שני צדדים בפינה)',text):
        state['layout_geometry']='corner'
    elif re.fullmatch(r'(?:זה |הוא |המקלחון )?(?:חזיתי|בין (?:שני |2 )?קירות|צד אחד בין (?:שני )?קירות)',text):
        state['layout_geometry']='front'
    return state


def missing_layout_detail(specs):
    if specs.get('layout_geometry')=='corner':
        if not specs.get('width_cm') or not specs.get('second_width_cm'):
            return 'מה המידות המשוערות של שני צדי המקלחת בפינה?'
        return 'יש ליד המקלחת ארון או אסלה שעלולים להפריע לפתיחת הדלתות?'
    if specs.get('layout_geometry')=='front':
        if not specs.get('width_cm'):
            return 'מה רוחב הפתח המשוער בין הקירות?'
        return 'יש מקום לדלת להיפתח, או שיש ארון או אסלה קרובים לפתח?'
    return 'צריך לסגור צד אחד בין שני קירות, או שני צדדים שנפגשים בפינה?'
