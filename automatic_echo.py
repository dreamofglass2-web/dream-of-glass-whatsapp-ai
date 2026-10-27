"""Exact configured WhatsApp Business auto-replies never imply human takeover."""
import hashlib
import os
import re

def fingerprint(text):
    return hashlib.sha256(str(text or '').replace('\r\n','\n').strip().encode('utf-8')).hexdigest()

def is_automatic_echo(message, env=None):
    env=os.environ if env is None else env
    hashes={v.strip().lower() for v in env.get('BUSINESS_AUTOMATIC_ECHO_HASHES','').split(',')
            if re.fullmatch(r'[a-fA-F0-9]{64}',v.strip())}
    return bool(hashes and fingerprint(message.get('text')) in hashes)
