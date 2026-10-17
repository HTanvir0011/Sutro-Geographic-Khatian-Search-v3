"""Availability reflects searchable records, not just names in the directory."""
import json
import unittest

import app
import test_admin
from location_directory import location_key


class LocationAvailabilityTests(unittest.TestCase):
    setUp = test_admin.AdminTests.setUp
    tearDown = test_admin.AdminTests.tearDown

    def places(self, **params):
        response = self.client.get('/api/khatian/filters', query_string=params)
        self.assertEqual(response.status_code, 200)
        return response.get_json()['places']

    def test_official_names_are_marked_from_matching_sample_records(self):
        places = self.places()
        sylhet = [p for p in places if p['district'] == 'সিলেট']
        self.assertTrue(sylhet)
        self.assertTrue(all(p['district_has_khatian'] for p in sylhet))
        self.assertTrue(any(p['district'] == 'পঞ্চগড়' and not p['district_has_khatian'] for p in places))
        beanibazar = [p for p in sylhet if location_key(p['upazila']) == location_key('বিয়ানীবাজার')]
        self.assertTrue(all(p['upazila_has_khatian'] for p in beanibazar))
        scoped = self.places(district='সিলেট', upazila='বিয়ানীবাজার')
        self.assertTrue(any(location_key(p['mouza']) == location_key('উত্তরপাড়া') and p['has_khatian'] for p in scoped))
        self.assertTrue(any(p['source'] == 'land.gov.bd' and p['mouza'] and not p['has_khatian'] for p in scoped))

    def test_deleting_all_sample_records_clears_stars_but_keeps_directory(self):
        with app.conn() as db:
            db.execute("INSERT OR REPLACE INTO record_controls(kind,record_id,deleted,warning) SELECT 'khatian',khatian_id,1,'' FROM khatians")
        places = self.places()
        self.assertEqual(len({p['district'] for p in places if p['source']=='land.gov.bd'}), 64)
        self.assertTrue(all(not p['district_has_khatian'] and not p['upazila_has_khatian'] and not p['has_khatian'] for p in places))

    def test_admin_publication_delete_and_restore_change_availability(self):
        rec = {'division': 'Test Division', 'district': 'Test District', 'upazila': 'Test Upazila',
               'mouza': 'Test Mouza', 'khatian_no': '12345', 'survey': 'RS', 'owners': []}
        with app.conn() as db:
            db.execute('INSERT INTO uploaded_khatians VALUES (?,?,?,?,?,?,?)',
                       ('Uavailability', 'test.jpg', json.dumps(rec), '', 'draft', app.now(), ''))
        self.assertFalse(any(p['district']=='Test District' for p in self.places()))
        with app.conn() as db:
            db.execute("UPDATE uploaded_khatians SET status='published' WHERE id='Uavailability'")
        place = next(p for p in self.places() if p['district']=='Test District')
        self.assertTrue(place['district_has_khatian'] and place['upazila_has_khatian'] and place['has_khatian'])
        with app.conn() as db:
            db.execute("INSERT INTO record_controls VALUES ('khatian','Uavailability',1,'')")
        self.assertFalse(any(p['district']=='Test District' for p in self.places()))
        with app.conn() as db:
            db.execute("UPDATE record_controls SET deleted=0 WHERE record_id='Uavailability'")
        self.assertTrue(any(p['district']=='Test District' and p['has_khatian'] for p in self.places()))


    def test_number_suggestions_are_scoped_and_searchable(self):
        params = {'district':'সিলেট','upazila':'বিয়ানীবাজার','mouza':'উত্তরপাড়া','survey':'RS'}
        response = self.client.get('/api/khatian/numbers',query_string=params)
        self.assertEqual(response.status_code,200)
        data = response.get_json()
        self.assertEqual(data['total'],len(data['numbers']))
        self.assertTrue(any(row['number']=='850' for row in data['numbers']))
        self.assertEqual([int(row['number']) for row in data['numbers']],sorted(int(row['number']) for row in data['numbers']))
        for suggestion in data['numbers']:
            self.assertEqual(suggestion['surveys'],['RS'])
            self.assertEqual(suggestion['mouzas'],[location_key('উত্তরপাড়া')])
            result = self.client.get('/api/khatian/search',query_string={**params,'q':suggestion['number']})
            self.assertGreater(result.get_json()['total'],0)
        unknown = self.client.get('/api/khatian/numbers',query_string={**params,'mouza':'Unknown Mouza'})
        self.assertEqual(unknown.get_json(),{'numbers':[],'total':0})

    def test_number_suggestions_publish_deduplicate_and_delete(self):
        def record(survey):
            return {'division':'Test','district':'Test District','upazila':'Test Upazila',
                    'mouza':'Test Mouza','khatian_no':'12345','survey':survey,'owners':[]}
        with app.conn() as db:
            for record_id,status,survey in [('Usuggest1','published','RS'),('Usuggest2','published','BS'),('Usuggest3','draft','CS')]:
                db.execute('INSERT INTO uploaded_khatians VALUES (?,?,?,?,?,?,?)',
                           (record_id,'test.jpg',json.dumps(record(survey)),'',status,app.now(),''))
        params={'district':'Test District','upazila':'Test Upazila'}
        data=self.client.get('/api/khatian/numbers',query_string=params).get_json()
        self.assertEqual(data['total'],1)
        self.assertEqual(data['numbers'][0],{'number':'12345','surveys':['BS','RS'],'mouzas':['Test Mouza'],'records':2})
        self.assertEqual(self.client.get('/api/khatian/numbers',query_string={**params,'survey':'CS'}).get_json()['total'],0)
        with app.conn() as db:
            db.execute("INSERT INTO record_controls VALUES ('khatian','Usuggest1',1,'')")
        remaining=self.client.get('/api/khatian/numbers',query_string=params).get_json()['numbers'][0]
        self.assertEqual(remaining['records'],1)
        self.assertEqual(remaining['surveys'],['BS'])
        with app.conn() as db:
            db.execute("INSERT INTO record_controls VALUES ('khatian','Usuggest2',1,'')")
        self.assertEqual(self.client.get('/api/khatian/numbers',query_string=params).get_json()['total'],0)

    def test_number_suggestions_require_valid_location_and_survey(self):
        for params in ({},{'district':'সিলেট'},{'district':'সিলেট','upazila':'test','survey':'INVALID'}):
            self.assertEqual(self.client.get('/api/khatian/numbers',query_string=params).status_code,400)


if __name__ == '__main__':
    unittest.main()
