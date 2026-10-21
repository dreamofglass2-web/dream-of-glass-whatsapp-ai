"""Separate explicitly numbered shower items without another model call."""
import re
from copy import deepcopy

FIELDS = ('stage', 'action', 'next_missing_fact', 'product', 'configuration',
          'width_cm', 'second_width_cm', 'height_cm', 'glass_type', 'finish',
          'handles', 'quote_requested', 'solution_agreed', 'validated_quote',
          'pricing_height_basis', 'bath_clearance_warned', 'requested_layout')


def preliminary_height(specs):
    """Owner's pricing basis only; an explicit customer height takes precedence."""
    if specs.get('height_cm') is not None:
        return specs['height_cm']
    return 140 if 'אמבטיון' in str(specs.get('product') or '') + str(specs.get('configuration') or '') else 200


def numbered_item(text):
    # A cardinal count of panels is not the ordinal second shower.
    if re.match(r'^\s*שני\s+(?:קבועים|מקלחונים|חלקים|צדדים|לוחות|דלתות)\b', text):
        return None
    matches = re.findall(r'(?:מקלחון\s*(?:ה)?|למקלחון\s*(?:ה)?|^(?:ה)?)(ראשון|שני|שלישי)\b', text)
    return {'ראשון': '1', 'שני': '2', 'שלישי': '3'}.get(matches[-1]) if matches else None


def order_inventory(history):
    """Recover explicitly requested products, never dimensions from image analysis."""
    count, mixed = 1, False
    for message in history:
        if message.get('role') != 'user':
            continue
        text = str(message.get('content') or '').split('[לקוח צירף', 1)[0]
        if re.search(r'(?:3|שלושה)\s*מקלחונים', text):
            count = max(count, 3)
        elif re.search(r'(?:2|שני|שתי)\s*מקלחונים|מקלחונים\s+(?:ל|ב)?(?:שני|שתי|שניי?ם|2)\s*(?:ה)?חדרים', text):
            count = max(count, 2)
        bath = re.search(r'אמבטיון|מקלחון\s+באמבטיה', text)
        shower = re.search(r'מקלחון\s+(?:בשירותים|ה?שירותים)', text)
        if bath and shower:
            count = max(count, 2)
            mixed = ('אמבטיון', 'מקלחון') if bath.start() < shower.start() else ('מקלחון', 'אמבטיון')
    return count, mixed


def item_context(prior, history, customer):
    state = deepcopy(prior or {})
    last_reply = next((str(m.get('content') or '') for m in reversed(history[:-1])
                       if m.get('role') == 'assistant'), '')
    count, mixed = order_inventory(history)
    count = max(count, int(state.get('expected_sales_item_count') or 1), len(state.get('sales_items') or {}))
    target = numbered_item(str(customer))
    if mixed and 'אמבטיון' in str(customer):
        target = str(mixed.index('אמבטיון') + 1)
    elif mixed and re.search(r'מקלחון\s+(?:בשירותים|ה?שירותים)', str(customer)):
        target = str(mixed.index('מקלחון') + 1)
    if not target and not re.search(r'יקר|זול|להשוות|השוואה|הצעה אחרת|תקציב|מאשר|מאשרת', str(customer)) and len(set(re.findall(r'מקלחון (?:ה)?(?:ראשון|שני|שלישי)',last_reply)))<2 and re.search(r'נעבור|למקלחון|במקלחון|מה.{0,15}מקלחון', last_reply):
        target = numbered_item(last_reply)
    multiple = bool(count > 1 or state.get('sales_items') or target or re.search(
        r'(?:[23]|שני|שתי|שלושה)\s*מקלחונים', str(customer)))
    if not multiple:
        return state
    active = str(state.get('active_sales_item') or '1')
    items = state.setdefault('sales_items', {})
    if active not in items or any(key in state for key in ('configuration','width_cm','glass_type')):
        items[active] = {k: deepcopy(state[k]) for k in FIELDS if k in state}
    count = max(count, int(target or active))
    state['expected_sales_item_count'] = count
    for number in range(1, count + 1):
        item = items.setdefault(str(number), {})
        if mixed:
            item.setdefault('product', mixed[number - 1] if number <= len(mixed) else 'מקלחון')
            if item.get('product') == 'מקלחון':
                for message in history:
                    if message.get('role') != 'user':
                        continue
                    written = str(message.get('content') or '').split('[לקוח צירף', 1)[0]
                    service = re.search(r'מקלחון\s+(?:בשירותים|ה?שירותים)', written)
                    if service and 'קבוע' in written[service.start():] and 'מתקפל' in written[service.start():]:
                        item.setdefault('requested_layout', 'צד קבוע וצד מתקפל')
    target = target or active
    if target != active:
        for key in FIELDS:
            state.pop(key, None)
        state.update(deepcopy(items.get(target, {})))
    state['active_sales_item'] = target
    if count > 1 and len((state.get('combined_offer') or {}).get('items') or []) < count:
        state.pop('combined_offer', None)
        state.pop('validated_quote', None)
    return state


