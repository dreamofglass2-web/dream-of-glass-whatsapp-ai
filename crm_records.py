"""Recorded conversation times and evidence-based CRM progress."""
from datetime import datetime, timezone


def stamp_new_messages(history, existing_count, recorded_at=None):
    at=recorded_at or datetime.now(timezone.utc).isoformat()
    return [dict(m, at=at) if i>=existing_count and not m.get('at') else dict(m)
            for i,m in enumerate(history)]


def conversation_status(history, context):
    quote=context.get('validated_quote') or {}
    if quote.get('issued') is True:
        return 'הצעה ניתנה'
    if context.get('product') and any(m.get('role')=='assistant' for m in history) and any(m.get('role')=='user' for m in history):
        return 'בטיפול'
    return 'חדש'
