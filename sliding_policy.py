"""Owner-defined minimum opening width for recommending or quoting sliding doors."""
import math
MIN_SLIDING_WIDTH_CM=140
POLICY='מקלחון הזזה אפשר להציע ולתמחר רק ברוחב פתח של 140 ס״מ ומעלה. מתחת ל־140 לא להציע הזזה גם אם יש אסלה קרובה. לבקש צילום ומרווחים כדי לבחון פתרון אחר, בלי להבטיח מפתח כניסה או התאמת צירים. רוחב לא ידוע מחייב בירור לפני המלצה. 140 הוא סף כניסה לבדיקה ולא הבטחת התאמה.'

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