def save_item(state):
    if state.get('active_sales_item'):
        state.setdefault('sales_items', {})[state['active_sales_item']] = {
            k: deepcopy(state[k]) for k in FIELDS if k in state}
    return state


def combined_quote(state, history, customer, calculator):
    items = state.get('sales_items') or {}
    if len(items) < 2:
        return None
    last_reply = next((str(m.get('content') or '') for m in reversed(history[:-1])
                       if m.get('role') == 'assistant'), '')
    explicit = bool(re.search(r'(?:מחיר|הצעה|כמה|תחשב|סכום).{0,30}(?:שני|שניהם|הכול|הכל|כולל)|'
                              r'(?:שני|שניהם).{0,20}(?:מחיר|הצעה)|סך\s*הכל', customer))
    accepting = bool(re.match(r'^(?:כן|תודה|בשמחה|תכין|אפשר)', customer.strip()) and
                     re.search(r'הצעת\s*מחיר.{0,20}(?:לשני|לשניהם)', last_reply))
    if not (explicit or accepting):
        return None
    lines, total, missing = [], 0, []
    for number, original in sorted(items.items()):
        specs = deepcopy(original)
        if not specs.get('solution_agreed'):
            missing.append(number)
            continue
        specs['height_cm'] = preliminary_height(specs)
        amount = calculator(specs)
        if amount is None:
            missing.append(number)
            continue
        total += round(amount)
        lines.append(f'מקלחון {number}: {amount:,.0f} ש״ח לפני מע״מ')
    if missing:
        return ('; '.join(lines) + '. ' if lines else '') + 'עדיין חסרים פרטים לחישוב מקלחון ' + ', '.join(missing) + '; אין עדיין סכום כולל להזמנה.'
    return ('הצעת המחיר הראשונית לשני המקלחונים: ' + '; '.join(lines) +
            f'. יחד {total:,.0f} ש״ח לפני מע״מ, כולל מדידה, הובלה והתקנה. '
            'גובה שלא נמדד חושב לפי 140 ס״מ לאמבטיון ו־200 ס״מ למקלחון לצורך תמחור בלבד. המידות הסופיות ייבדקו בשטח, '
            'ושינוי במידות או במפרט עשוי לשנות את המחיר.')

import hashlib
import json


