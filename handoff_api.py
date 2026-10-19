"""Signed owner controls; return queues a durable continuation, never sends inline."""
import hashlib, hmac, json, re, time
from datetime import datetime, timezone
from flask import request, Response
from contextlib import closing
from handoff_state import HandoffError
from handoff_store import read_state, owner_action


def register_routes(app, *, connect, ensure, enabled, key_hex):
    def handle():
        key_text = key_hex()
        if not enabled() or not re.fullmatch(r'[a-f0-9]{64}', key_text or ''):
            return Response('Control unavailable', status=503)
        key = bytes.fromhex(key_text)
        if request.content_length and request.content_length > 40000:
            return Response('Request too large', status=413)
        raw = request.get_data(cache=True)
        if len(raw) > 40000:
            return Response('Request too large', status=413)
        target = request.path + ('?' + request.query_string.decode('ascii') if request.query_string else '')
        stamp, nonce, signature = (request.headers.get(k, '') for k in
            ('X-CRM-Timestamp', 'X-CRM-Nonce', 'X-CRM-Signature'))
        if not re.fullmatch(r'\d{1,12}', stamp) or abs(int(time.time())-int(stamp)) > 300 or not re.fullmatch(r'[a-f0-9]{32}', nonce):
            return Response('Authentication required', status=401)
        canonical = '\n'.join([request.method, target, stamp, nonce, hashlib.sha256(raw).hexdigest()]).encode()
        expected = 'sha256=' + hmac.new(key, canonical, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return Response('Authentication required', status=401)
        try:
            if request.method == 'GET':
                if raw or set(request.args)-{'phone'} or any(len(request.args.getlist(k))!=1 for k in request.args):
                    raise HandoffError('Invalid request')
                phone = request.args.get('phone')
                action = None
            else:
                if request.args:
                    raise HandoffError('Invalid request')
                payload = json.loads(raw)
                if not isinstance(payload, dict) or set(payload) != {'phone', 'expectedRevision', 'action'}:
                    raise HandoffError('Invalid request')
                phone, action = payload['phone'], payload['action']
            if phone is not None and not re.fullmatch(r'\+?[1-9]\d{7,14}', phone):
                raise HandoffError('Invalid customer')
            if request.method == 'POST' and phone is None:
                raise HandoffError('Customer required')
            ensure()
            with closing(connect()) as connection, connection:
                with connection.cursor() as cursor:
                    cursor.execute('DELETE FROM yossi_control_nonces WHERE expires<now()')
                    cursor.execute("INSERT INTO yossi_control_nonces(nonce,expires) VALUES(%s,now()+interval '601 seconds') ON CONFLICT DO NOTHING RETURNING nonce", (nonce,))
                    if not cursor.fetchone():
                        return Response('Repeated request', status=401)
                    if phone is None:
                        cursor.execute("SELECT phone,state->>'owner',state->'revision',state->>'silenced_callback_id',state->>'silenced_inbound_at',state->'escalation' FROM yossi_handoffs ORDER BY phone LIMIT 2001")
                        rows = cursor.fetchall()
                        if len(rows)>2000:
                            raise HandoffError('Too many controls')
                        result = {'controls':[{'phone':p,'owner':o,'revision':v,'silencedCallbackId':cb,'silencedInboundAt':at,'escalation':e} for p,o,v,cb,at,e in rows]}
                    else:
                        cursor.execute('SELECT 1 FROM glass_leads WHERE phone=%s', (phone,))
                        if not cursor.fetchone():
                            return Response('Customer not found',status=404)
                        now = datetime.now(timezone.utc).isoformat()
                        state = owner_action(cursor, phone, payload['expectedRevision'], action, now) if action else read_state(cursor,phone)
                        result = {'phone':phone,'state':state}
            result.update(source_scope='handoff-v1', request_nonce=nonce)
            body = json.dumps(result,ensure_ascii=False,separators=(',',':')).encode()
            sig = 'sha256='+hmac.new(key,b'response\n'+nonce.encode()+b'\n'+body,hashlib.sha256).hexdigest()
            return Response(body,headers={'Content-Type':'application/json','Cache-Control':'no-store','X-CRM-Response-Signature':sig})
        except HandoffError as error:
            if str(error).startswith('Owner summary required'):
                return Response('Owner summary required',status=400,headers={
                    'X-CRM-Error-Code':'summary_required','Cache-Control':'no-store'})
            status = 409 if str(error).startswith('Conversation changed') else 400
            return Response('Invalid control action; reload if state changed',status=status)
        except (ValueError, TypeError, KeyError):
            return Response('Invalid control action',status=400)
        except Exception:
            app.logger.error('OPERATOR_CONTROL_STORAGE_FAILED')
            return Response('Control storage unavailable',status=503)
    app.add_url_rule('/v1/handoff','crm_operator_control',handle,methods=['GET','POST'])

