"""Password protected administration and reviewed OCR uploads."""
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import time
import uuid
import base64
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path

import pdfplumber
from flask import Blueprint, abort, jsonify, render_template, request, send_file, session
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfminer.pdfparser import PDFSyntaxError
from pdfplumber.utils.exceptions import PdfminerException
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from werkzeug.security import check_password_hash, generate_password_hash

try:
    import pypdfium2
except ImportError:
    pypdfium2 = None

bp = Blueprint('admin', __name__)
service = None


def controls(db, kind, record_id):
    row = db.execute('SELECT deleted,warning FROM record_controls WHERE kind=? AND record_id=?',
                     (kind, record_id)).fetchone()
    return dict(row) if row else {'deleted': 0, 'warning': ''}


def credential():
    with service.conn() as db:
        row = db.execute('SELECT password_hash FROM admin_users WHERE username=? AND active=1',
                         ('superadmin',)).fetchone()
        if row:
            return row['password_hash']
        row = db.execute('SELECT password_hash FROM admin_account WHERE id=1').fetchone()
    return row['password_hash'] if row else None


def authenticated():
    admin_id = session.get('admin_id')
    version = session.get('admin_version')
    if not admin_id or not version:
        return False
    with service.conn() as db:
        row = db.execute('SELECT password_hash,active FROM admin_users WHERE id=?', (admin_id,)).fetchone()
    return bool(row and row['active'] and version == hashlib.sha256(row['password_hash'].encode()).hexdigest())


def current_admin():
    admin_id = session.get('admin_id')
    if not admin_id:
        return None
    with service.conn() as db:
        row = db.execute('SELECT id,username,role,active FROM admin_users WHERE id=?', (admin_id,)).fetchone()
    return dict(row) if row else None


def superadmin():
    admin = current_admin()
    return bool(admin and admin['role'] == 'superadmin')


def authorize_superadmin():
    if not authenticated():
        return jsonify(error='Admin login required.'), 401
    if not superadmin():
        return jsonify(error='Super admin permission required.'), 403


def authorize_write():
    if not authenticated():
        return jsonify(error='Admin login required. Open /admin.'), 401
    if not hmac.compare_digest(str(session.get('csrf', '')), request.headers.get('X-CSRF-Token', '')):
        return jsonify(error='Session token missing or expired. Reload the admin panel.'), 403


def public_custom(db):
    rows = db.execute("SELECT * FROM uploaded_khatians WHERE status='published' ORDER BY created_at DESC").fetchall()
    result = []
    for row in rows:
        control = controls(db, 'khatian', row['id'])
        if not control['deleted']:
            rec = json.loads(row['record_json'])
            rec.update(khatian_id=row['id'], land_id='Admin upload', image_file=row['filename'],
                       has_image=True, image_url='/api/khatian-image/' + row['id'],
                       warning=control['warning'], source='admin_upload', history=[],
                       n_owners=str(len(rec.get('owners', []))))
            result.append(rec)
    return result


