"""Owner-approved kitchen cladding prices, based on customer-written dimensions."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import re

RATES = {'צבע': 1100, 'הדפסה': 1500}
POLICY = 'חיפוי מטבח: צבע לבחירת הלקוח 1100 למ״ר; הדפסה 1500 למ״ר, לפני מע״מ. כולל פתחים לשקעים, מדידה, הובלה והרכבה. מחיר רק בקובץ הצעה מחושב.'


def written(text):
    return str(text or '').split('[לקוח צירף', 1)[0].strip()


def number(value):
    try:
        n = Decimal(str(value).replace(',', '.'))
        return n if n.is_finite() and n > 0 else None
    except (InvalidOperation, ValueError):
        return None


def kitchen_state(prior, history, data=None):
    state = dict(prior or {})
    if 'חיפוי' not in str(state.get('product') or ''):
        for key in ('width_cm','height_cm','cladding_area_m2','cladding_type','cladding_color','socket_count'):
            state.pop(key,None)
    data = data or {}
    latest = written(history[-1].get('content')) if history else ''
    if re.search(r'מראה|מקלחון|אמבטיון|מחיצה|מעקה',latest) and 'חיפוי' not in latest:
        return None
    if 'חיפוי' not in str(data.get('product') or state.get('product') or ''):
        if not history or 'חיפוי' not in written(history[-1].get('content')):
            return None
    state['product'] = 'חיפוי מטבח'
    for key in ('cladding_type', 'cladding_color', 'socket_count'):
        if data.get(key) is not None:
            state[key] = data[key]
    previous = ''
    for m in history:
        text = written(m.get('content'))
        if m.get('role') != 'user':
            previous = text
            continue
        if re.search(r'בלי הדפס|ללא הדפס|לא.{0,12}הדפס|צבע אחיד', text):
            state['cladding_type'] = 'צבע'
        elif re.search(r'הדפס(?:ה)?|מודפס|להדפיס', text) and not re.search(r'אפשר|האם|או ', text):
            state['cladding_type'] = 'הדפסה'
        if re.search(r'(?:צבע|גוון)\s+\S+',text) and not re.search(r'הדפס|מודפס|\bאו\b',text):
            state['cladding_type'] = 'צבע'
        if re.search(r'(?:צבע|גוון)\s*לבן|בצבע\s+לבן', text):
            state.update(cladding_type='צבע', cladding_color='לבן')
        if re.fullmatch(r'כן[.! ]*', text) and 'לבן חם' in previous:
            state.update(cladding_type='צבע', cladding_color='לבן חם')
        sockets = re.search(r'(\d+)\s*שקע', text)
        if sockets:
            state['socket_count'] = int(sockets.group(1))
        area = re.search(r'(\d+(?:[.,]\d+)?)\s*מ[״"\u05f3\u05f4]?ר\b', text)
        if area:
            state['cladding_area_m2'] = float(number(area.group(1))) if number(area.group(1)) else None
            state.pop('width_cm',None);state.pop('height_cm',None)
        for field, label in (('width_cm', r'אורך|רוחב'), ('height_cm', r'גובה')):
            measured = re.search(r'(?:' + label + r')\s*([-+]?\d+(?:[.,]\d+)?)\s*(מטר(?:ים)?|ס[״"]?מ)?', text)
            if measured:
                n = number(measured.group(1))
                state[field] = None
                if n:
                    state[field] = float(n * (100 if (measured.group(2) or '').startswith('מטר') else 1))
        length = re.search(r'(\d+(?:[.,]\d+)?)\s*מטר(?:ים)?\s*רץ', text)
        if length and number(length.group(1)):
            state['width_cm'] = float(number(length.group(1)) * 100)
        if re.fullmatch(r'\d+(?:[.,]\d+)?', text):
            n = number(text)
            if n and re.search(r'גובה', previous) and not re.search(r'אורך|רוחב', previous):
                state['height_cm'] = float(n)
            elif n and re.search(r'אורך|רוחב', previous) and not re.search(r'גובה', previous):
                state['width_cm'] = float(n)
        previous = text
    return state


def kitchen_offer(state):
    kind = state.get('cladding_type')
    if kind not in RATES:
        return None
    width, height = number(state.get('width_cm')), number(state.get('height_cm'))
    area = width * height / Decimal(10000) if width and height else number(state.get('cladding_area_m2'))
    if not area:
        return None
    amount = int((area * RATES[kind]).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    if amount <= 0:
        return None
    spec = {'product':'חיפוי מטבח', 'cladding_type':kind,
            'cladding_color':state.get('cladding_color') or 'לבחירת הלקוח',
            'width_cm':float(width) if width else None, 'height_cm':float(height) if height else None,
            'area_m2':float(area), 'rate_ils_per_m2':RATES[kind],
            'socket_count':state.get('socket_count')}
    item = {'number':'1', 'amount_ils_pre_vat':amount, 'specification':spec}
    fingerprint = hashlib.sha256(json.dumps(item,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return {'kind':'kitchen_cladding', 'fingerprint':fingerprint, 'items':[item], 'amount_ils_pre_vat':amount}


def missing_kitchen_detail(state):
    if not (number(state.get('cladding_area_m2')) or (number(state.get('width_cm')) and number(state.get('height_cm')))):
        if not number(state.get('width_cm')):
            return 'מה האורך המשוער של החיפוי בס״מ או במטרים?'
        return 'מה הגובה המשוער של החיפוי בס״מ?'
    return 'תרצה חיפוי בגוון צבע לבחירתך או עם הדפסה?'
