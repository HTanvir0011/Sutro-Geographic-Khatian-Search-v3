import io
import unittest
from pathlib import Path

from PIL import Image
import app
import dolil
import test_admin


class LocalDeedTests(unittest.TestCase):
    login = test_admin.AdminTests.login
    call = test_admin.AdminTests.call

    def setUp(self):
        test_admin.AdminTests.setUp(self)
        self.original_folder = dolil.IMAGE_DIR
        dolil.IMAGE_DIR = Path(self.temp.name) / 'deed-copies'
        dolil.IMAGE_DIR.mkdir()
        picture = Image.new('RGB', (64, 80), 'white')
        for x in range(20):
            for y in range(35):
                picture.putpixel((x, y), (10, 80, 30))
        picture.save(dolil.IMAGE_DIR / 'dolil_1.jpg', quality=92)
        Image.new('RGB', (64, 80), 'blue').save(dolil.IMAGE_DIR / 'dolil_2.jpg')

    def tearDown(self):
        dolil.IMAGE_DIR = self.original_folder
        test_admin.AdminTests.tearDown(self)

    def compare(self, raw, number='1', filename='camera.jpg'):
        return self.client.post('/api/local-deeds/compare', data={
            'number': number, 'file': (io.BytesIO(raw), filename)})

    def test_filename_number_lookup_and_no_path_access(self):
        for value in ['1', '১', 'dolil_1', 'dolil_1.jpg', '0001']:
            response = self.client.get('/api/local-deeds/search', query_string={'number': value})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()['record']['number'], '1')
        self.assertEqual(self.client.get('/api/local-deeds/search?number=999').status_code, 404)
        self.assertEqual(self.client.get('/api/local-deeds/search?number=../outside').status_code, 400)
        with self.client.get('/api/local-deeds/1/image') as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(self.client.get('/api/admin/local-deeds/1/image').status_code, 401)

    def test_exact_file_and_lossless_image_match(self):
        raw = (dolil.IMAGE_DIR / 'dolil_1.jpg').read_bytes()
        result = self.compare(raw).get_json()
        self.assertEqual(result['status'], 'EXACT_FILE_MATCH')
        self.assertTrue(result['file_match'])
        self.assertEqual(self.compare(raw, number='', filename='dolil_1.jpg').get_json()['status'], 'EXACT_FILE_MATCH')
        output = io.BytesIO()
        with Image.open(io.BytesIO(raw)) as image:
            image.save(output, 'PNG')
        result = self.compare(output.getvalue(), filename='renamed.png').get_json()
        self.assertEqual(result['status'], 'EXACT_IMAGE_MATCH')
        self.assertFalse(result['file_match'])
        self.assertTrue(result['image_match'])

    def test_wrong_number_and_changed_image_do_not_verify(self):
        raw = (dolil.IMAGE_DIR / 'dolil_2.jpg').read_bytes()
        self.assertEqual(self.compare(raw, number='1').get_json()['status'], 'NOT_EXACT_MATCH')
        raw = (dolil.IMAGE_DIR / 'dolil_1.jpg').read_bytes()
        output = io.BytesIO()
        with Image.open(io.BytesIO(raw)) as image:
            image.putpixel((1, 1), (255, 0, 0)); image.save(output, 'PNG')
        self.assertEqual(self.compare(output.getvalue()).get_json()['status'], 'NOT_EXACT_MATCH')
        self.assertEqual(self.compare(b'fake image').status_code, 400)
        self.assertEqual(self.compare(raw, number='', filename='camera.jpg').status_code, 400)
        self.assertEqual(self.compare(raw, number='999').status_code, 404)

    def test_admin_warnings_delete_restore_and_listing(self):
        self.login()
        listing = self.client.get('/api/admin/records?kind=local_deed').get_json()
        self.assertEqual(listing['total'], 2)
        control_url = '/api/admin/records/local_deed/1'
        detail = self.client.get(control_url)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.get_json()['record']['filename'], 'dolil_1.jpg')
        self.assertEqual(self.call('PATCH', control_url, {'warning': 'Review this copy'}).status_code, 200)
        raw = (dolil.IMAGE_DIR / 'dolil_1.jpg').read_bytes()
        self.assertEqual(self.compare(raw).get_json()['record']['warning'], 'Review this copy')
        self.call('PATCH', control_url, {'deleted': True})
        self.assertEqual(self.client.get('/api/local-deeds/search?number=1').status_code, 404)
        self.assertEqual(self.client.get('/api/local-deeds/1/image').status_code, 404)
        self.assertEqual(self.compare(raw).status_code, 404)
        with self.client.get('/api/admin/local-deeds/1/image') as response:
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/api/admin/records?kind=local_deed&state=deleted').get_json()['total'], 1)
        self.call('PATCH', control_url, {'deleted': False, 'warning': ''})
        self.assertEqual(self.compare(raw).get_json()['status'], 'EXACT_FILE_MATCH')
        self.assertEqual((dolil.IMAGE_DIR / 'dolil_1.jpg').read_bytes(), raw)

    def test_duplicate_numbers_never_choose_arbitrary_image(self):
        (dolil.IMAGE_DIR / 'dolil_01.png').write_bytes((dolil.IMAGE_DIR / 'dolil_1.jpg').read_bytes())
        self.assertEqual(self.client.get('/api/local-deeds/search?number=1').status_code, 409)
        self.assertEqual(self.compare((dolil.IMAGE_DIR / 'dolil_1.jpg').read_bytes()).status_code, 409)


if __name__ == '__main__':
    unittest.main()