def ocr_image(path, psm=6, preprocess=False):
    executable = (os.getenv('SUTRO_TESSERACT_CMD') or shutil.which('tesseract') or
                  (r'C:\Program Files\Tesseract-OCR\tesseract.exe' if os.name == 'nt' else ''))
    if not executable or not Path(executable).is_file():
        return '', 'OCR engine পাওয়া যায়নি। Tesseract install করুন অথবা তথ্য হাতে পূরণ করুন।'
    tessdata = service.INSTANCE / 'tessdata'
    if not (tessdata / 'ben.traineddata').is_file():
        return '', 'বাংলা OCR model পাওয়া যায়নি। ben.traineddata install করুন।'
    source = Path(path)
    processed = None
    try:
        if preprocess:
            with Image.open(source) as image:
                image = ImageOps.exif_transpose(image).convert('L')
                image = ImageOps.autocontrast(image)
                image = ImageEnhance.Contrast(image).enhance(1.35)
                image = image.filter(ImageFilter.SHARPEN)
                image = image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS)
                processed = service.INSTANCE / 'deed_rewrites' / (uuid.uuid4().hex + '-ocr.png')
                image.save(processed, 'PNG')
            source = processed
        command = [executable, str(source), 'stdout', '-l', 'ben+eng', '--psm', str(psm),
                   '--tessdata-dir', str(tessdata)]
        result = subprocess.run(command,
                                capture_output=True, encoding='utf-8', errors='replace', timeout=60,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if result.returncode:
            return '', 'OCR ব্যর্থ হয়েছে। ben ও eng language data আছে কি না দেখুন; তথ্য হাতে পূরণ করা যাবে।'
        text = result.stdout.strip()[:100000]
        return text, '' if text else 'ছবি থেকে লেখা পাওয়া যায়নি। পরিষ্কার ছবি দিন অথবা তথ্য হাতে পূরণ করুন।'
    except (OSError, subprocess.TimeoutExpired):
        return '', 'OCR সময়ের মধ্যে শেষ হয়নি। তথ্য হাতে পূরণ করা যাবে।'
    finally:
        if processed:
            processed.unlink(missing_ok=True)


def usable_bengali_text(text):
    letters = re.findall(r'[A-Za-z\u0980-\u09FF]', text or '')
    bengali = re.findall(r'[\u0980-\u09FF]', text or '')
    if len(letters) < 20:
        return len(bengali) >= 8
    return len(bengali) >= 12 and len(bengali) / len(letters) >= 0.35


def ai_deed_text(images):
    api_key = os.getenv('SUTRO_AI_API_KEY', '').strip()
    endpoint = os.getenv('SUTRO_AI_ENDPOINT', 'https://api.openai.com/v1/chat/completions').strip()
    model = os.getenv('SUTRO_AI_MODEL', 'gpt-4o').strip()
    if not api_key:
        return '', 'বাংলা vision AI চালু নেই। .env-এ SUTRO_AI_API_KEY সেট করুন।'
    content = [{
        'type': 'text',
        'text': (
            'এই ছবিগুলো একটি বাংলা জমির দলিলের পৃষ্ঠা। ছবির দৃশ্যমান লেখা হুবহু '
            'বাংলা অক্ষরে টাইপ করে দিন। কোনো তথ্য অনুমান, সংশোধন বা বানাবেন না। '
            'পড়তে না পারলে [অস্পষ্ট] লিখুন। পৃষ্ঠা অনুযায়ী ধারাবাহিক plain text দিন; '
            'কোনো ব্যাখ্যা, সারাংশ, legal opinion বা markdown দেবেন না।'
        )
    }]
    for image in images:
        encoded = base64.b64encode(image).decode('ascii')
        content.append({'type': 'image_url', 'image_url': {
            'url': 'data:image/png;base64,' + encoded, 'detail': 'high'
        }})
    payload = json.dumps({
        'model': model,
        'temperature': 0,
        'messages': [{'role': 'user', 'content': content}]
    }).encode('utf-8')
    request = urllib.request.Request(endpoint, data=payload, method='POST',
                                     headers={'Authorization': 'Bearer ' + api_key,
                                              'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.loads(response.read().decode('utf-8'))
        value = result['choices'][0]['message']['content']
        if isinstance(value, list):
            value = ''.join(part.get('text', '') for part in value if isinstance(part, dict))
        value = str(value).strip()[:200000]
        if not usable_bengali_text(value):
            return '', 'Vision AI বাংলা transcription দেয়নি। পৃষ্ঠাগুলো পরিষ্কার কি না যাচাই করুন।'
        return value, ''
    except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError, IndexError, TypeError):
        return '', 'Vision AI transcription ব্যর্থ হয়েছে। পরে আবার চেষ্টা করুন অথবা হাতে সংশোধন করুন।'


def extract_deed_text(raw):
    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            text = '\n\n'.join((page.extract_text() or '').strip() for page in pdf.pages).strip()
            page_count = len(pdf.pages)
    except (OSError, ValueError, PDFPasswordIncorrect, PDFSyntaxError, PdfminerException):
        raise ValueError('PDF ফাইলটি পড়া যায়নি বা password-protected।')
    if usable_bengali_text(text) and not os.getenv('SUTRO_AI_API_KEY', '').strip():
        return text[:200000], '', page_count
    if pypdfium2 is None:
        return '', 'স্ক্যান করা PDF-এর OCR করার জন্য PDF renderer পাওয়া যায়নি।', page_count
    parts = []
    document = pypdfium2.PdfDocument(raw)
    try:
        for index, page in enumerate(document):
            if index >= 20:
                break
            image = page.render(scale=3.5).to_pil()
            temp_path = service.INSTANCE / 'deed_rewrites' / (uuid.uuid4().hex + '.png')
            try:
                image.save(temp_path, 'PNG')
                candidates = []
                for psm in (6, 11):
                    page_text, _ = ocr_image(temp_path, psm=psm, preprocess=True)
                    if page_text:
                        candidates.append(page_text)
                if candidates:
                    parts.append(max(candidates, key=lambda value: (
                        len(re.findall(r'[\u0980-\u09FF]', value)), len(value))))
            finally:
                temp_path.unlink(missing_ok=True)
    finally:
        document.close()
    text = '\n\n'.join(parts).strip()[:200000]
    if text and usable_bengali_text(text):
        return text, '', page_count
    if pypdfium2 is not None:
        images = []
        document = pypdfium2.PdfDocument(raw)
        try:
            max_pages = int(os.getenv('SUTRO_AI_MAX_PAGES', '20') or '20')
            for index, page in enumerate(document):
                if index >= max(1, min(max_pages, 20)):
                    break
                image_buffer = io.BytesIO()
                page.render(scale=2.5).to_pil().convert('RGB').save(image_buffer, 'PNG')
                images.append(image_buffer.getvalue())
        finally:
            document.close()
        ai_text, ai_message = ai_deed_text(images)
        if ai_text:
            return ai_text, 'Vision AI transcription: admin review required.', page_count
        if ai_message and os.getenv('SUTRO_AI_API_KEY'):
            return '', ai_message, page_count
    if text:
        return '', ('PDF-এর লেখা সঠিকভাবে পড়া যায়নি। Tesseract OCR চালু করে '
                    'আবার আপলোড করুন অথবা লেখা হাতে লিখে সংশোধন করুন।'), page_count
    return '', ('স্ক্যান করা PDF-এর বাংলা OCR পাওয়া যায়নি। Tesseract OCR install করে '
                'আবার আপলোড করুন অথবা লেখা হাতে লিখে সংশোধন করুন।'), page_count


def rewritten_deed_pdf(text):
    font_name = 'SutroRewriteBangla'
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font_name, str(service.ROOT / 'static/fonts/NotoSansBengali-Regular.ttf')))
    output = io.BytesIO()
    document = canvas.Canvas(output, pagesize=A4)
    width, height = A4
    left, top, bottom = 48, height - 54, 48
    document.setTitle('Sutro Bengali deed transcription')
    document.setAuthor('Sutro admin workspace')
    document.setFont(font_name, 16)
    document.setFillColorRGB(0.05, 0.35, 0.24)
    document.drawString(left, top, 'দলিলের বাংলা পুনর্লিখিত অনুলিপি')
    document.setFont(font_name, 9)
    document.setFillColorRGB(0.35, 0.45, 0.39)
    document.drawString(left, top - 22, 'এটি OCR ও প্রশাসনিক সম্পাদনার ভিত্তিতে তৈরি পুনর্লিখিত কপি; সরকারি বা আইনগত মূল দলিল নয়।')
    y = top - 58
    document.setStrokeColorRGB(0.75, 0.84, 0.78)
    document.line(left, y + 15, width - left, y + 15)
    document.setFont(font_name, 12)
    document.setFillColorRGB(0.09, 0.24, 0.18)
    for paragraph in text.splitlines():
        words = paragraph.split()
        line = ''
        for word in words or ['']:
            candidate = word if not line else line + ' ' + word
            if line and pdfmetrics.stringWidth(candidate, font_name, 12) > width - 2 * left:
                if y < bottom:
                    document.showPage()
                    document.setFont(font_name, 12)
                    y = height - 54
                document.drawString(left, y, line)
                y -= 20
                line = word
            else:
                line = candidate
        if y < bottom:
            document.showPage()
            document.setFont(font_name, 12)
            y = height - 54
        document.drawString(left, y, line)
        y -= 24
    document.save()
    output.seek(0)
    return output


