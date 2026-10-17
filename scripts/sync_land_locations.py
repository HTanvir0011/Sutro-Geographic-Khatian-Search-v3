"""Refresh the public DLRMS location directory; no deeds or owner data are fetched.

Run: python scripts/sync_land_locations.py
Completed upazilas are checkpointed so an interrupted download can be resumed.
"""
import http.cookiejar
import os
import json
import time
import urllib.parse
import urllib.request
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'data' / 'land_locations.json'
PORTAL = 'https://dlrms.land.gov.bd/'
API = 'https://gateway.dlrms.land.gov.bd/core-api/api/public/'


@contextmanager
def download_lock():
    OUTPUT.parent.mkdir(exist_ok=True)
    with OUTPUT.with_suffix('.lock').open('a+b') as lock:
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError('A location download is already running') from None
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


class Portal:
    def __init__(self):
        self.refresh()

    def refresh(self):
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        with self.opener.open(PORTAL, timeout=30) as response:
            response.read()
        self.token = next(c.value for c in jar if c.name == 'dlrms_app_token')

    def get(self, route, **params):
        url = API + route + ('?' + urllib.parse.urlencode(params) if params else '')
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={
                    'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json'})
                with self.opener.open(req, timeout=30) as response:
                    payload = json.load(response)
                if payload.get('success') is not True or not isinstance(payload.get('data'), list):
                    raise ValueError('Unexpected public location response')
                return payload['data']
            except Exception as exc:
                if attempt == 2:
                    raise
                print(f'Retrying public {route}: {type(exc).__name__}', flush=True)
                time.sleep(attempt + 1)
                self.refresh()


def save(data):
    OUTPUT.parent.mkdir(exist_ok=True)
    temp = OUTPUT.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    # Windows readers/virus scanners can briefly hold the destination open.
    for attempt in range(20):
        try:
            temp.replace(OUTPUT)
            break
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.1)


def main():
    portal = Portal()
    old = json.loads(OUTPUT.read_text(encoding='utf-8')) if OUTPUT.exists() else {}
    divisions = portal.get('divisions')
    districts = portal.get('districts')
    upazilas = portal.get('upazilas')
    data = {'source': PORTAL, 'api': API, 'started_at': datetime.now(timezone.utc).isoformat(),
            'complete': False, 'survey_scopes': old.get('survey_scopes', {}),
            'divisions': [{'id': r['BBS_CODE'], 'name': r['NAME']} for r in divisions],
            'districts': [{'id': r['BBS_CODE'], 'division_id': r['DIVISION_BBS_CODE'],
                           'name': r['NAME']} for r in districts],
            'upazilas': [], 'mouzas': old.get('mouzas', {})}
    for r in upazilas:
        key = f"{r['DISTRICT_BBS_CODE']}:{r['BBS_CODE']}"
        data['upazilas'].append({'id': key, 'district_id': r['DISTRICT_BBS_CODE'],
                                'bbs_code': r['BBS_CODE'], 'name': r['NAME']})
    # Only retain checkpoints for locations that are still in the official directory.
    keys = {r['id'] for r in data['upazilas']}
    data['mouzas'] = {k: v for k, v in data['mouzas'].items() if k in keys}
    for index, upazila in enumerate(data['upazilas'], 1):
        if upazila['id'] not in data['mouzas']:
            rows = portal.get('mouzas/jl-numbers', DISTRICT_BBS_CODE=upazila['district_id'],
                              UPAZILA_BBS_CODE=upazila['bbs_code'])
            data['mouzas'][upazila['id']] = [
                {'id': r['ID'], 'mouza_id': r['MOUZA_ID'], 'name': r['MOUZA_NAME'],
                 'jl_no': r['JL_NUMBER']} for r in rows]
            save(data)
            time.sleep(0.15)
        if index % 25 == 0:
            print(f"Loaded {index}/{len(upazilas)} upazilas", flush=True)
    # Survey records can use additional mouzas/spellings absent from mutation lists.
    # Fetch every survey assigned to each upazila, then union the location entries.
    def survey_locations(upazila):
        rows = list(data['mouzas'][upazila['id']])
        surveys = portal.get('upazilas/surveys', DISTRICT_BBS_CODE=upazila['district_id'],
                             UPAZILA_BBS_CODE=upazila['bbs_code'])
        for survey in surveys:
            entries = portal.get('mouzas/jl-numbers', DISTRICT_BBS_CODE=upazila['district_id'],
                                 UPAZILA_BBS_CODE=upazila['bbs_code'], SURVEY_ID=survey['SURVEY_ID'])
            rows.extend({'id': r['ID'], 'mouza_id': r['MOUZA_ID'], 'name': r['MOUZA_NAME'],
                         'jl_no': r['JL_NUMBER']} for r in entries)
            time.sleep(0.15)
        unique = {}
        for row in rows:
            row['name'] = (row['name'] or '').strip()
            if not row['name']:
                continue
            key = (row['mouza_id'], unicodedata.normalize('NFC', row['name']), row['jl_no'])
            unique.setdefault(key, row)
        return upazila['id'], list(unique.values()), [s['SURVEY_ID'] for s in surveys]

    pending = [r for r in data['upazilas'] if r['id'] not in data['survey_scopes']]
    failures = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(survey_locations, row): row['id'] for row in pending}
        for index, future in enumerate(as_completed(futures), 1):
            try:
                key, rows, scopes = future.result()
            except Exception as exc:
                failures.append(futures[future])
                print(f"Could not complete {futures[future]}: {type(exc).__name__}: {exc}", flush=True)
                continue
            data['mouzas'][key] = rows
            data['survey_scopes'][key] = scopes
            save(data)
            if index % 25 == 0:
                print(f"Survey lists loaded for {index}/{len(pending)} upazilas", flush=True)
    data['complete'] = not failures
    data['fetched_at'] = datetime.now(timezone.utc).isoformat()
    save(data)
    if failures:
        raise RuntimeError(f'{len(failures)} areas could not be refreshed; rerun to resume')
    print(f"Saved {len(districts)} districts, {len(upazilas)} upazilas and "
          f"{sum(len(v) for v in data['mouzas'].values())} mouza/JL entries to {OUTPUT}")


if __name__ == '__main__':
    with download_lock():
        main()
