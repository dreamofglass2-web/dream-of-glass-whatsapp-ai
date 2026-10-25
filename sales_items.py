"""Separate explicitly numbered shower items without another model call."""
import re
from layout_consultation import capture_layout_geometry
from sliding_policy import no_customer_photo, capture_spatial_answer, unknown_width_slider_reply
from copy import deepcopy
import hashlib
import json

FIELDS = ('stage', 'action', 'next_missing_fact', 'product', 'configuration',
          'width_cm', 'second_width_cm', 'height_cm', 'glass_type', 'finish',
          'handles', 'quote_requested', 'solution_agreed', 'validated_quote',
          'pricing_height_basis', 'bath_clearance_warned', 'requested_layout', 'front_only', 'layout_geometry', 'door_obstruction', 'customer_photo_unavailable', 'obstacle_side', 'obstacle_clearance_cm', 'shower_depth_cm')


def preliminary_height(specs):
    """Owner's pricing basis only; an explicit customer height takes precedence."""
    if specs.get('height_cm') is not None:
        return specs['height_cm']
    return 140 if 'אמבטיון' in str(specs.get('product') or '') + str(specs.get('configuration') or '') else 200


ORDINALS = {'ראשון':'1','שני':'2','שלישי':'3','רביעי':'4','חמישי':'5','שישי':'6'}
LABELS = {v:'ה'+k for k,v in ORDINALS.items()}


def slider_specs(specs):
    result = deepcopy(specs)
    if 'הזזה' in str(result.get('configuration') or ''):
        result['handles'] = ['ידית כפתור'] * (2 if '2 דלתות' in result['configuration'] else 1)
    return result


def written_inventory(history):
    """Expand an explicit multi-line quantity list, excluding image analysis."""
    inventory, groups = {}, []
    shared_glass=None
    for message in history:
        if message.get('role') != 'user':
            continue
        text = str(message.get('content') or '').split('[לקוח צירף',1)[0]
        if not inventory and re.search(r'זכוכית\s+(?:אנטיסן\s+)?ברונזה',text):
            shared_glass='אנטיסן ברונזה'
        rows = re.findall(r'(?:^|\n)\s*([1-9])\s*(מקלחונים|מקלחון|אמבטיון|אמבטיוו)([^\n]*)',text)
        if len(rows) < 2:
            continue
        inventory, groups = {}, []
        for quantity,product,detail in rows:
            group=[]
            for _ in range(int(quantity)):
                n=str(len(inventory)+1); group.append(n)
                specs={'product':'אמבטיון' if product.startswith('אמבט') else 'מקלחון'}
                pair=re.search(r'(\d{2,3})\s*[/xX×]\s*(\d{2,3})',detail)
                if pair:
                    specs.update(width_cm=int(pair[1]),second_width_cm=int(pair[2]))
                elif 'פתח' in detail:
                    width=re.search(r'פתח\s*(\d+(?:\.\d+)?)',detail)
                    if width:
                        value=float(width[1]);specs['width_cm']=int(value*100) if value<10 else value
                if shared_glass:specs['glass_type']=shared_glass
                inventory[n]=specs
            if len(group)>1:groups.append(group)
    return inventory,groups


def group_choices(state, history, data):
    """Apply a choice to identical items only when the customer said both."""
    customer=str(history[-1].get('content') or '') if history else ''
    previous=next((str(m.get('content') or '') for m in reversed(history[:-1]) if m.get('role')=='assistant'),'')
    group_request=bool(re.search(r'לשתיהם|לשניהם|לשתיהן|בשניהם|בשני המקלחונים|לשני המקלחונים',customer))
    group_confirmation=bool(re.fullmatch(r'כן[.!\s]*',customer) and re.search(r'בשני המקלחונים|שני המקלחונים של',previous))
    if not (group_request or group_confirmation):return state
    active=str(state.get('active_sales_item') or '1')
    group=next((g for g in state.get('sales_item_groups',[]) if active in g),[])
    reference=customer+' '+previous if group_confirmation else customer
    fields=[]
    if re.search(r'פרזול|גוון',reference):fields.append('finish')
    if 'זכוכית' in reference:fields.append('glass_type')
    if re.search(r'ידית|ידיות|כפתור|מגבת',reference):fields.append('handles')
    if group_confirmation and 'דלתות' in previous:fields += ['configuration','solution_agreed']
    for n in group:
        for key in fields:
            if data.get(key) is not None:
                state['sales_items'][n][key]=deepcopy(data[key])
    return state


def slider_reply(reply, specs, customer=''):
    reply=unknown_width_slider_reply(reply,specs)
    if 'הזזה' not in str(specs.get('configuration') or ''):
        return reply
    policy='במקלחון הזזה אנחנו מתקינים ידית כפתור בלבד.'
    if 'מגבת' in str(reply):
        parts=re.split(r'(?<=[.!?])\s+|\n+',str(reply))
        reply=' '.join(p for p in parts if 'מגבת' not in p).strip()
        return policy + (' '+reply if reply else '')
    if 'מגבת' in customer and policy not in reply:
        return policy+' '+reply
    return reply


