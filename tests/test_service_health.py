"""Readiness failures and bot-only startup, without network or customer sends."""
import os
import runpy
import unittest
from unittest.mock import MagicMock, patch
os.environ.setdefault('OPENAI_API_KEY', 'sk-offline-test-only')
import app as yossi


class ServiceHealthTests(unittest.TestCase):
    def setUp(self):
        self.client = yossi.app.test_client()
        self.connection = MagicMock()
        self.connection.__enter__.return_value = self.connection
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.cursor.fetchone.return_value = (1,)
        self.thread = MagicMock()
        self.thread.is_alive.return_value = True
        self.patches = [
            patch.object(yossi, 'db_connection', return_value=self.connection),
            patch.object(yossi, 'ensure_worker_started'),
            patch.object(yossi, 'worker_thread', self.thread),
            patch.object(yossi, 'worker_pid', os.getpid()),
            patch.object(yossi, 'pending', {}),
            patch.object(yossi, 'processing', set()),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])

    def test_healthy_requires_db_query_and_live_worker(self):
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['database_ready'])
        self.assertTrue(response.json['worker_alive'])
        self.assertIn(('SELECT 1',), [call.args for call in self.cursor.execute.call_args_list])
        self.connection.close.assert_called_once()
        yossi.db_connection.assert_called_once_with(connect_timeout=2)

    def test_db_failure_is_503_and_does_not_run_schema_initialization(self):
        with patch.object(yossi, 'db_connection', side_effect=RuntimeError('secret test detail')):
            response = self.client.get('/health')
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json['database_ready'])
        self.assertNotIn('secret test detail', response.get_data(as_text=True))
        yossi.ensure_worker_started.assert_not_called()

    def test_query_failure_closes_connection_and_returns_503(self):
        self.cursor.execute.side_effect = TimeoutError()
        self.assertEqual(self.client.get('/health').status_code, 503)
        self.connection.close.assert_called_once()

    def test_dead_missing_or_other_process_worker_is_unhealthy(self):
        self.thread.is_alive.return_value = False
        self.assertEqual(self.client.get('/health').status_code, 503)
        self.thread.is_alive.return_value = True
        with patch.object(yossi, 'worker_thread', None):
            self.assertEqual(self.client.get('/health').status_code, 503)
        with patch.object(yossi, 'worker_pid', os.getpid()+1):
            self.assertEqual(self.client.get('/health').status_code, 503)

    def test_startup_failure_is_unhealthy(self):
        with patch.object(yossi, 'ensure_worker_started', side_effect=RuntimeError()), patch.object(yossi, 'worker_thread', None):
            self.assertEqual(self.client.get('/health').status_code, 503)

    def test_gunicorn_starts_worker_for_bot_only(self):
        callback = runpy.run_path('gunicorn.conf.py')['post_worker_init']
        worker = MagicMock()
        worker.app.app_uri = 'app:app'
        callback(worker)
        yossi.ensure_worker_started.assert_called_once()
        yossi.ensure_worker_started.reset_mock()
        worker.app.app_uri = 'crm_lab.runtime:create_application()'
        callback(worker)
        yossi.ensure_worker_started.assert_not_called()


if __name__ == '__main__':
    unittest.main()
