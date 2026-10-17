"""Official location names, kept separate from the synthetic khatian dataset."""
import json
import unicodedata
from functools import lru_cache
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent / 'data' / 'land_locations.json'


def location_key(value):
    return unicodedata.normalize('NFC', str(value or '')).strip()


@lru_cache(maxsize=1)
def _read_directory(stamp):
    return json.loads(DIRECTORY.read_text(encoding='utf-8'))


def directory_places(district='', upazila=''):
    if not DIRECTORY.is_file():
        return [], {'available': False}
    data = _read_directory(DIRECTORY.stat().st_mtime_ns)
    divisions = {r['id']: r['name'] for r in data['divisions']}
    districts = {r['id']: r for r in data['districts']}
    places = []
    for row in data['upazilas']:
        parent = districts[row['district_id']]
        if district and location_key(parent['name']) != location_key(district):
            continue
        if upazila and location_key(row['name']) != location_key(upazila):
            continue
        base = {'division': divisions[parent['division_id']], 'district': parent['name'],
                'upazila': row['name'], 'source': 'land.gov.bd'}
        # Load mouzas only for a selected upazila to keep the initial response small.
        places.append({**base, 'mouza': ''})
        if district and upazila:
            for mouza in data['mouzas'].get(row['id'], []):
                places.append({**base, 'mouza': mouza['name'], 'jl_no': mouza['jl_no']})
    return places, {'available': True, 'source': data['source'],
                    'fetched_at': data.get('fetched_at'), 'complete': data['complete'],
                    'districts': len(data['districts']), 'upazilas': len(data['upazilas']),
                    'mouza_entries': sum(len(v) for v in data['mouzas'].values())}


def merge_places(official, samples):
    """Prefer official spellings; keep sample-only locations available for the demo."""
    result = {}
    labels = {}
    for row in official + samples:
        item = dict(row)
        for field in ('division', 'district', 'upazila', 'mouza'):
            key = (field, location_key(item[field]))
            item[field] = labels.setdefault(key, item[field])
        key = tuple(location_key(item[f]) for f in ('division', 'district', 'upazila', 'mouza'))
        result.setdefault(key, item)
    return list(result.values())
