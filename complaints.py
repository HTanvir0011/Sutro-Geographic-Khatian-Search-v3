"""Private land complaints: public submission, administrator-only management."""
import hashlib
import hmac
import io
import json
import re
import secrets
import time
import uuid

import pdfplumber
from PIL import Image, UnidentifiedImageError
from flask import Blueprint, abort, jsonify, render_template, request, send_file, session
from admin_panel import authenticated, authorize_write

bp = Blueprint('complaints', __name__)
service = None
CATEGORIES = {
    'encroachment': 'ভূমি দখল', 'boundary': 'সীমানা বিরোধ',
    'forged_documents': 'জাল দলিল / নথি', 'ownership': 'মালিকানা বিরোধ',
    'mutation': 'নামজারি / রেকর্ড সমস্যা', 'harassment': 'হয়রানি / বাধা প্রদান',
    'other': 'অন্যান্য ভূমি-সংক্রান্ত অভিযোগ',
}
STATUSES = {'new', 'read', 'reviewing', 'resolved', 'closed'}
STATUS_LABELS = {'new': 'অভিযোগ জমা হয়েছে', 'read': 'অ্যাডমিন অভিযোগ দেখেছেন',
                 'reviewing': 'অভিযোগ পর্যালোচনায় আছে', 'resolved': 'সমাধান হয়েছে', 'closed': 'অভিযোগ বন্ধ করা হয়েছে'}


@bp.before_request
def protect():
    if request.path.startswith('/api/admin/'):
        if not authenticated():
            return jsonify(error='Admin login required.'), 401
        if request.method != 'GET':
            return authorize_write()


@bp.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    return response


@bp.get('/complaints')
def page():
    return render_template('complaints.html', categories=CATEGORIES)


@bp.get('/api/complaints/session')
def form_session():
    session.setdefault('complaint_csrf', secrets.token_urlsafe(32))
    return jsonify(csrf=session['complaint_csrf'])


@bp.post('/api/complaints/track')
def track():
    token = session.get('complaint_csrf', '')
    if not token or not hmac.compare_digest(token, request.headers.get('X-CSRF-Token', '')):
        return jsonify(error='সেশন নতুন করতে পেজ reload করুন।'), 403
    obj = request.get_json(silent=True)
    receipt = obj.get('receipt', '') if isinstance(obj, dict) else ''
    if not isinstance(receipt, str):
        receipt = ''
    receipt = receipt.strip().upper()
    if not re.fullmatch(r'CMP-[0-9A-F]{32}', receipt):
        return jsonify(error='এই নম্বরে কোনো অভিযোগ পাওয়া যায়নি। সম্পূর্ণ অভিযোগ নম্বর দিন।'), 404
    with service.conn() as db:
        row = db.execute('SELECT id,status,created_at,updated_at FROM complaints WHERE id=?', (receipt,)).fetchone()
    if not row:
        return jsonify(error='এই নম্বরে কোনো অভিযোগ পাওয়া যায়নি। সম্পূর্ণ অভিযোগ নম্বর দিন।'), 404
    return jsonify(receipt=row['id'], status=row['status'], status_label=STATUS_LABELS[row['status']],
                   submitted_at=row['created_at'], updated_at=row['updated_at'])


def validate_attachment(file):
    raw = file.read(5 * 1024 * 1024 + 1)
    if not raw or len(raw) > 5 * 1024 * 1024:
        raise ValueError('প্রতিটি নথি ৫ MB এর মধ্যে হতে হবে।')
    if raw.startswith(b'%PDF-'):
        try:
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                if not 1 <= len(pdf.pages) <= 200:
                    raise ValueError()
        except Exception:
            raise ValueError('PDF নথিটি পড়া যায়নি। সঠিক PDF দিন।') from None
        suffix, mime = '.pdf', 'application/pdf'
    else:
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in {'JPEG', 'PNG', 'WEBP'} or image.width * image.height > 40_000_000:
                    raise ValueError()
                image.verify()
                suffix, mime = {'JPEG': ('.jpg', 'image/jpeg'), 'PNG': ('.png', 'image/png'),
                                'WEBP': ('.webp', 'image/webp')}[image.format]
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise ValueError('শুধু সঠিক PDF, JPG, PNG বা WEBP নথি দিন।') from None
    original = re.sub(r'[\x00-\x1f\x7f]', '', (file.filename or 'document').replace('\\', '/').split('/')[-1])[:150]
    return raw, suffix, mime, original or ('document' + suffix)


