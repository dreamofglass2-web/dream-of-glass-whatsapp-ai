"""Pure read-only projection of saved conversations and legacy quote evidence."""
import hashlib
import json
from decimal import Decimal,InvalidOperation
from crm_lab.lead_preview import map_leads,LeadPreviewError,text

def project_detail(row,*,synthetic=True):
    customer=map_leads([row],synthetic=synthetic)['customers'][0]
    history=row.get('conversation',[])
    if not isinstance(history,list) or len(history)>1000:
        raise LeadPreviewError('Complete conversation exceeds supported bounds; not truncated')
    messages=[]
    for index,message in enumerate(history):
        if not isinstance(message,dict) or message.get('role') not in ('user','assistant'):
            raise LeadPreviewError('Unsupported saved message role')
        content=message.get('content');attachments=0
        if isinstance(content,str):body=content
        elif isinstance(content,list):
            parts=[]
            for block in content:
                if not isinstance(block,dict):raise LeadPreviewError('Invalid saved message block')
                if block.get('type')=='text':
                    value=block.get('text');text(value,20000);parts.append(value)
                elif block.get('type')=='image_url':attachments+=1
                else:raise LeadPreviewError('Unsupported saved message block')
            body='\n'.join(parts)
        else:raise LeadPreviewError('Invalid saved message content')
        if not isinstance(body,str) or len(body)>20000:raise LeadPreviewError('Saved message too large')
        raw=json.dumps([customer['id'],index,message['role'],body,attachments],ensure_ascii=False).encode()
        messages.append({'id':'message-'+hashlib.sha256(raw).hexdigest(),'ordinal':index,
                         'role':message['role'],'content':body,'attachment_count':attachments,
                         'sent_at':None,'delivery_verified':False})
    if len(json.dumps(messages,ensure_ascii=False).encode())>700000:
        raise LeadPreviewError('Complete conversation exceeds supported bounds; not truncated')
    quote=row.get('legacy_quote');evidence=None
    if quote is not None:
        if not isinstance(quote,dict):raise LeadPreviewError('Invalid saved quote evidence')
        if quote.get('issued') is True:
            try:
                value=quote.get('amount_ils_pre_vat')
                if isinstance(value,bool):raise ValueError
                amount=Decimal(str(value))
                if not amount.is_finite() or amount<=0 or amount>Decimal('9999999999.99') or amount!=amount.quantize(Decimal('.01')):raise ValueError
            except (ValueError,InvalidOperation):raise LeadPreviewError('Invalid saved quote amount') from None
            specification={}
            for key in ('configuration','glass_type','finish','width_cm','second_width_cm','height_cm'):
                value=quote.get(key)
                if value is not None:
                    if key.endswith('_cm'):
                        try:
                            if isinstance(value,bool):raise ValueError
                            number=Decimal(str(value))
                            if not number.is_finite() or number<0 or number>10000:raise ValueError
                        except (ValueError,InvalidOperation):raise LeadPreviewError('Invalid saved quote dimension') from None
                        specification[key]=str(number)
                    else:specification[key]=text(value,200)
            handles=quote.get('handles')
            if handles is not None:
                if not isinstance(handles,list) or len(handles)>4:raise LeadPreviewError('Invalid saved handles')
                specification['handles']=[text(v,100) for v in handles]
            evidence={'amount_cents':int(amount*100),'currency':'ILS','vat_included':False,
                      'specification':specification,'recorded_approved':quote.get('approved') is True,
                      'verified_approval':False,'version':None,'evidence_kind':'legacy_latest_snapshot',
                      'limitations':['no_immutable_version_history','approval_not_receipt_verified']}
    callback=None
    if customer['legacy_status']=='ממתין לחזרה':
        callback={'source_status':customer['legacy_status'],'requested_time_text':customer['callback_text'],
                  'due_at':None,'request_id':customer['callback_request_id'],'requested_at':customer['callback_requested_at'],
                  'identity_quality':'durable_request_id' if customer['callback_request_id'] else 'legacy_state_without_request_id',
                  'read_only':True}
    return {'customer':customer,'conversation':messages,'conversation_complete':True,
            'conversation_timestamps_available':False,'callback':callback,'legacy_quote':evidence,
            'quote_versions':[],'synthetic':synthetic,'read_only':True}