def extract_fields(text):
    fields = {key: '' for key in ('division', 'district', 'upazila', 'mouza', 'khatian_no',
                                  'survey', 'year', 'sheet_no', 'jl_no', 'total_land_dec')}
    labels = {
        'division': r'(?:বিভাগ|Division)', 'district': r'(?:জেলা|District)',
        'upazila': r'(?:উপজেলা(?:/থানা)?|[থখ]ানা|Upazila|Thana)', 'mouza': r'(?:মৌজা|মৌজা|Mouza)',
        'khatian_no': r'(?:খতিয়ান|খতিয়ান|খতিয়ান নং|খতিয়ান নং|Khatian(?:\s+No)?)',
        'jl_no': r'(?:জে[.,\s]*এল[.,\s]*(?:নং)?|J\.?\s*L\.?(?:\s+No)?)',
        'sheet_no': r'(?:শিট(?:\s*নং)?|Sheet(?:\s+No)?)', 'year': r'(?:সাল|Year)',
        'total_land_dec': r'(?:মোট\s*জমি|Total\s*(?:Land|Area))'}
    # Only labelled values are proposed. Table rows require human review.
    stops = r'(?=\s+(?:বিভাগ|জেলা|উপজেলা(?:/থানা)?|[থখ]ানা|মৌজা|মৌজা|জে[.,\s]*এল|রেঃসাঃ|খতিয়ান|খতিয়ান|Division|District|Upazila|Mouza)(?:\s*(?:নং|নম্বর|No\.?))?\s*[:ঃ-]|$)'
    for key, label in labels.items():
        match = re.search(label + r'\s*(?:নং|নম্বর|No\.?)?\s*[:ঃ-]\s*(.+?)' + stops, text, re.I | re.M)
        if match:
            value = match.group(1).strip()[:90]
            if key in {'khatian_no', 'year', 'sheet_no', 'jl_no', 'total_land_dec'}:
                number = re.search(r'[0-9০-৯]+(?:[.][0-9০-৯]+)?', value)
                value = service.normalize_no(number.group()) if number else ''
            fields[key] = value
    survey = re.search(r'\b(CS|SA|RS|BS|BRS|BDS)\b', text, re.I)
    if survey:
        fields['survey'] = survey.group().upper()
    owners = []
    for line in text.splitlines():
        match = re.match(r'^\s*[0-9০-৯]+[।.)]\s*((?:মোঃ|মোসাঃ|মোছাঃ|Mr\.?|Mrs\.?)\s+[^0-9০-৯|\n]+)', line)
        if match:
            owners.append({'name_bn': match.group(1).strip(), 'father_or_spouse_bn': '', 'share_exact': ''})
    fields.update(owners=owners[:200], dag_rows=[])
    return fields


