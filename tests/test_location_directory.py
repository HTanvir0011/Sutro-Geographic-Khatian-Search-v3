"""Offline tests for the official directory and local khatian search integration."""
import json
import unicodedata
import unittest

import app
from location_directory import DIRECTORY, directory_places, location_key


class LocationDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_complete_official_hierarchy(self):
        data = json.loads(DIRECTORY.read_text(encoding='utf-8'))
        self.assertTrue(data['complete'])
        self.assertEqual(len(data['districts']), 64)
        self.assertEqual(len({d['id'] for d in data['districts']}), 64)
        district_ids = {d['id'] for d in data['districts']}
        self.assertGreaterEqual(len(data['upazilas']), 495)
        for upazila in data['upazilas']:
            self.assertIn(upazila['district_id'], district_ids)
            self.assertIn(upazila['id'], data['mouzas'])
            self.assertIn(upazila['id'], data['survey_scopes'])

    def test_initial_filters_include_districts_without_sample_records(self):
        response = self.client.get('/api/khatian/filters')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        official_districts = {p['district'] for p in data['places'] if p['source'] == 'land.gov.bd'}
        self.assertEqual(len(official_districts), 64)
        self.assertIn('পঞ্চগড়', official_districts)
        self.assertEqual(data['record_source'], 'local_sample_csv')

    def test_scoped_mouzas_and_sample_preservation(self):
        response = self.client.get('/api/khatian/filters', query_string={
            'district': 'সিলেট', 'upazila': 'বিয়ানীবাজার'})
        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(p['source'] == 'land.gov.bd' and p['mouza'] == 'খলাগাঁও'
                            for p in data['places']))
        self.assertTrue(any(location_key(p['mouza']) == location_key('উত্তরপাড়া')
                            for p in data['places']))
        self.assertTrue(all(location_key(p['upazila']) == location_key('বিয়ানীবাজার')
                            for p in data['places']))

    def test_unicode_equivalent_official_names_find_sample_record(self):
        response = self.client.get('/api/khatian/search', query_string={
            'district': 'সিলেট', 'upazila': unicodedata.normalize('NFC', 'বিয়ানীবাজার'),
            'mouza': unicodedata.normalize('NFC', 'উত্তরপাড়া'), 'q': '৮৫০', 'survey': 'RS'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['records'][0]['khatian_id'], 'L00000-v0')

    def test_invalid_scope(self):
        self.assertEqual(self.client.get('/api/khatian/filters?upazila=test').status_code, 400)

    def test_unavailable_location_returns_no_fabricated_mouzas(self):
        places, _ = directory_places('not a district', 'not an upazila')
        self.assertEqual(places, [])


if __name__ == '__main__':
    unittest.main()
