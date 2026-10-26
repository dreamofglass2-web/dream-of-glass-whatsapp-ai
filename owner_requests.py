"""Owner request summaries and quote readiness signals, without guessed facts."""
import re
QUOTE_REASON = 'הכנת הצעת מחיר על ידי אלירן'
CALLBACK_REASON = 'משימת חזרה ללקוח'
def conversation_summary(history, reason, preferred=None):
    lines = [reason]
    if preferred:
        lines.append('זמן מבוקש לחזרה: ' + preferred)
    statements = [str(m.get('content') or '').split('[לקוח צירף', 1)[0].strip() for m in history if m.get('role') == 'user']
    lines.extend('לקוח: ' + text[:420] for text in statements[-10:] if text)
    return '\n'.join(lines)[:5000]
def unavailable_quote(reply, data, prior, history):
    answer = str(reply or '')
    if re.search(r'(?:אין לי|לא יכול|לא אוכל|אין אפשרות).{0,60}(?:הצע[הת]|קובץ|מחיר)|(?:הפרטים|פרטי).{0,25}(?:הושלמו|מוכנים).{0,40}הצע|(?:המחיר יופיע|מכין לך הצע|אכין לך הצע|ההצעה תכלול)', answer):
        return True
    previous = next((str(m.get('content') or '') for m in reversed(history[:-1]) if m.get('role') == 'assistant'), '')
    current = str(history[-1].get('content') or '') if history else ''
    return bool(re.fullmatch(r'\s*(?:כן|אוקי|אוקיי|בסדר|בטח|תכין|יאללה)[.!\s]*', current) and re.search(r'(?:להכין|שאכין|אכין).{0,25}הצעת? מחיר', previous))