def clean_record(obj, publish=True):
    if not isinstance(obj, dict):
        raise ValueError('Invalid record.')
    result = {}
    for key in ('division', 'district', 'upazila', 'mouza', 'khatian_no', 'survey', 'year',
                'sheet_no', 'jl_no', 'total_land_dec'):
        value = str(obj.get(key, '')).strip()
        if len(value) > 90:
            raise ValueError('প্রতিটি তথ্য ৯০ অক্ষরের মধ্যে লিখুন।')
        result[key] = value
    result['khatian_no'] = service.normalize_no(result['khatian_no'])
    result['survey'] = result['survey'].upper()
    if publish and not all(result[k] for k in ('district', 'upazila', 'mouza', 'khatian_no', 'survey')):
        raise ValueError('জেলা, উপজেলা, মৌজা, খতিয়ান নম্বর ও জরিপ পূরণ করুন।')
    if result['khatian_no'] and not re.fullmatch(r'[0-9]{1,15}', result['khatian_no']):
        raise ValueError('সঠিক খতিয়ান নম্বর লিখুন।')
    if result['survey'] and result['survey'] not in {'CS', 'SA', 'RS', 'BS', 'BRS', 'BDS'}:
        raise ValueError('সঠিক জরিপ নির্বাচন করুন।')
    for name, keys in [('owners', ('name_bn', 'father_or_spouse_bn', 'share_exact')),
                       ('dag_rows', ('dag_no', 'land_class_bn', 'area_dec'))]:
        values = obj.get(name, [])
        if not isinstance(values, list) or len(values) > 200:
            raise ValueError('সর্বোচ্চ ২০০টি মালিক বা দাগ যোগ করা যাবে।')
        result[name] = []
        for index, row in enumerate(values, 1):
            if not isinstance(row, dict):
                raise ValueError('Invalid owner/dag row.')
            item = {k: str(row.get(k, '')).strip() for k in keys}
            if any(len(v) > 200 for v in item.values()):
                raise ValueError('মালিক বা দাগের তথ্য বেশি বড়।')
            item['owner_idx' if name == 'owners' else 'row_idx'] = str(index)
            result[name].append(item)
    return result


@bp.before_request
def protect():
    if request.path.startswith('/api/admin/'):
        if request.is_json and not isinstance(request.get_json(silent=True), dict):
            return jsonify(error='Invalid JSON object.'), 400
        if request.endpoint not in {'admin.auth_state', 'admin.login', 'admin.setup'} and not authenticated():
            return jsonify(error='Admin login required.'), 401
        if request.method != 'GET' and request.endpoint != 'admin.login':
            expected = str(session.get('csrf', ''))
            if not expected or not hmac.compare_digest(expected, request.headers.get('X-CSRF-Token', '')):
                return jsonify(error='Session token missing or expired. Reload the admin panel.'), 403


@bp.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    return response


@bp.get('/admin')
def page():
    return render_template('admin.html')


@bp.get('/api/admin/session')
def auth_state():
    session.setdefault('csrf', secrets.token_urlsafe(32))
    admin = current_admin()
    return jsonify(authenticated=authenticated(), setup_required=credential() is None,
                   setup_allowed=request.remote_addr in {'127.0.0.1', '::1'}, csrf=session['csrf'],
                   admin=admin)


def start_session(stored):
    with service.conn() as db:
        row = db.execute('SELECT id,username,role FROM admin_users WHERE password_hash=? AND active=1',
                         (stored,)).fetchone()
    session.clear()
    session['admin_id'] = row['id'] if row else 1
    session['admin_version'] = hashlib.sha256(stored.encode()).hexdigest()
    session['csrf'] = secrets.token_urlsafe(32)
    session.permanent = True
    return jsonify(authenticated=True, csrf=session['csrf'])


@bp.post('/api/admin/setup')
def setup():
    if request.remote_addr not in {'127.0.0.1', '::1'}:
        return jsonify(error='প্রথম পাসওয়ার্ড এই কম্পিউটার থেকে সেট করুন।'), 403
    password = (request.get_json(silent=True) or {}).get('password', '')
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        return jsonify(error='১২ থেকে ১২৮ অক্ষরের পাসওয়ার্ড দিন।'), 400
    stored = generate_password_hash(password)
    try:
        with service.conn() as db:
            db.execute('INSERT INTO admin_account(id,password_hash) VALUES (1,?)', (stored,))
            db.execute('INSERT INTO admin_users(id,username,password_hash,role,active,created_at) '
                       'VALUES (1,?,?,?,?,?)',
                       ('superadmin', stored, 'superadmin', 1, service.now()))
    except sqlite3.IntegrityError:
        return jsonify(error='পাসওয়ার্ড আগে সেট করা হয়েছে। Login করুন।'), 409
    service.audit('admin_password_created')
    return start_session(stored)