def numbered_item(text):
    # A cardinal count of panels is not the ordinal second shower.
    if re.match(r'^\s*שני\s+(?:קבועים|מקלחונים|חלקים|צדדים|לוחות|דלתות)\b', text):
        return None
    matches = re.findall(r'(?:מקלחון\s*(?:ה)?|למקלחון\s*(?:ה)?|אמבטיון\s*(?:ה)?|^(?:ה)?)(ראשון|שני|שלישי|רביעי|חמישי|שישי)\b', text)
    return ORDINALS.get(matches[-1]) if matches else None


def order_inventory(history):
    """Recover explicitly requested products, never dimensions from image analysis."""
    count, mixed = 1, False
    for message in history:
        if message.get('role') != 'user':
            continue
        text = str(message.get('content') or '').split('[לקוח צירף', 1)[0]
        explicit=re.search(r'(?<!\d)(\d{1,2}|ארבעה|ארבע)\s*מקלחונים',text)
        if explicit:
            count=max(count,int(explicit[1]) if explicit[1].isdigit() else 4)
        if re.search(r'(?:3|שלושה)\s*מקלחונים', text):
            count = max(count, 3)
        elif re.search(r'(?:2|שני|שתי)\s*מקלחונים|מקלחונים\s+(?:ל|ב)?(?:שני|שתי|שניי?ם|2)\s*(?:ה)?חדרים', text):
            count = max(count, 2)
        bath = re.search(r'אמבטיון|מקלחון\s+באמבטיה', text)
        shower = re.search(r'מקלחון\s+(?:בשירותים|ה?שירותים)', text)
        if bath and shower:
            count = max(count, 2)
            mixed = ('אמבטיון', 'מקלחון') if bath.start() < shower.start() else ('מקלחון', 'אמבטיון')
    inventory,_=written_inventory(history)
    return max(count,len(inventory)), mixed


def item_context(prior, history, customer):
    state = deepcopy(prior or {})
    last_reply = next((str(m.get('content') or '') for m in reversed(history[:-1])
                       if m.get('role') == 'assistant'), '')
    count, mixed = order_inventory(history)
    inventory,groups=written_inventory(history)
    seed=hashlib.sha256(json.dumps(inventory,sort_keys=True,ensure_ascii=False).encode()).hexdigest() if inventory else None
    fresh_inventory=bool(seed and state.get('inventory_seed')!=seed)
    count = max(count, int(state.get('expected_sales_item_count') or 1), len(state.get('sales_items') or {}))
    target = numbered_item(str(customer))
    baths=[n for n,s in inventory.items() if s.get('product')=='אמבטיון']
    if len(baths)==1 and ('אמבטיון' in str(customer) or
            re.search(r'נעבור.{0,15}אמבטיון|לאמבטיון|באמבטיון',last_reply) or
            (state.get('product')=='אמבטיון' and inventory.get(str(state.get('active_sales_item')),{}).get('product')!='אמבטיון')):
        target=baths[0]
    if mixed and 'אמבטיון' in str(customer):
        target = str(mixed.index('אמבטיון') + 1)
    elif mixed and re.search(r'מקלחון\s+(?:בשירותים|ה?שירותים)', str(customer)):
        target = str(mixed.index('מקלחון') + 1)
    if not target and not re.search(r'יקר|זול|להשוות|השוואה|הצעה אחרת|תקציב|מאשר|מאשרת', str(customer)) and len(set(re.findall(r'מקלחון (?:ה)?(?:ראשון|שני|שלישי|רביעי|חמישי|שישי)',last_reply)))<2 and re.search(r'נעבור|למקלחון|במקלחון|מה.{0,15}מקלחון', last_reply):
        target = numbered_item(last_reply)
    multiple = bool(count > 1 or state.get('sales_items') or target or re.search(
        r'(?:[23]|שני|שתי|שלושה)\s*מקלחונים', str(customer)))
    if not multiple:
        if no_customer_photo(customer):state['customer_photo_unavailable']=True
        return capture_spatial_answer(capture_layout_geometry(state, customer, last_reply), customer, last_reply)
    active = str(state.get('active_sales_item') or '1')
    items = state.setdefault('sales_items', {})
    if active not in items or any(key in state for key in ('configuration','width_cm','glass_type')):
        items[active] = {k: deepcopy(state[k]) for k in FIELDS if k in state}
    count = max(count, int(target or active))
    state['expected_sales_item_count'] = count
    if groups:state['sales_item_groups']=groups
    for number in range(1, count + 1):
        item = items.setdefault(str(number), {})
        if str(number) in inventory:
            old_product=item.get('product')
            if fresh_inventory and old_product and old_product!=inventory[str(number)]['product']:
                group=next((g for g in groups if str(number) in g),[])
                sibling=next((items[n] for n in group if n!=str(number) and n in items),{})
                confirmed=any(m.get('role')=='user' and re.fullmatch(r'כן[.!\s]*',str(m.get('content') or ''))
                    and i>0 and re.search(r'בשני המקלחונים.{0,100}בלי.{0,40}קבוע',str(history[i-1].get('content') or ''))
                    for i,m in enumerate(history))
                if confirmed and sibling.get('solution_agreed') and sibling.get('configuration')==item.get('configuration'):
                    item['solution_agreed']=True
            if fresh_inventory:item['product']=inventory[str(number)]['product']
            else:item.setdefault('product',inventory[str(number)]['product'])
            for k,v in inventory[str(number)].items():item.setdefault(k,deepcopy(v))
        if mixed and not inventory:
            item.setdefault('product', mixed[number - 1] if number <= len(mixed) else 'מקלחון')
            if item.get('product') == 'מקלחון':
                for message in history:
                    if message.get('role') != 'user':
                        continue
                    written = str(message.get('content') or '').split('[לקוח צירף', 1)[0]
                    service = re.search(r'מקלחון\s+(?:בשירותים|ה?שירותים)', written)
                    if service and 'קבוע' in written[service.start():] and 'מתקפל' in written[service.start():]:
                        item.setdefault('requested_layout', 'צד קבוע וצד מתקפל')
    if len(baths)==1:
        previous=''
        for m in history:
            text=str(m.get('content') or '').split('[לקוח צירף',1)[0]
            if m.get('role')=='user' and re.search(r'רק\s*(?:את\s*)?(?:הצד\s*)?(?:הארוך|תארוך|ארוך)',text):
                items[baths[0]]['front_only']=True
            if m.get('role')=='user' and 'אמבטיון' in previous and not re.search(r'ארון|אסלה|גובה',previous+text):
                value=re.search(r'(\d+\.\d+|\d{2,3})(?!\d)',text)
                if value:
                    width=float(value[1]);items[baths[0]].setdefault('width_cm',int(width*100) if width<10 else width)
            previous=text
    if seed:state['inventory_seed']=seed
    target = target or active
    if target != active:
        for key in FIELDS:
            state.pop(key, None)
        state.update(deepcopy(items.get(target, {})))
    state['active_sales_item'] = target
    if count > 1 and len((state.get('combined_offer') or {}).get('items') or []) < count:
        state.pop('combined_offer', None)
        state.pop('validated_quote', None)
    if state.get('product')=='אמבטיון' and state.get('front_only'):
        state.pop('second_width_cm',None)
        if str(state.get('configuration') or '').startswith('פינתי'):
            state.pop('configuration',None);state['solution_agreed']=False
    state=capture_layout_geometry(slider_specs(state), customer, last_reply if target==active else '')
    state=capture_spatial_answer(state, customer, last_reply if target==active else '')
    if no_customer_photo(customer):state['customer_photo_unavailable']=True
    for key in ('layout_geometry','door_obstruction','customer_photo_unavailable','obstacle_side','obstacle_clearance_cm','shower_depth_cm'):
        if key in state:items[target][key]=state[key]
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


