"""Pure bounded mapping of existing lead fields. No connection or writes."""
from datetime import datetime, timezone
import hashlib
import re

class LeadPreviewError(ValueError):
    pass

STATUS_STAGE = {'חדש':0,'בטיפול':1,'ממתין לחזרה':1,'ממתין לתמונה':1,
                'ממתין לתמחור':1,'הצעה ניתנה':2}

def text(value,limit):
    if not isinstance(value,str) or len(value)>limit:
        raise LeadPreviewError('Invalid lead text field')
    return value.strip()

def timestamp(value):
    try:
        parsed=value if isinstance(value,datetime) else datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None: raise ValueError
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError,ValueError):
        raise LeadPreviewError('Explicit source timestamp with timezone required') from None

def preview_leads(rows,*,has_more=False):
    return map_leads(rows,has_more=has_more,synthetic=True)

def map_leads(rows,*,has_more=False,synthetic=True):
    """Map explicitly selected rows; never imply verified delivery or approval.

    Missing names/products remain explicitly incomplete. Legacy closed/unknown
    statuses require review, not a fabricated approved quote or installation.
    Legacy callback text is shown verbatim and never schedules an action.
    """
    if not isinstance(rows,list) or len(rows)>300 or type(has_more) is not bool or type(synthetic) is not bool:
        raise LeadPreviewError('Bounded explicit fixture batch required')
    seen=set();customers=[]
    for row in rows:
        if not isinstance(row,dict): raise LeadPreviewError('Lead record required')
        phone=text(row.get('phone'),20)
        pattern=r'000[0-9]{6,17}' if synthetic else r'\+?[1-9][0-9]{7,14}'
        if not re.fullmatch(pattern,phone):
            raise LeadPreviewError('Dummy recipient required' if synthetic else 'Invalid source recipient')
        identity=phone.lstrip('+')
        if identity in seen: raise LeadPreviewError('Duplicate source phone; no implicit merge')
        seen.add(identity)
        status=text(row.get('status'),100)
        name=text(row.get('name',''),100);product=text(row.get('product',''),200)
        callback=text(row.get('callback_time',''),300)
        archived=status=='לא רלוונטי';stage=STATUS_STAGE.get(status)
        reasons=[]
        if not name: reasons.append('missing_name')
        if not product: reasons.append('missing_product')
        if stage is None and not archived: reasons.append('legacy_status_requires_review')
        if callback: reasons.append('callback_text_requires_manual_review')
        request_id=row.get('callback_request_id')
        if request_id is not None and (not isinstance(request_id,str) or not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}',request_id)):raise LeadPreviewError('Invalid callback request identity')
        customers.append({'id':('preview-' if synthetic else 'source-')+hashlib.sha256(identity.encode()).hexdigest(),
            'source':'synthetic_glass_leads_fixture' if synthetic else 'glass_leads','source_phone':phone,
            'source_updated_at':timestamp(row.get('updated_at')),
            'callback_request_id':request_id,'callback_requested_at':timestamp(row['callback_requested_at']) if row.get('callback_requested_at') is not None else None,
            'source_created_at':timestamp(row['created_at']) if row.get('created_at') is not None else None,
            'last_inbound_at':timestamp(row['last_inbound_at']) if row.get('last_inbound_at') is not None else None,
            'manual_followup_completed_at':timestamp(row['manual_followup_completed_at']) if row.get('manual_followup_completed_at') is not None else None,
            'name':name or 'לקוח ללא שם','product':product or 'סוג עבודה טרם זוהה',
            'notes':text(row.get('notes',''),3000),'legacy_status':status,'stage':stage,
            'archived':archived,'callback_text':callback,'review_reasons':reasons,
            'quote_versions':[],'verified_delivery':False,'verified_approval':False,
            'tasks_created':0,'read_only':True})
    return {'mode':'synthetic_read_only_preview' if synthetic else 'read_only_source_export','live_connection_enabled':not synthetic,
            'customer_messages_sent':0,'has_more':has_more,'customers':customers,
            'review_count':sum(bool(c['review_reasons']) for c in customers)}
