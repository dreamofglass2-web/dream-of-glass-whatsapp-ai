"""Answer option requests in the context of the last customer-facing question."""
import re

def asks_for_options(text):
    return bool(re.search(r'אפשרו?יו?ת|אפשרויות|אופציות|אופציה|מה יש|מה ההבדל|תסביר',str(text or '')))

def contextual_options_reply(text, previous, specs):
    if not asks_for_options(text):
        return None
    if re.search(r'סוג זכוכית|איזו זכוכית|איזה זכוכית',previous):
        return ('למראה פתוח אפשר לבחור שקופה, או אקסטרה קליר עם פחות גוון ירקרק. '
                'לגוון כהה יש אנטיסן אפור או ברונזה, וליותר פרטיות אפשר לבחור חלבי, אסיד או זכוכית עם דוגמה כמו גלינה. '
                'מה יותר חשוב לך — מראה שקוף ופתוח, פרטיות או גוון כהה?')
    if re.search(r'גוון פרזול|גימור|צבע פרזול',previous):
        return ('אפשר לבחור ניקל, ניקל מוברש, שחור, גרפיט, ברונזה, זהב או לבן. '
                'כדאי להתאים לברזים שבחדר. באיזה גוון הברזים שלך?')
    if re.search(r'סוג ידית|כפתור או מגבת|איזו ידית|איזה ידית',previous):
        if 'הזזה' in str(specs.get('configuration') or ''):
            return 'במקלחון הזזה מתקינים ידית כפתור בלבד. תרצה לראות דוגמה?'
        return ('ידית כפתור קטנה ומתאימה למראה נקי, וידית מגבת ארוכה מאפשרת גם תליית מגבת. '
                'איזה סגנון יותר מתאים לך?')
    return None
