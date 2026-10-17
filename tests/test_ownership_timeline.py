import unittest

import app


class OwnershipTimelineTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_sample_timeline_includes_owners_and_inheritance_evidence(self):
        response = self.client.get('/api/khatian/L00001-v0/ownership-timeline')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['land_id'], 'L00001')
        self.assertEqual(len(data['records']), 3)
        self.assertTrue(data['records'][0]['owners'])
        self.assertTrue(any(item['transition'] == 'inheritance' for item in data['transitions']))
        self.assertIn('not proof of legal ownership', data['notice'])

    def test_uploaded_or_invalid_ids_do_not_expose_a_fabricated_history(self):
        self.assertEqual(self.client.get('/api/khatian/Uaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/ownership-timeline').status_code, 404)
        self.assertEqual(self.client.get('/api/khatian/L99999-v0/ownership-timeline').status_code, 404)


if __name__ == '__main__':
    unittest.main()
