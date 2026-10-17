import io
import unittest

import app
import test_admin
from reportlab.pdfgen import canvas


class ComplaintTests(unittest.TestCase):
    setUp = test_admin.AdminTests.setUp
    tearDown = test_admin.AdminTests.tearDown
    login = test_admin.AdminTests.login
    call = test_admin.AdminTests.call
    image = test_admin.AdminTests.image

    def payload(self):
        return {'name': 'পরীক্ষা অভিযোগকারী', 'phone': '০১৭১২৩৪৫৬৭৮', 'district': 'সিলেট',
                'upazila': 'বিয়ানীবাজার', 'mouza': 'উত্তরপাড়া', 'khatian_no': '850', 'dag_no': '205',
                'category': 'encroachment', 'subject': 'পরীক্ষার ভূমি দখল অভিযোগ',
                'description': 'এটি পরীক্ষার ব্যক্তিগত অভিযোগের বিস্তারিত বিবরণ, প্রকাশ্যে দেখানো যাবে না।', 'consent': 'yes'}

    def public(self):
        client = app.app.test_client()
        token = client.get('/api/complaints/session').get_json()['csrf']
        return client, token

    def submit(self, client, token, docs=None, overrides=None):
        data = self.payload()
        data.update(overrides or {})
        if docs is not None:
            data['documents'] = docs
        response = client.post('/api/complaints', data=data, headers={'X-CSRF-Token': token})
        response.request.environ['wsgi.input'].close()
        return response

    def test_private_submission_and_admin_management(self):
        public, token = self.public()
        pdf = io.BytesIO()
        page = canvas.Canvas(pdf); page.drawString(40, 700, 'Complaint supporting document'); page.save(); pdf.seek(0)
        submitted = self.submit(public, token, [(self.image(), 'evidence.png'), (pdf, 'document.pdf')])
        self.assertEqual(submitted.status_code, 201)
        body = submitted.get_json()
        record_id = body['receipt']
        self.assertNotIn('description', body)
        self.assertEqual(public.get('/api/complaints/' + record_id).status_code, 404)
        self.assertEqual(public.get('/api/admin/complaints').status_code, 401)
        self.assertEqual(public.get('/api/admin/complaints/stats').status_code, 401)
        self.assertEqual(public.get('/api/admin/complaints/' + record_id).status_code, 401)
        self.login()
        stats = self.client.get('/api/admin/complaints/stats').get_json()
        self.assertEqual(stats['new'], 1)
        listing = self.client.get('/api/admin/complaints?status=new').get_json()
        self.assertEqual(listing['total'], 1)
        detail = self.client.get('/api/admin/complaints/' + record_id).get_json()
        self.assertEqual(detail['fields']['description'], self.payload()['description'])
        self.assertEqual(detail['fields']['phone'], '01712345678')
        self.assertEqual(detail['status'], 'new')
        self.assertFalse(detail['forwarding_available'])
        self.assertEqual(len(detail['documents']), 2)
        for document in detail['documents']:
            self.assertEqual(public.get(document['url']).status_code, 401)
            with self.client.get(document['url']) as response:
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.headers['Content-Disposition'].startswith('attachment;'))
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertGreater(len(response.data), 0)
        document = detail['documents'][0]
        wrong_url = document['url'].replace(record_id, 'CMP-OTHER')
        self.assertEqual(self.client.get(wrong_url).status_code, 404)
        url = '/api/admin/complaints/' + record_id
        self.assertEqual(self.client.patch(url, json={'status': 'read'}).status_code, 403)
        self.assertEqual(self.call('PATCH', url, {'status': 'reviewing', 'admin_note': 'Private admin note'}).status_code, 200)
        self.assertEqual(self.client.get('/api/admin/complaints/stats').get_json()['new'], 0)
        self.assertEqual(self.client.get(url).get_json()['admin_note'], 'Private admin note')
        self.assertEqual(self.client.get('/api/admin/complaints?q=' + record_id).get_json()['total'], 1)
        public_output = public.get('/api/audit').data + public.get('/api/dashboard').data
        for private in (record_id, self.payload()['name'], self.payload()['description'], 'Private admin note', 'evidence.png'):
            self.assertNotIn(private.encode('utf-8'), public_output)
        self.call('POST', '/api/admin/logout')
        self.assertEqual(self.client.get(document['url']).status_code, 401)

    def test_no_forwarding_or_fake_forwarded_status(self):
        public, token = self.public()
        record_id = self.submit(public, token).get_json()['receipt']
        self.login()
        url = '/api/admin/complaints/' + record_id
        self.assertEqual(self.call('PATCH', url, {'status': 'forwarded'}).status_code, 400)
        self.assertEqual(self.call('PATCH', url, {'status': []}).status_code, 400)
        self.assertEqual(self.call('POST', url + '/forward', {}).status_code, 404)
        html = self.client.get('/admin').data.decode()
        self.assertIn('id="forwardComplaint" disabled', html)
        self.assertIn('Forward to Land Office', html)
        self.assertEqual(self.client.get(url).get_json()['status'], 'new')

    def test_validation_and_file_limits(self):
        public, token = self.public()
        self.assertEqual(public.post('/api/complaints', data=self.payload()).status_code, 403)
        for override in ({'category': 'invalid'}, {'consent': ''}, {'description': 'short'}, {'phone': 'not a phone'}):
            self.assertEqual(self.submit(public, token, overrides=override).status_code, 400)
        self.assertEqual(self.submit(public, token, [(io.BytesIO(b'<html>bad</html>'), 'fake.pdf')]).status_code, 400)
        self.assertEqual(self.submit(public, token, [(io.BytesIO(b'0' * (5*1024*1024+1)), 'huge.png')]).status_code, 400)
        self.assertEqual(self.submit(public, token, [(self.image(), f'{i}.png') for i in range(6)]).status_code, 400)
        with app.conn() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM complaints').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM complaint_documents').fetchone()[0], 0)

    def test_rate_limit_and_status_filters(self):
        public, token = self.public()
        for _ in range(10):
            self.assertEqual(self.submit(public, token).status_code, 201)
        self.assertEqual(self.submit(public, token).status_code, 429)
        self.login()
        self.assertEqual(self.client.get('/api/admin/complaints?status=new').get_json()['total'], 10)
        self.assertEqual(self.client.get('/api/admin/complaints?status=resolved').get_json()['total'], 0)
        self.assertEqual(self.client.get('/api/admin/complaints?page=oops').status_code, 400)
        self.assertEqual(self.client.get('/api/admin/complaints?status=forwarded').status_code, 400)

    def test_receipt_tracks_status_without_private_details(self):
        public, token = self.public()
        record_id = self.submit(public, token, [(self.image(), 'private-evidence.png')]).get_json()['receipt']
        def track(receipt):
            return public.post('/api/complaints/track', json={'receipt': receipt}, headers={'X-CSRF-Token': token})
        self.assertEqual(public.post('/api/complaints/track', json={'receipt': record_id}).status_code, 403)
        response = track('  ' + record_id.lower() + '  ')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['status'], 'new')
        self.assertEqual(set(response.get_json()), {'receipt', 'status', 'status_label', 'submitted_at', 'updated_at'})
        self.login()
        self.call('PATCH', '/api/admin/complaints/' + record_id,
                  {'status': 'reviewing', 'admin_note': 'Private note never exposed'})
        result = track(record_id).get_json()
        self.assertEqual(result['status'], 'reviewing')
        self.assertNotIn('Private note', str(result))
        self.assertNotIn(self.payload()['name'], str(result))
        self.assertNotIn('private-evidence.png', str(result))
        self.assertEqual(track('CMP-' + '0'*32).status_code, 404)
        self.assertEqual(track('bad number').status_code, 404)
        self.assertEqual(track([]).status_code, 404)

    def test_home_has_tracking_link_without_bottom_admin_section(self):
        html = self.client.get('/').data.decode()
        self.assertNotIn('id="create"', html)
        self.assertNotIn('id="deedForm"', html)
        self.assertNotIn('Admin panel / Login', html)
        self.assertIn('href="/complaints#track"', html)
        form = self.client.get('/complaints').data.decode()
        self.assertIn('id="trackForm"', form)


if __name__ == '__main__':
    unittest.main()
