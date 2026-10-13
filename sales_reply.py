"""Grounded facts for the consultant and bounded preservation of quote wording."""
import re


def quote_facts_for_turn(prior, customer, calculator):
    prior = prior or {}
    if not str(prior.get('product') or '').startswith('מקלחון'):
        return None
    # Changed jobs/materials need model extraction and a fresh authoritative check.
    if re.search(r'בעצם|תיקון|במקום|תחליף|תשנה|לשנות|חדר אחר|מקלחון אחר|מראה|מחיצה|מעקה|חיפוי|אמבטיון', customer):
        return None
    specs = {k:prior.get(k) for k in ('configuration','width_cm','second_width_cm',
              'height_cm','glass_type','finish','handles')}
    height = re.search(r'גובה\s*(\d{2,3})', customer)
    width = re.search(r'רוחב\s*(\d{2,3})', customer)
    if height:
        specs['height_cm'] = int(height.group(1))
    if width:
        specs['width_cm'] = int(width.group(1))
    if specs['height_cm'] is None:
        specs['height_cm'] = 200
    try:
        amount = calculator(specs)
    except (TypeError, ValueError, KeyError):
        return None
    if amount is None:
        return None
    return {'amount_ils_pre_vat':amount, 'display_amount_ils':round(amount),
            'specification':specs, 'includes':['מדידה','הובלה','התקנה'],
            'preliminary':True, 'final_measurement_required':True,
            'specification_changes_may_change_price':True}


def safe_quote_wording(reply, amount):
    """Preserve phrasing only after calculator amount and required terms match."""
    text = str(reply or '')
    amounts = [float(a.replace(',', '')) for pair in re.findall(
        r'₪\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:₪|ש[״"]ח|שקלים)', text)
        for a in pair if a]
    if not amounts or any(a != round(amount) for a in amounts):
        return False
    if not re.search(r'לפני\s+מע[״"]?מ', text):
        return False
    if not all(term in text for term in ('מדידה','הובלה','התקנה','ראשונית')):
        return False
    if not re.search(r'בשטח|מידות\s+סופיות', text):
        return False
    if not re.search(r'שינוי.{0,90}מחיר|מחיר.{0,90}שינוי', text):
        return False
    if re.search(r'קבענו|תיאמתי|מחר|ביום|בשעה|הנחה|מקדמה|תשלומים|ציפוי|יש\s+אחריות\s+על\s+ה?זכוכית|אחריות\s+מלאה\s+לזכוכית|אטימות\s+מלאה|כולל\s+מע[״"]?מ|הבעלים\s+אישר', text):
        return False
    return True


def open_finish_question(reply, customer):
    """Change an unrequested list question without deleting the surrounding advice."""
    if re.search(r'איזה\s+(?:גוונים|צבעים).{0,15}(?:יש|קיימים)|אילו\s+(?:גוונים|צבעים)|במה\s+אפשר\s+לבחור', customer):
        return reply
    return re.sub(r'איזה\s+גוון\s+פרזול\s+(?:תרצו|תרצה|תרצי)[^.!?]{0,40}'
                  r'(?:שחור\s+או\s+כרום|כרום\s+או\s+שחור|שחור\s+או\s+ניקל|ניקל\s+או\s+שחור)[?]',
                  'איזה גוון פרזול תרצו?', reply)


def grounded_price_comparison(reply, amount, customer):
    """Allow only quoted total or a clearly relative customer-supplied gap."""
    gaps={int(v.replace(',','')) for v in re.findall(
        r'זול(?:ה)?(?:\s+יותר)?\s+ב[-־\s]*([\d,]+)\s*(?:שקל|ש[״"]ח|₪)', customer)}
    money=list(re.finditer(r'₪\s*([\d,]+)|([\d,]+)\s*(?:₪|ש[״"]ח|שקל(?:ים)?)', reply))
    if not money:
        return False
    for m in money:
        value=int((m.group(1) or m.group(2)).replace(',',''))
        if value==round(amount):
            continue
        relative=(re.match(r'\s*(?:יותר|פחות|(?:זה\s+)?פער|(?:זה\s+)?הפרש)',reply[m.end():]) or
                  re.search(r'(?:פער|הפרש)\s+(?:של\s+)?$',reply[max(0,m.start()-25):m.start()]))
        if value not in gaps or not relative:
            return False
    return True

def retain_known_quote_choices(prior, data, customer):
    """Only explicit customer changes may replace already known quote choices."""
    if not isinstance(data, dict):
        return data
    if re.search(r'חדר אחר|מקלחון אחר|מראה|מחיצה|מעקה|חיפוי|אמבטיון', customer):
        return data
    # Protect facts only on price/calculation turns, not answers to discovery
    # questions such as a bare new measurement or a newly accepted proposal.
    if re.fullmatch(r'\s*\d+(?:[.,]\d+)?\s*', customer):
        return data
    result = dict(data)
    changes = {
        'configuration':r'דלת|קבוע|פינתי|חזית|הזזה|הרמוניקה|בין.*קירות',
        'glass_type':r'זכוכית|שקופ|קליר|חלבי|חלבית|אסיד|אנטיסן|פיפיטה|ברונזה',
        'finish':r'פרזול|גוון|צבע|שחור|ניקל|גרפיט|ברונזה|זהב|לבן|כרום',
        'handles':r'ידית|ידיות|כפתור|מגבת',
        'width_cm':r'רוחב|מידה|מידות|\d+\s*[/×x]\s*\d+',
        'second_width_cm':r'רוחב|מידה|מידות|צלע|צד|\d+\s*[/×x]\s*\d+',
        'height_cm':r'גובה',
    }
    for field, pattern in changes.items():
        if (prior or {}).get(field) is not None and (not re.search(pattern, customer) or
                (re.search(r'היה לי|הקודם|בעבר|אהבתי', customer) and not re.search(r'רוצה|בוחר|תשנה|תחליף|במקום', customer))):
            result[field] = prior[field]
    return result

