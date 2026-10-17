"""Admin-only, explainable comparison of a signed deed and a khatian record."""
import json
import re
import unicodedata
import uuid
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request

bp = Blueprint('evidence_review', __name__)
service = None


def _text(value):
    value = unicodedata.normalize('NFC', str(value or '')).casefold()
    return re.sub(r'[^\w\u0980-\u09ff]+', '', value)


def _number(value):
    try:
        return Decimal(service.normalize_no(value))
    except (InvalidOperation, ValueError):
        return None


def _row(label, left, right, comparable=True):
    state = 'unavailable' if not left or not right else ('review' if not comparable else ('match' if _text(left) == _text(right) else 'different'))
    return {'field': label, 'deed': str(left or ''), 'khatian': str(right or ''), 'state': state}


def _get_khatian(db, record_id):
    uploaded = db.execute('SELECT * FROM uploaded_khatians WHERE id=?', (record_id,)).fetchone()
    if uploaded:
        if service.controls(db, 'khatian', record_id)['deleted']: return None
        return json.loads(uploaded['record_json']), [], 'admin upload'
    row = db.execute('''SELECT k.*,l.division,l.district,l.upazila,l.mouza,l.jl_no
                        FROM khatians k JOIN lands l ON l.land_id=k.land_id WHERE k.khatian_id=?''', (record_id,)).fetchone()
    if not row or service.controls(db, 'khatian', record_id)['deleted']: return None
    record = service.full_khatian_details(db, dict(row))
    return record, record.get('history', []), 'sample dataset'


def _comparison(deed, khatian):
    rows = [_row('Khatian number', deed.get('khatian_no'), khatian.get('khatian_no')),
            _row('District', deed.get('district'), khatian.get('district')),
            _row('Upazila / thana', deed.get('upazila'), khatian.get('upazila')),
            _row('Mouza', deed.get('mouza'), khatian.get('mouza'))]
    dag = service.normalize_no(deed.get('dag_no'))
    dag_rows = khatian.get('dag_rows') or []
    matching_dag = next((item for item in dag_rows if service.normalize_no(item.get('dag_no')) == dag), None)
    rows.append(_row('Dag number', deed.get('dag_no'), matching_dag.get('dag_no') if matching_dag else '', bool(dag_rows)))
    deed_area, khatian_area = _number(deed.get('land_area_decimal')), _number((matching_dag or {}).get('area_dec'))
    area_state = 'unavailable' if deed_area is None or khatian_area is None else ('match' if deed_area == khatian_area else ('review' if deed_area <= khatian_area else 'different'))
    rows.append({'field': 'Land area (decimal)', 'deed': str(deed.get('land_area_decimal') or ''), 'khatian': str((matching_dag or {}).get('area_dec') or ''), 'state': area_state})
    owners, owner = [str(x.get('name_bn') or '') for x in khatian.get('owners') or []], str(deed.get('owner_name') or '')
    owner_state = 'unavailable' if not owner or not owners else ('match' if any(_text(owner) == _text(candidate) for candidate in owners) else 'review')
    rows.append({'field': 'Named owner', 'deed': owner, 'khatian': ', '.join(owners[:6]), 'state': owner_state})
    return rows, ('needs_review' if any(x['state'] in {'different', 'review'} for x in rows) else 'consistent')


def _auth():
    if request.method == 'GET':
        return None if service.authenticated() else (jsonify(error='Admin login required. Open /admin.'), 401)
    return service.authorize_write()


