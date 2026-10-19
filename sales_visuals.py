"""Illustration intent and honest catalog matching; no model or delivery calls."""
import re

# Existing owner-approved portfolio assets, visually reviewed for the handle only.
# Do not infer glass, finish, measurements or configuration from these labels.
REVIEWED_HANDLE_LABELS = {
    'https://res.cloudinary.com/yovjswn9/image/upload/glass_010.jpeg': 'כפתור',
    'https://res.cloudinary.com/yovjswn9/image/upload/glass_009.jpeg': 'מגבת',
}



def catalog_handle_label(record):
    """Keep explicit handle metadata in supported catalog formats; never infer from glass/layout."""
    values = [record.get(key) for key in ('handle', 'handles', 'handle_type') if record.get(key)]
    labels = []
    for value in values:
        for label in value if isinstance(value, list) else [value]:
            if isinstance(label, str):
                labels.append(label.strip())
    return ' '.join(dict.fromkeys(labels)) or REVIEWED_HANDLE_LABELS.get(record.get('url'), '')

def handle_photo_request(text, history):
    if declines_visuals(text) or not re.search(r'תמונ|דוגמ|לראות|תראה|תראי|תשלח', text):
        return False
    if re.search(r'ידית|ידיות|כפתור|מגבת', text):
        return True
    last = next((str(m.get('content') or '') for m in reversed(history[:-1])
                 if m.get('role') == 'assistant'), '')
    return bool(re.search(r'ידית|ידיות|כפתור|מגבת', last) and not re.search(r'זכוכית|זכוכיות', text))


def handle_photos(catalog, text, context, button_url='', towel_url=''):
    wanted = ['כפתור', 'מגבת']
    named = [name for name in wanted if name in text]
    if not named:
        named = [name for name in wanted if any(name in h for h in (context.get('handles') or []))]
    wanted = named or wanted
    result = []
    for name in wanted:
        match = next((p for p in catalog if name in catalog_handle_label(p)), None)
        url = match['url'] if match else {'כפתור': button_url, 'מגבת': towel_url}[name]
        if url:
            result.append({'url': url, 'glass': (match or {}).get('glass', ''),
                           'caption': f'בתמונה רואים ידית {name}. המבנה והגוון בתמונה הם להמחשה.' if match else f'ידית {name}'})
    return result


def declines_visuals(text):
    return bool(re.search(r'לא\s+(?:רוצה|צריך|צריכה|מעוניין|מעוניינת).{0,18}(?:תמונ|דוגמ)|בלי\s+תמונ|אין\s+צורך.{0,12}תמונ|אל\s+תשלח.{0,15}תמונ', str(text or '')))


def implicit_visual_request(text):
    text = str(text or '')
    if declines_visuals(text):
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