@bp.post('/api/admin/login')
def login():
    ip = request.remote_addr or 'unknown'
    cutoff = time.time() - 900
    with service.conn() as db:
        db.execute('DELETE FROM admin_login_failures WHERE stamp<?', (cutoff,))
        failures = db.execute('SELECT COUNT(*) FROM admin_login_failures WHERE ip=?', (ip,)).fetchone()[0]
    if failures >= 5:
        return jsonify(error='অনেকবার ভুল পাসওয়ার্ড দেওয়া হয়েছে। ১৫ মিনিট পরে চেষ্টা করুন।'), 429
    obj = request.get_json(silent=True) or {}
    username = obj.get('username', 'superadmin')
    password = obj.get('password', '')
    if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{3,40}', username):
        username = ''
    with service.conn() as db:
        row = db.execute('SELECT password_hash FROM admin_users WHERE username=? AND active=1', (username,)).fetchone()
    stored = row['password_hash'] if row else None
    if not stored and username == 'superadmin':
        stored = credential()
    if not isinstance(password, str) or len(password) > 128 or not stored or not check_password_hash(stored, password):
        with service.conn() as db:
            db.execute('INSERT INTO admin_login_failures(ip,stamp) VALUES (?,?)', (ip, time.time()))
        return jsonify(error='পাসওয়ার্ড সঠিক নয়।'), 401
    with service.conn() as db:
        db.execute('DELETE FROM admin_login_failures WHERE ip=?', (ip,))
    service.audit('admin_logged_in')
    return start_session(stored)


@bp.post('/api/admin/logout')
def logout():
    session.clear()
    return jsonify(ok=True)


@bp.post('/api/admin/password')
def change_password():
    obj = request.get_json(silent=True) or {}
    old, new = obj.get('old_password', ''), obj.get('password', '')
    if not isinstance(old, str) or not check_password_hash(credential(), old):
        return jsonify(error='বর্তমান পাসওয়ার্ড সঠিক নয়।'), 400
    if not isinstance(new, str) or not 12 <= len(new) <= 128:
        return jsonify(error='নতুন পাসওয়ার্ড ১২–১২৮ অক্ষরের হতে হবে।'), 400
    stored = generate_password_hash(new)
    with service.conn() as db:
        db.execute('UPDATE admin_account SET password_hash=? WHERE id=1', (stored,))
        db.execute('UPDATE admin_users SET password_hash=? WHERE id=?', (stored, session.get('admin_id', 1)))
    service.audit('admin_password_changed')
    return start_session(stored)


@bp.get('/api/admin/users')
def users():
    denied = authorize_superadmin()
    if denied:
        return denied
    with service.conn() as db:
        rows = db.execute('SELECT id,username,role,active,created_at FROM admin_users ORDER BY id').fetchall()
    return jsonify(users=[dict(row) for row in rows])


@bp.post('/api/admin/users')
def create_user():
    denied = authorize_superadmin()
    if denied:
        return denied
    obj = request.get_json(silent=True) or {}
    username = obj.get('username', '')
    password = obj.get('password', '')
    if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{3,40}', username):
        return jsonify(error='Username must be 3–40 letters, numbers, dots, underscores or hyphens.'), 400
    if username == 'superadmin':
        return jsonify(error='This username is reserved.'), 400
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        return jsonify(error='Password must be 12–128 characters.'), 400
    try:
        with service.conn() as db:
            db.execute('INSERT INTO admin_users(username,password_hash,role,active,created_at) VALUES (?,?,?,?,?)',
                       (username, generate_password_hash(password), 'admin', 1, service.now()))
    except sqlite3.IntegrityError:
        return jsonify(error='That username is already registered.'), 409
    service.audit('admin_user_created', username)
    return jsonify(ok=True), 201


@bp.patch('/api/admin/users/<int:user_id>')
def update_user(user_id):
    denied = authorize_superadmin()
    if denied:
        return denied
    if user_id == session.get('admin_id'):
        return jsonify(error='Your own account cannot be deactivated here.'), 400
    obj = request.get_json(silent=True) or {}
    if set(obj) != {'active'} or not isinstance(obj['active'], bool):
        return jsonify(error='Only active status can be changed.'), 400
    with service.conn() as db:
        updated = db.execute('UPDATE admin_users SET active=? WHERE id=? AND role=?',
                             (int(obj['active']), user_id, 'admin')).rowcount
    if not updated:
        return jsonify(error='Admin account not found.'), 404
    service.audit('admin_user_status_changed', str(user_id), obj)
    return jsonify(ok=True)


@bp.post('/api/admin/khatian-upload')
def upload():
    file = request.files.get('file')
    if not file:
        return jsonify(error='খতিয়ানের JPG, PNG বা WEBP ছবি দিন।'), 400
    raw = file.read(15 * 1024 * 1024 + 1)
    if len(raw) > 15 * 1024 * 1024:
        return jsonify(error='ছবি ১৫ MB এর মধ্যে হতে হবে।'), 400
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in {'JPEG', 'PNG', 'WEBP'} or image.width * image.height > 40_000_000:
                raise ValueError()
            image.load()
            image = ImageOps.exif_transpose(image).convert('RGB')
            record_id = 'U' + uuid.uuid4().hex
            filename = record_id + '.jpg'
            path = service.INSTANCE / 'uploads' / filename
            image.save(path, 'JPEG', quality=95)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return jsonify(error='ছবিটি পড়া যায়নি, অথবা resolution বেশি বড়। JPG/PNG/WEBP দিন।'), 400
    text, message = ocr_image(path)
    rec = extract_fields(text)
    with service.conn() as db:
        db.execute('INSERT INTO uploaded_khatians VALUES (?,?,?,?,?,?,?)',
                   (record_id, filename, json.dumps(rec, ensure_ascii=False), text, 'draft', service.now(), message))
    service.audit('khatian_uploaded', record_id, {'ocr_available': bool(text)})
    return jsonify(id=record_id, record=rec, ocr_text=text, ocr_message=message, status='draft',
                   image_url='/api/admin/khatians/' + record_id + '/image'), 201


