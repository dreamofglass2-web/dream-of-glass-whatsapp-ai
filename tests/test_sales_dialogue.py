import unittest
from types import SimpleNamespace as NS
from sales_dialogue import dialogue_context, sales_turn_context, api_usage_metrics, compact_instructions


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


class SalesMethodTests(unittest.TestCase):
    def test_joint_decision_is_respected_without_approval(self):
        state = sales_turn_context('אני צריך להתייעץ עם אשתי', [], {})
        self.assertEqual(state['focus_hint'], 'joint_decision')
        self.assertNotEqual(state['phase_hint'], 'closing')

    def test_thinking_is_not_treated_as_approval(self):
        state = sales_turn_context('אני צריך לחשוב על זה', [], {'validated_quote': {'issued': True}})
        self.assertEqual(state['focus_hint'], 'respect_deliberation')
        self.assertEqual(state['phase_hint'], 'decision')

    def test_close_requires_an_issued_quote(self):
        state = sales_turn_context('איך מתקדמים', [], {})
        self.assertEqual(state['phase_hint'], 'quote_preparation')

    def test_explicit_refusal_takes_priority_over_sales(self):
        state = sales_turn_context('לא רוצה, יקר לי, תפסיק', [], {})
        self.assertEqual(state['focus_hint'], 'respect_boundary')

    def test_product_preference_is_not_a_refusal_to_continue(self):
        state = sales_turn_context('לא רוצה שקוף, מעדיף חלבי', [], {})
        self.assertNotEqual(state['focus_hint'], 'respect_boundary')

    def test_partner_mentioned_in_approval_does_not_restart_discovery(self):
        state = sales_turn_context('דיברתי עם אשתי, אני מאשר', [], {'validated_quote': {'issued': True}})
        self.assertEqual(state['phase_hint'], 'closing')

    def test_preserve_old_customer_goal_without_sending_old_ai_speeches(self):
        history = [
            {'role': 'user', 'content': 'חשוב לי שיהיה קל לנקות ויש לי ילדים'},
            {'role': 'assistant', 'content': 'הלקוח רוצה פרזול יקר'},
        ] + [{'role': 'user', 'content': 'תודה'}] * 36
        state = sales_turn_context('אז מה מתאים', history, {})
        self.assertEqual(state['older_customer_evidence'], ['חשוב לי שיהיה קל לנקות ויש לי ילדים'])

    def test_recent_customer_messages_are_not_duplicated(self):
        history = [{'role': 'user', 'content': 'חשוב לי ניקיון'}]
        self.assertEqual(sales_turn_context('מה מתאים', history, {})['older_customer_evidence'], [])

    def test_memory_budget_does_not_grow_with_long_transcript(self):
        history = [{'role': 'user', 'content': 'חשוב לי ' + str(i) + ' א' * 500} for i in range(100)]
        evidence = sales_turn_context('מה מתאים', history, {})['older_customer_evidence']
        self.assertLessEqual(sum(map(len, evidence)), 1080)
        self.assertLessEqual(len(evidence), 6)

    def test_invalid_cache_counts_do_not_produce_negative_bill(self):
        response = NS(model='gpt-6-astra', usage=NS(
            input_tokens=100, output_tokens=20,
            input_tokens_details=NS(cached_tokens=200, cache_write_tokens=0)))
        self.assertIsNone(api_usage_metrics(response)['estimated_usd'])


if __name__ == '__main__':
    unittest.main()

class GlobalConsultationTests(unittest.TestCase):
    def test_all_products_and_known_needs(self):
        from sales_dialogue import consultation_plan
        for text in ('צריך מקלחון','רוצה מראה','רוצה מחיצה','חיפוי למטבח'):
            self.assertEqual(consultation_plan([{'role':'user','content':text}],{},text)['step'],'project_context')
        text='מחפש מקלחון לשיפוץ, חשוב לי ניקוי קל'
        self.assertIsNone(consultation_plan([{'role':'user','content':text}],{},text)['question'])
        for text in ('צריך לחשוב','רק מחיר בלי שאלות','לא מעוניין'):
            self.assertIsNone(consultation_plan([],{'product':'מקלחון'},text)['question'])

    def test_uncertainty_is_not_repeated_needs_question(self):
        from sales_dialogue import consultation_plan
        history=[{'role':'user','content':'מקלחון לבית חדש'},
                 {'role':'assistant','content':'מה הכי חשוב לך בתוצאה?'},
                 {'role':'user','content':'אין לי מושג, תייעץ לי'}]
        self.assertIsNone(consultation_plan(history,{'product':'מקלחון'},'תייעץ לי')['question'])

class NaturalDiscoveryPreservationTests(unittest.TestCase):
    def test_keep_relevant_question_and_reject_price_or_wrong_axis(self):
        from sales_dialogue import preserves_consultation_step
        self.assertTrue(preserves_consultation_step('אשמח לעזור. זה לשיפוץ או לבית חדש?',{'step':'project_context'}))
        self.assertFalse(preserves_consultation_step('המחיר ₪2000. זה לבית חדש?',{'step':'project_context'}))
        self.assertFalse(preserves_consultation_step('מה רוחב הפתח?',{'step':'project_context'}))

class CustomerNameConsultationTests(unittest.TestCase):
    def test_name_is_asked_once_and_known_form_name_is_respected(self):
        from sales_dialogue import consultation_plan
        history=[{'role':'user','content':'מקלחון לבית חדש, חשוב לי ניקוי קל'}]
        self.assertEqual(consultation_plan(history,{},history[0]['content'])['step'],'customer_name')
        history += [{'role':'assistant','content':'אגב, איך קוראים לך?'},{'role':'user','content':'לא רוצה למסור שם'}]
        self.assertIsNone(consultation_plan(history,{},history[-1]['content'])['question'])
        prior={'meta_leads':{'lead':{'fields':{'full_name':['דניאל']}}}}
        self.assertIsNone(consultation_plan(history[:1],prior,'חשוב לי ניקוי קל')['question'])
