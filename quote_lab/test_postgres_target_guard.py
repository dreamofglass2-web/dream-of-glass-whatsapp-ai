"""Target restrictions checked without a database driver or connection."""
import unittest
from unittest.mock import patch
from quote_lab.durable_store import QuoteStoreError
from quote_lab.postgres_store import PostgresQuoteStore, test_database_parameters


class PostgresTargetGuardTests(unittest.TestCase):
    def test_local_test_database_is_explicit(self):
        params = test_database_parameters("postgresql://quote_lab_writer:test@localhost:5432/quote_lab_test")
        self.assertEqual(params["dbname"], "quote_lab_test")
        self.assertEqual(params["hostaddr"], "127.0.0.1")
        self.assertEqual(params["host"], "127.0.0.1")

    def test_remote_production_and_redirect_targets_are_rejected_before_driver_import(self):
        targets = [None, "", "dbname=quote_lab_test", "postgres://test:x@remote.example/quote_lab_test",
                   "postgres://test:x@localhost/production", "postgres://test:x@localhost/quote_lab_test?hostaddr=8.8.8.8",
                   "postgres://test:x@localhost:bad/quote_lab_test", "postgres://localhost/quote_lab_test",
                   "postgres://test:x@localhost/quote_lab_test#fragment"]
        for target in targets:
            with self.subTest(target=target), patch("builtins.__import__", wraps=__import__) as imports:
                with self.assertRaises(QuoteStoreError):
                    PostgresQuoteStore(target)
                self.assertFalse(any(c.args[0].startswith("psycopg2") for c in imports.call_args_list))