@bp.post('/api/admin/deed-rewrites')
def upload_deed_rewrite():
    file = request.files.get('file')
    if not file or not (file.filename or '').lower().endswith('.pdf'):
        return jsonify(error='শুধু PDF দলিল আপলোড করুন।'), 400
    raw = file.read(15 * 1024 * 1024 + 1)
    if len(raw) > 15 * 1024 * 1024:
        return jsonify(error='PDF ১৫ MB এর মধ্যে হতে হবে।'), 400
    rewrite_id = 'R' + uuid.uuid4().hex
    try:
        text, message, page_count = extract_deed_text(raw)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    original_name = rewrite_id + '-original.pdf'
    directory = service.INSTANCE / 'deed_rewrites'
    directory.mkdir(exist_ok=True)
    (directory / original_name).write_bytes(raw)
    with service.conn() as db:
        db.execute('INSERT INTO deed_rewrites '
                   '(id,original_filename,original_path,text,status,page_count,created_at,updated_at) '
                   'VALUES (?,?,?,?,?,?,?,?)',
                   (rewrite_id, file.filename[:255], original_name, text, 'draft', page_count,
                    service.now(), service.now()))
    service.audit('deed_rewrite_uploaded', rewrite_id, {'ocr_available': bool(text), 'pages': page_count})
    return jsonify(id=rewrite_id, filename=file.filename[:255], text=text, message=message,
                   page_count=page_count, status='draft',
                   original_url='/api/admin/deed-rewrites/' + rewrite_id + '/original'), 201


@bp.get('/api/admin/deed-rewrites/<rewrite_id>')
def deed_rewrite(rewrite_id):
    with service.conn() as db:
        row = db.execute('SELECT id,original_filename,text,status,page_count,created_at,updated_at '
                         'FROM deed_rewrites WHERE id=?', (rewrite_id,)).fetchone()
    if not row:
        abort(404)
    result = dict(row)
    result['original_url'] = '/api/admin/deed-rewrites/' + rewrite_id + '/original'
    if result['status'] == 'completed':
        result['rewritten_url'] = '/api/admin/deed-rewrites/' + rewrite_id + '/rewritten'
    return jsonify(result)


@bp.patch('/api/admin/deed-rewrites/<rewrite_id>')
def save_deed_rewrite(rewrite_id):
    obj = request.get_json(silent=True) or {}
    text = obj.get('text')
    if not isinstance(text, str) or not text.strip() or len(text) > 200000:
        return jsonify(error='বাংলা লেখা ১ থেকে ২,০০,০০০ অক্ষরের মধ্যে দিন।'), 400
    rewritten_name = rewrite_id + '-rewritten.pdf'
    rewritten_path = service.INSTANCE / 'deed_rewrites' / rewritten_name
    rewritten_path.write_bytes(rewritten_deed_pdf(text.strip()).read())
    with service.conn() as db:
        row = db.execute('SELECT id FROM deed_rewrites WHERE id=?', (rewrite_id,)).fetchone()
        if not row:
            rewritten_path.unlink(missing_ok=True)
            abort(404)
        db.execute('UPDATE deed_rewrites SET text=?,status=?,rewritten_path=?,updated_at=? WHERE id=?',
                   (text.strip(), 'completed', rewritten_name, service.now(), rewrite_id))
    service.audit('deed_rewrite_generated', rewrite_id, {'characters': len(text.strip())})
    return jsonify(ok=True, id=rewrite_id, status='completed',
                   rewritten_url='/api/admin/deed-rewrites/' + rewrite_id + '/rewritten')


@bp.get('/api/admin/deed-rewrites/<rewrite_id>/original')
def deed_rewrite_original(rewrite_id):
    with service.conn() as db:
        row = db.execute('SELECT original_path FROM deed_rewrites WHERE id=?', (rewrite_id,)).fetchone()
    if not row:
        abort(404)
    path = service.INSTANCE / 'deed_rewrites' / row['original_path']
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype='application/pdf', as_attachment=False,
                     download_name=rewrite_id + '-original.pdf')


@bp.get('/api/admin/deed-rewrites/<rewrite_id>/rewritten')
def deed_rewrite_output(rewrite_id):
    with service.conn() as db:
        row = db.execute('SELECT rewritten_path FROM deed_rewrites WHERE id=? AND status=?',
                         (rewrite_id, 'completed')).fetchone()
    if not row:
        abort(404)
    path = service.INSTANCE / 'deed_rewrites' / row['rewritten_path']
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype='application/pdf', as_attachment=True,
                     download_name=rewrite_id + '-bangla.pdf')


@bp.get('/api/admin/khatians/<record_id>/image')
def preview_image(record_id):
    with service.conn() as db:
        row = db.execute('SELECT filename FROM uploaded_khatians WHERE id=?', (record_id,)).fetchone()
        if not row:
            sample = db.execute('SELECT * FROM khatians WHERE khatian_id=?', (record_id,)).fetchone()
            path = service.image_path(dict(sample)) if sample else None
            if not path:
                abort(404)
            return send_file(path)
    return send_file(service.INSTANCE / 'uploads' / row['filename'])


