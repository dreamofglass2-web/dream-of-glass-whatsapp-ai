import unittest
from types import SimpleNamespace as NS
from sales_dialogue import dialogue_context, api_usage_metrics, compact_instructions


class ConsultationStateTests(unittest.TestCase):
    def test_customer_confusion_is_not_unfinished_renovation(self):
        history = [
            {'role': 'user', 'content': 'מימין כיור ומשמאל אסלה'},
            {'role': 'user', 'content': 'לא יודע צריך לראות אני לא מבין בזה'},
            {'role': 'user', 'content': 'הם כבר מורכבים'},
        ]
        state = dialogue_context(history)
        self.assertTrue(state['customer_needs_plain_visual_explanation'])
        self.assertTrue(state['sanitary_fixtures_installed'])

    def test_latest_explicit_installation_correction_wins(self):
        history = [{'role': 'user', 'content': s} for s in (
            'הכיור והאסלה עוד לא מורכבים', 'הם כבר מורכבים',
            'תיקון: הם לא מורכבים')]
        self.assertFalse(dialogue_context(history)['sanitary_fixtures_installed'])

    def test_business_policy_is_compact_and_has_no_internal_cost_table(self):
        prompt = compact_instructions('עובדות אתר', ['שקופה'], ['פינתי 2 דלתות'])
        self.assertLess(len(prompt), 10000)
        self.assertIn('מחיר סופי רק מחישוב', prompt)
        self.assertIn('אין למדוד בס״מ', prompt)


class UsageAccountingTests(unittest.TestCase):
    def test_cache_reads_and_writes_have_different_rates(self):
        response = NS(model='gpt-6-astra', usage=NS(
            input_tokens=10000, output_tokens=500,
            input_tokens_details=NS(cached_tokens=8000, cache_write_tokens=1000),
            output_tokens_details=NS(reasoning_tokens=100)))
        self.assertAlmostEqual(api_usage_metrics(response)['estimated_usd'], .0555)

    def test_missing_usage_does_not_become_a_zero_bill(self):
        self.assertIsNone(api_usage_metrics(NS())['estimated_usd'])

    def test_unknown_cache_accounting_does_not_claim_exact_cost(self):
        response = NS(model='gpt-6-astra', usage=NS(input_tokens=100, output_tokens=20))
        self.assertIsNone(api_usage_metrics(response)['estimated_usd'])

    def test_invalid_cache_counts_do_not_produce_negative_bill(self):
        response = NS(model='gpt-6-astra', usage=NS(
            input_tokens=100, output_tokens=20,
            input_tokens_details=NS(cached_tokens=200, cache_write_tokens=0)))
        self.assertIsNone(api_usage_metrics(response)['estimated_usd'])


if __name__ == '__main__':
    unittest.main()