def bundle_offer(state, calculator, allow_single=False):
    """Calculate every selected item; never issue an incomplete order total."""
    items=state.get('sales_items') or {}
    if len(items)<max(int(state.get('expected_sales_item_count') or 1), (1 if allow_single else 2)):
        return None
    offers=[]
    for number, original in sorted(items.items(),key=lambda pair:int(pair[0])):
        specs=deepcopy(original)
        if not specs.get('solution_agreed'):
            return None
        specs['height_cm']=preliminary_height(specs)
        amount=calculator(specs)
        if amount is None:
            return None
        offers.append({'number':number,'amount_ils_pre_vat':amount,
                       'specification':{k:deepcopy(specs.get(k)) for k in FIELDS
                         if k in ('product','configuration','width_cm','second_width_cm','height_cm','glass_type','finish','handles')}})
    fingerprint=hashlib.sha256(json.dumps(offers,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return {'fingerprint':fingerprint,'items':offers,
            'amount_ils_pre_vat':sum(o['amount_ils_pre_vat'] for o in offers)}


def offer_height_note(offer):
    """Mention only the actual products and pricing heights in this offer."""
    return ' '.join(('אמבטיון' if 'אמבטיון' in str(i['specification'].get('product') or '') +
                    str(i['specification'].get('configuration') or '') else 'מקלחון') +
                   ' בגובה ' + str(i['specification']['height_cm']) + ' ס״מ.' for i in offer['items']) + \
           ' המידות הסופיות ייבדקו בשטח. שינוי במידות או במפרט עשוי לשנות את המחיר.'


def offer_document_caption(offer):
    if len(offer['items']) > 1:
        return 'מצורפת הצעת המחיר המלאה למקלחונים שבחרנו. המפרטים, המחירים והתנאים נמצאים בקובץ. מתאים לך לאשר את ההצעה המלאה?'
    s = offer['items'][0]['specification']
    product = 'אמבטיון' if 'אמבטיון' in str(s.get('product') or '') + str(s.get('configuration') or '') else 'מקלחון'
    return 'מצורפת הצעת המחיר ל' + product + ' שבחרנו, לפריט הזה בלבד. המפרט, המחיר והתנאים נמצאים בקובץ. מתאים לך לאשר את ההצעה לפריט הזה?'


def bundle_offer_reply(offer):
    lines=[]
    for item in offer['items']:
        s=item['specification']
        size=str(s['width_cm'])+((' על '+str(s['second_width_cm'])) if s.get('second_width_cm') else '')
        handles=', '.join(s.get('handles') or [])
        label={'1':'הראשון','2':'השני','3':'השלישי'}.get(item['number'],item['number'])
        product = 'אמבטיון' if 'אמבטיון' in str(s.get('product') or s.get('configuration') or '') else 'מקלחון'
        handle_text = (', ' + handles) if handles else ''
        name = product + (' ' + label if len(offer['items']) > 1 else '')
        lines.append(f"{name}, {s['configuration']}, {size} ס״מ, גובה {s['height_cm']} ס״מ, זכוכית {s['glass_type']}, פרזול {s['finish']}{handle_text}. המחיר {item['amount_ils_pre_vat']:,.0f} ש״ח לפני מע״מ.")
    if len(offer['items']) > 1:
        lines.append(f"סך הכול לכל המקלחונים {offer['amount_ils_pre_vat']:,.0f} ש״ח לפני מע״מ, כולל מדידה, הובלה והתקנה.")
    else:
        lines.append("המחיר מתייחס לפריט הזה בלבד וכולל מדידה, הובלה והתקנה.")
    lines.append('זו הצעה ראשונית. ' + offer_height_note(offer))
    lines.append('מתאים לך לאשר את ההצעה המלאה?' if len(offer['items']) > 1 else 'מתאים לך לאשר את ההצעה לפריט הזה?')
    return '\n\n'.join(lines)



def partial_offer_reply(state, calculator, missing_detail):
    """Price the active item honestly and continue to the next unfinished one."""
    items = state.get('sales_items') or {}
    active = str(state.get('active_sales_item') or '1')
    specs = dict(items.get(active) or {})
    specs['height_cm'] = preliminary_height(specs)
    amount = calculator(specs) if specs.get('solution_agreed') else None
    unfinished = next(((n, s) for n, s in sorted(items.items()) if n != active
                       and (not s.get('solution_agreed') or calculator(dict(s, height_cm=preliminary_height(s))) is None)), None)
    if amount is None or unfinished is None:
        return None
    number, other = unfinished
    product = 'האמבטיון' if 'אמבטיון' in str(specs.get('product') or specs.get('configuration') or '') else 'המקלחון'
    label = {'1':'הראשון','2':'השני','3':'השלישי'}.get(number, number)
    layout = (' עם ' + str(other['requested_layout']) + ' שביקשת') if other.get('requested_layout') else ''
    question = ('מה המידות המשוערות שלו?' if not other.get('width_cm') else missing_detail(other))
    return (f'סיכמנו את פרטי {product} שבחרת. '
            f'נמשיך למקלחון {label}{layout} כדי להשלים את ההצעה לשניהם. ' + question)
