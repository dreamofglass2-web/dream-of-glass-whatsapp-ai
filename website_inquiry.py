"""Customer-reported website arrival, only from authenticated business inbound."""
import re
PATTERN=r'(?:הגעתי|באתי|פניתי)(?:\s+אליכם)?\s+(?:דרך\s+האתר|מהאתר)(?:\s+שלכם)?'

def arrives_from_website(text):
    text=str(text or '')
    match=re.search(PATTERN,text)
    return bool(match and not re.search(r'(?:לא|בכלל לא)\s*$',text[max(0,match.start()-20):match.start()]))

def greeting_only(text):
    return bool(re.fullmatch(r'\s*(?:(?:היי|הי|שלום|אהלן|בוקר טוב|ערב טוב)[!,.\s]*)?(?:אני\s+)?'+PATTERN+r'[!?,.\s]*',str(text or '')))
