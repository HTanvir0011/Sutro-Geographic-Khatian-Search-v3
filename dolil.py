"""Read-only lookup and exact-copy comparison against filename-numbered deeds."""
import hashlib
import io
import os
import re
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from flask import Blueprint, abort, jsonify, request, send_file
from admin_panel import authenticated, controls

bp = Blueprint('local_dolil', __name__)
service = None
IMAGE_DIR = None
MAX_BYTES = 15 * 1024 * 1024
NOTICE = 'শুধু স্থানীয় ছবির সঙ্গে কপি মেলানো হয়; এটি দলিলের আইনি সত্যতা বা মালিকানা যাচাই নয়।'


def number(value):
    value = str(value or '').strip().translate(str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789'))
    match = re.fullmatch(r'(?:dolil[ _-]*)?([0-9]{1,15})(?:\.(?:jpg|jpeg|png|webp))?', value, re.I)
    return str(int(match.group(1))) if match else None


def catalogue():
    result = {}
    if not IMAGE_DIR.is_dir():
        return result
    root = IMAGE_DIR.resolve()
    for file in IMAGE_DIR.iterdir():
        if file.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp'}:
            continue
        key = number(file.stem)
        if key and file.is_file() and file.resolve().is_relative_to(root):
            result.setdefault(key, []).append(file)
    return result


def source_path(key):
    files = catalogue().get(number(key), [])
    if len(files) > 1:
        raise ValueError('একই নম্বরের একাধিক ছবি আছে। অ্যাডমিনকে filename ঠিক করতে বলুন।')
    return files[0] if files else None


def visible(key):
    with service.conn() as db:
        return controls(db, 'local_deed', key)


def reference(key, private=False):
    key = number(key)
    if not key:
        return None
    control = visible(key)
    if control['deleted'] and not private:
        return None
    path = source_path(key)
    if not path:
        return None
    return {'number': key, 'filename': path.name, 'warning': control['warning'],
            'image_url': ('/api/admin/local-deeds/' if private else '/api/local-deeds/') + key + '/image',
            'notice': NOTICE}


def pixels(raw):
    with Image.open(io.BytesIO(raw)) as image:
        if (image.format not in {'JPEG', 'PNG', 'WEBP'} or image.width * image.height > 40_000_000
                or getattr(image, 'n_frames', 1) != 1):
            raise ValueError()
        image.load()
        canonical = ImageOps.exif_transpose(image).convert('RGBA')
        digest = hashlib.sha256(str(canonical.size).encode() + b':' + canonical.tobytes()).hexdigest()
        return digest


@bp.after_request
def cache_policy(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@bp.get('/api/local-deeds/search')
def lookup():
    key = number(request.args.get('number', ''))
    if key is None:
        return jsonify(error='দলিলের ছবি নম্বর দিন, যেমন 1, ১ অথবা dolil_1।'), 400
    try:
        item = reference(key)
    except ValueError as exc:
        return jsonify(error=str(exc)), 409
    if not item:
        return jsonify(error='এই নম্বরের স্থানীয় দলিলের ছবি পাওয়া যায়নি।'), 404
    return jsonify(record=item)


@bp.get('/api/local-deeds/<key>/image')
def image(key):
    try:
        item = reference(key)
    except ValueError:
        abort(409)
    if not item:
        abort(404)
    return send_file(source_path(key), conditional=False)


@bp.get('/api/admin/local-deeds/<key>/image')
def private_image(key):
    if not authenticated():
        return jsonify(error='Admin login required.'), 401
    try:
        path = source_path(key)
    except ValueError:
        abort(409)
    if not path:
        abort(404)
    return send_file(path, conditional=False)


@bp.post('/api/local-deeds/compare')
def compare():
    file = request.files.get('file')
    if not file:
        return jsonify(error='তুলনা করার জন্য JPG, PNG বা WEBP দলিলের ছবি দিন।'), 400
    key = number(request.form.get('number') or file.filename)
    if key is None:
        return jsonify(error='দলিলের ছবি নম্বর দিন। Filename dolil_1.jpg হলে নম্বর 1।'), 400
    try:
        item = reference(key)
    except ValueError as exc:
        return jsonify(error=str(exc)), 409
    if not item:
        return jsonify(error='এই নম্বরের স্থানীয় দলিলের ছবি পাওয়া যায়নি।'), 404
    raw = file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        return jsonify(error='ছবি সর্বোচ্চ ১৫ MB হতে পারবে।'), 400
    try:
        uploaded_pixels = pixels(raw)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return jsonify(error='সঠিক JPG, PNG বা WEBP ছবি দিন (সর্বোচ্চ ৪০ মিলিয়ন পিক্সেল)।'), 400
    path = source_path(key)
    if not path or path.stat().st_size > MAX_BYTES:
        return jsonify(error='রেফারেন্স ছবিটি এখন পড়া যাচ্ছে না।'), 503
    try:
        original = path.read_bytes()
        original_pixels = pixels(original)
    except (OSError, ValueError, Image.DecompressionBombError):
        return jsonify(error='রেফারেন্স ছবিটি এখন পড়া যাচ্ছে না।'), 503
    exact = hashlib.sha256(raw).digest() == hashlib.sha256(original).digest()
    pixel_match = uploaded_pixels == original_pixels
    status = 'EXACT_FILE_MATCH' if exact else ('EXACT_IMAGE_MATCH' if pixel_match else 'NOT_EXACT_MATCH')
    return jsonify(status=status, file_match=exact, image_match=pixel_match, record=item,
                   message={'EXACT_FILE_MATCH': 'আপলোড করা ফাইলটি স্থানীয় কপির সঙ্গে হুবহু মিলে গেছে।',
                            'EXACT_IMAGE_MATCH': 'ফাইলের encoding আলাদা হলেও ছবির সব পিক্সেল মিলে গেছে।',
                            'NOT_EXACT_MATCH': 'ছবিটি হুবহু মেলেনি। পরিবর্তন, compression, resize বা নতুন ছবি তোলার কারণেও এমন হতে পারে; এটি জাল দলিলের প্রমাণ নয়।'}[status])


def admin_records():
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        return jsonify(error='Invalid page.'), 400
    state = request.args.get('state', 'all')
    if state not in {'all', 'active', 'deleted', 'draft', 'warning'}:
        return jsonify(error='Invalid state.'), 400
    query = request.args.get('q', '').strip().casefold()[:100]
    rows = []
    with service.conn() as db:
        control_map = {r['record_id']: dict(r) for r in db.execute("SELECT * FROM record_controls WHERE kind='local_deed'")}
    for key, files in sorted(catalogue().items(), key=lambda pair: int(pair[0])):
        control = control_map.get(key, {})
        rows.append({'id': key, 'title': 'দলিলের ছবি ' + key, 'location': ' / '.join(f.name for f in files),
                     'survey': '', 'status': 'local_image' if len(files) == 1 else 'duplicate_number',
                     'deleted': control.get('deleted', 0), 'warning': control.get('warning', '')})
    counts = {'total': len(rows), 'deleted': sum(bool(r['deleted']) for r in rows),
              'warnings': sum(bool(r['warning']) for r in rows), 'drafts': 0}
    rows = [r for r in rows if (not query or query in (r['id']+' '+r['location']).casefold()) and
            (state == 'all' or (state == 'active' and not r['deleted']) or
             (state == 'deleted' and r['deleted']) or (state == 'warning' and r['warning']))]
    return jsonify(records=rows[(page-1)*25:page*25], total=len(rows), counts=counts, page=page)


def register_dolil(app, backend):
    global service, IMAGE_DIR
    service = backend
    default = service.ROOT.parent / 'Dolil'
    IMAGE_DIR = Path(os.getenv('SUTRO_DOLIL_IMAGE_DIR', str(default))).expanduser()
    app.register_blueprint(bp)
