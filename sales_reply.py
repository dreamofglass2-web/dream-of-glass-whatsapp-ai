"""Grounded facts for the consultant and bounded preservation of quote wording."""
import re
from sales_items import preliminary_height

# Hebrew word boundaries prevent words such as ניקרא from becoming price objections.
EXPENSIVE_WORD = r'(?<![א-ת])(?:יקר(?:ה|ים|ות)?|התייקר(?:ה|ו)?)(?![א-ת])'


def is_price_objection(text):
    return bool(re.search(EXPENSIVE_WORD +
        r'|(?<![א-ת])זול(?:ה|ים|ות)?(?![א-ת])|תקציב|הנחה|הנחות|להוזיל|תוזיל|תוריד.{0,15}מחיר|תעשה.{0,15}מחיר|'
        r'יש מה לעשות.{0,20}מחיר|חשבתי.{0,30}(?:מחיר|פחות|עד\s*\d)|'
        r'מחיר.{0,15}(?:גבוה|נמוך)|הציעו לי|מתחר.{0,35}(?:נותן|מציע|אותו|זהה)',str(text or '')))


def quote_facts_for_turn(prior, customer, calculator):
    prior = prior or {}
    if not str(prior.get('product') or '').startswith(('מקלחון', 'אמבטיון')):
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
        specs['height_cm'] = preliminary_height(dict(prior, **specs))
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

ROSE_GOLD = re.compile(r'(?<![\w])(?:רוז[\s-]*גולד|רוזגולד|rose[\s-]*gold)(?![\w])', re.I)


def canonical_finish_text(text):
    """Owner-confirmed business alias; no claim about another vendor's exact shade."""
    return ROSE_GOLD.sub('ברונזה', str(text or ''))


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
            candidate=canonical_finish_text(re.sub(r'^פרזול\s+','',candidate))
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
    properties['cladding_type']={'type':['string','null'],'enum':['צבע','הדפסה',None]}
    properties['cladding_color']={'type':['string','null']}
    properties['socket_count']={'type':['integer','null'],'minimum':0}
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
        elif re.search(r'ידית מגבת|ידיות מגבת',turn) or turn.strip()=='מגבת':data['handle_choice']='ידית מגבת'
    if not data.get('handle_choice') and data.get('handles') and len(set(data['handles']))==1:
        data['handle_choice']=data['handles'][0]
    data.setdefault('height_cm',200)
    state={'pending':True,'configurations':configs,'specification':data}
    result=dict(prior,quote_comparison=state)
    result.update({k:data[k] for k in ('width_cm','second_width_cm','height_cm','glass_type','finish') if data.get(k) is not None})
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


BUYER_SERVICE_BENEFIT = ('הסיבה שאני ממליץ לבחור אצלנו היא שיש לך כתובת אחת שמכירה את העבודה מהמדידה ועד השירות, '
                         'בלי שתצטרך לתאם בין מודד למתקין.')

PERSONAL_SERVICE_FACTS = ('אלירן בעל העסק מגיע בעצמו למדידה ולהתקנה, בלי קבלני משנה, '
                          'ומלווה אותך מההתחלה ועד הסוף וגם אם נדרש שירות אחר כך.')
PERSONAL_SERVICE_VALUE = PERSONAL_SERVICE_FACTS + ' ' + BUYER_SERVICE_BENEFIT


