"""Illustration intent and honest catalog matching; no model or delivery calls."""
import re


def implicit_visual_request(text):
    text = str(text or '')
    if re.search(r'לא\s+(?:רוצה|צריך|צריכה|מעוניין|מעוניינת).{0,18}(?:תמונ|דוגמ)|בלי\s+תמונ', text):
        return False
    return bool(re.search(
        r'קשה\s+לי\s+לדמיין|לא\s+(?:מצליח|מצליחה|יכול|יכולה)\s+לדמיין'
        r'|לא\s+(?:מבין|מבינה)\s+איך\s+זה\s+(?:ייראה|יראה|נראה)'
        r'|(?:צריך|צריכה|רוצה)\s+לראות\s+איך\s+זה\s+(?:ייראה|יראה|נראה)', text))


def consultation_photos(catalog, context, max_photos=2):
    """Match declared catalog metadata, never infer a layout from an image."""
    context = context or {}
    product = str(context.get('product') or '')
    configuration = context.get('configuration')
    glass = context.get('glass_type')
    choices = [p for p in catalog if (not product or
               ('מקלחון' in product and ('מקלחון' in p.get('product', '') or 'אמבטיון' in p.get('product', ''))) or
               (product not in ('מקלחון',) and product in p.get('product', '')))]
    if not choices:
        return []
    choices = sorted(choices, key=lambda p: (
        bool(configuration and p.get('configuration') == configuration),
        bool(glass and p.get('glass') == glass)), reverse=True)
    chosen, seen = [], set()
    for item in choices:
        if item['url'] in seen:
            continue
        chosen.append(item)
        seen.add(item['url'])
        if len(chosen) >= max_photos:
            break
    return chosen


def consultation_photo_intro(photos, context):
    """Only claim a matching layout if every chosen record explicitly matches it."""
    configuration = (context or {}).get('configuration')
    if configuration and photos and all(p.get('configuration') == configuration for p in photos):
        return f'הנה דוגמאות לתצורה {configuration}, כדי להמחיש את הכיוון שדיברנו עליו. אלה עבודות להמחשה; את ההתאמה לשטח שלך נבדוק בנפרד.'
    return 'הנה דוגמאות להמחשה. המבנה והגימור בתמונות יכולים להיות שונים מהפתרון שלך; את ההתאמה לשטח שלך נבדוק בנפרד.'
