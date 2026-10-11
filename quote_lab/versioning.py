from dataclasses import dataclass, replace

@dataclass(frozen=True)
class QuoteRecord:
    quote_id: str
    revision: int
    specification: str
    total: str
    status: str = 'draft'
    delivery_reference: str = ''
    approval_reference: str = ''

class QuoteLedger:
    def __init__(self):
        self.items = {}

    def draft(self, quote_id, spec, total):
        if not quote_id or not spec or not total:
            raise ValueError('Missing quote inputs')
        versions = self.items.setdefault(quote_id, [])
        record = QuoteRecord(quote_id, len(versions)+1, spec, str(total))
        versions.append(record)
        return record

    def current(self, quote_id, revision):
        versions = self.items.get(quote_id, [])
        if not versions or versions[-1].revision != revision:
            raise ValueError('Outdated or missing revision')
        return versions[-1]

    def mark_sent(self, quote_id, revision, delivery_reference):
        old = self.current(quote_id, revision)
        if old.status != 'draft' or not delivery_reference:
            raise ValueError('Delivery confirmation required')
        result = replace(old, status='sent', delivery_reference=delivery_reference)
        self.items[quote_id][-1] = result
        return result

    def approve(self, quote_id, revision, specification, total, approval_reference):
        old = self.current(quote_id, revision)
        if old.status != 'sent' or not approval_reference:
            raise ValueError('Explicit approval required')
        if old.specification != specification or old.total != str(total):
            raise ValueError('Approval differs from sent quote')
        result = replace(old, status='approved', approval_reference=approval_reference)
        self.items[quote_id][-1] = result
        return result
