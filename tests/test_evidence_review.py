import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import app


class EvidenceReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db, self.original_instance = app.DB_FILE, app.INSTANCE
        app.DB_FILE, app.INSTANCE = Path(self.temp.name) / 'test.sqlite3', Path(self.temp.name)
        with closing(sqlite3.connect(self.original_db)) as source, closing(sqlite3.connect(app.DB_FILE)) as destination:
            source.backup(destination)
            for table in ('admin_account', 'admin_users', 'admin_login_failures', 'evidence_reviews'):
                destination.execute('DELETE FROM ' + table)
            destination.commit()
        self.client = app.app.test_client()
        self.csrf = self.client.get('/api/admin/session').get_json()['csrf']
        response = self.client.post('/api/admin/setup', json={'password': 'Testing-password-123!'}, headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 200)
        self.csrf = response.get_json()['csrf']

    def tearDown(self):
        app.DB_FILE, app.INSTANCE = self.original_db, self.original_instance
        self.temp.cleanup()

    def call(self, method, url, body=None):
        return self.client.open(url, method=method, json=body, headers={'X-CSRF-Token': self.csrf})

    def test_requires_admin_and_persists_explainable_result(self):
        public = app.app.test_client()
        self.assertEqual(public.get('/api/admin/evidence/khatian-options?q=850').status_code, 401)
        options = self.client.get('/api/admin/evidence/khatian-options?q=850').get_json()['records']
        self.assertTrue(options)
        deed = self.call('POST', '/api/deeds', {'owner_name': 'Different person', 'khatian_no': '850', 'dag_no': '205',
                                                'land_area_decimal': '12.5', 'mouza': 'North Para', 'upazila': 'Beanibazar',
                                                'district': 'Sylhet', 'deed_date': '2026-10-17'})
        self.assertEqual(deed.status_code, 201)
        result = self.call('POST', '/api/admin/evidence/reviews', {'khatian_id': options[0]['khatian_id'],
                                                                    'deed_id': deed.get_json()['record']['deed_id']})
        self.assertEqual(result.status_code, 201)
        payload = result.get_json()
        self.assertTrue(payload['id'].startswith('EV-'))
        self.assertIn(payload['outcome'], {'consistent', 'needs_review'})
        self.assertEqual(len(payload['fields']), 7)
        history = self.client.get('/api/admin/evidence/reviews').get_json()['reviews']
        self.assertEqual(history[0]['id'], payload['id'])


if __name__ == '__main__':
    unittest.main()
