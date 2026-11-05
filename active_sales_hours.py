"""Continue an active two-way session after closing, never start a new night chat."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
TZ=ZoneInfo('Asia/Jerusalem')
IDLE=timedelta(hours=1)


def active_session(history,context,now):
    if not isinstance(history,list) or not isinstance(context,dict) or now.tzinfo is None:return False
    if context.get('needs_human') or str(context.get('no_followups','')).lower()=='true' or context.get('stage') in ('closed','completed','canceled','handoff'):return False
    tail=[]
    previous=now
    for message in reversed(history):
        if not isinstance(message,dict) or message.get('role') not in ('assistant','user'):continue
        try:
            at=datetime.fromisoformat(str(message.get('at','')).replace('Z','+00:00'))
            if at.tzinfo is None:return False
        except (ValueError,TypeError):return False
        if at>previous or previous-at>IDLE:break
        tail.append((message['role'],at.astimezone(TZ)))
        previous=at
    # The persisted session must include an actual customer turn and an assistant
    # answer in working hours. A template alone cannot enable night outreach.
    return (any(role=='user' for role,_ in tail)
            and any(role=='assistant' for role,_ in tail)
            and any(at.weekday() in (6,0,1,2,3) and 8<=at.hour<20 for role,at in tail))
