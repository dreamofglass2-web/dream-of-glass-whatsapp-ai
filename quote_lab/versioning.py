from dataclasses import dataclass

@dataclass(frozen=True)
class QuoteRecord:
    quote_id: str
    revision: int
    specification: str
    total: str
    status: str = 'draft'