def bundle_offer(state, calculator, allow_single=False):
    """Calculate every selected item; never issue an incomplete order total."""
    items=state.get('sales_items') or {}
    if len(items)<max(int(state.get('expected_sales_item_count') or 1), (1 if allow_single else 2)):
        return None
    offers=[]
    for number, original in sorted(items.items(),key=lambda pair:int(pair[0])):
        specs=slider_specs(original)
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
    if offer.get('kind') == 'kitchen_cladding':
        return 'מצורפת הצעת המחיר לחיפוי המטבח. המפרט, המחיר והתנאים נמצאים בקובץ. מתאים לך לאשר את ההצעה?'
    if len(offer['items']) > 1 and any('אמבטיון' in str(i['specification'].get('product') or '') for i in offer['items']):
        return 'מצורפת הצעת המחיר המלאה לכל הפריטים שבחרנו. המפרטים, המחירים והתנאים נמצאים בקובץ. מתאים לך לאשר את ההצעה המלאה?'
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
    label = LABELS.get(number, number)
    layout = (' עם ' + str(other['requested_layout']) + ' שביקשת') if other.get('requested_layout') else ''
    other=slider_specs(dict(other,height_cm=preliminary_height(other)))
    question = ('מה המידות המשוערות שלו?' if not other.get('width_cm') else missing_detail(other))
    if (not other.get('handles') and specs.get('handles')==['ידית כפתור','ידית כפתור']
            and other.get('configuration')==specs.get('configuration')
            and other.get('width_cm')==specs.get('width_cm') and other.get('finish')==specs.get('finish')):
        question='גם כאן תרצה שתי ידיות כפתור?'
    next_product='אמבטיון' if 'אמבטיון' in str(other.get('product') or '') else 'מקלחון'
    scope='לשניהם' if len(items)==2 else 'לכל הפריטים'
    return (f'סיכמנו את פרטי {product} שבחרת. '
            f'נמשיך ל{next_product} {label}{layout} כדי להשלים את ההצעה {scope}. ' + question)