@bp.post('/api/complaints')
def submit():
    token = session.get('complaint_csrf', '')
    if not token or not hmac.compare_digest(token, request.headers.get('X-CSRF-Token', '')):
        return jsonify(error='ফর্মের সময় শেষ হয়েছে। পেজ reload করে আবার চেষ্টা করুন।'), 403
    fields = {}
    limits = {'name': (2, 100), 'phone': (7, 30), 'subject': (5, 200),
              'description': (20, 10000), 'district': (1, 90), 'upazila': (1, 90),
              'mouza': (1, 90), 'khatian_no': (0, 75), 'dag_no': (0, 75)}
    for name, (minimum, maximum) in limits.items():
        value = request.form.get(name, '').strip()
        if not minimum <= len(value) <= maximum:
            return jsonify(error='প্রয়োজনীয় তথ্য ও অভিযোগের বিস্তারিত সঠিকভাবে পূরণ করুন।'), 400
        fields[name] = value
    fields['phone'] = service.normalize_no(fields['phone'])
    if not re.fullmatch(r'\+?[0-9][0-9 ()-]{5,25}[0-9]', fields['phone']):
        return jsonify(error='সঠিক যোগাযোগের ফোন নম্বর লিখুন।'), 400
    category = request.form.get('category', '')
    if category not in CATEGORIES:
        return jsonify(error='অভিযোগের ধরন নির্বাচন করুন।'), 400
    if request.form.get('consent') != 'yes':
        return jsonify(error='অ্যাডমিনকে অভিযোগ ও নথি দেখার সম্মতি দিন।'), 400
    files = [file for file in request.files.getlist('documents') if file.filename]
    if len(files) > 5:
        return jsonify(error='সর্বোচ্চ ৫টি নথি দিন।'), 400
    attachments = []
    try:
        for file in files:
            attachments.append(validate_attachment(file))
        if sum(len(item[0]) for item in attachments) > 10 * 1024 * 1024:
            raise ValueError('সব নথি মিলে সর্বোচ্চ ১০ MB হতে পারবে।')
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    ip_hash = hmac.new(service.app.secret_key, (request.remote_addr or '').encode(), hashlib.sha256).hexdigest()
    record_id = 'CMP-' + uuid.uuid4().hex.upper()
    directory = service.INSTANCE / 'complaints'
    directory.mkdir(exist_ok=True)
    written = []
    try:
        with service.conn() as db:
            # Serialize the limit check and insert, including simultaneous submissions.
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM complaint_submission_limits WHERE stamp<?', (time.time() - 3600,))
            count = db.execute('SELECT COUNT(*) FROM complaint_submission_limits WHERE ip_hash=?', (ip_hash,)).fetchone()[0]
            if count >= 10:
                return jsonify(error='এক ঘণ্টায় সর্বোচ্চ ১০টি অভিযোগ জমা দেওয়া যাবে। পরে চেষ্টা করুন।'), 429
            db.execute('INSERT INTO complaints(id,category,fields_json,status,admin_note,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
                       (record_id, category, json.dumps(fields, ensure_ascii=False), 'new', '', service.now(), service.now()))
            for raw, suffix, mime, original in attachments:
                attachment_id = uuid.uuid4().hex
                stored = attachment_id + suffix
                path = directory / stored
                path.write_bytes(raw)
                written.append(path)
                db.execute('INSERT INTO complaint_documents VALUES (?,?,?,?,?,?)',
                           (attachment_id, record_id, stored, original, mime, len(raw)))
            db.execute('INSERT INTO complaint_submission_limits VALUES (?,?)', (ip_hash, time.time()))
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    # Public audit endpoints must never reveal complaint IDs, contact details or contents.
    return jsonify(receipt=record_id, message='অভিযোগ জমা হয়েছে। শুধু অ্যাডমিন অভিযোগ ও নথি দেখতে পারবেন।'), 201


@bp.get('/api/admin/complaints/stats')
def stats():
    with service.conn() as db:
        counts = {row['status']: row['n'] for row in db.execute('SELECT status,COUNT(*) n FROM complaints GROUP BY status')}
    return jsonify(total=sum(counts.values()), new=counts.get('new', 0), counts=counts)


