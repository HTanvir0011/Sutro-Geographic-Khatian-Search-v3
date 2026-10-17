import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import closing

from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import app
import admin_panel


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db, self.original_instance = app.DB_FILE, app.INSTANCE
        app.DB_FILE = Path(self.temp.name) / 'test.sqlite3'
        app.INSTANCE = Path(self.temp.name)
        (app.INSTANCE / 'uploads').mkdir()
        (app.INSTANCE / 'deed_rewrites').mkdir()
        with closing(sqlite3.connect(self.original_db)) as src, closing(sqlite3.connect(app.DB_FILE)) as dst:
            src.backup(dst)
            for table in ('admin_account', 'admin_users', 'admin_login_failures', 'uploaded_khatians', 'record_controls',
                          'complaints', 'complaint_documents', 'complaint_submission_limits', 'deed_rewrites'):
                dst.execute('DELETE FROM ' + table)
            dst.commit()
        self.client = app.app.test_client()
        self.csrf = self.client.get('/api/admin/session').get_json()['csrf']

    def tearDown(self):
        app.DB_FILE, app.INSTANCE = self.original_db, self.original_instance
        self.temp.cleanup()

    def image_status(self, url):
        with self.client.get(url) as response:
            return response.status_code

    def call(self, method, url, obj=None, **kwargs):
        return self.client.open(url, method=method, json=obj,
                                headers={'X-CSRF-Token': self.csrf}, **kwargs)

    def login(self):
        response = self.call('POST', '/api/admin/setup', {'password': 'Testing-password-123!'})
        self.assertEqual(response.status_code, 200)
        self.csrf = response.get_json()['csrf']

    def image(self):
        output = io.BytesIO()
        Image.new('RGB', (300, 200), 'white').save(output, 'PNG')
        output.seek(0)
        return output

    def pdf(self, text='মূল দলিলের লেখা'):
        output = io.BytesIO()
        document = canvas.Canvas(output, pagesize=A4)
        document.drawString(50, 780, text)
        document.save()
        output.seek(0)
        return output

    def upload(self):
        with patch('admin_panel.ocr_image', return_value=(
                'District: Test District\nUpazila: Test Upazila\nMouza: Test Mouza\nKhatian No: 12345\nRS', '')):
            response = self.client.post('/api/admin/khatian-upload', data={'file': (self.image(), 'scan.png')},
                                        headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 201)
        return response.get_json()

    def query(self):
        return self.client.get('/api/khatian/search', query_string={
            'district': 'Test District', 'upazila': 'Test Upazila', 'mouza': 'Test Mouza', 'q': '12345'})

    def test_auth_setup_csrf_and_password_change(self):
        self.assertEqual(self.client.get('/api/admin/records').status_code, 401)
        self.assertEqual(self.client.post('/api/deeds', json={}).status_code, 401)
        self.assertEqual(self.client.post('/api/admin/setup', json={'password': 'Testing-password-123!'}).status_code, 403)
        remote = self.call('POST', '/api/admin/setup', {'password': 'Testing-password-123!'},
                           environ_overrides={'REMOTE_ADDR': '192.0.2.1'})
        self.assertEqual(remote.status_code, 403)
        self.login()
        self.assertEqual(self.client.get('/api/admin/records').status_code, 200)
        self.assertEqual(self.call('POST', '/api/admin/setup', {'password': 'Other-password-123!'}).status_code, 409)
        self.assertEqual(self.client.patch('/api/admin/records/khatian/L00000-v0', json={'warning': 'x'}).status_code, 403)
        other = app.app.test_client()
        token = other.get('/api/admin/session').get_json()['csrf']
        old_login = other.post('/api/admin/login', json={'password': 'Testing-password-123!'}, headers={'X-CSRF-Token': token})
        self.assertEqual(old_login.status_code, 200)
        changed = self.call('POST', '/api/admin/password', {'old_password': 'Testing-password-123!', 'password': 'New-password-456!'})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(other.get('/api/admin/records').status_code, 401)

    def test_login_does_not_depend_on_stale_csrf_token(self):
        self.login()
        other = app.app.test_client()
        response = other.post('/api/admin/login',
                              json={'username': 'superadmin', 'password': 'Testing-password-123!'})
        self.assertEqual(response.status_code, 200)

    def test_login_rate_limit(self):
        self.login()
        self.call('POST', '/api/admin/logout')
        self.csrf = self.client.get('/api/admin/session').get_json()['csrf']
        for _ in range(5):
            self.assertEqual(self.call('POST', '/api/admin/login', {'password': 'wrong'}).status_code, 401)
        self.assertEqual(self.call('POST', '/api/admin/login', {'password': 'Testing-password-123!'}).status_code, 429)

    def test_superadmin_can_register_and_disable_admin(self):
        self.login()
        created = self.call('POST', '/api/admin/users',
                            {'username': 'editor1', 'password': 'Editor-password-123!'})
        self.assertEqual(created.status_code, 201)
        users = self.client.get('/api/admin/users').get_json()['users']
        editor = next(user for user in users if user['username'] == 'editor1')
        other = app.app.test_client()
        token = other.get('/api/admin/session').get_json()['csrf']
        self.assertEqual(other.post('/api/admin/login',
                                    json={'username': 'editor1', 'password': 'Editor-password-123!'},
                                    headers={'X-CSRF-Token': token}).status_code, 200)
        other_token = other.get('/api/admin/session').get_json()['csrf']
        self.assertEqual(other.get('/api/admin/users').status_code, 403)
        self.assertEqual(self.call('PATCH', '/api/admin/users/' + str(editor['id']),
                                    {'active': False}).status_code, 200)
        other.post('/api/admin/logout', headers={'X-CSRF-Token': other_token})
        token = other.get('/api/admin/session').get_json()['csrf']
        self.assertEqual(other.post('/api/admin/login',
                                    json={'username': 'editor1', 'password': 'Editor-password-123!'},
                                    headers={'X-CSRF-Token': token}).status_code, 401)

    def test_admin_can_review_and_generate_private_bengali_deed_pdf(self):
        self.login()
        response = self.client.post('/api/admin/deed-rewrites',
                                    data={'file': (self.pdf(), 'source.pdf')},
                                    headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 201)
        rewrite = response.get_json()
        self.assertEqual(rewrite['status'], 'draft')
        with self.client.get(rewrite['original_url']) as original:
            self.assertEqual(original.status_code, 200)
        generated = self.call('PATCH', '/api/admin/deed-rewrites/' + rewrite['id'],
                              {'text': 'এটি সংশোধিত বাংলা দলিলের লেখা।'})
        self.assertEqual(generated.status_code, 200)
        output = generated.get_json()['rewritten_url']
        with self.client.get(output) as download:
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.mimetype, 'application/pdf')
            self.assertIn(b'%PDF', download.data[:10])
        self.assertEqual(self.client.get('/api/admin/deed-rewrites/unknown/original').status_code, 404)

    def test_deed_rewrite_requires_pdf_and_admin_session(self):
        self.assertEqual(self.client.post('/api/admin/deed-rewrites',
                                          data={'file': (self.image(), 'scan.png')},
                                          headers={'X-CSRF-Token': self.csrf}).status_code, 401)
        self.login()
        self.assertEqual(self.client.post('/api/admin/deed-rewrites',
                                          data={'file': (self.image(), 'scan.png')},
                                          headers={'X-CSRF-Token': self.csrf}).status_code, 400)
        self.assertEqual(self.client.post('/api/admin/deed-rewrites',
                                          data={'file': (io.BytesIO(b'not a pdf'), 'broken.pdf')},
                                          headers={'X-CSRF-Token': self.csrf}).status_code, 400)

    def test_low_quality_pdf_text_is_not_presented_as_transcription(self):
        self.assertFalse(admin_panel.usable_bengali_text('Fat i = 1285 Cae DN NTE WTA'))
        self.assertTrue(admin_panel.usable_bengali_text('এটি একটি বাংলা দলিলের লেখা এবং আরও কিছু বাংলা বাক্য আছে।'))

    def test_configured_vision_ai_takes_priority_for_deed_text(self):
        self.login()
        with patch.dict('os.environ', {'SUTRO_AI_API_KEY': 'test-key'}), \
             patch('admin_panel.extract_deed_text',
                   return_value=('সরাসরি বাংলা দলিলের লেখা।', 'Vision AI transcription: admin review required.', 1)):
            response = self.client.post('/api/admin/deed-rewrites',
                                        data={'file': (self.pdf('বাংলা text layer'), 'source.pdf')},
                                        headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()['text'], 'সরাসরি বাংলা দলিলের লেখা।')

    def test_upload_review_publish_warning_delete_restore(self):
        self.login()
        draft = self.upload()
        record_id = draft['id']
        self.assertEqual(draft['record']['khatian_no'], '12345')
        self.assertEqual(self.query().get_json()['total'], 0)
        self.assertEqual(self.client.get('/api/khatian-image/' + record_id).status_code, 404)
        self.assertEqual(self.image_status(draft['image_url']), 200)
        draft['record']['owners'] = [{'name_bn': 'পরীক্ষা মালিক', 'father_or_spouse_bn': 'পিতা', 'share_exact': '1'}]
        draft['record']['dag_rows'] = [{'dag_no': '205', 'land_class_bn': 'কৃষি', 'area_dec': '12.5'}]
        published = self.call('PATCH', '/api/admin/khatians/' + record_id, {'record': draft['record'], 'status': 'published'})
        self.assertEqual(published.status_code, 200)
        record = self.query().get_json()['records'][0]
        self.assertEqual(record['khatian_id'], record_id)
        self.assertEqual(record['owners'][0]['name_bn'], 'পরীক্ষা মালিক')
        self.assertEqual(self.image_status(record['image_url']), 200)
        filters = self.client.get('/api/khatian/filters', query_string={'district': 'Test District', 'upazila': 'Test Upazila'}).get_json()
        self.assertTrue(any(r['mouza'] == 'Test Mouza' for r in filters['places']))
        url = '/api/admin/records/khatian/' + record_id
        self.assertEqual(self.call('PATCH', url, {'warning': 'তথ্য যাচাই প্রয়োজন'}).status_code, 200)
        self.assertEqual(self.query().get_json()['records'][0]['warning'], 'তথ্য যাচাই প্রয়োজন')
        self.call('PATCH', url, {'deleted': True})
        self.assertEqual(self.query().get_json()['total'], 0)
        self.assertEqual(self.client.get(record['image_url']).status_code, 404)
        detail = self.client.get(url).get_json()
        self.assertTrue(detail['deleted'])
        self.assertEqual(self.image_status(detail['image_url']), 200)
        self.call('PATCH', url, {'deleted': False, 'warning': ''})
        self.assertEqual(self.query().get_json()['total'], 1)

    def test_invalid_image_and_publication(self):
        self.login()
        response = self.client.post('/api/admin/khatian-upload', data={'file': (io.BytesIO(b'not an image'), 'x.png')},
                                    headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 400)
        draft = self.upload()
        draft['record']['district'] = ''
        response = self.call('PATCH', '/api/admin/khatians/' + draft['id'], {'record': draft['record'], 'status': 'published'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.query().get_json()['total'], 0)

    def test_bangla_ocr_label_boundaries(self):
        fields = admin_panel.extract_fields('খতিয়ান নং-৮৫০\nবিভাগঃ সিলেট জেলাঃ সিলেট খানাঃ বিয়ানীবাজার মৌজাঃ উত্তরপাড়া জে, এল নং-৬ রেঃসাঃ নঃ ২\n১। মোঃ সিরাজুল আলী ০.৫০০')
        self.assertEqual(fields['district'], 'সিলেট')
        self.assertEqual(fields['upazila'], 'বিয়ানীবাজার')
        self.assertEqual(fields['mouza'], 'উত্তরপাড়া')
        self.assertEqual(fields['khatian_no'], '850')
        self.assertEqual(fields['owners'][0]['name_bn'], 'মোঃ সিরাজুল আলী')

    def test_sample_delete_is_persistent_and_admin_can_view(self):
        self.login()
        url = '/api/admin/records/khatian/L00000-v0'
        self.call('PATCH', url, {'deleted': True, 'warning': 'Review'})
        app.import_khatians()
        public = self.client.get('/api/khatian/search', query_string={'district': 'সিলেট', 'upazila': 'বিয়ানীবাজার', 'q': '850', 'survey': 'RS'}).get_json()
        self.assertNotIn('L00000-v0', [r['khatian_id'] for r in public['records']])
        self.assertEqual(self.client.get('/api/khatian-image/L00000-v0').status_code, 404)
        detail = self.client.get(url).get_json()
        self.assertEqual(self.image_status(detail['image_url']), 200)
        self.assertEqual(self.client.get('/api/admin/records?kind=khatian&q=L00000-v0').get_json()['total'], 1)

    def test_deed_creation_warning_verification_and_delete(self):
        self.login()
        obj = {'owner_name': 'Test Owner', 'khatian_no': '12345', 'dag_no': '205', 'land_area_decimal': '12.5',
               'district': 'Test District', 'upazila': 'Test Upazila', 'mouza': 'Test Mouza', 'deed_date': '2026-10-17'}
        response = self.call('POST', '/api/deeds', obj)
        self.assertEqual(response.status_code, 201)
        record_id = response.get_json()['record']['deed_id']
        self.call('PATCH', '/api/admin/records/deed/' + record_id, {'warning': 'Pending review'})
        pdf = self.client.get('/api/deeds/' + record_id + '/pdf')
        self.assertEqual(pdf.status_code, 200)
        verified = self.client.post('/api/verify', data={'file': (io.BytesIO(pdf.data), 'deed.pdf')}).get_json()
        self.assertEqual(verified['status'], 'VERIFIED')
        self.assertEqual(verified['warning'], 'Pending review')
        self.call('PATCH', '/api/admin/records/deed/' + record_id, {'deleted': True})
        self.assertEqual(self.client.get('/api/deeds/' + record_id).status_code, 404)
        with self.client.get('/api/admin/deeds/' + record_id + '/pdf') as admin_pdf:
            self.assertEqual(admin_pdf.status_code, 200)
        self.assertNotIn(record_id, [r['deed_id'] for r in self.client.get('/api/dashboard').get_json()['deeds']])
        self.assertTrue(app.audit_check())

    def test_bangla_deed_pdf_roundtrip(self):
        self.login()
        obj = {'owner_name': 'মোঃ সিরাজুল আলী', 'khatian_no': '850', 'dag_no': '205', 'land_area_decimal': '12.5',
               'district': 'সিলেট', 'upazila': 'বিয়ানীবাজার', 'mouza': 'উত্তরপাড়া', 'deed_date': '2026-10-17'}
        response = self.call('POST', '/api/deeds', obj)
        self.assertEqual(response.status_code, 201)
        record_id = response.get_json()['record']['deed_id']
        with self.client.get('/api/deeds/' + record_id + '/pdf') as pdf:
            verified = self.client.post('/api/verify', data={'file': (io.BytesIO(pdf.data), 'deed.pdf')}).get_json()
        self.assertEqual(verified['status'], 'VERIFIED')

    def test_incomplete_draft_can_be_saved(self):
        self.login()
        draft = self.upload()
        response = self.call('PATCH', '/api/admin/khatians/' + draft['id'],
                             {'record': {'district': 'Partial district'}, 'status': 'draft'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.query().get_json()['total'], 0)


if __name__ == '__main__':
    unittest.main()
