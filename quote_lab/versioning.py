from dataclasses import dataclass

@dataclass(frozen=True)
class QuoteRecord:
    quote_id: str
    revision: int
    specification: str
    total: str
    status: str = 'draft'

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