def personal_service_value(reply, customer, history, product=None):
    """Complete missing value facts, including when the model supplied only some."""
    text = str(customer or '')
    if not re.search(EXPENSIVE_WORD + r'|מחיר.{0,15}גבוה|הציעו לי|מתחר|להשוות|השוואה|הצעה אחרת|מישהו אחר.{0,15}זול', text):
        return reply
    if re.search(r'לא מעוניין|אל תפנ|אלך איתם|אסגור איתם|הולך איתם', text):
        return reply
    same_offer = bool(re.search(r'מתחר.{0,40}(?:אותו\s*(?:הדבר|דבר|מפרט)|זהה)', text))
    if same_offer:
        # The customer already answered equivalence; do not send them back to compare.
        reply = re.sub(r'(?:^|(?<=[.!?])\s+)[^.!?\n]*(?:אותו.{0,20}מפרט|מה.{0,20}(?:כולל|נותן))[^.!?\n]*\?\s*$', '', str(reply or '')).strip()
        if not reply:
            reply = 'גם כשפרטי ההצעות דומים, אני ממליץ להתקדם איתנו בזכות הליווי האישי לאורך העבודה וגם אחריה.'
    recent = [str(m.get('content') or '') for m in history[-7:] if m.get('role') == 'assistant']
    answers = [str(reply or '')] + recent
    additions = []
    facts = []
    if str(product or '').startswith(('מקלחון', 'אמבטיון')):
        if not any('פליז' in answer and 'פרימיום' in answer for answer in answers):
            facts.append('פרזול מפליז פרימיום')
        if not any(re.search(r'(?:7|שבע)\s*(?:שנות|שנים).{0,25}אחריות.{0,25}פרזול|אחריות.{0,25}פרזול.{0,25}(?:7|שבע)\s*(?:שנות|שנים)', answer) for answer in answers):
            facts.append('7 שנות אחריות על הפרזול')
        if not any(re.search(r'(?:שנה|שנת|1\s*שנ(?:ה|ת)).{0,20}אחריות.{0,20}התקנה|אחריות.{0,20}התקנה.{0,15}(?:שנה|שנת)|שנה.{0,10}(?:על\s+ההתקנה|ל?התקנה)', answer) for answer in answers):
            facts.append('שנה אחריות על ההתקנה')
    if facts:
        additions.append('אצלנו מקבלים ' + ', '.join(facts) + '.')
    personal_execution=any('אלירן' in answer and ('קבלני משנה' in answer or
        ('בעצמו' in answer and re.search(r'מדידה|מודד',answer) and re.search(r'התקנה|מתקין',answer)))
        for answer in answers)
    if not personal_execution:
        additions.append(PERSONAL_SERVICE_FACTS)
    elif not any('קבלני משנה' in answer for answer in answers):
        additions.append('העבודה מתבצעת בלי קבלני משנה.')
    # A fact list alone does not explain why the customer should choose this service.
    benefit_explained = any(re.search(
        r'כתובת אחת|כתובת שמכירה את העבודה|(?:נשאר|נשארת|יש לך|תהיה לך).{0,25}ה?כתובת|אותו אדם.{0,70}(?:מכיר|אחראי|מטפל)|בלי שתצטרך לתאם|'
        r'(?:כך|לכן|כדי|בשבילך|עבורך).{0,70}(?:שקט|תיאום|כתובת|מכיר.{0,15}העבודה)', answer)
        for answer in answers + additions)
    if not benefit_explained:
        additions.append(BUYER_SERVICE_BENEFIT)
    if not additions:
        return reply
    addition = ' '.join(additions)
    # Keep the customer's next step last, rather than placing a pitch after it.
    value = str(reply or '').strip()
    question = re.search(r'(?:^|(?<=[.!?])\s+)([^.!?\n]+\?)\s*$', value)
    if question:
        prefix = value[:question.start()].rstrip()
        return ' '.join(part for part in (prefix, addition, question.group(1).strip()) if part)
    return value + ' ' + addition


def shower_thickness_reply(customer, product):
    """Owner policy plus bounded material comparison, never a site safety verdict.

    Price requests and mixed technical/design requests stay in the usual flow.
    """
    if not str(product or '').startswith(('מקלחון', 'אמבטיון')):
        return None
    text = str(customer or '')
    thickness = bool(re.search(r'(?<!\d)[68]\s*(?:מ[״"׳\']?מ|מילימטר)', text))
    question = bool(re.search(r'למה|מדוע|מה\s+ההבדל|מה\s+החשיבות|מה\s+היתרון|בשביל\s+מה', text))
    if not (thickness and question):
        return None
    if re.search(r'מחיר|עולה|עלות|הצעה|אלירן|אדם|בטוח|בטיחות|תקן|שבר|סדק|רוחב|גובה|מידות|אחריות', text):
        return None
    return ('אני ממליץ להתקדם עם זכוכית מחוסמת 8 מ״מ; אצלנו לא עובדים עם 6 מ״מ. '
            'באותן מידות ותמיכות, 8 מ״מ קשיחה יותר ומתכופפת פחות, כך שהמקלחון מרגיש מוצק ויציב יותר. '
            'את הזכוכית אנחנו משלבים עם פרזול פליז פרימיום, ואלירן עצמו מגיע למדידה ולהתקנה, '
            'כדי להתאים לך את המקלחון החדש וללוות אותך גם בהמשך.')


