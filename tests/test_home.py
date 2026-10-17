"""Home navigation and public chart aggregation tests."""
import json
import unittest
from pathlib import Path

import app
import dolil
import test_admin


class HomeTests(unittest.TestCase):
    def setUp(self):
        test_admin.AdminTests.setUp(self)
        self.original_folder = dolil.IMAGE_DIR
        dolil.IMAGE_DIR = Path(self.temp.name) / 'deeds'
        dolil.IMAGE_DIR.mkdir()
        (dolil.IMAGE_DIR / 'dolil_1.jpg').write_bytes(b'test reference')

    def tearDown(self):
        dolil.IMAGE_DIR = self.original_folder
        test_admin.AdminTests.tearDown(self)

    def test_generation_about_footer_and_charts_are_visible(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        for text in ('id="generateDeed"', 'href="/admin#deed"', 'id="insights"',
                     'id="surveyChart"', 'id="districtChart"', 'id="motionToggle"',
                     'id="feeCalculator"', 'id="feeForm"', 'id="feeResult"',
                     'id="about"', 'class="site-footer"', 'Tanvir Hossin', 'Team Leader',
                     '0242310005101466', 'Md. Omar Faruk', '0242310005101863',
                     'Shumaiya Akter Shammi', 'MD Shoaib Khan',
                     'shammi.cse0532.c@diu.edu.bd', '01843441269', 'theshoaib.me@gmail.com',
                     'https://landtech.diu.edu.bd/team/edit'):
            self.assertIn(text, html)
        self.assertNotIn('id="create"', html)

    def test_charts_count_visible_records_only(self):
        baseline = self.client.get('/api/insights').get_json()
        self.assertEqual(sum(row['count'] for row in baseline['surveys']), baseline['khatian_total'])
        self.assertEqual(sum(row['count'] for row in baseline['districts']), baseline['khatian_total'])
        self.assertEqual(baseline['local_deed_images'], 1)
        record = {'district': 'Test District', 'survey': 'BRS', 'owners': [], 'dag_rows': []}
        with app.conn() as db:
            db.execute('INSERT INTO uploaded_khatians VALUES (?,?,?,?,?,?,?)',
                       ('Utestpublic', 'test.jpg', json.dumps(record), '', 'published', app.now(), ''))
            db.execute('INSERT INTO uploaded_khatians VALUES (?,?,?,?,?,?,?)',
                       ('Utestdraft', 'draft.jpg', json.dumps({'district': 'Secret Draft', 'survey': 'RS'}),
                        '', 'draft', app.now(), ''))
            db.execute('INSERT INTO complaints VALUES (?,?,?,?,?,?,?)',
                       ('CMP-PRIVATE', 'encroachment', '{"name":"Secret Complaint"}', 'new',
                        'Secret note', app.now(), app.now()))
        visible = self.client.get('/api/insights').get_json()
        self.assertEqual(visible['khatian_total'], baseline['khatian_total'] + 1)
        self.assertTrue(any(row['label'] == 'Test District' for row in visible['districts']))
        self.assertNotIn('Secret', str(visible))
        self.assertNotIn('CMP-PRIVATE', str(visible))
        with app.conn() as db:
            db.executemany('INSERT INTO record_controls VALUES (?,?,?,?)',
                           [('khatian', 'Utestpublic', 1, ''), ('local_deed', '1', 1, '')])
        hidden = self.client.get('/api/insights').get_json()
        self.assertEqual(hidden['khatian_total'], baseline['khatian_total'])
        self.assertEqual(hidden['local_deed_images'], 0)
        self.assertNotIn('Test District', str(hidden['districts']))


if __name__ == '__main__':
    unittest.main()