@bp.get('/api/admin/complaints')
def list_complaints():
    status = request.args.get('status', 'all')
    query = request.args.get('q', '').strip()[:100]
    try:
        page_no = max(1, int(request.args.get('page', 1)))
    except ValueError:
        return jsonify(error='Invalid page.'), 400
    if status != 'all' and status not in STATUSES:
        return jsonify(error='Invalid status.'), 400
    where, args = [], []
    if status != 'all':
        where.append('status=?'); args.append(status)
    if query:
        where.append('instr(lower(id||fields_json),lower(?))>0'); args.append(query)
    condition = ' WHERE ' + ' AND '.join(where) if where else ''
    with service.conn() as db:
        total = db.execute('SELECT COUNT(*) FROM complaints' + condition, args).fetchone()[0]
        rows = db.execute('SELECT * FROM complaints' + condition + ' ORDER BY created_at DESC,rowid DESC LIMIT 20 OFFSET ?',
                          args + [(page_no - 1) * 20]).fetchall()
        counts = {row['status']: row['n'] for row in db.execute('SELECT status,COUNT(*) n FROM complaints GROUP BY status')}
        documents = {r['complaint_id']: r['n'] for r in db.execute('SELECT complaint_id,COUNT(*) n FROM complaint_documents GROUP BY complaint_id')}
    return jsonify(total=total, page=page_no, counts=counts, complaints=[
        {'id': row['id'], 'category': CATEGORIES[row['category']], 'status': row['status'],
         'created_at': row['created_at'], 'documents': documents.get(row['id'], 0),
         **{k: json.loads(row['fields_json'])[k] for k in ('name', 'subject', 'district', 'upazila', 'mouza')}} for row in rows])


@bp.get('/api/admin/complaints/<record_id>')
def detail(record_id):
    with service.conn() as db:
        row = db.execute('SELECT * FROM complaints WHERE id=?', (record_id,)).fetchone()
        if not row:
            abort(404)
        docs = db.execute('SELECT id,original_name,mime,size FROM complaint_documents WHERE complaint_id=?', (record_id,)).fetchall()
    return jsonify(id=record_id, category=CATEGORIES[row['category']], status=row['status'],
                   created_at=row['created_at'], updated_at=row['updated_at'], admin_note=row['admin_note'],
                   fields=json.loads(row['fields_json']), documents=[{**dict(doc), 'url':
                   '/api/admin/complaints/' + record_id + '/documents/' + doc['id']} for doc in docs],
                   forwarding_available=False)


@bp.patch('/api/admin/complaints/<record_id>')
def update(record_id):
    obj = request.get_json(silent=True)
    if not isinstance(obj, dict) or not obj or set(obj) - {'status', 'admin_note'}:
        return jsonify(error='Invalid update.'), 400
    if 'status' in obj and (not isinstance(obj['status'], str) or obj['status'] not in STATUSES):
        return jsonify(error='Invalid status.'), 400
    if 'admin_note' in obj and (not isinstance(obj['admin_note'], str) or len(obj['admin_note']) > 5000):
        return jsonify(error='অ্যাডমিন নোট ৫০০০ অক্ষরের মধ্যে লিখুন।'), 400
    with service.conn() as db:
        row = db.execute('SELECT * FROM complaints WHERE id=?', (record_id,)).fetchone()
        if not row:
            abort(404)
        db.execute('UPDATE complaints SET status=?,admin_note=?,updated_at=? WHERE id=?',
                   (obj.get('status', row['status']), obj.get('admin_note', row['admin_note']), service.now(), record_id))
    return jsonify(ok=True)


@bp.get('/api/admin/complaints/<record_id>/documents/<document_id>')
def document(record_id, document_id):
    with service.conn() as db:
        row = db.execute('SELECT * FROM complaint_documents WHERE id=? AND complaint_id=?', (document_id, record_id)).fetchone()
    if not row:
        abort(404)
    return send_file(service.INSTANCE / 'complaints' / row['stored_name'], mimetype=row['mime'],
                     download_name=row['original_name'], as_attachment=True, conditional=False)


def register_complaints(app, backend):
    global service
    service = backend
    with service.conn() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS complaints(id TEXT PRIMARY KEY,category TEXT NOT NULL,fields_json TEXT NOT NULL,
                status TEXT NOT NULL,admin_note TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS ix_complaint_status ON complaints(status,created_at);
            CREATE TABLE IF NOT EXISTS complaint_documents(id TEXT PRIMARY KEY,complaint_id TEXT NOT NULL,
                stored_name TEXT NOT NULL,original_name TEXT NOT NULL,mime TEXT NOT NULL,size INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS ix_complaint_docs ON complaint_documents(complaint_id);
            CREATE TABLE IF NOT EXISTS complaint_submission_limits(ip_hash TEXT,stamp REAL);
        ''')
    app.register_blueprint(bp)