@bp.patch('/api/admin/khatians/<record_id>')
def save_khatian(record_id):
    obj = request.get_json(silent=True) or {}
    try:
        rec = clean_record(obj.get('record'), publish=obj.get('status') == 'published')
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if obj.get('status') not in {'draft', 'published'}:
        return jsonify(error='Invalid publication status.'), 400
    with service.conn() as db:
        if not db.execute('SELECT 1 FROM uploaded_khatians WHERE id=?', (record_id,)).fetchone():
            abort(404)
        db.execute('UPDATE uploaded_khatians SET record_json=?,status=? WHERE id=?',
                   (json.dumps(rec, ensure_ascii=False), obj['status'], record_id))
    service.audit('khatian_' + obj['status'], record_id)
    return jsonify(ok=True, id=record_id)


def record_exists(db, kind, record_id):
    if kind == 'local_deed':
        from dolil import catalogue
        return record_id in catalogue()
    if kind == 'deed':
        return db.execute('SELECT 1 FROM deeds WHERE deed_id=?', (record_id,)).fetchone()
    if kind == 'khatian':
        return (db.execute('SELECT 1 FROM khatians WHERE khatian_id=?', (record_id,)).fetchone() or
                db.execute('SELECT 1 FROM uploaded_khatians WHERE id=?', (record_id,)).fetchone())
    return False


@bp.patch('/api/admin/records/<kind>/<record_id>')
def record_control(kind, record_id):
    obj = request.get_json(silent=True) or {}
    if not isinstance(obj, dict) or not obj or set(obj) - {'deleted', 'warning'}:
        return jsonify(error='Invalid update.'), 400
    if 'deleted' in obj and not isinstance(obj['deleted'], bool):
        return jsonify(error='Invalid deletion state.'), 400
    if 'warning' in obj and (not isinstance(obj['warning'], str) or len(obj['warning']) > 1000):
        return jsonify(error='Warning ১০০০ অক্ষরের মধ্যে লিখুন।'), 400
    with service.conn() as db:
        if not record_exists(db, kind, record_id):
            abort(404)
        current = controls(db, kind, record_id)
        current.update(obj)
        db.execute('INSERT OR REPLACE INTO record_controls VALUES (?,?,?,?)',
                   (kind, record_id, int(current['deleted']), current['warning']))
    service.audit('admin_record_updated', record_id, {'kind': kind, **obj})
    return jsonify(ok=True)


@bp.get('/api/admin/records/<kind>/<record_id>')
def details(kind, record_id):
    with service.conn() as db:
        if not record_exists(db, kind, record_id):
            abort(404)
        control = controls(db, kind, record_id)
        if kind == 'local_deed':
            from dolil import reference
            try:
                item = reference(record_id, private=True)
            except ValueError as exc:
                return jsonify(error=str(exc)), 409
            return jsonify(kind=kind, id=record_id, record={'deed_no':record_id,'filename':item['filename']},
                           image_url=item['image_url'], editable=False, status='local_image', **control)
        if kind == 'deed':
            row = db.execute('SELECT * FROM deeds WHERE deed_id=?', (record_id,)).fetchone()
            return jsonify(kind=kind, id=record_id, record=json.loads(row['record_json']),
                           hash=row['hash'], signature=row['signature'], **control)
        custom = db.execute('SELECT * FROM uploaded_khatians WHERE id=?', (record_id,)).fetchone()
        if custom:
            return jsonify(kind=kind, id=record_id, record=json.loads(custom['record_json']),
                           ocr_text=custom['ocr_text'], ocr_message=custom['ocr_message'], status=custom['status'],
                           editable=True, image_url='/api/admin/khatians/' + record_id + '/image', **control)
        row = db.execute('SELECT k.*,l.division,l.district,l.upazila,l.mouza,l.jl_no FROM khatians k '
                         'JOIN lands l ON l.land_id=k.land_id WHERE k.khatian_id=?', (record_id,)).fetchone()
        rec = service.full_khatian_details(db, service.khatian_dict(row))
        return jsonify(kind=kind, id=record_id, record=rec, editable=False,
                       image_url='/api/admin/khatians/' + record_id + '/image' if rec['has_image'] else None, status='sample', **control)


@bp.get('/api/admin/deeds/<record_id>/pdf')
def admin_pdf(record_id):
    with service.conn() as db:
        row = db.execute('SELECT * FROM deeds WHERE deed_id=?', (record_id,)).fetchone()
    if not row:
        abort(404)
    deed = {'record': json.loads(row['record_json']), 'hash': row['hash'], 'signature': row['signature']}
    service.audit('admin_pdf_exported', record_id)
    return send_file(service.deed_pdf_bytes(deed), mimetype='application/pdf',
                     download_name=record_id + '.pdf', as_attachment=True)


