"""Run on your PC after pip install -r requirements.txt: python -m unittest discover -s tests -v"""
import unittest
import app

class SutroTests(unittest.TestCase):
    def test_csv_load(self):
        with app.conn() as db:
            count=db.execute('SELECT COUNT(*) n FROM khatians').fetchone()['n']
        self.assertEqual(count,5794)

    def test_many_matches_for_850(self):
        with app.conn() as db:
            count=db.execute("SELECT COUNT(*) n FROM khatians WHERE khatian_no='850'").fetchone()['n']
        self.assertEqual(count,5)

    def test_bangla_numbers(self):
        self.assertEqual(app.normalize_no('৮৫০'),'850')

    def test_pdf_digest_and_signature(self):
        context = app.app.test_request_context('/')
        context.push()
        self.addCleanup(context.pop)
        record=app.find_deed('ST-DEMO-0001')
        self.assertTrue(app.signature_ok(record['hash'],record['signature']))
        pdf=app.deed_pdf_bytes(record)
        extracted=app.extract_pdf(pdf)
        self.assertEqual(app.digest(extracted),record['hash'])
        self.assertTrue(app.signature_ok(app.digest(extracted),extracted['_signature']))
        modified=app.extract_pdf(app.deed_pdf_bytes(record,change_owner=True))
        self.assertNotEqual(modified['owner_name'],record['record']['owner_name'])
        self.assertFalse(app.signature_ok(app.digest(modified),modified['_signature']))

    def test_audit_chain(self):
        self.assertTrue(app.audit_check())

if __name__=='__main__':unittest.main()