def shower_six_mm_choice(customer, product, policy_replies=()):
    """Reject an unsupported purchase, distinguishing preference from old glass/negation."""
    if not str(product or '').startswith(('מקלחון', 'אמבטיון')):
        return None
    def normalize(value):
        return re.sub(r'(?<!\d)([68])\s*(?:מ[״"׳\']?מ|מילימטר(?:ים)?)', r'\1mm', str(value or ''))
    text = normalize(customer)
    explained = any('8mm' in normalize(reply) and re.search(r'לא.{0,35}6mm', normalize(reply))
                    for reply in policy_replies)
    # In an explicit thickness exchange, a short answer need not repeat the unit.
    # Do not reinterpret dimensions or quantities such as 6 panels or 80 cm.
    current_thickness_exchange = bool(policy_replies and '8mm' in normalize(policy_replies[-1])
        and re.search(r'לא.{0,35}6mm',normalize(policy_replies[-1])))
    if current_thickness_exchange:
        text = re.sub(r'(?<!\d)([68])(?=\s*[,!.?]|\s*$)',r'\1mm',text)
    if re.match(r'\s*(?:למה|מדוע|מה\s+(?:ההבדל|היתרון|החשיבות))', text):
        return None
    if re.search(r'אלירן|אדם|אחריות|סדק|נשבר|בטיחות|תקן|מראה|מחיצה|מעקה', text):
        return None
    # A negated preference cannot become an order for that thickness.
    negative = r'(?:לא|אינני|איני)\s+(?:רוצה|צריך|צריכה|מעוניין|מעוניינת|מבקש|מבקשת)(?:(?![68]mm).){0,35}'
    positive_text = re.sub(negative + r'6mm', '', text)
    wants_six = bool(re.search(
        r'(?:רוצה|צריך|צריכה|מבקש|מבקשת|מעוניין|מעוניינת|מחפש|מחפשת|מתעקש|מתעקשת|אפשר|רק|דווקא)'
        r'(?:(?!8mm).){0,60}6mm', positive_text) or re.search(
        r'(?:מחיר|עלות|הצעה|כמה.{0,12}עולה)(?:(?!8mm).){0,35}6mm|6mm.{0,20}(?:מחיר|כמה.{0,12}עולה)', positive_text) or re.fullmatch(r'\s*6mm[.!?\s]*', positive_text))
    rejects_eight = bool(re.search(negative + r'8mm', text))
    if explained and (wants_six or rejects_eight):
        return 'close'
    if wants_six or rejects_eight:
        return 'offer_eight'
    positive_eight = re.sub(negative + r'8mm', '', positive_text)
    if (re.search(r'(?:רוצה|צריך|צריכה|מעוניין|מעוניינת|אפשר)(?:(?!6mm).){0,35}8mm', positive_eight)
            or re.fullmatch(r'\s*(?:אני\s+)?8mm[.!?\s]*', positive_eight)):
        return 'accept_eight'
    return None


def no_discount_reply(reply):
    """The owner removed discounts; stale history cannot authorize an offer."""
    text = str(reply or '')
    if re.search(r'הנח(?:ה|ות)|קופון|\d+\s*(?:%|אחוז)|(?:להוריד|להפחית|להוריד לך|להפחית לך)\s+(?:את\s+)?ה?מחיר', text):
        return ('אנחנו לא נותנים הנחות. המחיר בהצעה הוא למפרט שבחרת, כולל מדידה, הובלה והתקנה. '
                'אפשר לבחון שינוי במפרט ולחשב הצעה חדשה. איזה חלק במפרט חשוב לך לשמור?')
    return reply