@bp.get('/api/admin/records')
def records():
    kind = request.args.get('kind', 'khatian')
    if kind == 'local_deed':
        from dolil import admin_records
        return admin_records()
    if kind not in {'khatian', 'deed'}:
        return jsonify(error='Invalid record type.'), 400
    try:
        page_no = max(1, int(request.args.get('page', 1)))
    except ValueError:
        return jsonify(error='Invalid page.'), 400
    query = request.args.get('q', '').strip().casefold()[:100]
    state = request.args.get('state', 'all')
    if state not in {'all', 'active', 'deleted', 'draft', 'warning'}:
        return jsonify(error='Invalid status.'), 400
    with service.conn() as db:
        rows = []
        if kind == 'khatian':
            for row in db.execute('SELECT k.khatian_id,k.khatian_no,k.survey,l.district,l.upazila,l.mouza '
                                  'FROM khatians k JOIN lands l ON l.land_id=k.land_id'):
                rows.append({'id': row['khatian_id'], 'title': row['khatian_no'], 'status': 'sample',
                             'location': ' · '.join(row[k] for k in ('district', 'upazila', 'mouza')),
                             'survey': row['survey']})
            for row in db.execute('SELECT * FROM uploaded_khatians ORDER BY created_at DESC'):
                rec = json.loads(row['record_json'])
                rows.insert(0, {'id': row['id'], 'title': rec.get('khatian_no') or 'Untitled upload',
                                'status': row['status'], 'location': ' · '.join(rec.get(k, '') for k in
                                ('district', 'upazila', 'mouza')), 'survey': rec.get('survey', '')})
        else:
            for row in db.execute('SELECT deed_id,record_json FROM deeds ORDER BY created_at DESC'):
                rec = json.loads(row['record_json'])
                rows.append({'id': row['deed_id'], 'title': rec['owner_name'], 'status': 'signed',
                             'location': ' · '.join(rec[k] for k in ('district', 'upazila', 'mouza')),
                             'survey': rec['khatian_no'] + ' / ' + rec['dag_no']})
        control_map = {r['record_id']: dict(r) for r in db.execute('SELECT * FROM record_controls WHERE kind=?', (kind,))}
        for row in rows:
            row.update({k: control_map.get(row['id'], {}).get(k, default) for k, default in [('deleted', 0), ('warning', '')]})
        counts = {'total': len(rows), 'deleted': sum(bool(r['deleted']) for r in rows),
                  'warnings': sum(bool(r['warning']) for r in rows), 'drafts': sum(r['status'] == 'draft' for r in rows)}
        rows = [r for r in rows if (not query or query in json.dumps(r, ensure_ascii=False).casefold())
                and (state == 'all' or (state == 'deleted' and r['deleted']) or
                     (state == 'active' and not r['deleted'] and r['status'] != 'draft') or
                     (state == 'draft' and r['status'] == 'draft') or (state == 'warning' and r['warning']))]
    return jsonify(records=rows[(page_no-1)*25:page_no*25], total=len(rows), page=page_no, counts=counts)


def register_admin(app, backend):
    global service
    service = backend
    secret_path = service.INSTANCE / 'session_secret.key'
    try:
        with secret_path.open('xb') as file:
            file.write(secrets.token_bytes(32))
    except FileExistsError:
        pass
    app.secret_key = secret_path.read_bytes()
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
                      SESSION_COOKIE_SECURE=os.getenv('SUTRO_COOKIE_SECURE', '0') == '1',
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
    (service.INSTANCE / 'uploads').mkdir(exist_ok=True)
    (service.INSTANCE / 'deed_rewrites').mkdir(exist_ok=True)
    with service.conn() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS admin_account(id INTEGER PRIMARY KEY CHECK(id=1),password_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS admin_users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('superadmin','admin')),
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_login_failures(ip TEXT,stamp REAL);
            CREATE TABLE IF NOT EXISTS uploaded_khatians(id TEXT PRIMARY KEY,filename TEXT NOT NULL,
                record_json TEXT NOT NULL,ocr_text TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,ocr_message TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS record_controls(kind TEXT,record_id TEXT,deleted INTEGER NOT NULL DEFAULT 0,
                warning TEXT NOT NULL DEFAULT '',PRIMARY KEY(kind,record_id));
            CREATE TABLE IF NOT EXISTS deed_rewrites(
                id TEXT PRIMARY KEY,original_filename TEXT NOT NULL,original_path TEXT NOT NULL,
                text TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('draft','completed')),
                rewritten_path TEXT,page_count INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
            );
        ''')
        configured = os.getenv('SUTRO_ADMIN_PASSWORD')
        if configured and not db.execute('SELECT 1 FROM admin_account WHERE id=1').fetchone():
            if not 12 <= len(configured) <= 128:
                raise RuntimeError('SUTRO_ADMIN_PASSWORD must be 12–128 characters')
            db.execute('INSERT INTO admin_account VALUES (1,?)', (generate_password_hash(configured),))
        legacy = db.execute('SELECT password_hash FROM admin_account WHERE id=1').fetchone()
        if legacy and not db.execute('SELECT 1 FROM admin_users WHERE username=?', ('superadmin',)).fetchone():
            db.execute('INSERT INTO admin_users(id,username,password_hash,role,active,created_at) VALUES (1,?,?,?,?,?)',
                       ('superadmin', legacy['password_hash'], 'superadmin', 1, service.now()))
    app.register_blueprint(bp)