def normalize_sales_fields(data, configurations, glass_types, finishes):
    """Normalize only exact wording aliases of catalog values, never a new design."""
    if not isinstance(data,dict):
        return data
    result=dict(data)
    for field,allowed in (('configuration',configurations),('glass_type',glass_types),('finish',finishes)):
        value=result.get(field)
        if not isinstance(value,str) or value in allowed:
            continue
        candidate=value.strip()
        if field=='configuration':
            candidate=re.sub(r'^מקלחון\s+','',candidate)
            candidate=candidate.replace('חזיתי','חזית')
            candidate=re.sub(r'קבוע\s+ודלת', 'קבוע + דלת', candidate)
        elif field=='glass_type':
            candidate=re.sub(r'^זכוכית\s+','',candidate)
        else:
            candidate=re.sub(r'^פרזול\s+','',candidate)
        if candidate in allowed:
            result[field]=candidate
    return result

def sales_output_format(configurations, glass_types, finishes):
    """The API enforces catalog spelling and field types in the single model call."""
    properties={}
    for field in ('stage','action','next_missing_fact','reply','product'):
        properties[field]={'type':['string','null']} if field not in ('reply','stage','action') else {'type':'string'}
    for field,values in (('configuration',configurations),('glass_type',glass_types),('finish',finishes)):
        properties[field]={'type':['string','null'],'enum':list(values)+[None]}
    for field in ('width_cm','second_width_cm','height_cm'):
        properties[field]={'type':['number','null']}
    properties['handles']={'type':['array','null'],'items':{'type':'string','enum':['ידית כפתור','ידית מגבת']}}
    for field in ('quote_requested','solution_agreed','needs_human','send_handle_images','send_glass_images'):
        properties[field]={'type':'boolean'}
    return {'type':'json_schema','name':'yossi_sales_turn','strict':True,
            'schema':{'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}}
,reply[max(0,m.start()-25):m.start()]))
        if value not in gaps or not relative:
            return False
    return True

def retain_known_quote_choices(prior, data, customer):
    """Only explicit customer changes may replace already known quote choices."""
    if not isinstance(data, dict):
        return data
    if re.search(r'חדר אחר|מקלחון אחר|מראה|מחיצה|מעקה|חיפוי|אמבטיון', customer):
        return data
    # Protect facts only on price/calculation turns, not answers to discovery
    # questions such as a bare new measurement or a newly accepted proposal.
    if re.fullmatch(r'\s*\d+(?:[.,]\d+)?\s*', customer):
        return data
    result = dict(data)
    changes = {
        'configuration':r'דלת|קבוע|פינתי|חזית|הזזה|הרמוניקה|בין.*קירות',
        'glass_type':r'זכוכית|שקופ|קליר|חלבי|חלבית|אסיד|אנטיסן|פיפיטה|ברונזה',
        'finish':r'פרזול|גוון|צבע|שחור|ניקל|גרפיט|ברונזה|זהב|לבן|כרום',
        'handles':r'ידית|ידיות|כפתור|מגבת',
        'width_cm':r'רוחב|מידה|מידות|\d+\s*[/×x]\s*\d+',
        'second_width_cm':r'רוחב|מידה|מידות|צלע|צד|\d+\s*[/×x]\s*\d+',
        'height_cm':r'גובה',
    }
    for field, pattern in changes.items():
        if (prior or {}).get(field) is not None and (not re.search(pattern, customer) or
                (re.search(r'היה לי|הקודם|בעבר|אהבתי', customer) and not re.search(r'רוצה|בוחר|תשנה|תחליף|במקום', customer))):
            result[field] = prior[field]
    return result

def normalize_sales_fields(data, configurations, glass_types, finishes):
    """Normalize only exact wording aliases of catalog values, never a new design."""
    if not isinstance(data,dict):
        return data
    result=dict(data)
    for field,allowed in (('configuration',configurations),('glass_type',glass_types),('finish',finishes)):
        value=result.get(field)
        if not isinstance(value,str) or value in allowed:
            continue
        candidate=value.strip()
        if field=='configuration':
            candidate=re.sub(r'^מקלחון\\s+','',candidate)
            candidate=candidate.replace('חזיתי','חזית')
            candidate=re.sub(r'קבוע\\s+ודלת', 'קבוע + דלת', candidate)
        elif field=='glass_type':
            candidate=re.sub(r'^זכוכית\\s+','',candidate)
        else:
            candidate=re.sub(r'^פרזול\\s+','',candidate)
        if candidate in allowed:
            result[field]=candidate
    return result

def sales_output_format(configurations, glass_types, finishes):
    """The API enforces catalog spelling and field types in the single model call."""
    properties={}
    for field in ('stage','action','next_missing_fact','reply','product'):
        properties[field]={'type':['string','null']} if field not in ('reply','stage','action') else {'type':'string'}
    for field,values in (('configuration',configurations),('glass_type',glass_types),('finish',finishes)):
        properties[field]={'type':['string','null'],'enum':list(values)+[None]}
    for field in ('width_cm','second_width_cm','height_cm'):
        properties[field]={'type':['number','null']}
    properties['handles']={'type':['array','null'],'items':{'type':'string','enum':['ידית כפתור','ידית מגבת']}}
    for field in ('quote_requested','solution_agreed','needs_human','send_handle_images','send_glass_images'):
        properties[field]={'type':'boolean'}
    return {'type':'json_schema','name':'yossi_sales_turn','strict':True,
            'schema':{'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}}
