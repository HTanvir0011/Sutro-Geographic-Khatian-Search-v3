"""Sutro / সূত্র: synthetic khatian image lookup and digital deed verification demo.

Khatian search uses local CSVs and admin-reviewed uploads. Admin image uploads
use local Bengali/English OCR to propose a draft before publication.
"""
from __future__ import annotations
import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

import pdfplumber
import qrcode
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from flask import Flask, abort, jsonify, render_template, request, send_file
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from dotenv import load_dotenv
from location_directory import directory_places, location_key, merge_places
from admin_panel import register_admin, controls, public_custom, authorize_write, authenticated
from complaints import register_complaints
from dolil import register_dolil
from evidence_review import register_evidence

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
INSTANCE = ROOT / 'instance'
INSTANCE.mkdir(exist_ok=True)
DB_FILE = INSTANCE / 'sutro.sqlite3'
CSV_FILE = ROOT / 'khatians.csv'
LANDS_FILE = ROOT / 'lands.csv'
OWNERS_FILE = ROOT / 'owners.csv'
DAGS_FILE = ROOT / 'dag_rows.csv'
TITLE_FILE = ROOT / 'title_line.csv'
PHOTO_ROOT = Path(os.getenv('SUTRO_KHATIAN_IMAGE_DIR', str(ROOT / 'khatian'))).expanduser()
DEMO_PHOTO = ROOT / 'static' / 'demo' / 'L00000-v0.jpg'
BN_DIGITS = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')
DATA_FIELDS = ['deed_id', 'owner_name', 'khatian_no', 'dag_no', 'land_area_decimal', 'mouza', 'upazila', 'district', 'deed_date']
PDF_LABELS = ['Deed ID', 'Owner Name', 'Khatian No', 'Dag No', 'Land Area Decimal', 'Mouza', 'Upazila', 'District', 'Deed Date']
app = Flask(__name__)
app.json.ensure_ascii = False
app.config['MAX_CONTENT_LENGTH'] = 15 * 1024 * 1024
pdfmetrics.registerFont(TTFont('SutroBangla', str(ROOT/'static/fonts/NotoSansBengali-Regular.ttf')))


@contextmanager
def conn():
    con = sqlite3.connect(DB_FILE, timeout=30)
    con.row_factory = sqlite3.Row
    con.create_function('location_key', 1, location_key, deterministic=True)
    try:
        with con:
            yield con
    finally:
        con.close()


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def normalize_no(value: str) -> str:
    return str(value or '').translate(BN_DIGITS).strip()