@bp.get('/api/admin/evidence/khatian-options')
def khatian_options():
    if response := _auth(): return response
    query = request.args.get('q', '').strip()
    if len(query) < 2 or len(query) > 90: return jsonify(records=[])
    like, result = '%' + query + '%', []
    with service.conn() as db:
        rows = db.execute('''SELECT k.khatian_id,k.khatian_no,k.survey,l.district,l.upazila,l.mouza
                             FROM khatians k JOIN lands l ON l.land_id=k.land_id
                             WHERE k.khatian_id LIKE ? OR k.khatian_no LIKE ? OR l.mouza LIKE ? ORDER BY k.khatian_id LIMIT 30''', (like, like, like)).fetchall()
        for row in rows:
            item = dict(row)
            if not service.controls(db, 'khatian', item['khatian_id'])['deleted']:
                item['label'] = f"{item['khatian_id']} · {item['khatian_no']} {item['survey']} · {item['mouza']}"; result.append(item)
        for row in db.execute("SELECT id,record_json FROM uploaded_khatians WHERE id LIKE ? OR record_json LIKE ? ORDER BY created_at DESC LIMIT 30", (like, like)):
            if service.controls(db, 'khatian', row['id'])['deleted']: continue
            record = json.loads(row['record_json'])
            result.append({'khatian_id': row['id'], 'label': f"{row['id']} · {record.get('khatian_no','')} {record.get('survey','')} · {record.get('mouza','')}"})
    return jsonify(records=result[:30])


@bp.get('/api/admin/evidence/deed-options')
def deed_options():
    if response := _auth(): return response
    query = request.args.get('q', '').strip()
    if len(query) < 1 or len(query) > 90: return jsonify(records=[])
    like, result = '%' + query + '%', []
    with service.conn() as db:
        for row in db.execute('SELECT deed_id,record_json FROM deeds WHERE deed_id LIKE ? OR record_json LIKE ? ORDER BY created_at DESC LIMIT 30', (like, like)):
            if service.controls(db, 'deed', row['deed_id'])['deleted']: continue
            record = json.loads(row['record_json'])
            result.append({'deed_id': row['deed_id'], 'label': f"{row['deed_id']} · {record.get('owner_name','')} · khatian {record.get('khatian_no','')}"})
    return jsonify(records=result)


@bp.post('/api/admin/evidence/reviews')
def create_review():
    if response := _auth(): return response
    data = request.get_json(silent=True) or {}; khatian_id, deed_id = str(data.get('khatian_id', '')).strip(), str(data.get('deed_id', '')).strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', khatian_id) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', deed_id):
        return jsonify(error='Choose a khatian and a signed deed from the suggestions.'), 400
    with service.conn() as db:
        found, deed_row = _get_khatian(db, khatian_id), db.execute('SELECT record_json FROM deeds WHERE deed_id=?', (deed_id,)).fetchone()
        if not found or not deed_row or service.controls(db, 'deed', deed_id)['deleted']: return jsonify(error='One of the selected records is unavailable.'), 404
        khatian, history, source = found; deed = json.loads(deed_row['record_json']); fields, outcome = _comparison(deed, khatian)
        review_id = 'EV-' + uuid.uuid4().hex[:12].upper()
        snapshot = {'deed': deed, 'khatian': khatian, 'fields': fields, 'history': history, 'source': source, 'notice': 'This compares supplied record fields. It is not a finding of legal ownership, authenticity, possession, or fraud.'}
        db.execute('INSERT INTO evidence_reviews(id,khatian_id,deed_id,outcome,snapshot_json,created_at) VALUES (?,?,?,?,?,?)', (review_id, khatian_id, deed_id, outcome, json.dumps(snapshot, ensure_ascii=False), service.now()))
    service.audit('evidence_review_created', review_id, {'khatian_id': khatian_id, 'deed_id': deed_id, 'outcome': outcome})
    return jsonify(id=review_id, outcome=outcome, **snapshot), 201


@bp.get('/api/admin/evidence/reviews')
def list_reviews():
    if response := _auth(): return response
    with service.conn() as db: rows = [dict(row) for row in db.execute('SELECT id,khatian_id,deed_id,outcome,created_at FROM evidence_reviews ORDER BY created_at DESC LIMIT 50')]
    return jsonify(reviews=rows)


def register_evidence(app, backend):
    global service
    service = backend
    app.register_blueprint(bp)
