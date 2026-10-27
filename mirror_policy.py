"""Owner-approved frame availability, grounded in the customer's mirror shape."""
import re

FRAME_POLICY = 'מסגרת אפשרית רק למראות ישרות. מראות עגולות או צורתיות אנחנו עושים ללא מסגרת.'

def curved_mirror(history, product=''):
    if product and 'מרא' not in str(product):
        return False
    for message in reversed(history):
        if message.get('role') != 'user':
            continue
        text=str(message.get('content') or '').split('[לקוח צירף',1)[0]
        shapes=list(re.finditer(r'מלבני[תות]*|מרובע[תות]*|ישר[הות]*|עגול[הות]*|עיגול|אובלי[תות]*|אסימטרי[תות]*|צורתי[תות]*|קשת|קוטר',text))
        for shape in reversed(shapes):
            before=text[max(0,shape.start()-16):shape.start()]
            if re.search(r'(?:לא|בלי|ללא)\s*$',before):
                continue
            return not bool(re.match(r'מלבנ|מרובע|ישר',shape.group()))
    return False

def curved_frame_request(customer, history, product=''):
    text=str(customer or '')
    return (curved_mirror(history,product) and 'מסגרת' in text and
            not re.search(r'(?:בלי|ללא|לא רוצה|לא צריך|אין צורך ב)\s*(?:שום\s+)?מסגרת',text))

def guard_mirror_frame(reply, history, product=''):
    text=str(reply or '')
    if not curved_mirror(history,product):
        return text
    candidate=re.sub(r'(?:בלי|ללא)\s+מסגרת', '', text)
    if not re.search(r'(?:עם|להוסיף|נוסיף|שקול|שוקל|שקלי|לשקול|ממליץ|מציע|אפשר|ניתן|כולל|מסגרת דקה).{0,35}מסגרת|מסגרת דקה',candidate):
        return text
    if re.search(r'(?:אין אפשרות|לא ניתן|לא אפשרי).{0,20}מסגרת',text):
        return text
    rest=' '.join(s for s in re.split(r'(?<=[.!?])\s+',text) if 'מסגרת' not in s)
    return FRAME_POLICY + (' ' + rest if rest else '')
