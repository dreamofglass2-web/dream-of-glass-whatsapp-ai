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
    """Keep current choices when discussing needs or a past product."""
    if not isinstance(data,dict):
        return data
    if re.search(r'חדר אחר|מקלחון אחר|מראה|מחיצה|מעקה|חיפוי|אמבטיון',customer):
        return data
    if re.fullmatch(r'\s*\d+(?:[.,]\d+)?\s*',customer):
        return data
    result=dict(data)
    changes={
        'configuration':r'דלת|קבוע|פינתי|חזית|הזזה|הרמוניקה|בין.*קירות',
        'glass_type':r'זכוכית|שקופ|קליר|חלבי|חלבית|אסיד|אנטיסן|פיפיטה|ברונזה',
        'finish':r'פרזול|גוון|צבע|שחור|ניקל|גרפיט|ברונזה|זהב|לבן|כרום',
        'handles':r'ידית|ידיות|כפתור|מגבת',
        'width_cm':r'רוחב|מידה|מידות|\d+\s*[/×x]\s*\d+',
        'second_width_cm':r'רוחב|מידה|מידות|צלע|צד|\d+\s*[/×x]\s*\d+',
        'height_cm':r'גובה',
    }
    past=bool(re.search(r'היה לי|הקודם|בעבר|אהבתי',customer)) and not re.search(r'רוצה|בוחר|תשנה|תחליף|במקום',customer)
    for field,pattern in changes.items():
        if (prior or {}).get(field) is not None and (past or not re.search(pattern,customer)):
            result[field]=prior[field]
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


def comparison_turn(history, prior, customer, calculate, bom, glass_types, finishes):
    """Compare alternatives for one shower; never treat them as extra orders."""
    text=str(customer or '')
    saved=prior.get('quote_comparison') or {}
    requesting=bool(re.search(r'מחיר|עול|יעל|עלות|הצעה',text))
    configs=[]
    if requesting:
        if re.search(r'(?:2|שני)\s+קבועים.{0,8}(?:2|שתי)\s+דלתות',text):
            configs.append('פינתי 2 קבועים + 2 דלתות')
        if re.search(r'הרמוניקה',text):configs.append('פינתי הרמוניקה')
        # Standalone two doors, not the suffix of the fixed-panel alternative.
        stripped=re.sub(r'(?:2|שני)\s+קבועים.{0,8}(?:2|שתי)\s+דלתות','',text)
        if re.search(r'(?:2|שתי)\s+דלתות',stripped):configs.insert(0,'פינתי 2 דלתות')
    if len(configs)<2:
        if not saved.get('pending'):return None
        if re.search(r'מראה|מחיצה|חיפוי|מקלחון (?:שני|אחר)|תמונה|אחריות|לא מעוניין',text):return None
        configs=list(saved['configurations'])
    data=dict(saved.get('specification') or {})
    for key in ('width_cm','second_width_cm','height_cm','glass_type','finish','handles'):
        if prior.get(key) is not None:data[key]=prior[key]
    users=[str(m.get('content') or '') for m in history if m.get('role')=='user']
    # Current dimensions override prior state. History is already scoped by reset.
    for turn in users:
        pair=re.search(r'(\d{2,3})\s*[/xX×]\s*(\d{2,3})',turn)
        if pair:data.update(width_cm=int(pair[1]),second_width_cm=int(pair[2]))
        height=re.search(r'גובה\s*(\d{2,3})',turn)
        if height:data['height_cm']=int(height[1])
        for field,options in (('glass_type',glass_types),('finish',finishes)):
            matches=[v for v in options if v in turn]
            if matches:data[field]=max(matches,key=len)
        if re.search(r'כפתור',turn):data['handle_choice']='ידית כפתור'
        elif re.search(r'ידית מגבת|ידיות מגבת',turn):data['handle_choice']='ידית מגבת'
    if not data.get('handle_choice') and data.get('handles') and len(set(data['handles']))==1:
        data['handle_choice']=data['handles'][0]
    data.setdefault('height_cm',200)
    state={'pending':True,'configurations':configs,'specification':data}
    result=dict(prior,quote_comparison=state)
    if not data.get('width_cm') or not data.get('second_width_cm'):
        return 'אפשר להשוות את האפשרויות. מה המידות המשוערות של שתי הצלעות?',result
    if not data.get('glass_type'):
        return 'נחשב את האפשרויות לאותו מפרט, כדי שההשוואה תהיה ברורה. איזה סוג זכוכית תרצה?',result
    if not data.get('finish'):
        return 'איזה גוון פרזול תרצה לצורך השוואת המחירים?',result
    if not data.get('handle_choice'):
        return 'לצורך התמחור, תרצה ידיות כפתור או ידיות מגבת?',result
    offers=[]
    for config in configs:
        spec=dict(data,product='מקלחון',configuration=config)
        count=bom[config].get('ידית כפתור',0)+bom[config].get('ידית מגבת',0)
        spec['handles']=[data['handle_choice']]*count
        amount=calculate(spec)
        if amount is None:
            return 'המידות או המפרט האלה דורשים בדיקת תמחור, ולכן לא אוכל לתת להם מחיר אוטומטי מדויק.',result
        offers.append(dict(spec,amount_ils_pre_vat=amount))
    state.update(pending=False,offers=offers)
    lines=[f"{o['configuration']}: ₪{o['amount_ils_pre_vat']:,.0f}" for o in offers]
    reply=(f"להשוואה, לפי {data['width_cm']}×{data['second_width_cm']} ס״מ, גובה {data['height_cm']} ס״מ, זכוכית {data['glass_type']}, פרזול {data['finish']} ו{data['handle_choice']}:\n"+
           '\n'.join(lines)+
           '\nהמחירים לפני מע״מ וכוללים מדידה, הובלה והתקנה. זו הצעה ראשונית; המידות וההתאמה לפתיחה ייבדקו בשטח, ושינוי מפרט או מידות עשוי לשנות את המחיר. אלה חלופות לאותו מקלחון, ולא סכום להזמנת כולן.')
    return reply,result