def canon(data: dict[str, Any]) -> bytes:
    return json.dumps({k: str(data.get(k, '')).strip() for k in DATA_FIELDS}, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def digest(data):
    return hashlib.sha256(canon(data)).hexdigest()


def get_keys():
    # Reuse the prior Sutro signing key when upgrading an existing project.
    modern = INSTANCE / 'private_ed25519.pem'
    previous = INSTANCE / 'ed25519_private.pem'
    priv_file = modern if modern.exists() or not previous.exists() else previous
    pub_file = INSTANCE / ('ed25519_public.pem' if priv_file == previous else 'public_ed25519.pem')
    if priv_file.exists():
        private = serialization.load_pem_private_key(priv_file.read_bytes(), password=None)
        if not isinstance(private, Ed25519PrivateKey):
            raise RuntimeError('Stored private key is not Ed25519')
    else:
        private = Ed25519PrivateKey.generate()
        priv_file.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        try: os.chmod(priv_file, 0o600)
        except OSError: pass
    public = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    if not pub_file.exists() or pub_file.read_bytes() != public:
        pub_file.write_bytes(public)
    return private, public.decode('ascii')


PRIVATE_KEY, PUBLIC_KEY_PEM = get_keys()


def signature_ok(data_hash: str, sig: str) -> bool:
    try:
        PRIVATE_KEY.public_key().verify(bytes.fromhex(sig), bytes.fromhex(data_hash))
        return True
    except (ValueError, InvalidSignature, TypeError):
        return False


def audit(event: str, deed_id: str = '', details: dict | None = None, stamp: str | None = None):
    stamp = stamp or now()
    details = details or {}
    details_str = json.dumps(details, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    with conn() as db:
        db.execute('BEGIN IMMEDIATE')
        last = db.execute('SELECT event_hash FROM audit ORDER BY id DESC LIMIT 1').fetchone()
        previous = last['event_hash'] if last else '0'*64
        body = json.dumps({'stamp': stamp, 'deed_id': deed_id, 'event': event, 'details': details_str, 'previous': previous}, sort_keys=True, separators=(',', ':'))
        event_hash = hashlib.sha256(body.encode()).hexdigest()
        db.execute('INSERT INTO audit (stamp,deed_id,event,details,previous_hash,event_hash) VALUES (?,?,?,?,?,?)', (stamp,deed_id,event,details_str,previous,event_hash))


def audit_check():
    prev='0'*64
    with conn() as db:
        rows=db.execute('SELECT * FROM audit ORDER BY id').fetchall()
    for r in rows:
        body=json.dumps({'stamp':r['stamp'],'deed_id':r['deed_id'],'event':r['event'],'details':r['details'],'previous':r['previous_hash']},sort_keys=True,separators=(',', ':'))
        current=hashlib.sha256(body.encode()).hexdigest()
        if r['previous_hash']!=prev or r['event_hash']!=current:
            return False
        prev=current
    return True


def insert_deed(data: dict[str, str], actor='Demo officer') -> dict:
    clean={field: str(data.get(field,'')).strip() for field in DATA_FIELDS}
    h=digest(clean)
    sig=PRIVATE_KEY.sign(bytes.fromhex(h)).hex()
    with conn() as db:
        db.execute('INSERT INTO deeds (deed_id,record_json,hash,signature,created_at,actor) VALUES (?,?,?,?,?,?)', (clean['deed_id'],json.dumps(clean,ensure_ascii=False),h,sig,now(),actor))
    audit('deed_created',clean['deed_id'],{'hash':h})
    return {'record':clean, 'hash':h,'signature':sig}


def find_deed(deed_id: str):
    with conn() as db:
        row=db.execute('SELECT * FROM deeds WHERE deed_id=?',(deed_id,)).fetchone()
        control=controls(db,'deed',deed_id)
    if control['deleted']:return None
    if not row:return None
    return {'record':json.loads(row['record_json']),'hash':row['hash'],'signature':row['signature'],'created_at':row['created_at'],'warning':control['warning']}


def conflicts():
    with conn() as db:
        rows=db.execute("SELECT deed_id,record_json FROM deeds WHERE NOT EXISTS (SELECT 1 FROM record_controls c WHERE c.kind='deed' AND c.record_id=deeds.deed_id AND c.deleted=1) ORDER BY deed_id").fetchall()
    groups={}
    for r in rows:
        rec=json.loads(r['record_json'])
        key=tuple(location_key(rec[k]).casefold() for k in ('district','upazila','mouza'))+(normalize_no(rec['khatian_no']),normalize_no(rec['dag_no']))
        groups.setdefault(key,[]).append({'deed_id':r['deed_id'],'owner_name':rec['owner_name']})
    return [{'khatian_no':key[-2],'dag_no':key[-1],'deeds':entries} for key,entries in groups.items() if len(entries)>1 and len({e['owner_name'].casefold() for e in entries})>1]


def import_khatians():
    if not CSV_FILE.is_file():
        raise FileNotFoundError('khatians.csv missing. Place it beside app.py')
    with conn() as db:
        existing=db.execute('SELECT COUNT(*) c FROM khatians').fetchone()['c']
        meta=db.execute('SELECT val FROM config WHERE key="csv_signature"').fetchone()
        # Length and mtime are enough to detect edits in local demo; avoid reloading on every request.
        stat=CSV_FILE.stat()
        stamp=f'{stat.st_size}:{stat.st_mtime_ns}'
        if existing and meta and meta['val']==stamp: return
        with CSV_FILE.open('r',encoding='utf-8-sig',newline='') as f:
            reader=csv.DictReader(f)
            expected={'khatian_id','khatian_no','image_file','survey','year','sheet_no','land_id','total_land_dec'}
            if not expected.issubset(set(reader.fieldnames or [])):
                raise ValueError('CSV is missing required khatian columns')
            records=[]
            for row in reader:
                kid=row['khatian_id'].strip()
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,70}',kid): continue
                rel=row['image_file'].replace('\\','/').strip()
                parts=PurePosixPath(rel).parts
                if not parts or '..' in parts or rel.startswith('/') or not rel.lower().endswith(('.jpg','.jpeg','.png','.webp')): continue
                records.append((kid,row.get('land_id','').strip(),normalize_no(row.get('khatian_no','')),row.get('survey','').strip().upper(),row.get('year','').strip(),row.get('sheet_no','').strip(),row.get('n_owners','').strip(),row.get('n_dag_rows','').strip(),row.get('total_land_dec','').strip(),rel,row.get('split','').strip()))
        db.execute('DELETE FROM khatians')
        db.executemany('INSERT INTO khatians (khatian_id,land_id,khatian_no,survey,year,sheet_no,n_owners,n_dag_rows,total_land_dec,image_file,split) VALUES (?,?,?,?,?,?,?,?,?,?,?)',records)
        db.execute('INSERT OR REPLACE INTO config(key,val) VALUES (?,?)',('csv_signature',stamp))


def import_related_csvs():
    """Load the source CSVs with their actual foreign keys:

    khatians.land_id -> lands.land_id
    owners/dag_rows.khatian_id -> khatians.khatian_id
    title_line.from_khatian_id/to_khatian_id -> khatians.khatian_id

    These are synthetic sample records, not official deeds or ownership proof.
    """
    sources = (
        ('lands', LANDS_FILE, ['land_id','split','division','district','upazila','mouza','jl_no','n_dags','n_versions']),
        ('owners', OWNERS_FILE, ['khatian_id','owner_idx','name_bn','gender','father_or_spouse_bn','relation','village_bn','share_exact','share_printed_3dp']),
        ('dag_rows', DAGS_FILE, ['khatian_id','row_idx','dag_no','land_class_bn','total_acre','total_dec','share_in_dag','area_acre','area_dec','remark_bn','revenue']),
        ('title_line', TITLE_FILE, ['land_id','from_khatian_id','to_khatian_id','from_survey','to_survey','transition','detail_json']),
    )
    with conn() as db:
        for table, file_path, keys in sources:
            if not file_path.is_file():
                raise FileNotFoundError(f'Missing dataset: {file_path.name}. Keep all source CSVs beside app.py')
            file_stat = file_path.stat()
            stamp = f'{file_stat.st_size}:{file_stat.st_mtime_ns}'
            meta_key = f'{table}_csv_signature'
            old_stamp = db.execute('SELECT val FROM config WHERE key=?',(meta_key,)).fetchone()
            exists = db.execute(f'SELECT COUNT(*) n FROM {table}').fetchone()['n']
            if old_stamp and old_stamp['val']==stamp and exists:
                continue
            with file_path.open('r',encoding='utf-8-sig',newline='') as src:
                reader = csv.DictReader(src)
                if not set(keys).issubset(set(reader.fieldnames or [])):
                    raise ValueError(f'{file_path.name} is missing expected columns')
                rows = [tuple((row.get(k) or '').strip() for k in keys) for row in reader]
            db.execute(f'DELETE FROM {table}')
            columns = ','.join(keys)
            marks = ','.join('?' for _ in keys)
            db.executemany(f'INSERT INTO {table} ({columns}) VALUES ({marks})',rows)
            db.execute('INSERT OR REPLACE INTO config(key,val) VALUES (?,?)',(meta_key,stamp))


def full_khatian_details(db: sqlite3.Connection, record: dict):
    kid = record['khatian_id']
    record['owners'] = [dict(row) for row in db.execute(
        'SELECT owner_idx,name_bn,father_or_spouse_bn,relation,village_bn,share_exact,share_printed_3dp '
        'FROM owners WHERE khatian_id=? ORDER BY CAST(owner_idx AS INTEGER)',(kid,))]
    record['dag_rows'] = [dict(row) for row in db.execute(
        'SELECT row_idx,dag_no,land_class_bn,total_dec,share_in_dag,area_dec,remark_bn '
        'FROM dag_rows WHERE khatian_id=? ORDER BY CAST(row_idx AS INTEGER)',(kid,))]
    record['history'] = [dict(row) for row in db.execute(
        'SELECT from_khatian_id,to_khatian_id,from_survey,to_survey,transition '
        'FROM title_line WHERE from_khatian_id=? OR to_khatian_id=? '
        'ORDER BY from_khatian_id LIMIT 12',(kid,kid))]
    return record

def migrate_previous_registry():
    """Keep signed deeds/keys from the earlier Sutro prototype when upgrading in place."""
    with conn() as db:
        existing={col['name'] for col in db.execute('PRAGMA table_info(deeds)').fetchall()}
        if existing and 'hash' not in existing and 'record_hash' in existing:
            db.execute("ALTER TABLE deeds ADD COLUMN hash TEXT NOT NULL DEFAULT ''")
            db.execute('UPDATE deeds SET hash=record_hash WHERE hash=?',('',))
        if existing and 'actor' not in existing:
            db.execute("ALTER TABLE deeds ADD COLUMN actor TEXT NOT NULL DEFAULT 'Legacy demo officer'")
            if 'created_by' in existing: db.execute('UPDATE deeds SET actor=created_by')
        legacy=db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audit_events'").fetchone()
        has_new=db.execute('SELECT COUNT(*) n FROM audit').fetchone()['n']
        old=[]
        if legacy and has_new==0:
            old=db.execute('SELECT deed_id,event_type,details_json,created_at FROM audit_events ORDER BY id').fetchall()
    for row in old:
        try: details=json.loads(row['details_json'])
        except (TypeError,ValueError): details={}
        audit('legacy_'+str(row['event_type']),row['deed_id'] or '',details,stamp=row['created_at'])


def initialize():
    with conn() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, val TEXT);
            CREATE TABLE IF NOT EXISTS khatians (
              khatian_id TEXT PRIMARY KEY,land_id TEXT,khatian_no TEXT,survey TEXT,year TEXT,
              sheet_no TEXT,n_owners TEXT,n_dag_rows TEXT,total_land_dec TEXT,image_file TEXT,split TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_khatian_no ON khatians(khatian_no);
            CREATE INDEX IF NOT EXISTS ix_khatian_land ON khatians(land_id);
            CREATE TABLE IF NOT EXISTS lands (
                land_id TEXT PRIMARY KEY, split TEXT, division TEXT, district TEXT,
                upazila TEXT, mouza TEXT, jl_no TEXT, n_dags TEXT, n_versions TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_land_location ON lands(district,upazila,mouza);
            CREATE TABLE IF NOT EXISTS owners (
                khatian_id TEXT,owner_idx TEXT,name_bn TEXT,gender TEXT,
                father_or_spouse_bn TEXT,relation TEXT,village_bn TEXT,
                share_exact TEXT,share_printed_3dp TEXT,
                PRIMARY KEY(khatian_id,owner_idx)
            );
            CREATE TABLE IF NOT EXISTS dag_rows (
                khatian_id TEXT,row_idx TEXT,dag_no TEXT,land_class_bn TEXT,
                total_acre TEXT,total_dec TEXT,share_in_dag TEXT,area_acre TEXT,
                area_dec TEXT,remark_bn TEXT,revenue TEXT,
                PRIMARY KEY(khatian_id,row_idx)
            );
            CREATE TABLE IF NOT EXISTS title_line (
                land_id TEXT,from_khatian_id TEXT,to_khatian_id TEXT,
                from_survey TEXT,to_survey TEXT,transition TEXT,detail_json TEXT,
                PRIMARY KEY(land_id,from_khatian_id,to_khatian_id)
            );
            CREATE INDEX IF NOT EXISTS ix_owner_khatian ON owners(khatian_id);
            CREATE INDEX IF NOT EXISTS ix_dag_khatian ON dag_rows(khatian_id);
            CREATE INDEX IF NOT EXISTS ix_title_to ON title_line(to_khatian_id);

            CREATE TABLE IF NOT EXISTS deeds (deed_id TEXT PRIMARY KEY,record_json TEXT NOT NULL,hash TEXT NOT NULL,signature TEXT NOT NULL,created_at TEXT NOT NULL,actor TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT,stamp TEXT NOT NULL,deed_id TEXT NOT NULL,event TEXT NOT NULL,details TEXT NOT NULL,previous_hash TEXT NOT NULL,event_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evidence_reviews (
                id TEXT PRIMARY KEY,khatian_id TEXT NOT NULL,deed_id TEXT NOT NULL,outcome TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,created_at TEXT NOT NULL
            );
        ''')
        count=db.execute('SELECT COUNT(*) n FROM deeds').fetchone()['n']
    migrate_previous_registry()
    import_khatians()
    import_related_csvs()
    with conn() as db:
        count=db.execute('SELECT COUNT(*) n FROM deeds').fetchone()['n']
    if not count:
        for d in [
            {'deed_id':'ST-DEMO-0001','owner_name':'Demo Owner 001','khatian_no':'850','dag_no':'205','land_area_decimal':'12.50','mouza':'Demo Mouza A','upazila':'Savar','district':'Dhaka','deed_date':'2026-10-01'},
            {'deed_id':'ST-DEMO-0002','owner_name':'Demo Owner 009','khatian_no':'850','dag_no':'205','land_area_decimal':'12.50','mouza':'Demo Mouza A','upazila':'Savar','district':'Dhaka','deed_date':'2026-10-02'},
            {'deed_id':'ST-DEMO-0003','owner_name':'Demo Owner 003','khatian_no':'538','dag_no':'410','land_area_decimal':'7.25','mouza':'Demo Mouza B','upazila':'Savar','district':'Dhaka','deed_date':'2026-10-03'}]:
            insert_deed(d,'Synthetic starter data')


def image_path(record: dict) -> Path | None:
    # No user-controlled paths: only CSV-listed records, with validated segments.
    rel=PurePosixPath(record['image_file'])
    basename=rel.name
    if not re.fullmatch(r'[\w.\-]{1,150}',basename): return None
    candidates=[PHOTO_ROOT.joinpath(*rel.parts), PHOTO_ROOT / basename]
    # Support a common alternative layout where files are in ./khatian/train/*.jpg
    if PHOTO_ROOT.name.lower() != 'khatian':
        candidates += [ROOT / 'khatian' / basename,ROOT / 'khatian' / Path(*rel.parts)]
    for candidate in candidates:
        try:
            safe_root=PHOTO_ROOT.resolve()
            if candidate.resolve().is_relative_to(safe_root) and candidate.is_file():return candidate
        except (OSError,ValueError):pass
    if record['khatian_id']=='L00000-v0' and DEMO_PHOTO.is_file():return DEMO_PHOTO
    return None


def khatian_dict(row: sqlite3.Row, include_image=True):
    obj=dict(row)
    image=image_path(obj) if include_image else None
    obj['has_image']=image is not None
    obj['image_url'] = '/api/khatian-image/'+quote(obj['khatian_id'],safe='') if image else None
    return obj


@app.get('/')
def home():return render_template('index.html', qr_deed='')

@app.get('/verify/<deed_id>')
def verification_page(deed_id):return render_template('index.html',qr_deed=deed_id)

@app.get('/api/khatian/filters')
def khatian_filters():
    district = request.args.get('district', '').strip()
    upazila = request.args.get('upazila', '').strip()
    if any(len(value) > 90 for value in (district, upazila)) or (upazila and not district):
        return jsonify({'error': 'Invalid location selection.'}), 400
    official, directory = directory_places(district, upazila)
    with conn() as db:
        places = db.execute('''SELECT DISTINCT division,district,upazila,mouza FROM lands
                               WHERE district != '' AND upazila != '' AND mouza != ''
                               ORDER BY division,district,upazila,mouza''').fetchall()
        uploaded = [{k: rec.get(k,'') for k in ('division','district','upazila','mouza')} for rec in public_custom(db)]
        available = db.execute('''SELECT DISTINCT l.district,l.upazila,l.mouza
            FROM khatians k JOIN lands l ON l.land_id=k.land_id
            WHERE NOT EXISTS (SELECT 1 FROM record_controls c WHERE c.kind='khatian'
                              AND c.record_id=k.khatian_id AND c.deleted=1)''').fetchall()
    available = [tuple(location_key(row[field]) for field in ('district','upazila','mouza'))
                 for row in list(available)+uploaded]
    available_districts = {row[0] for row in available}
    available_upazilas = {row[:2] for row in available}
    available_mouzas = set(available)
    places = list(places) + uploaded
    samples = [{**dict(row), 'source': 'sample'} for row in places
               if (not district or location_key(row['district']) == location_key(district))
               and (not upazila or location_key(row['upazila']) == location_key(upazila))]
    merged = merge_places(official, samples)
    for place in merged:
        key = tuple(location_key(place[field]) for field in ('district','upazila','mouza'))
        place['district_has_khatian'] = key[0] in available_districts
        place['upazila_has_khatian'] = key[:2] in available_upazilas
        place['has_khatian'] = bool(key[2]) and key in available_mouzas
    return jsonify({'places': merged, 'directory': directory,
                    'surveys': ['CS','SA','RS','BS','BRS','BDS'], 'record_source': 'local_sample_csv', 'additional_record_source': 'admin_upload'})


@app.get('/api/khatian/numbers')
def khatian_numbers():
    district = request.args.get('district', '').strip()
    upazila = request.args.get('upazila', '').strip()
    mouza = request.args.get('mouza', '').strip()
    survey = request.args.get('survey', '').strip().upper()
    if not district or not upazila or any(len(v)>90 for v in (district,upazila,mouza)):
        return jsonify(error='Select a valid district and upazila.'), 400
    if survey and survey not in {'CS','SA','RS','BS','BRS','BDS'}:
        return jsonify(error='Invalid survey selection.'), 400
    where = ['location_key(l.district)=?', 'location_key(l.upazila)=?',
             "NOT EXISTS (SELECT 1 FROM record_controls c WHERE c.kind='khatian' AND c.record_id=k.khatian_id AND c.deleted=1)"]
    args = [location_key(district), location_key(upazila)]
    if mouza:
        where.append('location_key(l.mouza)=?');args.append(location_key(mouza))
    if survey:
        where.append('k.survey=?');args.append(survey)
    with conn() as db:
        rows = [dict(row) for row in db.execute('SELECT k.khatian_no,k.survey,l.mouza FROM khatians k '
                'JOIN lands l ON l.land_id=k.land_id WHERE '+' AND '.join(where),args)]
        rows += [rec for rec in public_custom(db)
                 if location_key(rec['district'])==location_key(district)
                 and location_key(rec['upazila'])==location_key(upazila)
                 and (not mouza or location_key(rec['mouza'])==location_key(mouza))
                 and (not survey or rec['survey']==survey)]
    grouped = {}
    for rec in rows:
        number = normalize_no(rec['khatian_no'])
        if not re.fullmatch(r'[0-9]{1,15}',number):
            continue
        entry = grouped.setdefault(number, {'number': number, 'surveys': set(), 'mouzas': set(), 'records': 0})
        entry['surveys'].add(rec['survey'])
        entry['mouzas'].add(location_key(rec['mouza']))
        entry['records'] += 1
    numbers = [{**entry,'surveys':sorted(entry['surveys']),'mouzas':sorted(entry['mouzas'])}
               for entry in sorted(grouped.values(),key=lambda entry:(int(entry['number']),entry['number']))]
    return jsonify(numbers=numbers,total=len(numbers))


@app.get('/api/khatian/search')
def khatian_search():
    q = normalize_no(request.args.get('q',''))
    district = request.args.get('district','').strip()
    upazila = request.args.get('upazila','').strip()
    mouza = request.args.get('mouza','').strip()
    survey = request.args.get('survey','').strip().upper()
    if not district or not upazila:
        return jsonify({'error':'Select district and upazila before searching.'}),400
    if not q or not re.fullmatch(r'\d{1,15}',q):
        return jsonify({'error':'Enter a numeric khatian number, such as 850 or ৮৫০.'}),400
    if any(len(s)>90 for s in (district,upazila,mouza)) or (survey and survey not in {'CS','SA','RS','BS','BRS','BDS'}):
        return jsonify({'error':'Invalid location or survey selection.'}),400
    where = ['k.khatian_no=?','location_key(l.district)=?','location_key(l.upazila)=?']
    args = [q,location_key(district),location_key(upazila)]
    if mouza:
        where.append('location_key(l.mouza)=?');args.append(location_key(mouza))
    if survey:
        where.append('k.survey=?');args.append(survey)
    where.append("NOT EXISTS (SELECT 1 FROM record_controls c WHERE c.kind='khatian' AND c.record_id=k.khatian_id AND c.deleted=1)")
    sql = '''SELECT k.*,l.division,l.district,l.upazila,l.mouza,l.jl_no
             FROM khatians k JOIN lands l ON l.land_id=k.land_id
             WHERE '''+' AND '.join(where)+''' ORDER BY k.year,k.khatian_id LIMIT 200'''
    with conn() as db:
        rows = db.execute(sql,args).fetchall()
        records = [full_khatian_details(db,khatian_dict(r)) for r in rows]
        for rec in records:
            rec['warning'] = controls(db,'khatian',rec['khatian_id'])['warning']
        for rec in public_custom(db):
            if (rec['khatian_no']==q and location_key(rec['district'])==location_key(district)
                    and location_key(rec['upazila'])==location_key(upazila)
                    and (not mouza or location_key(rec['mouza'])==location_key(mouza))
                    and (not survey or rec['survey']==survey)):
                records.insert(0,rec)
    return jsonify({'query':q,'district':district,'upazila':upazila,'mouza':mouza,
                    'survey':survey,'total':len(records),'records':records})


@app.get('/api/khatian-image/<khatian_id>')
def khatian_image(khatian_id):
    if not re.fullmatch(r'(?:L\d{5}-v\d+|U[a-f0-9]{32})',khatian_id):abort(404)
    with conn() as db:
        if controls(db,'khatian',khatian_id)['deleted']:abort(404)
        if khatian_id.startswith('U'):
            upload=db.execute("SELECT filename FROM uploaded_khatians WHERE id=? AND status='published'",(khatian_id,)).fetchone()
            if not upload:abort(404)
            return send_file(INSTANCE/'uploads'/upload['filename'],conditional=True,max_age=0)
        row=db.execute('SELECT * FROM khatians WHERE khatian_id=?',(khatian_id,)).fetchone()
    if row is None:abort(404)
    file=image_path(dict(row))
    if not file:abort(404)
    return send_file(file,conditional=True,max_age=0)

@app.get('/api/khatian/<khatian_id>/ownership-timeline')
def ownership_timeline(khatian_id):
    """Evidence sequence for one supplied sample land record, never an ownership decision."""
    if not re.fullmatch(r'L\d{5}-v\d+', khatian_id):
        return jsonify(error='This history is available for linked sample khatians only.'), 404
    with conn() as db:
        selected = db.execute('SELECT land_id FROM khatians WHERE khatian_id=?', (khatian_id,)).fetchone()
        if not selected or controls(db, 'khatian', khatian_id)['deleted']:
            return jsonify(error='Khatian record not found.'), 404
        land = db.execute('SELECT division,district,upazila,mouza,jl_no FROM lands WHERE land_id=?', (selected['land_id'],)).fetchone()
        rows = db.execute('''SELECT k.*,l.division,l.district,l.upazila,l.mouza,l.jl_no FROM khatians k
                             JOIN lands l ON l.land_id=k.land_id WHERE k.land_id=?
                             ORDER BY CAST(substr(k.khatian_id,instr(k.khatian_id,'-v')+2) AS INTEGER)''', (selected['land_id'],)).fetchall()
        records = []
        for row in rows:
            if controls(db, 'khatian', row['khatian_id'])['deleted']: continue
            record = full_khatian_details(db, khatian_dict(row, include_image=False))
            records.append({key: record[key] for key in ('khatian_id','khatian_no','survey','year','owners','dag_rows')})
        transitions = []
        for row in db.execute('SELECT from_khatian_id,to_khatian_id,from_survey,to_survey,transition,detail_json FROM title_line WHERE land_id=? ORDER BY from_khatian_id,to_khatian_id', (selected['land_id'],)):
            try: details = json.loads(row['detail_json'])
            except (ValueError, TypeError): details = []
            transitions.append({'from_khatian_id':row['from_khatian_id'],'to_khatian_id':row['to_khatian_id'],
                                'from_survey':row['from_survey'],'to_survey':row['to_survey'],
                                'transition':row['transition'],'details':details if isinstance(details,list) else []})
        deeds = []
        for row in db.execute('SELECT deed_id,record_json,created_at FROM deeds ORDER BY created_at'):
            record = json.loads(row['record_json'])
            if (normalize_no(record.get('khatian_no')) == records[0]['khatian_no'] and
                    all(location_key(record.get(key)) == location_key(land[key]) for key in ('district','upazila','mouza')) and
                    not controls(db, 'deed', row['deed_id'])['deleted']):
                deeds.append({'deed_id':row['deed_id'],'owner_name':record.get('owner_name',''),'dag_no':record.get('dag_no',''),
                              'land_area_decimal':record.get('land_area_decimal',''),'deed_date':record.get('deed_date',''),'created_at':row['created_at']})
    return jsonify(land_id=selected['land_id'],location=dict(land),records=records,transitions=transitions,deeds=deeds,
                   notice='This is a sequence of supplied local sample records. It is not proof of legal ownership, death, inheritance entitlement, possession, or deed authenticity.')


@app.get('/api/dashboard')
def dashboard():
    with conn() as db:
        total=db.execute("SELECT COUNT(*) n FROM khatians WHERE NOT EXISTS (SELECT 1 FROM record_controls c WHERE c.kind='khatian' AND c.record_id=khatians.khatian_id AND c.deleted=1)").fetchone()['n']+len(public_custom(db))
        deeds=db.execute("SELECT deed_id,record_json,created_at FROM deeds WHERE NOT EXISTS (SELECT 1 FROM record_controls c WHERE c.kind='deed' AND c.record_id=deeds.deed_id AND c.deleted=1) ORDER BY created_at DESC,deed_id DESC").fetchall()
        warning_map={r['record_id']:r['warning'] for r in db.execute("SELECT record_id,warning FROM record_controls WHERE kind='deed'")}
        events=db.execute('SELECT COUNT(*) n FROM audit').fetchone()['n']
    rows=[{'deed_id':r['deed_id'],'created_at':r['created_at'],'warning':warning_map.get(r['deed_id'],''),**json.loads(r['record_json'])} for r in deeds]
    return jsonify({'khatian_total':total,'deed_total':len(rows),'audit_events':events,'conflicts':conflicts(),'deeds':rows[:30],'audit_valid':audit_check()})


@app.get('/api/insights')
def insights():
    """Aggregate public records only; never include private complaints or drafts."""
    from collections import Counter
    from dolil import catalogue
    surveys, districts = Counter(), Counter()
    with conn() as db:
        rows=db.execute("""SELECT k.survey,l.district FROM khatians k
            JOIN lands l ON l.land_id=k.land_id WHERE NOT EXISTS
            (SELECT 1 FROM record_controls c WHERE c.kind='khatian'
             AND c.record_id=k.khatian_id AND c.deleted=1)""").fetchall()
        for row in list(rows)+public_custom(db):
            surveys[row['survey'] or 'Other']+=1
            districts[location_key(row['district']) or 'Other']+=1
        signed=db.execute("""SELECT COUNT(*) FROM deeds WHERE NOT EXISTS
            (SELECT 1 FROM record_controls c WHERE c.kind='deed'
             AND c.record_id=deeds.deed_id AND c.deleted=1)""").fetchone()[0]
        hidden={r['record_id'] for r in db.execute("SELECT record_id FROM record_controls WHERE kind='local_deed' AND deleted=1")}
    return jsonify(khatian_total=sum(surveys.values()),signed_deeds=signed,
                   local_deed_images=sum(len(files)==1 and key not in hidden for key,files in catalogue().items()),
                   district_total=len(districts),generated_at=now(),
                   surveys=[{'label':key,'count':value} for key,value in sorted(surveys.items())],
                   districts=[{'label':key,'count':value} for key,value in sorted(districts.items(),key=lambda item:(-item[1],item[0]))])

@app.get('/api/deeds/<deed_id>')
def deed_details(deed_id):
    item=find_deed(deed_id)
    if not item:return jsonify({'error':'Deed not found in demo registry.'}),404
    return jsonify({**item,'signature_valid':signature_ok(item['hash'],item['signature']),'record_matches_hash':digest(item['record'])==item['hash']})

@app.post('/api/deeds')
def new_deed():
    denied=authorize_write()
    if denied:return denied
    obj=request.get_json(silent=True) or {}
    if not isinstance(obj,dict):return jsonify({'error':'Invalid record.'}),400
    required=[x for x in DATA_FIELDS if x!='deed_id']
    if any(not str(obj.get(x,'')).strip() for x in required):return jsonify({'error':'Fill all required fields.'}),400
    rec={key:re.sub(r'[\r\n\t]',' ',str(obj.get(key,''))).strip() for key in required}
    if any(len(v)>75 for v in rec.values()):return jsonify({'error':'Each field must be 75 characters or less.'}),400
    try:
        amount=float(rec['land_area_decimal'])
        if not 0<amount<10**9:raise ValueError()
        rec['land_area_decimal']=f'{amount:.2f}'
    except ValueError:return jsonify({'error':'Use valid positive land area.'}),400
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',rec['deed_date']):return jsonify({'error':'Date must be YYYY-MM-DD.'}),400
    try:datetime.strptime(rec['deed_date'],'%Y-%m-%d')
    except ValueError:return jsonify({'error':'Use a valid calendar date.'}),400
    import uuid
    rec['deed_id']='ST-ADMIN-'+uuid.uuid4().hex[:16].upper()
    saved=insert_deed(rec,'Administrator')
    return jsonify(saved),201


def base_qr(deed_id):
    base=os.getenv('PUBLIC_BASE_URL','').strip().rstrip('/') or request.host_url.rstrip('/')
    return f'{base}/verify/{quote(deed_id)}'


def deed_pdf_bytes(deed: dict,change_owner=False) -> io.BytesIO:
    rec=dict(deed['record'])
    if change_owner:
        rec['owner_name']='Demo Owner 009' if rec['owner_name']!='Demo Owner 009' else 'Demo Owner 777'
    output=io.BytesIO()
    pdf=canvas.Canvas(output,pagesize=A4)
    w,h=A4
    pdf.setFillColor(colors.HexColor('#075942'));pdf.rect(0,h-110,w,110,stroke=0,fill=1)
    pdf.setFillColor(colors.white);pdf.setFont('Helvetica-Bold',22);pdf.drawString(45,h-49,'SUTRO / DIGITAL DEED')
    pdf.setFont('Helvetica',10);pdf.drawString(45,h-69,'Synthetic sample only - NOT a government-issued legal deed')
    pdf.setFillColor(colors.HexColor('#173d31'));pdf.setFont('Helvetica-Bold',13);pdf.drawString(46,h-148,'SIGNED RECORD INFORMATION')
    y=h-182
    for key,label in zip(DATA_FIELDS,PDF_LABELS):
        value=rec[key]
        # The fixed text template is the basis for field-by-field upload extraction.
        # Keep English/numeric sample data for this prototype's PDF parsing.
        pdf.setFillColor(colors.HexColor('#687e70'));pdf.setFont('Helvetica',10);pdf.drawString(46,y,label+':')
        pdf.setFillColor(colors.HexColor('#173d31'))
        # Keep the logical Unicode text extractable for field-level verification.
        runs=[(part,'SutroBangla' if re.search(r'[\u0980-\u09ff]',part) else 'Helvetica-Bold')
              for part in re.findall(r'[\u0980-\u09ff]+|[^\u0980-\u09ff]+',value)]
        width=sum(pdfmetrics.stringWidth(part,font,10) for part,font in runs)
        size=min(10,3500/max(width,1))
        x=184
        for part,font in runs:
            pdf.setFont(font,size);pdf.drawString(x,y,part)
            x+=pdfmetrics.stringWidth(part,font,size)
        y-=30
    pdf.setFillColor(colors.HexColor('#edf7f0'));pdf.roundRect(44,y-87,w-88,106,10,fill=1,stroke=0)
    pdf.setFillColor(colors.HexColor('#075942'));pdf.setFont('Helvetica-Bold',10);pdf.drawString(56,y-6,'SHA-256:')
    pdf.setFont('Courier',8);pdf.drawString(113,y-6,deed['hash'])
    pdf.setFont('Helvetica-Bold',10);pdf.drawString(56,y-31,'Ed25519 Signature:')
    pdf.setFont('Courier',5.3);pdf.drawString(154,y-31,deed['signature'])
    q=qrcode.make(base_qr(rec['deed_id'])).convert('RGB')
    img=io.BytesIO();q.save(img,format='PNG');img.seek(0)
    pdf.drawImage(ImageReader(img),w-158,85,100,100,mask='auto')
    pdf.setFont('Helvetica-Bold',9);pdf.setFillColor(colors.HexColor('#075942'));pdf.drawString(w-160,74,'SCAN TO OPEN RECORD')
    pdf.setFont('Helvetica',9);pdf.setFillColor(colors.HexColor('#60776a'))
    pdf.drawString(45,75,'Record integrity verification is not a government ownership certificate.')
    pdf.drawString(45,58,'Search and scan use the Sutro demonstration database only.')
    pdf.save();output.seek(0);return output

@app.get('/api/deeds/<deed_id>/pdf')
def download_deed(deed_id):
    d=find_deed(deed_id)
    if not d:abort(404)
    audit('pdf_exported',deed_id)
    return send_file(deed_pdf_bytes(d),mimetype='application/pdf',download_name=deed_id+'.pdf',as_attachment=True)

@app.get('/api/deeds/<deed_id>/tampered-pdf')
def download_tamper(deed_id):
    d=find_deed(deed_id)
    if not d:abort(404)
    return send_file(deed_pdf_bytes(d,change_owner=True),mimetype='application/pdf',download_name=deed_id+'-tampered.pdf',as_attachment=True)


def extract_pdf(file):
    with pdfplumber.open(file) as pdf:
        text='\n'.join(page.extract_text() or '' for page in pdf.pages)
    result={}
    for key,label in zip(DATA_FIELDS,PDF_LABELS):
        variations=[label]
        if key=='land_area_decimal': variations.append('Land Area (decimal)')
        label_pattern='|'.join(re.escape(item) for item in variations)
        match=re.search(rf'^(?:{label_pattern})\s*:\s*(.*?)\s*$',text,re.M|re.I)
        if match:result[key]=match.group(1).strip()
    hm=re.search(r'^SHA-256:\s*([a-f\d]{64})\s*$',text,re.M|re.I)
    sm=re.search(r'^Ed25519 Signature:\s*([a-f\d]{128})\s*$',text,re.M|re.I)
    result['_hash']=hm.group(1).lower() if hm else ''
    result['_signature']=sm.group(1).lower() if sm else ''
    return result

@app.post('/api/verify')
def verify():
    file=request.files.get('file')
    if not file or not (file.filename or '').lower().endswith('.pdf'):
        return jsonify({'error':'Upload a Sutro PDF.'}),400
    try:found=extract_pdf(file.stream)
    except Exception:return jsonify({'error':'PDF could not be read.'}),400
    if any(not found.get(k) for k in DATA_FIELDS) or not found['_hash'] or not found['_signature']:
        return jsonify({'error':'The uploaded PDF is not a complete Sutro-generated signed deed.'}),400
    original=find_deed(found['deed_id'])
    mismatches=[]
    if original:
        for k,label in zip(DATA_FIELDS,PDF_LABELS):
            if found[k]!=original['record'][k]:mismatches.append({'field':k,'label':label,'original':original['record'][k],'uploaded':found[k]})
    current_hash=digest(found)
    hash_ok=current_hash==found['_hash']
    sig_ok=signature_ok(current_hash,found['_signature'])
    registry_ok=bool(original and not mismatches and original['hash']==current_hash and original['signature']==found['_signature'])
    status='VERIFIED' if (hash_ok and sig_ok and registry_ok) else ('UNREGISTERED' if not original else 'TAMPERED')
    audit('pdf_verified',found['deed_id'],{'status':status,'mismatches':len(mismatches)})
    return jsonify({'status':status,'deed_id':found['deed_id'],'hash_valid':hash_ok,'signature_valid':sig_ok,'registry_match':registry_ok,'mismatches':mismatches,'warning':original.get('warning','') if original else ''})

@app.get('/api/audit')
def audit_events():
    with conn() as db:
        rows=db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 15').fetchall()
    return jsonify({'valid':audit_check(),'events':[{'stamp':r['stamp'],'deed_id':r['deed_id'],'event':r['event'],'details':json.loads(r['details']),'hash':r['event_hash']} for r in rows]})

@app.get('/api/public-key')
def pubkey():return jsonify({'algorithm':'Ed25519','public_key':PUBLIC_KEY_PEM})

@app.errorhandler(413)
def large(_):return jsonify({'error':'File must be smaller than 15 MB.'}),413

initialize()
register_admin(app,sys.modules[__name__])
register_complaints(app,sys.modules[__name__])
register_dolil(app,sys.modules[__name__])
register_evidence(app,sys.modules[__name__])

if __name__=='__main__':
    app.run(host=os.getenv('HOST','127.0.0.1'),port=int(os.getenv('PORT','5000')),debug=False)
