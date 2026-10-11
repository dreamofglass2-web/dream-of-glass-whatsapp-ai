"""Persist callback identity only; no message sending or price calculation."""
from uuid import uuid4

def save_callback_record(cursor,phone,preferred_time):
    request_id=str(uuid4())
    cursor.execute("""INSERT INTO glass_leads(phone,status,callback_time,
        callback_request_id,callback_requested_at)
        VALUES (%s,'ממתין לחזרה',%s,%s,now())
        ON CONFLICT(phone) DO UPDATE SET
        callback_request_id=CASE WHEN glass_leads.status='ממתין לחזרה'
          AND glass_leads.callback_time=EXCLUDED.callback_time
          AND glass_leads.callback_request_id IS NOT NULL
          AND glass_leads.callback_request_inbound_at IS NOT NULL
          AND glass_leads.callback_request_inbound_at=glass_leads.last_inbound_at
          THEN glass_leads.callback_request_id ELSE EXCLUDED.callback_request_id END,
        callback_requested_at=CASE WHEN glass_leads.status='ממתין לחזרה'
          AND glass_leads.callback_time=EXCLUDED.callback_time
          AND glass_leads.callback_request_id IS NOT NULL
          AND glass_leads.callback_request_inbound_at IS NOT NULL
          AND glass_leads.callback_request_inbound_at=glass_leads.last_inbound_at
          THEN glass_leads.callback_requested_at ELSE EXCLUDED.callback_requested_at END,
        callback_request_inbound_at=glass_leads.last_inbound_at,
        status='ממתין לחזרה',callback_time=EXCLUDED.callback_time,updated_at=now()
        RETURNING callback_request_id""",(phone,preferred_time or 'ממתין לתיאום',request_id))
    row=cursor.fetchone()
    return row['callback_request_id'] if isinstance(row,dict) else row[0]
