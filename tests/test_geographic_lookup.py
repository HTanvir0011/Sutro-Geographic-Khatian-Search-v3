"""Integration tests for the real synthetic CSV relationship keys."""
import unittest
import app


class GeoLookupTests(unittest.TestCase):
    def test_join_counts(self):
        with app.conn() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) n FROM lands').fetchone()['n'], 2000)
            self.assertEqual(db.execute('SELECT COUNT(*) n FROM khatians').fetchone()['n'], 5794)
            self.assertEqual(db.execute('SELECT COUNT(*) n FROM owners').fetchone()['n'], 23120)
            self.assertEqual(db.execute('SELECT COUNT(*) n FROM dag_rows').fetchone()['n'], 31572)
            self.assertEqual(db.execute('SELECT COUNT(*) n FROM title_line').fetchone()['n'], 3794)
            unmatched=db.execute('SELECT count(*) n FROM khatians k LEFT JOIN lands l ON k.land_id=l.land_id WHERE l.land_id IS NULL').fetchone()['n']
            self.assertEqual(unmatched,0)

    def test_specific_real_csv_relationship(self):
        with app.conn() as db:
            row=db.execute('''SELECT k.*, l.division, l.district, l.upazila, l.mouza, l.jl_no
                              FROM khatians k JOIN lands l ON k.land_id=l.land_id
                              WHERE k.khatian_no=? AND l.district=? AND l.upazila=? AND l.mouza=? AND k.survey=?''',
                           ('850','সিলেট','বিয়ানীবাজার','উত্তরপাড়া','RS')).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row['khatian_id'],'L00000-v0')
            detail=app.full_khatian_details(db,app.khatian_dict(row))
            self.assertEqual(len(detail['owners']),2)
            self.assertEqual(len(detail['dag_rows']),3)
            self.assertTrue(detail['history'])

    def test_source_annotations_confirm_synthetic(self):
        # This application does not depend on OCR or JSONL runtime input.
        with app.conn() as db:
            self.assertGreater(db.execute('SELECT COUNT(*) n FROM lands WHERE district=?',('সিলেট',)).fetchone()['n'],0)


if __name__ == '__main__':
    unittest.main()
