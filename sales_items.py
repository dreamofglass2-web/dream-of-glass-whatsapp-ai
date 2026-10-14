"""Separate explicitly numbered shower items without another model call."""
import re
from copy import deepcopy

FIELDS = ('stage', 'action', 'next_missing_fact', 'product', 'configuration',
          'width_cm', 'second_width_cm', 'height_cm', 'glass_type', 'finish',
          'handles', 'quote_requested', 'solution_agreed', 'validated_quote',
          'pricing_height_basis')


def numbered_item(text):
    matches = re.findall(r'(?:מקלחון\s*(?:ה)?|למקלחון\s*(?:ה)?|^(?:ה)?)(ראשון|שני|שלישי)\b', text)
    return {'ראשון': '1', 'שני': '2', 'שלישי': '3'}.get(matches[-1]) if matches else None


def item_context(prior, history, customer):
    state = deepcopy(prior or {})
    last_reply = next((str(m.get('content') or '') for m in reversed(history[:-1])
                       if m.get('role') == 'assistant'), '')
    target = numbered_item(str(customer))
    if not target and len(set(re.findall(r'מקלחון (?:ה)?(?:ראשון|שני|שלישי)',last_reply)))<2 and re.search(r'נעבור|למקלחון|במקלחון|מה.{0,15}מקלחון', last_reply):
        target = numbered_item(last_reply)
    multiple = bool(state.get('sales_items') or target or re.search(
        r'(?:[23]|שני|שתי|שלושה)\s*מקלחונים', str(customer)))
    if not multiple:
        return state
    active = str(state.get('active_sales_item') or '1')
    items = state.setdefault('sales_items', {})
    if active not in items or any(key in state for key in ('configuration','width_cm','glass_type')):
        items[active] = {k: deepcopy(state[k]) for k in FIELDS if k in state}
    target = target or active
    if target != active:
        for key in FIELDS:
            state.pop(key, None)
        state.update(deepcopy(items.get(target, {})))
    state['active_sales_item'] = target
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
        specs.setdefault('height_cm', 200)
        if specs.get('height_cm') is None:
            specs['height_cm'] = 200
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
            'גובה שלא נמדד חושב לפי 200 ס״מ לצורך תמחור בלבד. המידות הסופיות ייבדקו בשטח, '
            'ושינוי במידות או במפרט עשוי לשנות את המחיר.')

import hashlib
import json


def bundle_offer(state, calculator):
    """Calculate every selected item; never issue an incomplete order total."""
    items=state.get('sales_items') or {}
    if len(items)<2:
        return None
    offers=[]
    for number, original in sorted(items.items(),key=lambda pair:int(pair[0])):
        specs=deepcopy(original)
        if not specs.get('solution_agreed'):
            return None
        specs['height_cm']=specs.get('height_cm') or 200
        amount=calculator(specs)
        if amount is None:
            return None
        offers.append({'number':number,'amount_ils_pre_vat':amount,
                       'specification':{k:deepcopy(specs.get(k)) for k in FIELDS
                         if k in ('configuration','width_cm','second_width_cm','height_cm','glass_type','finish','handles')}})
    fingerprint=hashlib.sha256(json.dumps(offers,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return {'fingerprint':fingerprint,'items':offers,
            'amount_ils_pre_vat':sum(o['amount_ils_pre_vat'] for o in offers)}


def bundle_offer_reply(offer):
    lines=[]
    for item in offer['items']:
        s=item['specification']
        size=str(s['width_cm'])+((' על '+str(s['second_width_cm'])) if s.get('second_width_cm') else '')
        handles=', '.join(s.get('handles') or [])
        label={'1':'הראשון','2':'השני','3':'השלישי'}.get(item['number'],item['number'])
        lines.append(f"מקלחון {label}, {s['configuration']}, {size} ס״מ, גובה {s['height_cm']} ס״מ, זכוכית {s['glass_type']}, פרזול {s['finish']}, {handles}. המחיר {item['amount_ils_pre_vat']:,.0f} ש״ח לפני מע״מ.")
    lines.append(f"סך הכול לכל המקלחונים {offer['amount_ils_pre_vat']:,.0f} ש״ח לפני מע״מ, כולל מדידה, הובלה והתקנה.")
    lines.append('זו הצעה ראשונית, והמידות הסופיות ייבדקו בשטח. גובה שלא נמדד חושב לפי 200 ס״מ לצורך ההצעה, ושינוי במידות או במפרט עשוי לשנות את המחיר.')
    lines.append('מתאים לך לאשר את ההצעה המלאה?')
    return '\n\n'.join(lines)
