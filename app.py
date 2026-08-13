# -*- coding: utf-8 -*-
"""
کلاس دهم — سامانهٔ جامع مدیریت محتوای آموزشی پایهٔ دهم
نسخهٔ «پایتون خالص»: تمام صفحات HTML داخل توابع پایتون ساخته می‌شوند.
بدون Jinja2، بدون render_template، بدون پوشهٔ templates.
"""
import os
import re
import json
import glob
import html
import sqlite3
import subprocess
import threading
import urllib.request
import uuid
import mimetypes
from datetime import datetime
from functools import wraps

import jdatetime
from flask import (Flask, g, request, redirect, url_for, session, flash,
                   get_flashed_messages, send_file, Response, abort)
from werkzeug.middleware.proxy_fix import ProxyFix

# ============================================================================
# تنظیمات پایه
# ============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# مسیر داده‌ها (دیتابیس + آپلودها) — در هاست می‌توان با DATA_DIR به دیسک پایدار
# (persistent disk) اشاره کرد تا بعد از هر deploy اطلاعات از بین نرود.
DATA_DIR = os.environ.get('DATA_DIR', BASE_DIR)
DB_PATH = os.path.join(DATA_DIR, 'dahom.db')
UPLOAD_DIR = os.path.join(DATA_DIR, 'uploads')
VIDEO_DIR = os.path.join(UPLOAD_DIR, 'videos')
DOC_DIR = os.path.join(UPLOAD_DIR, 'docs')

SITE_NAME = 'کلاس دهم'
SITE_TAGLINE = 'پایگاه جامع آموزشی پایهٔ دهم — ویدیو، جزوه، گام به گام، نمونه سوال و سوالات کتاب'
GRADE = 'پایهٔ دهم'
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'dahom123')

CONTENT_TYPES = {
    'video':    {'label': 'ویدیو آموزشی',       'icon': '🎬', 'color': '#e11d48'},
    'note':     {'label': 'جزوه',               'icon': '📄', 'color': '#2563eb'},
    'solution': {'label': 'گام به گام',         'icon': '📘', 'color': '#7c3aed'},
    'exam':     {'label': 'نمونه سوال امتحانی', 'icon': '📝', 'color': '#059669'},
    'textbook': {'label': 'سوالات کتاب',        'icon': '📗', 'color': '#d97706'},
}
CONTENT_ORDER = ['video', 'note', 'solution', 'exam', 'textbook']

VIDEO_EXTS = {'.mp4', '.webm', '.mov', '.m4v', '.ogv'}
DOC_EXTS = {'.pdf', '.png', '.jpg', '.jpeg', '.zip', '.doc', '.docx', '.txt'}

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dahom-secret-key-1404')
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 ** 3  # تا ۴ گیگابایت برای ویدیوها
# امنیت کوکی جلسه
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
if os.environ.get('COOKIE_SECURE', '0') == '1':
    app.config['SESSION_COOKIE_SECURE'] = True
# پشت Nginx/Proxy قرار می‌گیریم؛ این باعث می‌شود url_for آدرس https بسازد
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# آدرس جداگانهٔ پنل مدیریت (قابل تغییر با ADMIN_PANEL_PATH)
ADMIN_PANEL_PATH = os.environ.get('ADMIN_PANEL_PATH', 'panel').strip('/')
ADMIN_PREFIX = '/' + ADMIN_PANEL_PATH

# ============================================================================
# تنظیمات زرین‌پال
# ZARINPAL_MERCHANT_ID: مرچنت‌کد درگاه (از پنل زرین‌پال)
# ZARINPAL_SANDBOX: 1 = درگاه تست، 0 = درگاه واقعی
# ============================================================================
ZARINPAL_MERCHANT_ID = os.environ.get('ZARINPAL_MERCHANT_ID', '').strip()
ZARINPAL_SANDBOX = os.environ.get('ZARINPAL_SANDBOX', '1') == '1'

if ZARINPAL_SANDBOX:
    ZP_REQUEST_URL = 'https://sandbox.zarinpal.com/pg/v4/payment/request.json'
    ZP_VERIFY_URL = 'https://sandbox.zarinpal.com/pg/v4/payment/verify.json'
    ZP_STARTPAY_URL = 'https://sandbox.zarinpal.com/pg/StartPay/'
else:
    ZP_REQUEST_URL = 'https://payment.zarinpal.com/pg/v4/payment/request.json'
    ZP_VERIFY_URL = 'https://payment.zarinpal.com/pg/v4/payment/verify.json'
    ZP_STARTPAY_URL = 'https://payment.zarinpal.com/pg/StartPay/'

# ============================================================================
# دیتابیس
# ============================================================================
SCHEMA = """
CREATE TABLE IF NOT EXISTS fields (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    slug        TEXT UNIQUE NOT NULL,
    description TEXT DEFAULT '',
    icon        TEXT DEFAULT '📚',
    color       TEXT DEFAULT '#4f46e5',
    sort_order  INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS subjects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    slug        TEXT UNIQUE NOT NULL,
    description TEXT DEFAULT '',
    icon        TEXT DEFAULT '📖',
    color       TEXT DEFAULT '#0ea5e9',
    grade       TEXT DEFAULT 'دهم',
    sort_order  INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS subject_fields (
    subject_id INTEGER NOT NULL,
    field_id   INTEGER NOT NULL,
    is_common  INTEGER DEFAULT 0,
    PRIMARY KEY (subject_id, field_id),
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    FOREIGN KEY (field_id)   REFERENCES fields(id)   ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS contents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id     INTEGER NOT NULL,
    content_type   TEXT NOT NULL,
    title          TEXT NOT NULL,
    description    TEXT DEFAULT '',
    file_path      TEXT DEFAULT '',
    file_orig_name TEXT DEFAULT '',
    mime           TEXT DEFAULT '',
    url            TEXT DEFAULT '',
    source         TEXT DEFAULT '',
    added_at       TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_contents_subject ON contents(subject_id);
CREATE INDEX IF NOT EXISTS idx_contents_type ON contents(content_type);
CREATE TABLE IF NOT EXISTS download_jobs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id INTEGER NOT NULL,
    status     TEXT DEFAULT 'queued',
    progress   TEXT DEFAULT '',
    error      TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (content_id) REFERENCES contents(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    sub_end       TEXT DEFAULT '',          -- تاریخ پایان اشتراک (ISO: YYYY-MM-DD HH:MM:SS)
    created_at    TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS plans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    months          INTEGER NOT NULL DEFAULT 1,
    price           INTEGER NOT NULL DEFAULT 0,   -- قیمت به تومان
    discount_percent INTEGER NOT NULL DEFAULT 0,
    active          INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS transactions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    plan_id    INTEGER NOT NULL,
    amount     INTEGER NOT NULL,                  -- مبلغ نهایی به تومان
    authority  TEXT DEFAULT '',
    ref_id     TEXT DEFAULT '',
    status     TEXT DEFAULT 'pending',            -- pending / success / failed
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    paid_at    TEXT DEFAULT '',
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_transactions_authority ON transactions(authority);
"""


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def get_setting(key, default=''):
    row = get_db().execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
    return row['value'] if row else default


def set_setting(key, value):
    db = get_db()
    db.execute('INSERT INTO settings (key, value) VALUES (?, ?) '
               'ON CONFLICT(key) DO UPDATE SET value = excluded.value', (key, value))
    db.commit()


def check_admin_password(pw):
    from werkzeug.security import check_password_hash
    stored = get_setting('admin_password')
    if stored:
        return check_password_hash(stored, pw)
    return pw == ADMIN_PASSWORD


def slugify(text):
    s = re.sub(r'[^\w\u0600-\u06FF\s-]', '', str(text)).strip().lower()
    s = re.sub(r'\s+', '-', s)
    s = re.sub(r'-+', '-', s)
    return s or 'item'


def unique_slug(table, name, exclude_id=None):
    base = slugify(name)
    slug = base
    n = 2
    while True:
        q = f'SELECT id FROM {table} WHERE slug = ?'
        args = [slug]
        if exclude_id:
            q += ' AND id != ?'
            args.append(exclude_id)
        if not get_db().execute(q, args).fetchone():
            return slug
        slug = f'{base}-{n}'
        n += 1


# ============================================================================
# داده‌های اولیه (برنامه درسی پایهٔ دهم)
# ============================================================================
FIELD_SEED = [
    {'name': 'ریاضی و فیزیک', 'icon': '📐', 'color': '#4338ca',
     'description': 'دروس تخصصی: ریاضی ۱، فیزیک ۱، شیمی ۱، هندسه ۱ و آزمایشگاه علوم تجربی'},
    {'name': 'علوم تجربی', 'icon': '🔬', 'color': '#0d9488',
     'description': 'دروس تخصصی: زیست‌شناسی ۱، شیمی ۱، فیزیک ۱، ریاضی ۱ و آزمایشگاه علوم تجربی'},
    {'name': 'علوم انسانی', 'icon': '🏛️', 'color': '#d97706',
     'description': 'دروس تخصصی: منطق، جامعه‌شناسی ۱، تاریخ ۱، ریاضی و آمار ۱، علوم و فنون ادبی ۱ و اقتصاد'},
]

SUBJECT_SEED = [
    ('فارسی ۱', '📖', '#4f46e5'),
    ('نگارش ۱', '✍️', '#6366f1'),
    ('عربی، زبان قرآن ۱', '📿', '#0e7490'),
    ('زبان انگلیسی ۱', '🌍', '#0284c7'),
    ('دین و زندگی ۱', '🕌', '#15803d'),
    ('تفکر و سواد رسانه‌ای', '💭', '#7c3aed'),
    ('آمادگی دفاعی', '🛡️', '#b91c1c'),
    ('کارگاه کارآفرینی و تولید', '🛠️', '#b45309'),
    ('جغرافیای ایران', '🗺️', '#0d9488'),
    ('ریاضی ۱', '📐', '#4338ca'),
    ('فیزیک ۱', '⚡', '#ea580c'),
    ('شیمی ۱', '🧪', '#0891b2'),
    ('آزمایشگاه علوم تجربی ۱', '🧫', '#16a34a'),
    ('هندسه ۱', '📏', '#4f46e5'),
    ('زیست‌شناسی ۱', '🧬', '#16a34a'),
    ('ریاضی و آمار ۱', '📊', '#7c3aed'),
    ('منطق', '🧠', '#9333ea'),
    ('جامعه‌شناسی ۱', '👥', '#db2777'),
    ('تاریخ ۱', '🏺', '#a16207'),
    ('علوم و فنون ادبی ۱', '🖋️', '#c2410c'),
    ('اقتصاد', '💰', '#65a30d'),
]

COMMON_SUBJECTS = ['فارسی ۱', 'نگارش ۱', 'عربی، زبان قرآن ۱', 'زبان انگلیسی ۱',
                   'دین و زندگی ۱', 'تفکر و سواد رسانه‌ای', 'آمادگی دفاعی',
                   'کارگاه کارآفرینی و تولید', 'جغرافیای ایران']
STEM_SHARED = ['ریاضی ۱', 'فیزیک ۱', 'شیمی ۱', 'آزمایشگاه علوم تجربی ۱']
RIAZI_ONLY = ['هندسه ۱']
TAJROBI_ONLY = ['زیست‌شناسی ۱']
ENSANI_ONLY = ['ریاضی و آمار ۱', 'منطق', 'جامعه‌شناسی ۱', 'تاریخ ۱',
               'علوم و فنون ادبی ۱', 'اقتصاد']


def seed():
    db = get_db()
    if db.execute('SELECT COUNT(*) AS c FROM fields').fetchone()['c']:
        return
    field_ids = {}
    for i, f in enumerate(FIELD_SEED):
        cur = db.execute(
            'INSERT INTO fields (name, slug, description, icon, color, sort_order) VALUES (?,?,?,?,?,?)',
            (f['name'], unique_slug('fields', f['name']), f['description'],
             f['icon'], f['color'], i))
        field_ids[f['name']] = cur.lastrowid

    def add_subject(name, icon, color, field_names, is_common):
        cur = db.execute(
            'INSERT INTO subjects (name, slug, icon, color, sort_order) VALUES (?,?,?,?,?)',
            (name, unique_slug('subjects', name), icon, color, 0))
        sid = cur.lastrowid
        for fn in field_names:
            db.execute('INSERT INTO subject_fields (subject_id, field_id, is_common) VALUES (?,?,?)',
                       (sid, field_ids[fn], 1 if is_common else 0))

    riazi, tajrobi, ensani = 'ریاضی و فیزیک', 'علوم تجربی', 'علوم انسانی'
    all_fields = [riazi, tajrobi, ensani]

    for name, icon, color in SUBJECT_SEED:
        if name in COMMON_SUBJECTS:
            add_subject(name, icon, color, all_fields, True)
        elif name in STEM_SHARED:
            add_subject(name, icon, color, [riazi, tajrobi], False)
        elif name in RIAZI_ONLY:
            add_subject(name, icon, color, [riazi], False)
        elif name in TAJROBI_ONLY:
            add_subject(name, icon, color, [tajrobi], False)
        elif name in ENSANI_ONLY:
            add_subject(name, icon, color, [ensani], False)
    db.commit()

    # پلن‌های پیش‌فرض اشتراک (اگر جدول خالی است)
    if db.execute('SELECT COUNT(*) AS c FROM plans').fetchone()['c'] == 0:
        db.executemany(
            'INSERT INTO plans (name, months, price, discount_percent, active) VALUES (?,?,?,?,?)',
            [
                ('پلن یک‌ماهه', 1, 50000, 0, 1),
                ('پلن سه‌ماهه', 3, 140000, 7, 1),
                ('پلن یک‌ساله', 12, 500000, 20, 1),
            ])
        db.commit()


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    db.close()
    os.makedirs(VIDEO_DIR, exist_ok=True)
    os.makedirs(DOC_DIR, exist_ok=True)
    with app.app_context():
        seed()


_init_lock = threading.Lock()


def ensure_init():
    """راه‌اندازی امن دیتابیس — برای gunicorn چند-ورکر (بدون رقابت همزمان)"""
    with _init_lock:
        try:
            init_db()
        except sqlite3.IntegrityError:
            pass  # ورکر دیگری همین لحظه seed کرده است — نادیده بگیر


# ============================================================================
# توابع کمکی عمومی
# ============================================================================
def e(text):
    """فرار از کاراکترهای HTML برای جلوگیری از XSS"""
    return html.escape(str(text if text is not None else ''), quote=True)


def fa_date(dt_str):
    try:
        dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
        return jdatetime.datetime.fromgregorian(datetime=dt).strftime('%d %B %Y ساعت %H:%M')
    except Exception:
        return dt_str or ''


# ============================================================================
# دانش‌آموز و اشتراک
# ============================================================================
def current_user():
    """کاربر دانش‌آموز واردشده یا None"""
    uid = session.get('user_id')
    if not uid:
        return None
    row = get_db().execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
    return dict(row) if row else None


def sub_end_dt(user):
    """تاریخ پایان اشتراک به‌صورت datetime یا None"""
    s = (user or {}).get('sub_end') or ''
    if not s:
        return None
    try:
        return datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
    except Exception:
        return None


def has_active_sub(user):
    """آیا اشتراک فعال دارد؟ (مدیر همیشه بله)"""
    if session.get('admin'):
        return True
    end = sub_end_dt(user)
    return end is not None and end >= datetime.now()


def can_download():
    """آیا کاربر فعلی اجازهٔ دانلود فایل‌ها را دارد؟ (مدیر یا دانش‌آموز با اشتراک فعال)"""
    if session.get('admin'):
        return True
    return has_active_sub(current_user())


def add_months(dt, months):
    """افزودن ماه به تاریخ با رعایت تعداد روزهای ماه"""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, _month_days(year, month))
    return dt.replace(year=year, month=month, day=day)


def _month_days(year, month):
    import calendar
    return calendar.monthrange(year, month)[1]


def plan_final_price(plan):
    """قیمت نهایی پلن بعد از اعمال درصد تخفیف (تومان)"""
    return max(0, plan['price'] * (100 - plan['discount_percent']) // 100)


def zp_post(url, payload):
    """ارسال درخواست JSON به زرین‌پال"""
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={
        'Content-Type': 'application/json',
        'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))


def youtube_embed(url):
    m = re.search(r'(?:youtube\.com/(?:watch\?v=|embed/|shorts/|live/)|youtu\.be/)([\w-]{6,})', url)
    if m:
        return f'https://www.youtube.com/embed/{m.group(1)}'
    m2 = re.search(r'youtube\.com/playlist\?list=([\w-]+)', url)
    if m2:
        return f'https://www.youtube.com/embed/videoseries?list={m2.group(1)}'
    return None


def content_counts():
    rows = get_db().execute(
        'SELECT subject_id, content_type, COUNT(*) AS c FROM contents '
        'GROUP BY subject_id, content_type').fetchall()
    out = {}
    for r in rows:
        out.setdefault(r['subject_id'], {})[r['content_type']] = r['c']
    return out


def get_field(slug):
    return get_db().execute('SELECT * FROM fields WHERE slug = ?', (slug,)).fetchone()


def get_subject(slug):
    return get_db().execute('SELECT * FROM subjects WHERE slug = ?', (slug,)).fetchone()


def subject_fields(subject_id):
    return get_db().execute(
        'SELECT f.*, sf.is_common FROM subject_fields sf JOIN fields f ON f.id = sf.field_id '
        'WHERE sf.subject_id = ? ORDER BY sf.is_common DESC, f.sort_order', (subject_id,)).fetchall()


def field_subjects(field_id, common_only=None):
    q = ('SELECT s.*, sf.is_common, COUNT(c.id) AS content_count FROM subject_fields sf '
         'JOIN subjects s ON s.id = sf.subject_id '
         'LEFT JOIN contents c ON c.subject_id = s.id '
         'WHERE sf.field_id = ? ')
    params = [field_id]
    if common_only is not None:
        q += 'AND sf.is_common = ? '
        params.append(1 if common_only else 0)
    q += 'GROUP BY s.id ORDER BY s.name'
    return get_db().execute(q, params).fetchall()


# ============================================================================
# دریافت خودکار فایل از لینک (یوتیوب و هر لینک دیگر)
# ============================================================================
YTDLP_TIMEOUT = 60 * 30
DOC_MAX = 1500 * 1024 * 1024


def db_exec(sql, params=(), fetch=False):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    try:
        cur = con.execute(sql, params)
        con.commit()
        lid = cur.lastrowid
        rows = [dict(r) for r in cur.fetchall()] if fetch else None
    finally:
        con.close()
    return rows if fetch else lid


def get_latest_job(content_id):
    rows = db_exec('SELECT * FROM download_jobs WHERE content_id = ? '
                   'ORDER BY id DESC LIMIT 1', (content_id,), fetch=True)
    return rows[0] if rows else None


def start_url_fetch(content_id):
    rows = db_exec('SELECT * FROM contents WHERE id = ?', (content_id,), fetch=True)
    if not rows:
        return None
    content = rows[0]
    if content['file_path'] or not content['url']:
        return None
    job = get_latest_job(content_id)
    if job and job['status'] in ('queued', 'running'):
        return job['id']
    job_id = db_exec("INSERT INTO download_jobs (content_id, status) VALUES (?, 'queued')",
                     (content_id,))
    if content['content_type'] == 'video':
        t = threading.Thread(target=video_fetch_worker,
                             args=(job_id, content_id, content['url']), daemon=True)
    else:
        t = threading.Thread(target=doc_fetch_worker,
                             args=(job_id, content_id, content['url']), daemon=True)
    t.start()
    return job_id


def video_fetch_worker(job_id, content_id, url):
    db_exec("UPDATE download_jobs SET status='running', progress='1%', "
            "updated_at=datetime('now','localtime') WHERE id=?", (job_id,))
    outbase = os.path.join(VIDEO_DIR, 'ytdlp_' + uuid.uuid4().hex)
    cmd = ['yt-dlp',
           '-f', 'best[height<=720]/best',
           '--merge-output-format', 'mp4',
           '--no-playlist',
           '--no-warnings',
           '--socket-timeout', '30',
           '-o', outbase + '.%(ext)s',
           url]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE,
                                text=True, encoding='utf-8', errors='replace')
        for line in proc.stderr:
            line = line.strip()
            m = re.search(r'(\d+(?:\.\d+)?)%', line)
            if m:
                db_exec("UPDATE download_jobs SET progress=?, "
                        "updated_at=datetime('now','localtime') WHERE id=?",
                        (m.group(1) + '%', job_id))
        proc.wait(timeout=YTDLP_TIMEOUT)
    except Exception as exc:
        db_exec("UPDATE download_jobs SET status='error', error=?, "
                "updated_at=datetime('now','localtime') WHERE id=?",
                (str(exc)[:400], job_id))
        return

    if proc.returncode != 0:
        db_exec("UPDATE download_jobs SET status='error', "
                "error='دریافت ناموفق بود؛ لینک را بررسی کنید.', "
                "updated_at=datetime('now','localtime') WHERE id=?", (job_id,))
        return

    matches = glob.glob(outbase + '.*')
    if not matches:
        db_exec("UPDATE download_jobs SET status='error', error='فایلی ساخته نشد.', "
                "updated_at=datetime('now','localtime') WHERE id=?", (job_id,))
        return
    src = matches[0]
    fname = uuid.uuid4().hex + os.path.splitext(src)[1].lower()
    os.rename(src, os.path.join(VIDEO_DIR, fname))
    mime = mimetypes.guess_type(fname)[0] or 'video/mp4'
    db_exec("UPDATE contents SET file_path=?, file_orig_name=?, mime=?, url='' WHERE id=?",
            ('videos/' + fname, 'ویدیو (دریافت‌شده از لینک)', mime, content_id))
    db_exec("UPDATE download_jobs SET status='done', progress='100%', "
            "updated_at=datetime('now','localtime') WHERE id=?", (job_id,))


def ext_from_url(url):
    m = re.search(r'\.([A-Za-z0-9]{2,5})(?:$|[?#])', url)
    return m.group(1).lower() if m else ''


def mime_to_ext(ct):
    ct = (ct or '').lower().split(';')[0].strip()
    mp = {
        'application/pdf': 'pdf',
        'application/zip': 'zip',
        'application/msword': 'doc',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
        'application/vnd.ms-excel': 'xls',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
        'application/vnd.ms-powerpoint': 'ppt',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
        'text/plain': 'txt',
    }
    for k, v in mp.items():
        if ct.startswith(k):
            return v
    if ct.startswith('image/'):
        return 'png' if 'png' in ct else 'jpg'
    if ct.startswith('video/'):
        return 'mp4'
    if ct.startswith('audio/'):
        return 'mp3'
    return ''


def doc_fetch_worker(job_id, content_id, url):
    db_exec("UPDATE download_jobs SET status='running', progress='1%', "
            "updated_at=datetime('now','localtime') WHERE id=?", (job_id,))
    tmp = os.path.join(DOC_DIR, 'tmp_' + uuid.uuid4().hex)
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          'Chrome/126.0 Safari/537.36'})
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get('Content-Length') or 0)
            ext = ext_from_url(url) or mime_to_ext(resp.headers.get('Content-Type', ''))
            if not ext or ('.' + ext) not in DOC_EXTS:
                ext = 'bin'
            got = 0
            with open(tmp, 'wb') as f:
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if got > DOC_MAX:
                        raise Exception('حجم فایل بیش از حد مجاز است')
                    if total:
                        pct = min(99, int(got * 100 / total))
                        if pct % 10 == 0:
                            db_exec("UPDATE download_jobs SET progress=?, "
                                    "updated_at=datetime('now','localtime') WHERE id=?",
                                    (f'{pct}%', job_id))
        if got == 0:
            raise Exception('فایل خالی دریافت شد')
        if ext == 'bin':
            raise Exception('فرمت فایل در لینک قابل شناسایی نیست')
        fname = uuid.uuid4().hex + '.' + ext
        os.replace(tmp, os.path.join(DOC_DIR, fname))
        mime = mimetypes.guess_type(fname)[0] or 'application/octet-stream'
        db_exec("UPDATE contents SET file_path=?, file_orig_name=?, mime=?, url='' WHERE id=?",
                ('docs/' + fname, 'فایل (دریافت‌شده از لینک)', mime, content_id))
        db_exec("UPDATE download_jobs SET status='done', progress='100%', "
                "updated_at=datetime('now','localtime') WHERE id=?", (job_id,))
    except Exception as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        db_exec("UPDATE download_jobs SET status='error', error=?, "
                "updated_at=datetime('now','localtime') WHERE id=?",
                (str(exc)[:300], job_id))


# ============================================================================
# لایهٔ ساخت HTML (همهٔ صفحات داخل پایتون — بدون موتور قالب)
# ============================================================================
def page_base(title, content, active=''):
    """قالب اصلی صفحه: هدر + پیام‌ها + محتوا + فوتر"""
    return ('<!doctype html>\n<html lang="fa" dir="rtl">\n<head>\n'
            '  <meta charset="utf-8">\n'
            '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '  <title>' + e(title) + ' | ' + e(SITE_NAME) + '</title>\n'
            '  <meta name="description" content="' + e(SITE_TAGLINE) + '">\n'
            '  <link rel="icon" href="data:image/svg+xml,<svg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 100 100%27><text y=%27.9em%27 font-size=%2790%27>🎓</text></svg>">\n'
            '  <link rel="stylesheet" href="' + url_for('static', filename='css/style.css') + '">\n'
            '</head>\n<body>\n'
            + header_html(active)
            + flash_html()
            + '<main>' + content + '</main>'
            + footer_html()
            + '<script src="' + url_for('static', filename='js/main.js') + '"></script>\n'
            '</body>\n</html>')


def header_html(active=''):
    nav_home = ' class="active"' if active == 'index' else ''
    nav_bank = ' class="active"' if active == 'contents' else ''
    nav_plans = ' class="active"' if active == 'plans' else ''
    # لینک‌های کاربر دانش‌آموز
    u = current_user()
    if u:
        auth_links = ('<a href="' + url_for('account') + '">👤 ' + e(u['name']) + '</a>\n'
                      '        <a href="' + url_for('logout_student') + '">خروج</a>\n')
    else:
        auth_links = ('<a href="' + url_for('signup') + '">ثبت‌نام</a>\n'
                      '        <a href="' + url_for('login_student') + '">ورود</a>\n')
    return ('  <header class="site-header">\n'
            '    <div class="header-inner">\n'
            '      <a href="' + url_for('index') + '" class="logo">\n'
            '        <span class="logo-badge">🎓</span>\n'
            '        <span>' + e(SITE_NAME) + '<small>' + e(GRADE) + ' — سایت درسی</small></span>\n'
            '      </a>\n'
            '      <nav class="main-nav">\n'
            '        <a href="' + url_for('index') + '"' + nav_home + '>خانه</a>\n'
            '        <a href="' + url_for('contents_list') + '"' + nav_bank + '>بانک مطالب</a>\n'
            '        <a href="' + url_for('plans') + '"' + nav_plans + '>💎 اشتراک</a>\n'
            + auth_links +
            '      </nav>\n'
            '    </div>\n'
            '  </header>\n')


def flash_html():
    msgs = []
    for cat, msg in get_flashed_messages(with_categories=True):
        ic = '✅' if cat == 'success' else '⚠️'
        msgs.append('<div class="flash ' + e(cat) + '">' + ic + ' ' + e(msg) + '</div>')
    if not msgs:
        return ''
    return ('<div class="flash-wrap">' + ''.join(msgs) + '</div>\n')


def footer_html():
    admin_link = ''
    if session.get('admin'):
        admin_link = ' · <a href="' + url_for('admin_dashboard') + '">⚙️ پنل مدیریت</a>'
    type_links = ' · '.join(
        '<a href="' + url_for('contents_list', type=k) + '">' + e(CONTENT_TYPES[k]['label']) + '</a>'
        for k in CONTENT_ORDER)
    type_links += ' · <a href="' + url_for('plans') + '">💎 اشتراک</a>'
    return ('  <footer class="site-footer">\n'
            '    <div class="container">\n'
            '      <div class="cols">\n'
            '        <div><h5>🎓 ' + e(SITE_NAME) + '</h5>\n'
            '          <p style="max-width:420px; font-size:.85rem;">' + e(SITE_TAGLINE) + '</p></div>\n'
            '        <div><h5>دسترسی سریع</h5>\n'
            '          <p style="font-size:.85rem;">'
            '<a href="' + url_for('index') + '">خانه</a> · '
            '<a href="' + url_for('contents_list') + '">بانک مطالب</a>'
            + admin_link + '</p></div>\n'
            '        <div><h5>نوع مطالب</h5>\n'
            '          <p style="font-size:.85rem;">' + type_links + '</p></div>\n'
            '      </div>\n'
            '      <div class="copy">© ۱۴۰۴ ' + e(SITE_NAME) + ' — ساخته‌شده برای یادگیری بهتر دانش‌آموزان پایهٔ دهم</div>\n'
            '    </div>\n'
            '  </footer>\n')


def section_title(title, sub='', bar_grad=''):
    bar = ('<span class="bar" style="background: ' + bar_grad + ';"></span>') if bar_grad \
        else '<span class="bar"></span>'
    sub_html = ('<p class="sub">' + e(sub) + '</p>') if sub else ''
    return ('<div class="section-title">' + bar +
            '<div><h2>' + e(title) + '</h2>' + sub_html + '</div></div>\n')


def badge_type(key):
    t = CONTENT_TYPES[key]
    return ('<span class="badge-type" style="background:' + t['color'] + ';">' +
            t['icon'] + ' ' + t['label'] + '</span>')


def item_row(item, show_subject=False):
    """ردیف کارتی یک مطلب در صفحات عمومی (بدون تاریخ و ساعت)"""
    item = dict(item)
    t = CONTENT_TYPES[item['content_type']]
    desc = e(item['description'])
    meta_parts = []
    if show_subject:
        meta_parts.append('<a href="' + url_for('subject_page', slug=item['subject_slug']) + '">' +
                          e(item['subject_icon']) + ' ' + e(item['subject_name']) + '</a>')
    meta_parts.append(badge_type(item['content_type']))
    if item.get('source'):
        meta_parts.append('<span>👤 ' + e(item['source']) + '</span>')
    # دانلود فقط با اشتراک فعال (یا مدیر)
    dl = ''
    if item.get('file_path'):
        if can_download():
            dl = ('<a href="' + url_for('media', relpath=item['file_path'], dl=1) + '" '
                  'class="btn btn-outline btn-sm">⬇ دانلود</a>')
        else:
            dl = ('<a href="' + url_for('plans') + '" title="دانلود نیاز به اشتراک فعال دارد" '
                  'class="btn btn-outline btn-sm">🔒 اشتراک</a>')
    btn_label = 'پخش' if item['content_type'] == 'video' else 'مشاهده'
    return ('<div class="item-row">\n'
            '  <div class="item-ic" style="background: ' + t['color'] + '14;">' + t['icon'] + '</div>\n'
            '  <div class="item-body">\n'
            '    <h4><a href="' + url_for('content_view', content_id=item['id']) + '">' + e(item['title']) + '</a></h4>\n'
            '    <p>' + desc + '</p>\n'
            '    <div class="item-meta">' + ''.join(meta_parts) + '</div>\n'
            '  </div>\n'
            '  <div class="item-actions">\n'
            '    <a href="' + url_for('content_view', content_id=item['id']) + '" class="btn btn-primary btn-sm">' + btn_label + '</a>\n'
            + dl + '\n'
            '  </div>\n'
            '</div>\n')


def subject_card(s, counts):
    """کارت درس (در صفحهٔ رشته‌ها)"""
    s = dict(s)
    badges = []
    for key in CONTENT_ORDER:
        cnt = counts.get(s['id'], {}).get(key, 0)
        if cnt > 0:
            t = CONTENT_TYPES[key]
            badges.append('<span class="badge-type" style="background:' + t['color'] + ';">' +
                          t['icon'] + ' ' + t['label'] + ' (' + str(cnt) + ')</span>')
    if not badges:
        badges.append('<span class="count-pill">هنوز مطلبی ندارد</span>')
    tags = '<span class="tag">' + e(s['grade']) + '</span>'
    if s.get('is_common'):
        tags = '<span class="tag common">مشترک همهٔ رشته‌ها</span>' + tags
    return ('<a href="' + url_for('subject_page', slug=s['slug']) + '" class="card subject-card hoverable">\n'
            '  <h3><span>' + e(s['icon']) + '</span> ' + e(s['name']) + '</h3>\n'
            '  <div class="badges">' + ''.join(badges) + '</div>\n'
            '  <div class="tags">' + tags + '</div>\n'
            '</a>\n')


def page_head(icon, title, desc, color, crumbs='', extra=''):
    return ('<section class="page-head" style="background: linear-gradient(135deg, ' +
            color + ', ' + color + 'bb);">\n'
            '  <div class="container">\n'
            '    <div class="page-head-inner">\n'
            '      <div class="big-icon">' + icon + '</div>\n'
            '      <div>\n'
            + (('<div class="crumbs">' + crumbs + '</div>') if crumbs else '') +
            '        <h1>' + e(title) + '</h1>\n'
            '        <p>' + e(desc) + '</p>\n'
            + (extra or '') +
            '      </div>\n'
            '    </div>\n'
            '  </div>\n'
            '</section>\n')


def empty_box(icon, title, text=''):
    return ('<div class="empty"><div class="e-ic">' + icon + '</div>\n'
            '<h4>' + e(title) + '</h4>\n'
            + (('<p>' + e(text) + '</p>') if text else '') + '</div>\n')


# ============================================================================
# صفحات عمومی
# ============================================================================
@app.route('/')
def index():
    db = get_db()
    stats = {
        'fields': db.execute('SELECT COUNT(*) AS c FROM fields').fetchone()['c'],
        'subjects': db.execute('SELECT COUNT(*) AS c FROM subjects').fetchone()['c'],
        'contents': db.execute('SELECT COUNT(*) AS c FROM contents').fetchone()['c'],
        'videos': db.execute("SELECT COUNT(*) AS c FROM contents WHERE content_type='video'").fetchone()['c'],
    }
    fields = db.execute('SELECT * FROM fields ORDER BY sort_order').fetchall()
    field_cards = []
    for f in fields:
        sc = db.execute('SELECT COUNT(*) AS c FROM subject_fields WHERE field_id = ?',
                        (f['id'],)).fetchone()['c']
        cc = db.execute('SELECT COUNT(*) AS c FROM contents c JOIN subject_fields sf '
                        'ON sf.subject_id = c.subject_id WHERE sf.field_id = ?',
                        (f['id'],)).fetchone()['c']
        field_cards.append(
            '<a href="' + url_for('field_page', slug=f['slug']) + '" class="card field-card hoverable">\n'
            '  <div class="field-icon" style="background: linear-gradient(135deg, ' + f['color'] + ', ' +
            f['color'] + 'cc);">' + f['icon'] + '</div>\n'
            '  <h3>' + e(f['name']) + '</h3>\n'
            '  <p>' + e(f['description']) + '</p>\n'
            '  <div class="meta"><span class="mini-stat">📖 ' + str(sc) + ' درس</span>'
            '<span class="mini-stat">📦 ' + str(cc) + ' مطلب</span></div>\n'
            '  <span class="link">مشاهدهٔ درس‌ها ←</span>\n'
            '</a>')

    latest = db.execute(
        'SELECT c.*, s.name AS subject_name, s.slug AS subject_slug, s.icon AS subject_icon '
        'FROM contents c JOIN subjects s ON s.id = c.subject_id ORDER BY c.id DESC LIMIT 6').fetchall()
    latest_html = ''.join(item_row(r, show_subject=True) for r in latest) if latest \
        else empty_box('📭', 'هنوز مطلبی بارگذاری نشده است',
                       'به‌زودی ویدیوها، جزوه‌ها و سوالات درس‌های پایهٔ دهم به این بخش اضافه می‌شوند.')

    feature_cards = ''.join(
        '<a href="' + url_for('contents_list', type=k) + '" class="card feature-card hoverable">'
        '<div class="f-ic">' + CONTENT_TYPES[k]['icon'] + '</div>'
        '<h4>' + CONTENT_TYPES[k]['label'] + '</h4>'
        '<p>مشاهدهٔ همهٔ ' + CONTENT_TYPES[k]['label'] + 'های بارگذاری‌شده</p></a>'
        for k in CONTENT_ORDER)

    content = (
        '<!-- هیرو -->\n<section class="hero">\n<div class="hero-inner">\n'
        '<span class="grade-chip">📚 ' + e(GRADE) + ' — دورهٔ دوم متوسطه</span>\n'
        '<h1>همهٔ مطالب درسی پایهٔ دهم، در یک‌جا</h1>\n'
        '<p class="lead">ویدیوهای آموزشی، جزوه‌ها، گام به گام درس‌ها، نمونه سوالات امتحانی و سوالات کتاب — '
        'ویژهٔ همهٔ رشته‌ها و تمامی درس‌های مشترک و تخصصی.</p>\n'
        '<form class="hero-search" action="' + url_for('search') + '" method="get">\n'
        '<input type="text" name="q" placeholder="جستجو بین مطالب… مثلاً «زیست»، «نمونه سوال ریاضی»">\n'
        '<button type="submit">جستجو 🔍</button>\n</form>\n'
        '<div class="hero-stats">\n'
        '<span class="stat-chip"><b>' + str(stats['fields']) + '</b> رشتهٔ تحصیلی</span>\n'
        '<span class="stat-chip"><b>' + str(stats['subjects']) + '</b> درس</span>\n'
        '<span class="stat-chip"><b>' + str(stats['contents']) + '</b> مطلب آموزشی</span>\n'
        '<span class="stat-chip"><b>' + str(stats['videos']) + '</b> ویدیو</span>\n'
        '</div>\n</div>\n</section>\n'
        '<div class="container">\n'
        '<section class="section">' + section_title('رشته‌های تحصیلی', 'برای هر رشته، درس‌های تخصصی و مشترک را ببینید') +
        '<div class="grid grid-3">' + ''.join(field_cards) + '</div></section>\n'
        '<section class="section">' + section_title('دسته‌بندی مطالب', 'هر نوع مطلب آموزشی را جداگانه مرور کنید',
                                                    'linear-gradient(#0d9488, #0f766e)') +
        '<div class="grid feature-grid">' + feature_cards + '</div></section>\n'
        '<section class="section">' + section_title('جدیدترین مطالب',
                                                    'آخرین ویدیوها، جزوه‌ها و سوالاتی که اضافه شده‌اند',
                                                    'linear-gradient(#e11d48, #be123c)') +
        latest_html + '</section>\n</div>\n')
    return page_base('خانه', content, active='index')


@app.route('/contents')
def contents_list():
    db = get_db()
    q = request.args.get('q', '').strip()
    ctype = request.args.get('type') or ''
    subject_id = request.args.get('subject_id', type=int) or None

    sql = ('SELECT c.*, s.name AS subject_name, s.slug AS subject_slug, s.icon AS subject_icon '
           'FROM contents c JOIN subjects s ON s.id = c.subject_id WHERE 1=1 ')
    params = []
    if ctype in CONTENT_TYPES:
        sql += 'AND c.content_type = ? '
        params.append(ctype)
    if subject_id:
        sql += 'AND c.subject_id = ? '
        params.append(subject_id)
    if q:
        sql += 'AND (c.title LIKE ? OR c.description LIKE ? OR s.name LIKE ?) '
        like = f'%{q}%'
        params += [like, like, like]
    sql += 'ORDER BY c.id DESC LIMIT 200'
    items = db.execute(sql, params).fetchall()
    subjects = db.execute('SELECT id, name FROM subjects ORDER BY name').fetchall()

    sel = {}
    for s in subjects:
        sel[s['id']] = ' selected' if subject_id == s['id'] else ''
    subject_opts = '<option value="">همهٔ درس‌ها</option>' + ''.join(
        '<option value="' + str(s['id']) + '"' + sel[s['id']] + '>' + e(s['name']) + '</option>'
        for s in subjects)

    chips = ['<a href="' + url_for('contents_list', q=q, subject_id=subject_id) + '" class="chip' +
             ('' if ctype else ' chip-active') + '">همه</a>']
    for k in CONTENT_ORDER:
        chips.append('<a href="' + url_for('contents_list', type=k, q=q, subject_id=subject_id) +
                     '" class="chip' + (' chip-active' if ctype == k else '') + '">' +
                     CONTENT_TYPES[k]['icon'] + ' ' + CONTENT_TYPES[k]['label'] + '</a>')

    if items:
        results = ('<p class="muted" style="color:var(--muted); font-size:.85rem;">' +
                   str(len(items)) + ' مطلب یافت شد</p>' +
                   ''.join(item_row(r, show_subject=True) for r in items))
    else:
        results = empty_box('🔎', 'موردی پیدا نشد', 'فیلترها را تغییر دهید یا عبارت دیگری را جستجو کنید.')

    title = ('نتایج جستجو: «' + q + '»') if q else 'بانک مطالب'
    heading = ('نتایج جستجو برای «' + q + '»') if q else 'بانک مطالب'
    content = ('<section class="section" style="padding-top:34px;"><div class="container">' +
               section_title(heading, 'همهٔ ویدیوها، جزوه‌ها، گام به گام‌ها و سوالات در یک لیست') +
               '<form class="card" method="get" action="' + url_for('contents_list') + '" style="padding:16px;">'
               '<div class="flex" style="align-items:stretch;">'
               '<input type="text" name="q" value="' + e(q) + '" class="form-control" '
               'placeholder="جستجو در عنوان یا توضیح مطالب…" style="flex:2; min-width:200px;">'
               '<select name="subject_id" class="form-control" style="flex:1; min-width:150px;">' +
               subject_opts + '</select>'
               '<button type="submit" class="btn btn-primary">فیلتر</button></div>'
               '<div class="chips mt-2">' + ''.join(chips) + '</div></form>'
               '<div class="mt-3">' + results + '</div></div></section>')
    return page_base(title, content, active='contents')


@app.route('/search')
def search():
    return redirect(url_for('contents_list', q=request.args.get('q', '')))


@app.route('/field/<slug>')
def field_page(slug):
    field = get_field(slug)
    if not field:
        abort(404)
    common = field_subjects(field['id'], common_only=1)
    special = field_subjects(field['id'], common_only=0)
    counts = content_counts()

    def grid(rows, title, sub, grad):
        if not rows:
            return ''
        cards = ''.join(subject_card(r, counts) for r in rows)
        return ('<section class="section">' +
                section_title(title, sub, grad) +
                '<div class="grid grid-auto">' + cards + '</div></section>')

    content = (page_head(field['icon'], field['name'], field['description'], field['color'],
                         '<a href="' + url_for('index') + '">خانه</a> ← رشتهٔ ' + e(GRADE),
                         '<div class="flex mt-1">'
                         '<span class="chip" style="background:rgba(255,255,255,.15); '
                         'border-color:rgba(255,255,255,.3); color:#fff;">📖 ' +
                         str(len(common) + len(special)) + ' درس</span>'
                         '<span class="chip" style="background:rgba(255,255,255,.15); '
                         'border-color:rgba(255,255,255,.3); color:#fff;">📦 ' +
                         str(get_db().execute('SELECT COUNT(*) AS c FROM contents c JOIN subject_fields sf '
                                              'ON sf.subject_id = c.subject_id WHERE sf.field_id = ?',
                                              (field['id'],)).fetchone()['c']) +
                         ' مطلب</span></div>') +
               '<div class="container">' +
               grid(special, '⭐ درس‌های تخصصی', 'مخصوص رشتهٔ ' + field['name'], '') +
               grid(common, '🔗 درس‌های مشترک', 'مشترک بین همهٔ رشته‌ها', 'linear-gradient(#0d9488, #0f766e)') +
               '</div>')
    return page_base(field['name'], content)


@app.route('/subject/<slug>')
def subject_page(slug):
    subject = get_subject(slug)
    if not subject:
        abort(404)
    fields_of_subject = subject_fields(subject['id'])
    items = get_db().execute('SELECT * FROM contents WHERE subject_id = ? ORDER BY id DESC',
                             (subject['id'],)).fetchall()

    counts = {}
    for it in items:
        counts[it['content_type']] = counts.get(it['content_type'], 0) + 1

    # تب‌ها
    tabs = []
    panels = []
    for i, key in enumerate(CONTENT_ORDER):
        active_cls = ' active' if i == 0 else ''
        tabs.append('<button class="tab-btn' + active_cls + '" data-tab="' + key + '">' +
                    CONTENT_TYPES[key]['icon'] + ' ' + CONTENT_TYPES[key]['label'] +
                    '<span class="cnt">' + str(counts.get(key, 0)) + '</span></button>')
        type_items = [it for it in items if it['content_type'] == key]
        if type_items:
            rows = []
            for it in type_items:
                t = CONTENT_TYPES[key]
                meta = []
                if it['source']:
                    meta.append('<span>👤 ' + e(it['source']) + '</span>')
                if it['file_path']:
                    meta.append('<span>📎 ' + e(it['file_orig_name'] or 'فایل بارگذاری‌شده') + '</span>')
                elif it['url']:
                    meta.append('<span>⏳ در حال آماده‌سازی</span>')
                dl = ''
                if it['file_path']:
                    if can_download():
                        dl = '<a href="' + url_for('media', relpath=it['file_path'], dl=1) + '" class="btn btn-outline btn-sm">⬇ دانلود</a>'
                    else:
                        dl = '<a href="' + url_for('plans') + '" title="دانلود نیاز به اشتراک فعال دارد" class="btn btn-outline btn-sm">🔒 اشتراک</a>'
                btn = 'پخش' if key == 'video' else 'مشاهده'
                rows.append(
                    '<div class="item-row">'
                    '<div class="item-ic" style="background: ' + t['color'] + '14;">' + t['icon'] + '</div>'
                    '<div class="item-body">'
                    '<h4><a href="' + url_for('content_view', content_id=it['id']) + '">' + e(it['title']) + '</a></h4>'
                    '<p>' + e(it['description']) + '</p>'
                    '<div class="item-meta">' + ''.join(meta) + '</div></div>'
                    '<div class="item-actions">'
                    '<a href="' + url_for('content_view', content_id=it['id']) + '" class="btn btn-primary btn-sm">' + btn + '</a>'
                    + dl + '</div></div>')
            panel_body = ''.join(rows)
        else:
            panel_body = empty_box(CONTENT_TYPES[key]['icon'],
                                   'هنوز ' + CONTENT_TYPES[key]['label'] + ' برای این درس بارگذاری نشده است',
                                   'به‌زودی به این بخش اضافه می‌شود.')
        panels.append('<div class="tab-panel' + active_cls + '" data-panel="' + key + '">' +
                      panel_body + '</div>')

    field_chips = ''.join(
        '<a href="' + url_for('field_page', slug=f['slug']) + '" class="chip" '
        'style="background:rgba(255,255,255,.15); border-color:rgba(255,255,255,.3); color:#fff;">' +
        f['icon'] + ' ' + e(f['name']) + '</a>' for f in fields_of_subject)

    desc = subject['description'] or ('ویدیو، جزوه، گام به گام و نمونه سوال درس ' + subject['name'])
    content = (page_head(subject['icon'], subject['name'], desc, subject['color'],
                         '<a href="' + url_for('index') + '">خانه</a> ← ' + e(GRADE),
                         '<div class="flex mt-1">' + field_chips + '</div>') +
               '<div class="container">'
               '<div class="tabs" role="tablist">' + ''.join(tabs) + '</div>'
               + ''.join(panels) +
               '<div class="flex mt-3"><a href="' + url_for('contents_list') +
               '" class="btn btn-outline">→ بازگشت به بانک مطالب</a></div>'
               '</div>')
    return page_base(subject['name'], content)


def yt_progress_script(content_id):
    js = ("<script>\n(function(){var p=document.getElementById('yt-progress');if(!p)return;"
          "var t=setInterval(function(){fetch('@@P@@/content/@@CID@@/yt-status')"
          ".then(function(r){return r.json();})"
          ".then(function(j){if(j.status==='done'||j.status==='error'){clearInterval(t);location.reload();}"
          "else{p.textContent=j.progress||'…';}}).catch(function(){});},2000);})();\n</script>")
    return js.replace('@@P@@', ADMIN_PREFIX).replace('@@CID@@', str(content_id))


@app.route('/content/<int:content_id>')
def content_view(content_id):
    item = get_db().execute(
        'SELECT c.*, s.name AS subject_name, s.slug AS subject_slug, s.icon AS subject_icon '
        'FROM contents c JOIN subjects s ON s.id = c.subject_id WHERE c.id = ?',
        (content_id,)).fetchone()
    if not item:
        abort(404)
    job = get_latest_job(content_id) if not item['file_path'] else None
    yt = youtube_embed(item['url']) if item['url'] else None
    t = CONTENT_TYPES[item['content_type']]

    # --- بدنهٔ نمایش محتوا ---
    if item['content_type'] == 'video' and item['file_path']:
        viewer = ('<div class="viewer-box">'
                  '<video controls controlsList="nodownload" preload="metadata" poster="">'
                  '<source src="' + url_for('media', relpath=item['file_path']) + '" type="' + e(item['mime']) + '">'
                  'مرورگر شما از پخش ویدیو پشتیبانی نمی‌کند.</video></div>'
                  '<p style="font-size:.8rem; color:var(--muted); text-align:center;">🎬 ویدیو برای همه پخش می‌شود؛ '
                  'دانلود نیاز به اشتراک فعال دارد.</p>')
    elif item['url'] and job and job['status'] in ('queued', 'running'):
        viewer = (empty_box('⏳', 'مطلب در حال آماده‌سازی است…',
                            'سرور در حال دریافت فایل است؛ به‌محض آماده شدن، همین‌جا نمایش داده می‌شود.') +
                  '<p style="font-size:1.4rem; font-weight:800; color:var(--primary-600); text-align:center;" '
                  'id="yt-progress">' + e(job.get('progress') or '1%') + '</p>' +
                  yt_progress_script(content_id))
    elif item['content_type'] == 'video' and yt:
        body = '<h4>این ویدیو به‌زودی در دسترس قرار می‌گیرد</h4>'
        if job and job['status'] == 'error':
            body += '<p style="color:#b42318;">خطا در دریافت: ' + e(job.get('error')) + '</p>'
        admin_row = ''
        if session.get('admin'):
            admin_row = ('<div class="flex" style="justify-content:center; margin-top:10px;">'
                         '<a href="' + e(item['url']) + '" target="_blank" rel="noopener" '
                         'class="btn btn-outline btn-sm">🔗 لینک منبع</a>'
                         '<form method="post" action="' + url_for('admin_content_fetch_youtube', cid=content_id) + '">'
                         '<button type="submit" class="btn btn-accent btn-sm">⬇ دریافت و ذخیره از لینک</button>'
                         '</form></div>')
        viewer = '<div class="empty"><div class="e-ic">🎬</div>' + body + admin_row + '</div>'
    elif item['content_type'] != 'video' and item['file_path'] and (
            item['mime'] == 'application/pdf' or item['file_path'].endswith('.pdf')):
        viewer = ('<div class="file-embed"><iframe src="' + url_for('media', relpath=item['file_path']) +
                  '" title="' + e(item['title']) + '"></iframe></div>')
    elif item['file_path']:
        if can_download():
            viewer = (empty_box('📁', 'فایل بارگذاری‌شده', 'این فایل را دانلود کنید: ' + e(item['file_orig_name'])) +
                      '<div style="text-align:center; margin-top:12px;"><a href="' +
                      url_for('media', relpath=item['file_path'], dl=1) +
                      '" class="btn btn-primary">⬇ دانلود ' + e(item['file_orig_name']) + '</a></div>')
        else:
            viewer = (empty_box('🔒', 'دانلود نیاز به اشتراک فعال دارد',
                                'این فایل برای اعضای دارای اشتراک قابل دانلود است.') +
                      '<div style="text-align:center; margin-top:12px;"><a href="' +
                      url_for('plans') + '" class="btn btn-accent">💎 مشاهدهٔ پلن‌های اشتراک</a></div>')
    elif item['url']:
        body = '<h4>این مطلب به‌زودی در دسترس قرار می‌گیرد</h4>'
        if job and job['status'] == 'error':
            body += '<p style="color:#b42318;">دریافت فایل ناموفق بود؛ دوباره تلاش می‌شود.</p>'
        else:
            body += '<p>لطفاً کمی بعد دوباره مراجعه کنید.</p>'
        admin_row = ''
        if session.get('admin'):
            admin_row = ('<div class="flex" style="justify-content:center; margin-top:10px;">'
                         '<a href="' + e(item['url']) + '" target="_blank" rel="noopener" '
                         'class="btn btn-outline btn-sm">🔗 لینک منبع</a>'
                         '<form method="post" action="' + url_for('admin_content_fetch_youtube', cid=content_id) + '">'
                         '<button type="submit" class="btn btn-accent btn-sm">⬇ دریافت و ذخیره از لینک</button>'
                         '</form></div>')
        viewer = '<div class="empty"><div class="e-ic">📦</div>' + body + admin_row + '</div>'
    else:
        viewer = empty_box('📦', 'مطلبی یافت نشد')

    dl_btn = ''
    if item['file_path']:
        if can_download():
            dl_btn = ('<a href="' + url_for('media', relpath=item['file_path'], dl=1) +
                      '" class="btn btn-accent">⬇ دانلود فایل</a>')
        else:
            dl_btn = ('<a href="' + url_for('plans') + '" class="btn btn-accent">🔒 دانلود با اشتراک</a>')

    meta = [badge_type(item['content_type'])]
    if item['source']:
        meta.append('<span>👤 ' + e(item['source']) + '</span>')
    meta.append('<span>📚 ' + e(item['subject_icon']) + ' ' + e(item['subject_name']) + '</span>')

    crumbs = ('<a href="' + url_for('index') + '">خانه</a> ← '
              '<a href="' + url_for('subject_page', slug=item['subject_slug']) + '">' +
              e(item['subject_icon']) + ' ' + e(item['subject_name']) + '</a> ← ' + t['label'])

    desc_p = ('<p class="mt-2" style="color:#475467;">' + e(item['description']) + '</p>') \
        if item['description'] else ''

    content = ('<section class="section" style="padding-top:34px;">'
               '<div class="container" style="max-width:1000px;">'
               '<div class="crumbs mb-2" style="color:var(--muted); font-size:.82rem;">' + crumbs + '</div>'
               '<div class="side-card">'
               '<div class="flex between" style="align-items:flex-start;">'
               '<div><h1 style="font-size:1.35rem; font-weight:900;">' + e(item['title']) + '</h1>'
               '<div class="item-meta">' + ''.join(meta) + '</div></div>'
               '<div class="item-actions">' + dl_btn + '</div></div>'
               + desc_p + '</div>'
               '<div class="mt-3">' + viewer + '</div>'
               '<div class="flex mt-3"><a href="' + url_for('subject_page', slug=item['subject_slug']) +
               '" class="btn btn-outline">→ بازگشت به درس ' + e(item['subject_name']) + '</a></div>'
               '</div></section>')
    return page_base(item['title'], content)


@app.route('/media/<path:relpath>')
def media(relpath):
    relpath = os.path.normpath(relpath)
    if relpath.startswith('..') or os.path.isabs(relpath):
        abort(404)
    full = os.path.join(UPLOAD_DIR, relpath)
    if not os.path.isfile(full):
        abort(404)

    if request.args.get('dl') == '1':
        # دانلود فقط برای مدیر یا دانش‌آموز با اشتراک فعال
        if not can_download():
            return redirect(url_for('plans', next='dl'))
        row = get_db().execute('SELECT file_orig_name FROM contents WHERE file_path = ?',
                               (relpath,)).fetchone()
        name = (row['file_orig_name'] if row and row['file_orig_name'] else os.path.basename(full))
        return send_file(full, as_attachment=True, download_name=name)

    mimetype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
    size = os.path.getsize(full)
    rng = request.headers.get('Range')
    if rng:
        m = re.match(r'bytes=(\d*)-(\d*)$', rng)
        if m:
            start_s, end_s = m.groups()
            if start_s == '' and end_s != '':
                start = max(0, size - int(end_s))
                end = size - 1
            else:
                start = int(start_s or 0)
                end = int(end_s) if end_s else size - 1
            end = min(end, size - 1)
            if start > end or start >= size:
                abort(416)
            length = end - start + 1

            def gen():
                with open(full, 'rb') as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(256 * 1024, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk

            resp = Response(gen(), status=206, mimetype=mimetype, direct_passthrough=True)
            resp.headers['Content-Range'] = f'bytes {start}-{end}/{size}'
            resp.headers['Accept-Ranges'] = 'bytes'
            resp.headers['Content-Length'] = str(length)
            resp.headers['Cache-Control'] = 'no-cache'
            return resp
    resp = send_file(full, mimetype=mimetype, conditional=True)
    resp.headers['Accept-Ranges'] = 'bytes'
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.errorhandler(404)
def not_found(e):
    content = ('<section class="section" style="padding-top:60px;">'
               '<div class="container" style="max-width:560px;">'
               + empty_box('🧭', 'صفحهٔ مورد نظر پیدا نشد!', 'آدرس اشتباه است یا این صفحه حذف شده است.') +
               '<div style="text-align:center; margin-top:14px;"><a href="' + url_for('index') +
               '" class="btn btn-primary">بازگشت به خانه</a></div>'
               '</div></section>')
    return page_base('صفحه پیدا نشد', content), 404


# ============================================================================
# دانش‌آموز: ثبت‌نام، ورود، حساب
# ============================================================================
def student_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login_student', next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def auth_form(title, action, fields_html, submit_label, alt_html=''):
    content = ('<section class="section" style="padding-top:44px;">'
               '<div class="container" style="max-width:430px;">'
               '<div class="card side-card">'
               '<div style="text-align:center; margin-bottom:18px;">'
               '<div class="field-icon" style="margin:0 auto 12px; background: linear-gradient(135deg, #4f46e5, #0d9488);">🎓</div>'
               '<h1 style="font-size:1.25rem;">' + e(title) + '</h1></div>'
               '<form method="post" action="' + e(action) + '">' + fields_html +
               '<button type="submit" class="btn btn-primary btn-block">' + e(submit_label) + '</button>'
               '</form>' + alt_html + '</div></div></section>')
    return page_base(title, content)


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if session.get('user_id'):
        return redirect(url_for('account'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        pw = request.form.get('password', '')
        pw2 = request.form.get('password2', '')
        if not name or not email or '@' not in email:
            flash('نام و ایمیل معتبر وارد کنید.', 'error')
        elif len(pw) < 4:
            flash('رمز عبور باید حداقل ۴ کاراکتر باشد.', 'error')
        elif pw != pw2:
            flash('رمز عبور و تکرار آن یکی نیستند.', 'error')
        else:
            db = get_db()
            if db.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone():
                flash('این ایمیل قبلاً ثبت شده است. وارد شوید.', 'error')
            else:
                from werkzeug.security import generate_password_hash
                cur = db.execute('INSERT INTO users (name, email, password_hash) VALUES (?,?,?)',
                                 (name, email, generate_password_hash(pw)))
                db.commit()
                session['user_id'] = cur.lastrowid
                flash('ثبت‌نام موفق بود. خوش آمدید! 🎉', 'success')
                return redirect(url_for('account'))
    fields = ('<div class="form-group"><label>نام و نام خانوادگی</label>'
              '<input type="text" name="name" class="form-control" required autofocus></div>'
              '<div class="form-group"><label>ایمیل</label>'
              '<input type="email" name="email" class="form-control" dir="ltr" style="text-align:left;" required></div>'
              '<div class="form-group"><label>رمز عبور (حداقل ۴ کاراکتر)</label>'
              '<input type="password" name="password" class="form-control" required></div>'
              '<div class="form-group"><label>تکرار رمز عبور</label>'
              '<input type="password" name="password2" class="form-control" required></div>')
    alt = '<p style="text-align:center; font-size:.85rem; margin-top:14px; color:var(--muted);">' \
          'حساب دارید؟ <a href="' + url_for('login_student') + '">ورود</a></p>'
    return auth_form('ثبت‌نام دانش‌آموز', url_for('signup'), fields, 'ثبت‌نام', alt)


@app.route('/login', methods=['GET', 'POST'])
def login_student():
    if session.get('user_id'):
        return redirect(url_for('account'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        pw = request.form.get('password', '')
        from werkzeug.security import check_password_hash
        row = get_db().execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        if row and check_password_hash(row['password_hash'], pw):
            session['user_id'] = row['id']
            flash('خوش آمدید! 👋', 'success')
            nxt = request.args.get('next')
            if nxt and nxt.startswith('/') and not nxt.startswith('//'):
                return redirect(nxt)
            return redirect(url_for('account'))
        flash('ایمیل یا رمز عبور اشتباه است.', 'error')
    fields = ('<div class="form-group"><label>ایمیل</label>'
              '<input type="email" name="email" class="form-control" dir="ltr" style="text-align:left;" required autofocus></div>'
              '<div class="form-group"><label>رمز عبور</label>'
              '<input type="password" name="password" class="form-control" required></div>')
    alt = '<p style="text-align:center; font-size:.85rem; margin-top:14px; color:var(--muted);">' \
          'حساب ندارید؟ <a href="' + url_for('signup') + '">ثبت‌نام</a></p>'
    return auth_form('ورود دانش‌آموز', url_for('login_student', next=request.args.get('next', '')),
                     fields, 'ورود', alt)


@app.route('/logout')
def logout_student():
    session.pop('user_id', None)
    flash('از حساب خارج شدید.', 'success')
    return redirect(url_for('index'))


@app.route('/account')
@student_required
def account():
    u = current_user()
    end = sub_end_dt(u)
    active = has_active_sub(u)
    if active and end:
        status_html = ('<div class="card" style="border-color:#a7f3d0; background:#ecfdf5;">'
                       '<h3>✅ اشتراک شما فعال است</h3>'
                       '<p style="color:#065f46;">تاریخ پایان اشتراک: <b>' + e(fa_date(end.strftime('%Y-%m-%d %H:%M:%S'))) + '</b></p>'
                       '<a href="' + url_for('plans') + '" class="btn btn-outline btn-sm">تمدید اشتراک</a></div>')
    else:
        status_html = ('<div class="card" style="border-color:#fde68a; background:#fffbeb;">'
                       '<h3>⚠️ اشتراک شما فعال نیست</h3>'
                       '<p style="color:#92400e;">برای دانلود فایل‌ها، یکی از پلن‌های اشتراک را فعال کنید.</p>'
                       '<a href="' + url_for('plans') + '" class="btn btn-accent btn-sm">💎 خرید اشتراک</a></div>')
    recent = get_db().execute(
        'SELECT * FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 5',
        (u['id'],)).fetchall()
    status_map = {'pending': 'در انتظار پرداخت', 'success': 'موفق', 'failed': 'ناموفق'}
    rows = ''.join(
        '<tr><td>' + e(tr['id']) + '</td><td>' + e(fa_date(tr['created_at'])) + '</td>'
        '<td>' + e(plan_name(tr['plan_id'])) + '</td>'
        '<td>' + str(tr['amount']) + ' تومان</td>'
        '<td><span class="badge-type" style="background:' + ('#059669' if tr['status'] == 'success' else '#d97706' if tr['status'] == 'pending' else '#e11d48') + ';">' +
        status_map.get(tr['status'], tr['status']) + '</span></td></tr>'
        for tr in recent) or '<tr><td colspan="5" style="text-align:center; color:var(--muted);">تراکنشی ندارید</td></tr>'
    content = ('<section class="section" style="padding-top:34px;"><div class="container" style="max-width:860px;">'
               '<div class="crumbs mb-2" style="color:var(--muted); font-size:.82rem;">'
               '<a href="' + url_for('index') + '">خانه</a> ← حساب من</div>'
               '<h1 style="font-size:1.4rem; font-weight:900; margin-bottom:16px;">👤 حساب من — ' + e(u['name']) + '</h1>'
               + status_html +
               '<div class="section-title" style="margin-top:26px;"><span class="bar"></span>'
               '<div><h2>تراکنش‌های اخیر</h2></div></div>'
               '<div class="table-wrap"><table class="table"><thead><tr>'
               '<th>شماره</th><th>تاریخ</th><th>پلن</th><th>مبلغ</th><th>وضعیت</th></tr></thead>'
               '<tbody>' + rows + '</tbody></table></div>'
               '<div class="flex mt-3"><a href="' + url_for('plans') + '" class="btn btn-accent">💎 مشاهدهٔ پلن‌ها</a>'
               '<a href="' + url_for('logout_student') + '" class="btn btn-outline">خروج</a></div>'
               '</div></section>')
    return page_base('حساب من', content)


def plan_name(plan_id):
    row = get_db().execute('SELECT name FROM plans WHERE id = ?', (plan_id,)).fetchone()
    return row['name'] if row else ('پلن ' + str(plan_id))


# ============================================================================
# اشتراک و پرداخت زرین‌پال
# ============================================================================
@app.route('/plans')
def plans():
    active_tab = 'plans'
    db = get_db()
    plans_rows = db.execute('SELECT * FROM plans WHERE active = 1 ORDER BY months').fetchall()
    if not plans_rows:
        content = ('<section class="section" style="padding-top:44px;"><div class="container" style="max-width:760px;">'
                   + empty_box('💎', 'هنوز پلنی ثبت نشده است', 'به‌زودی پلن‌های اشتراک اضافه می‌شوند.') +
                   '</div></section>')
        return page_base('اشتراک', content, active=active_tab)

    cards = []
    for p in plans_rows:
        final = plan_final_price(p)
        disc = ''
        if p['discount_percent'] > 0:
            disc = ('<div class="badge-type" style="background:#e11d48; margin-bottom:8px;">'
                    + str(p['discount_percent']) + '٪ تخفیف</div>')
        old = ('<span style="text-decoration:line-through; color:var(--muted); font-size:.85rem;">'
               + str(p['price']) + ' تومان</span> ') if p['discount_percent'] > 0 else ''
        btn = ('<a href="' + url_for('buy_plan', plan_id=p['id']) + '" class="btn btn-primary btn-block">'
               'خرید و فعال‌سازی</a>') if session.get('user_id') else \
              ('<a href="' + url_for('login_student', next=url_for('buy_plan', plan_id=p['id'])) +
               '" class="btn btn-primary btn-block">برای خرید وارد شوید</a>')
        cards.append(
            '<div class="card field-card" style="text-align:center;">' + disc +
            '<div class="field-icon" style="margin:0 auto 12px; background:linear-gradient(135deg,#4338ca,#0d9488);">💎</div>'
            '<h3>' + e(p['name']) + '</h3>'
            '<p><b style="font-size:1.15rem;">' + e(p['months']) + '</b> ماه</p>'
            '<p style="font-size:1.3rem; font-weight:900; color:var(--primary-700);">' + old +
            '<span>' + str(final) + '</span> تومان</p>'
            '<p style="font-size:.8rem; color:var(--muted);">پرداخت امن با زرین‌پال</p>' + btn + '</div>')

    u = current_user()
    note = ''
    if u and has_active_sub(u):
        note = '<div class="card" style="border-color:#a7f3d0; background:#ecfdf5; margin-bottom:20px;">' \
               '✅ اشتراک شما فعال است. <a href="' + url_for('account') + '">مشاهدهٔ حساب</a></div>'

    content = ('<section class="section" style="padding-top:34px;"><div class="container">'
               '<div class="section-title"><span class="bar"></span>'
               '<div><h2>💎 پلن‌های اشتراک</h2>'
               '<p class="sub">با فعال‌سازی اشتراک، دانلود همهٔ جزوه‌ها و ویدیوها برایتان باز می‌شود</p></div></div>'
               + note +
               '<div class="grid grid-3">' + ''.join(cards) + '</div>'
               '<p style="text-align:center; color:var(--muted); font-size:.8rem; margin-top:22px;">'
               'درگاه پرداخت امن زرین‌پال — بعد از پرداخت، اشتراک به‌صورت خودکار فعال می‌شود.</p>'
               '</div></section>')
    return page_base('اشتراک', content, active=active_tab)


@app.route('/buy/<int:plan_id>')
@student_required
def buy_plan(plan_id):
    if not ZARINPAL_MERCHANT_ID:
        flash('درگاه پرداخت هنوز راه‌اندازی نشده است (MERCHANT_ID تنظیم نشده).', 'error')
        return redirect(url_for('plans'))
    p = get_db().execute('SELECT * FROM plans WHERE id = ? AND active = 1', (plan_id,)).fetchone()
    if not p:
        abort(404)
    p = dict(p)
    u = current_user()
    amount = plan_final_price(p)  # تومان
    # ساخت تراکنش pending
    cur = get_db().execute(
        'INSERT INTO transactions (user_id, plan_id, amount, status) VALUES (?,?,?,?)',
        (u['id'], p['id'], amount, 'pending'))
    get_db().commit()
    tx_id = cur.lastrowid

    callback_url = url_for('zp_callback', _external=True)
    payload = {
        'merchant_id': ZARINPAL_MERCHANT_ID,
        'amount': amount * 10,  # زرین‌پال به ریال نیاز دارد
        'callback_url': callback_url,
        'description': 'خرید اشتراک ' + p['name'] + ' — ' + SITE_NAME,
    }
    try:
        result = zp_post(ZP_REQUEST_URL, payload)
        data = result.get('data') or {}
        if data.get('code') == 100 and data.get('authority'):
            authority = data['authority']
            get_db().execute('UPDATE transactions SET authority = ? WHERE id = ?', (authority, tx_id))
            get_db().commit()
            return redirect(ZP_STARTPAY_URL + authority)
        flash('خطا در شروع پرداخت (کد: ' + str(data.get('code', '?')) + '). دوباره تلاش کنید.', 'error')
    except Exception as exc:
        get_db().execute("UPDATE transactions SET status='failed' WHERE id = ?", (tx_id,))
        get_db().commit()
        flash('اتصال به درگاه پرداخت ممکن نشد: ' + str(exc)[:120], 'error')
    return redirect(url_for('plans'))


@app.route('/payment/callback')
def zp_callback():
    authority = request.args.get('Authority', '')
    status = request.args.get('Status', '')
    tx = get_db().execute(
        'SELECT * FROM transactions WHERE authority = ? ORDER BY id DESC LIMIT 1',
        (authority,)).fetchone()
    if not tx:
        return page_base('پرداخت', empty_box('❌', 'تراکنش یافت نشد.'))
    tx = dict(tx)
    ok = status == 'OK' and ZARINPAL_MERCHANT_ID
    ref_id = ''
    if ok:
        payload = {
            'merchant_id': ZARINPAL_MERCHANT_ID,
            'amount': tx['amount'] * 10,
            'authority': authority,
        }
        try:
            result = zp_post(ZP_VERIFY_URL, payload)
            data = result.get('data') or {}
            if data.get('code') in (100, 101):
                ref_id = str(data.get('ref_id', ''))
                ok = True
            else:
                ok = False
        except Exception:
            ok = False

    if ok:
        # فعال‌سازی اشتراک: از امروز یا ادامهٔ اشتراک قبلی + مدت پلن
        u = get_db().execute('SELECT * FROM users WHERE id = ?', (tx['user_id'],)).fetchone()
        u = dict(u)
        base = sub_end_dt(u) or datetime.now()
        base = base if base > datetime.now() else datetime.now()
        new_end = add_months(base, get_db().execute(
            'SELECT months FROM plans WHERE id = ?', (tx['plan_id'],)).fetchone()['months'])
        get_db().execute("UPDATE users SET sub_end = ? WHERE id = ?",
                         (new_end.strftime('%Y-%m-%d %H:%M:%S'), tx['user_id']))
        get_db().execute("UPDATE transactions SET status='success', ref_id=?, paid_at=datetime('now','localtime') "
                         "WHERE id = ?", (ref_id, tx['id']))
        get_db().commit()
        session['user_id'] = tx['user_id']  # اگر هنوز وارد نشده بود
        content = ('<section class="section" style="padding-top:44px;"><div class="container" style="max-width:560px;">'
                   '<div class="card" style="border-color:#a7f3d0; background:#ecfdf5; text-align:center; padding:32px;">'
                   '<div style="font-size:3rem;">🎉</div>'
                   '<h2>پرداخت موفق بود!</h2>'
                   '<p>اشتراک شما فعال شد. کد پیگیری: <b>' + e(ref_id) + '</b></p>'
                   '<p style="color:#065f46;">مبلغ: ' + str(tx['amount']) + ' تومان</p>'
                   '<a href="' + url_for('account') + '" class="btn btn-primary mt-2">مشاهدهٔ حساب من</a></div>'
                   '</div></section>')
        return page_base('پرداخت موفق', content)
    # ناموفق
    get_db().execute("UPDATE transactions SET status='failed' WHERE id = ?", (tx['id'],))
    get_db().commit()
    content = ('<section class="section" style="padding-top:44px;"><div class="container" style="max-width:560px;">'
               '<div class="card" style="border-color:#fecaca; background:#fef2f2; text-align:center; padding:32px;">'
               '<div style="font-size:3rem;">😔</div>'
               '<h2>پرداخت ناموفق بود</h2>'
               '<p style="color:#b42318;">پرداخت شما تکمیل نشد. می‌توانید دوباره تلاش کنید.</p>'
               '<a href="' + url_for('plans') + '" class="btn btn-primary mt-2">بازگشت به پلن‌ها</a></div>'
               '</div></section>')
    return page_base('پرداخت ناموفق', content)


# ============================================================================
# پنل مدیریت
# ============================================================================
def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('admin'):
            return redirect(url_for('admin_login', next=request.path))
        return fn(*args, **kwargs)
    return wrapper


@app.route(ADMIN_PREFIX + '/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if check_admin_password(request.form.get('password', '')):
            session['admin'] = True
            flash('خوش آمدید! وارد پنل مدیریت شدید.', 'success')
            nxt = request.args.get('next') or url_for('admin_dashboard')
            if nxt.startswith('/') and not nxt.startswith('//'):
                return redirect(nxt)
            return redirect(url_for('admin_dashboard'))
        flash('رمز عبور اشتباه است.', 'error')
    content = ('<section class="section" style="padding-top:60px;">'
               '<div class="container" style="max-width:420px;">'
               '<div class="card side-card">'
               '<div style="text-align:center; margin-bottom:18px;">'
               '<div class="field-icon" style="margin:0 auto 12px; background: linear-gradient(135deg, #4f46e5, #7c3aed);">🔐</div>'
               '<h1 style="font-size:1.25rem;">ورود به پنل مدیریت</h1>'
               '<p style="color:var(--muted); font-size:.85rem;">برای بارگذاری ویدیو، جزوه و سوالات وارد شوید</p>'
               '</div>'
               '<form method="post" action="' + url_for('admin_login', next=request.args.get('next', '')) + '">'
               '<div class="form-group"><label for="password">رمز عبور</label>'
               '<input type="password" id="password" name="password" class="form-control" '
               'placeholder="رمز عبور را وارد کنید" autofocus required></div>'
               '<button type="submit" class="btn btn-primary btn-block">ورود</button>'
               '</form></div></div></section>')
    return page_base('ورود مدیریت', content)


@app.route(ADMIN_PREFIX + '/logout')
def admin_logout():
    session.pop('admin', None)
    flash('از پنل مدیریت خارج شدید.', 'success')
    return redirect(url_for('index'))


@app.route(ADMIN_PREFIX + '/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    if request.method == 'POST':
        current = request.form.get('current', '')
        new = request.form.get('new', '')
        confirm = request.form.get('confirm', '')
        if not check_admin_password(current):
            flash('رمز عبور فعلی اشتباه است.', 'error')
        elif len(new) < 4:
            flash('رمز جدید باید حداقل ۴ کاراکتر باشد.', 'error')
        elif new != confirm:
            flash('رمز جدید و تکرار آن با هم یکی نیستند.', 'error')
        else:
            from werkzeug.security import generate_password_hash
            set_setting('admin_password', generate_password_hash(new))
            flash('رمز عبور با موفقیت تغییر کرد ✅ — از این پس با رمز جدید وارد شوید.', 'success')
        return redirect(url_for('admin_settings'))
    content = ('<section class="section" style="padding-top:34px;">'
               '<div class="container" style="max-width:480px;">'
               '<div class="crumbs mb-2" style="color:var(--muted); font-size:.82rem;">'
               '<a href="' + url_for('admin_dashboard') + '">پنل مدیریت</a> ← تغییر رمز</div>'
               '<form class="card side-card" method="post" action="' + url_for('admin_settings') + '">'
               '<h3 style="font-size:1.1rem; margin-bottom:6px;">🔑 تغییر رمز عبور</h3>'
               '<p style="color:var(--muted); font-size:.85rem;">رمز جدید بعد از ذخیره، از همین لحظه معتبر است.</p>'
               '<div class="form-group mt-2"><label>رمز عبور فعلی</label>'
               '<input type="password" name="current" class="form-control" required autofocus></div>'
               '<div class="form-group"><label>رمز جدید (حداقل ۴ کاراکتر)</label>'
               '<input type="password" name="new" class="form-control" required></div>'
               '<div class="form-group"><label>تکرار رمز جدید</label>'
               '<input type="password" name="confirm" class="form-control" required></div>'
               '<button type="submit" class="btn btn-primary btn-block">ذخیرهٔ رمز جدید</button>'
               '</form>'
               '<div class="card mt-2" style="background:#fffbeb; border-color:#fde68a;">'
               '<p style="font-size:.82rem; color:#92400e; margin:0;">💡 اگر رمز را فراموش کردید: '
               'فایل <code>app.py</code> را باز کنید و مقدار پیش‌فرض رمز را عوض کنید؛ سپس سایت را دوباره اجرا کنید.</p>'
               '</div></div></section>')
    return page_base('تغییر رمز عبور', content)


@app.route(ADMIN_PREFIX + '')
@admin_required
def admin_dashboard():
    db = get_db()
    stats = {
        'fields': db.execute('SELECT COUNT(*) AS c FROM fields').fetchone()['c'],
        'subjects': db.execute('SELECT COUNT(*) AS c FROM subjects').fetchone()['c'],
        'contents': db.execute('SELECT COUNT(*) AS c FROM contents').fetchone()['c'],
    }
    by_type = {t: db.execute('SELECT COUNT(*) AS c FROM contents WHERE content_type = ?',
                             (t,)).fetchone()['c'] for t in CONTENT_TYPES}
    recent = db.execute(
        'SELECT c.*, s.name AS subject_name FROM contents c JOIN subjects s ON s.id = c.subject_id '
        'ORDER BY c.id DESC LIMIT 8').fetchall()

    stat_cards = [
        ('🎓', '#4338ca', stats['fields'], 'رشته'),
        ('📚', '#0d9488', stats['subjects'], 'درس'),
        ('📦', '#d97706', stats['contents'], 'مطلب'),
        ('🎬', '#e11d48', by_type['video'], 'ویدیو'),
        ('📄', '#2563eb', by_type['note'] + by_type['solution'] + by_type['exam'] + by_type['textbook'], 'جزوه و سوال'),
    ]
    stats_html = ''.join(
        '<div class="admin-stat"><div class="ic" style="background:linear-gradient(135deg,' + c + ',' + c + ');">' + ic +
        '</div><div><b>' + str(n) + '</b><span>' + lbl + '</span></div></div>'
        for ic, c, n, lbl in stat_cards)

    quick = [
        ('➕', '#e11d48', url_for('admin_content_new'), 'بارگذاری مطلب جدید',
         'ویدیو، جزوه، گام به گام، نمونه سوال یا سوالات کتاب را برای یک درس آپلود کنید.'),
        ('🗂️', '#4338ca', url_for('admin_contents'), 'مدیریت مطالب',
         'مشاهدهٔ همهٔ مطالب، ویرایش یا حذف موارد تکراری.'),
        ('🏷️', '#0d9488', url_for('admin_fields'), 'رشته‌ها و درس‌ها',
         'افزودن رشته یا درس جدید و تعیین درس‌های مشترک و تخصصی.'),
        ('💎', '#7c3aed', url_for('admin_plans'), 'پلن‌های اشتراک',
         'تعیین نام، مدت، قیمت و تخفیف پلن‌های اشتراک.'),
        ('🧾', '#059669', url_for('admin_transactions'), 'خریداران و تراکنش‌ها',
         'مشاهدهٔ پرداخت‌ها، خریداران و کد پیگیری.'),
        ('🔑', '#d97706', url_for('admin_settings'), 'تغییر رمز عبور',
         'رمز ورود به پنل مدیریت را از همین‌جا عوض کنید.'),
    ]
    quick_html = ''.join(
        '<a href="' + u + '" class="card field-card hoverable">'
        '<div class="field-icon" style="background:linear-gradient(135deg,' + c + ',' + c + ');">' + ic + '</div>'
        '<h3>' + t_ + '</h3><p>' + d_ + '</p></a>' for ic, c, u, t_, d_ in quick)

    recent_rows = ''.join(
        '<tr><td><a href="' + url_for('content_view', content_id=r['id']) + '">' + e(r['title']) + '</a></td>'
        '<td>' + e(r['subject_name']) + '</td>'
        '<td>' + badge_type(r['content_type']) + '</td>'
        '<td style="white-space:nowrap;">' + e(fa_date(r['added_at'])) + '</td>'
        '<td><a href="' + url_for('content_view', content_id=r['id']) + '" class="btn btn-outline btn-sm">باز</a></td></tr>'
        for r in recent)

    content = ('<section class="section" style="padding-top:34px;"><div class="container">'
               '<div class="flex between mb-2">'
               '<div class="section-title" style="margin:0;"><span class="bar"></span>'
               '<div><h2>⚙️ پنل مدیریت</h2><p class="sub">مدیریت رشته‌ها، درس‌ها و مطالب آموزشی</p></div></div>'
               '<a href="' + url_for('index') + '" class="btn btn-outline btn-sm">مشاهدهٔ سایت ←</a></div>'
               '<div class="admin-stat-grid">' + stats_html + '</div>'
               '<div class="grid grid-4 mb-2">' + quick_html + '</div>'
               '<div class="section-title" style="margin-top:26px;"><span class="bar" '
               'style="background:linear-gradient(#7c3aed,#a855f7);"></span>'
               '<div><h2>آخرین مطالب منتشرشده</h2></div></div>'
               '<div class="table-wrap"><table class="table"><thead><tr>'
               '<th>عنوان</th><th>درس</th><th>نوع</th><th>تاریخ</th><th>مشاهده</th></tr></thead>'
               '<tbody>' + recent_rows + '</tbody></table></div>'
               '</div></section>')
    return page_base('پنل مدیریت', content)


# ---------- رشته‌ها ----------
@app.route(ADMIN_PREFIX + '/fields', methods=['GET', 'POST'])
@admin_required
def admin_fields():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('نام رشته الزامی است.', 'error')
        else:
            db = get_db()
            db.execute(
                'INSERT INTO fields (name, slug, description, icon, color, sort_order) VALUES (?,?,?,?,?,?)',
                (name, unique_slug('fields', name), request.form.get('description', '').strip(),
                 request.form.get('icon', '📚') or '📚',
                 request.form.get('color', '#4f46e5') or '#4f46e5',
                 db.execute('SELECT COALESCE(MAX(sort_order),0)+1 AS n FROM fields').fetchone()['n']))
            db.commit()
            flash('رشته با موفقیت اضافه شد.', 'success')
        return redirect(url_for('admin_fields'))
    fields = get_db().execute('SELECT * FROM fields ORDER BY sort_order').fetchall()

    rows = ''.join(
        '<tr><td style="font-weight:800;"><span style="font-size:1.2rem;">' + e(f['icon']) + '</span> ' +
        e(f['name']) + '</td>'
        '<td style="color:var(--muted); font-size:.8rem;">' + e(f['description'][:80]) + '</td>'
        '<td style="white-space:nowrap;">'
        '<a href="' + url_for('admin_field_edit', fid=f['id']) + '" class="btn btn-outline btn-sm">ویرایش</a> '
        '<form method="post" action="' + url_for('admin_field_delete', fid=f['id']) + '" '
        'data-confirm="رشتهٔ «' + e(f['name']) + '» حذف شود؟" style="display:inline;">'
        '<button type="submit" class="btn btn-danger btn-sm">حذف</button></form></td></tr>'
        for f in fields)

    content = ('<section class="section" style="padding-top:34px;"><div class="container">'
               '<div class="flex between mb-2"><div class="section-title" style="margin:0;">'
               '<span class="bar"></span><div><h2>مدیریت رشته‌ها</h2>'
               '<p class="sub">افزودن و ویرایش رشته‌های تحصیلی (ریاضی، تجربی، انسانی، هنر، …)</p></div></div>'
               '<a href="' + url_for('admin_dashboard') + '" class="btn btn-outline btn-sm">← پنل مدیریت</a></div>'
               '<div class="grid" style="grid-template-columns: 1fr 1.4fr; align-items:start;">'
               '<form class="card side-card" method="post" action="' + url_for('admin_fields') + '">'
               '<h3 style="font-size:1.05rem; margin-bottom:14px;">➕ افزودن رشتهٔ جدید</h3>'
               '<div class="form-group"><label>نام رشته</label>'
               '<input type="text" name="name" class="form-control" placeholder="مثلاً: هنر و رسانه" required></div>'
               '<div class="form-grid">'
               '<div class="form-group"><label>آیکون (ایموجی)</label>'
               '<input type="text" name="icon" class="form-control" placeholder="🎨"></div>'
               '<div class="form-group"><label>رنگ</label>'
               '<input type="color" name="color" class="form-control" value="#4f46e5"></div></div>'
               '<div class="form-group"><label>توضیح کوتاه</label>'
               '<textarea name="description" class="form-control" '
               'placeholder="مثلاً: دروس تخصصی این رشته…"></textarea></div>'
               '<button type="submit" class="btn btn-primary">ذخیرهٔ رشته</button></form>'
               '<div class="table-wrap"><table class="table"><thead>'
               '<tr><th>رشته</th><th>توضیح</th><th>عملیات</th></tr></thead><tbody>'
               + rows + '</tbody></table></div></div></div></section>')
    return page_base('مدیریت رشته‌ها', content)


@app.route(ADMIN_PREFIX + '/fields/<int:fid>/edit', methods=['GET', 'POST'])
@admin_required
def admin_field_edit(fid):
    db = get_db()
    field = db.execute('SELECT * FROM fields WHERE id = ?', (fid,)).fetchone()
    if not field:
        abort(404)
    if request.method == 'POST':
        name = request.form.get('name', '').strip() or field['name']
        db.execute('UPDATE fields SET name=?, slug=?, description=?, icon=?, color=? WHERE id=?',
                   (name, unique_slug('fields', name, fid),
                    request.form.get('description', '').strip(),
                    request.form.get('icon', '📚') or '📚',
                    request.form.get('color', '#4f46e5') or '#4f46e5', fid))
        db.commit()
        flash('تغییرات ذخیره شد.', 'success')
        return redirect(url_for('admin_fields'))
    content = ('<section class="section" style="padding-top:34px;">'
               '<div class="container" style="max-width:640px;">'
               '<div class="crumbs mb-2" style="color:var(--muted); font-size:.82rem;">'
               '<a href="' + url_for('admin_dashboard') + '">پنل مدیریت</a> ← '
               '<a href="' + url_for('admin_fields') + '">رشته‌ها</a> ← ویرایش</div>'
               '<form class="card side-card" method="post">'
               '<h3 style="font-size:1.05rem; margin-bottom:14px;">✏️ ویرایش رشتهٔ «' + e(field['name']) + '»</h3>'
               '<div class="form-group"><label>نام رشته</label>'
               '<input type="text" name="name" class="form-control" value="' + e(field['name']) + '" required></div>'
               '<div class="form-grid">'
               '<div class="form-group"><label>آیکون (ایموجی)</label>'
               '<input type="text" name="icon" class="form-control" value="' + e(field['icon']) + '"></div>'
               '<div class="form-group"><label>رنگ</label>'
               '<input type="color" name="color" class="form-control" value="' + e(field['color']) + '"></div></div>'
               '<div class="form-group"><label>توضیح کوتاه</label>'
               '<textarea name="description" class="form-control">' + e(field['description']) + '</textarea></div>'
               '<div class="flex"><button type="submit" class="btn btn-primary">ذخیرهٔ تغییرات</button>'
               '<a href="' + url_for('admin_fields') + '" class="btn btn-outline">انصراف</a></div>'
               '</form></div></section>')
    return page_base('ویرایش رشته', content)


@app.route(ADMIN_PREFIX + '/fields/<int:fid>/delete', methods=['POST'])
@admin_required
def admin_field_delete(fid):
    db = get_db()
    db.execute('DELETE FROM fields WHERE id = ?', (fid,))
    db.commit()
    flash('رشته حذف شد.', 'success')
    return redirect(url_for('admin_fields'))


# ---------- درس‌ها ----------
@app.route(ADMIN_PREFIX + '/subjects', methods=['GET', 'POST'])
@admin_required
def admin_subjects():
    db = get_db()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('نام درس الزامی است.', 'error')
        else:
            field_ids = [int(x) for x in request.form.getlist('fields') if x.isdigit()]
            all_fields = request.form.get('all_fields') == '1'
            if all_fields:
                field_ids = [r['id'] for r in db.execute('SELECT id FROM fields').fetchall()]
            cur = db.execute(
                'INSERT INTO subjects (name, slug, icon, color, grade, description) VALUES (?,?,?,?,?,?)',
                (name, unique_slug('subjects', name), request.form.get('icon', '📖') or '📖',
                 request.form.get('color', '#0ea5e9') or '#0ea5e9',
                 request.form.get('grade', 'دهم') or 'دهم',
                 request.form.get('description', '').strip()))
            sid = cur.lastrowid
            for fid in field_ids:
                db.execute('INSERT INTO subject_fields (subject_id, field_id, is_common) VALUES (?,?,?)',
                           (sid, fid, 1 if all_fields else 0))
            db.commit()
            flash('درس با موفقیت اضافه شد.', 'success')
        return redirect(url_for('admin_subjects'))

    subjects = db.execute('SELECT * FROM subjects ORDER BY name').fetchall()
    fields = db.execute('SELECT * FROM fields ORDER BY sort_order').fetchall()

    # فرم افزودن: چک‌باکس رشته‌ها
    checkboxes = ['<label class="check-item" style="margin-bottom:8px;">'
                  '<input type="checkbox" id="all-fields-toggle"> مشترک همهٔ رشته‌ها (دروس عمومی)</label>']
    for f in fields:
        checkboxes.append('<label class="check-item">'
                          '<input type="checkbox" name="fields" value="' + str(f['id']) + '"> ' +
                          f['icon'] + ' ' + e(f['name']) + '</label>')

    rows = []
    for s in subjects:
        flds = subject_fields(s['id'])
        tags = ''.join(
            '<span class="tag' + (' common' if f['is_common'] else '') + '">' +
            e(f['icon']) + ' ' + e(f['name']) + '</span>' for f in flds) or \
            '<span style="color:var(--muted); font-size:.8rem;">—</span>'
        rows.append(
            '<tr><td style="font-weight:800;">' + e(s['icon']) + ' ' + e(s['name']) + '</td>'
            '<td>' + tags + '</td>'
            '<td style="white-space:nowrap;">'
            '<a href="' + url_for('admin_subject_edit', sid=s['id']) + '" class="btn btn-outline btn-sm">ویرایش</a> '
            '<form method="post" action="' + url_for('admin_subject_delete', sid=s['id']) + '" '
            'data-confirm="درس «' + e(s['name']) + '» و مطالبش حذف شود؟" style="display:inline;">'
            '<button type="submit" class="btn btn-danger btn-sm">حذف</button></form></td></tr>')

    content = ('<section class="section" style="padding-top:34px;"><div class="container">'
               '<div class="flex between mb-2"><div class="section-title" style="margin:0;">'
               '<span class="bar"></span><div><h2>مدیریت درس‌ها</h2>'
               '<p class="sub">افزودن درس جدید و تعیین اینکه در کدام رشته‌ها ارائه می‌شود</p></div></div>'
               '<a href="' + url_for('admin_dashboard') + '" class="btn btn-outline btn-sm">← پنل مدیریت</a></div>'
               '<div class="grid" style="grid-template-columns: 1fr 1.5fr; align-items:start;">'
               '<form class="card side-card" method="post" action="' + url_for('admin_subjects') + '">'
               '<h3 style="font-size:1.05rem; margin-bottom:14px;">➕ افزودن درس جدید</h3>'
               '<div class="form-group"><label>نام درس</label>'
               '<input type="text" name="name" class="form-control" placeholder="مثلاً: ریاضی ۱" required></div>'
               '<div class="form-grid">'
               '<div class="form-group"><label>آیکون (ایموجی)</label>'
               '<input type="text" name="icon" class="form-control" placeholder="📖"></div>'
               '<div class="form-group"><label>رنگ</label>'
               '<input type="color" name="color" class="form-control" value="#0ea5e9"></div>'
               '<div class="form-group full"><label>پایه</label>'
               '<input type="text" name="grade" class="form-control" value="دهم"></div></div>'
               '<div class="form-group"><label>این درس در کدام رشته‌ها ارائه می‌شود؟</label>'
               '<div class="check-group">' + ''.join(checkboxes) + '</div></div>'
               '<div class="form-group"><label>توضیح (اختیاری)</label>'
               '<textarea name="description" class="form-control" '
               'placeholder="توضیح کوتاه دربارهٔ این درس"></textarea></div>'
               '<button type="submit" class="btn btn-primary">ذخیرهٔ درس</button></form>'
               '<div class="table-wrap"><table class="table"><thead>'
               '<tr><th>درس</th><th>رشته‌ها</th><th>عملیات</th></tr></thead><tbody>'
               + ''.join(rows) + '</tbody></table></div></div></div></section>')
    return page_base('مدیریت درس‌ها', content)


@app.route(ADMIN_PREFIX + '/subjects/<int:sid>/edit', methods=['GET', 'POST'])
@admin_required
def admin_subject_edit(sid):
    db = get_db()
    subject = db.execute('SELECT * FROM subjects WHERE id = ?', (sid,)).fetchone()
    if not subject:
        abort(404)
    fields = db.execute('SELECT * FROM fields ORDER BY sort_order').fetchall()
    if request.method == 'POST':
        name = request.form.get('name', '').strip() or subject['name']
        db.execute('UPDATE subjects SET name=?, slug=?, icon=?, color=?, grade=?, description=? WHERE id=?',
                   (name, unique_slug('subjects', name, sid),
                    request.form.get('icon', '📖') or '📖',
                    request.form.get('color', '#0ea5e9') or '#0ea5e9',
                    request.form.get('grade', 'دهم') or 'دهم',
                    request.form.get('description', '').strip(), sid))
        db.execute('DELETE FROM subject_fields WHERE subject_id = ?', (sid,))
        all_fields = request.form.get('all_fields') == '1'
        if all_fields:
            fids = [r['id'] for r in db.execute('SELECT id FROM fields').fetchall()]
        else:
            fids = [int(x) for x in request.form.getlist('fields') if x.isdigit()]
        for fid in fids:
            db.execute('INSERT INTO subject_fields (subject_id, field_id, is_common) VALUES (?,?,?)',
                       (sid, fid, 1 if all_fields else 0))
        db.commit()
        flash('تغییرات ذخیره شد.', 'success')
        return redirect(url_for('admin_subjects'))
    current_ids = {r['id'] for r in subject_fields(sid)}
    all_checked = ' checked' if len(current_ids) == len(fields) else ''
    checkboxes = ['<label class="check-item" style="margin-bottom:8px;">'
                  '<input type="checkbox" id="all-fields-toggle"' + all_checked + '> مشترک همهٔ رشته‌ها</label>']
    for f in fields:
        chk = ' checked' if f['id'] in current_ids else ''
        checkboxes.append('<label class="check-item">'
                          '<input type="checkbox" name="fields" value="' + str(f['id']) + '"' + chk + '> ' +
                          f['icon'] + ' ' + e(f['name']) + '</label>')
    content = ('<section class="section" style="padding-top:34px;">'
               '<div class="container" style="max-width:640px;">'
               '<div class="crumbs mb-2" style="color:var(--muted); font-size:.82rem;">'
               '<a href="' + url_for('admin_dashboard') + '">پنل مدیریت</a> ← '
               '<a href="' + url_for('admin_subjects') + '">درس‌ها</a> ← ویرایش</div>'
               '<form class="card side-card" method="post">'
               '<h3 style="font-size:1.05rem; margin-bottom:14px;">✏️ ویرایش درس «' + e(subject['name']) + '»</h3>'
               '<div class="form-group"><label>نام درس</label>'
               '<input type="text" name="name" class="form-control" value="' + e(subject['name']) + '" required></div>'
               '<div class="form-grid">'
               '<div class="form-group"><label>آیکون (ایموجی)</label>'
               '<input type="text" name="icon" class="form-control" value="' + e(subject['icon']) + '"></div>'
               '<div class="form-group"><label>رنگ</label>'
               '<input type="color" name="color" class="form-control" value="' + e(subject['color']) + '"></div>'
               '<div class="form-group"><label>پایه</label>'
               '<input type="text" name="grade" class="form-control" value="' + e(subject['grade']) + '"></div></div>'
               '<div class="form-group"><label>این درس در کدام رشته‌ها ارائه می‌شود؟</label>'
               '<div class="check-group">' + ''.join(checkboxes) + '</div></div>'
               '<div class="form-group"><label>توضیح</label>'
               '<textarea name="description" class="form-control">' + e(subject['description']) + '</textarea></div>'
               '<div class="flex"><button type="submit" class="btn btn-primary">ذخیرهٔ تغییرات</button>'
               '<a href="' + url_for('admin_subjects') + '" class="btn btn-outline">انصراف</a></div>'
               '</form></div></section>')
    return page_base('ویرایش درس', content)


@app.route(ADMIN_PREFIX + '/subjects/<int:sid>/delete', methods=['POST'])
@admin_required
def admin_subject_delete(sid):
    db = get_db()
    db.execute('DELETE FROM subjects WHERE id = ?', (sid,))
    db.commit()
    flash('درس حذف شد.', 'success')
    return redirect(url_for('admin_subjects'))


# ---------- محتوا ----------
@app.route(ADMIN_PREFIX + '/content')
@admin_required
def admin_contents():
    db = get_db()
    rows = db.execute(
        'SELECT c.*, s.name AS subject_name, s.slug AS subject_slug '
        'FROM contents c JOIN subjects s ON s.id = c.subject_id ORDER BY c.id DESC').fetchall()

    body_rows = []
    has_fetch = False
    for r in rows:
        t = CONTENT_TYPES[r['content_type']]
        file_cell = e(r['file_orig_name'] or r['file_path']) if r['file_path'] \
            else '<a href="' + e(r['url']) + '" target="_blank" rel="noopener">🔗 لینک</a>'
        fetch_block = ''
        if r['url'] and not r['file_path']:
            has_fetch = True
            btn_txt = '⬇ دریافت و ذخیره از لینک' if r['content_type'] == 'video' else '⬇ دریافت و ذخیره'
            fetch_block = ('<div class="yt-fetch mt-1" data-cid="' + str(r['id']) + '">'
                           '<button type="button" class="btn btn-accent btn-sm js-yt-start">' + btn_txt + '</button>'
                           '<span class="yt-status" style="font-size:.75rem; color:var(--muted);"></span></div>')
        body_rows.append(
            '<tr>'
            '<td style="font-weight:800;"><a href="' + url_for('content_view', content_id=r['id']) + '">' +
            e(r['title']) + '</a></td>'
            '<td><a href="' + url_for('subject_page', slug=r['subject_slug']) + '">' + e(r['subject_name']) + '</a></td>'
            '<td>' + badge_type(r['content_type']) + '</td>'
            '<td style="font-size:.78rem; color:var(--muted); max-width:180px; overflow:hidden; '
            'text-overflow:ellipsis; white-space:nowrap;">' + file_cell + '</td>'
            '<td style="white-space:nowrap;">' + e(fa_date(r['added_at'])) + '</td>'
            '<td style="white-space:nowrap;">'
            '<a href="' + url_for('content_view', content_id=r['id']) + '" class="btn btn-outline btn-sm">مشاهده</a>'
            + fetch_block +
            '<form method="post" action="' + url_for('admin_content_delete', cid=r['id']) + '" '
            'data-confirm="مطلب «' + e(r['title']) + '» حذف شود؟" style="display:inline;">'
            '<button type="submit" class="btn btn-danger btn-sm">حذف</button></form>'
            '</td></tr>')

    if not body_rows:
        table_area = ('<div class="empty mt-2"><div class="e-ic">📦</div>'
                      '<h4>هنوز مطلبی بارگذاری نشده است</h4>'
                      '<a href="' + url_for('admin_content_new') + '" class="btn btn-primary mt-2">'
                      'اولین مطلب را بارگذاری کنید</a></div>')
    else:
        table_area = ('<div class="table-wrap"><table class="table"><thead><tr>'
                      '<th>عنوان</th><th>درس</th><th>نوع</th><th>فایل/لینک</th><th>تاریخ</th><th>عملیات</th>'
                      '</tr></thead><tbody>' + ''.join(body_rows) + '</tbody></table></div>')

    script = ''
    if has_fetch:
        js = ("<script>\ndocument.addEventListener('DOMContentLoaded',function(){"
              "document.querySelectorAll('.yt-fetch').forEach(function(box){"
              "var cid=box.getAttribute('data-cid');var btn=box.querySelector('.js-yt-start');"
              "var st=box.querySelector('.yt-status');var timer=null;"
              "function refresh(){fetch('@@P@@/content/'+cid+'/yt-status').then(function(r){return r.json();})"
              ".then(function(j){if(j.status==='running'||j.status==='queued'){if(btn)btn.style.display='none';"
              "st.textContent='⏳ در حال دریافت… '+(j.progress||'');if(!timer)timer=setInterval(refresh,2000);}"
              "else if(j.status==='done'){st.textContent='✅ دانلود شد.';if(timer)clearInterval(timer);"
              "setTimeout(function(){location.reload();},1500);}"
              "else if(j.status==='error'){st.textContent='❌ '+(j.error||'خطا');if(btn)btn.style.display='';"
              "if(timer)clearInterval(timer);}}).catch(function(){});}"
              "refresh();if(btn)btn.addEventListener('click',function(){"
              "fetch('@@P@@/content/'+cid+'/fetch-youtube',{method:'POST'}).then(function(){refresh();});});});});"
              "</script>")
        script = js.replace('@@P@@', ADMIN_PREFIX)

    content = ('<section class="section" style="padding-top:34px;"><div class="container">'
               '<div class="flex between mb-2">'
               '<div class="section-title" style="margin:0;"><span class="bar"></span>'
               '<div><h2>مدیریت مطالب</h2><p class="sub">همهٔ ویدیوها، جزوه‌ها، گام به گام‌ها و سوالات بارگذاری‌شده</p></div></div>'
               '<div class="flex"><a href="' + url_for('admin_content_new') + '" class="btn btn-primary">'
               '➕ بارگذاری مطلب جدید</a>'
               '<a href="' + url_for('admin_dashboard') + '" class="btn btn-outline btn-sm">← پنل مدیریت</a></div></div>'
               + table_area + '</div></section>' + script)
    return page_base('مدیریت مطالب', content)


@app.route(ADMIN_PREFIX + '/content/new', methods=['GET', 'POST'])
@admin_required
def admin_content_new():
    db = get_db()
    subjects = db.execute('SELECT * FROM subjects ORDER BY name').fetchall()
    if request.method == 'POST':
        subject_id = request.form.get('subject_id', type=int)
        ctype = request.form.get('content_type')
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        source = request.form.get('source', '').strip()
        url = request.form.get('url', '').strip()
        if not subject_id or ctype not in CONTENT_TYPES or not title:
            flash('عنوان، درس و نوع مطلب الزامی است.', 'error')
            return redirect(url_for('admin_content_new'))

        file_path, orig, mime = '', '', ''
        f = request.files.get('file')
        if f and f.filename:
            orig = f.filename
            ext = os.path.splitext(orig)[1].lower()
            if ctype == 'video':
                if ext not in VIDEO_EXTS:
                    flash('فرمت ویدیو مجاز نیست (mp4, webm, mov, m4v, ogv).', 'error')
                    return redirect(url_for('admin_content_new'))
                folder, sub = VIDEO_DIR, 'videos'
            else:
                if ext not in DOC_EXTS:
                    flash('فرمت فایل مجاز نیست (pdf, تصویر, zip, doc, docx, txt).', 'error')
                    return redirect(url_for('admin_content_new'))
                folder, sub = DOC_DIR, 'docs'
            fname = uuid.uuid4().hex + ext
            f.save(os.path.join(folder, fname))
            file_path = f'{sub}/{fname}'
            mime = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'

        if not file_path and not url:
            flash('یا فایل را بارگذاری کنید یا یک لینک (مثلاً ویدیوی یوتیوب) قرار دهید.', 'error')
            return redirect(url_for('admin_content_new'))

        cur = db.execute(
            'INSERT INTO contents (subject_id, content_type, title, description, file_path, file_orig_name, mime, url, source) '
            'VALUES (?,?,?,?,?,?,?,?,?)',
            (subject_id, ctype, title, description, file_path, orig, mime, url, source))
        db.commit()
        cid = cur.lastrowid
        if url and not file_path:
            start_url_fetch(cid)
            flash('مطلب منتشر شد؛ دانلود از لینک به‌صورت خودکار شروع شد و پس از پایان، فقط لینک سایت خودتان نمایش داده می‌شود.', 'success')
        else:
            flash('مطلب با موفقیت منتشر شد ✅', 'success')
        return redirect(url_for('admin_contents'))

    subject_opts = '<option value="">— انتخاب درس —</option>' + ''.join(
        '<option value="' + str(s['id']) + '">' + e(s['icon']) + ' ' + e(s['name']) + '</option>'
        for s in subjects)
    type_opts = ''.join(
        '<option value="' + k + '">' + CONTENT_TYPES[k]['icon'] + ' ' + CONTENT_TYPES[k]['label'] + '</option>'
        for k in CONTENT_ORDER)

    content = ('<section class="section" style="padding-top:34px;"><div class="container">'
               '<div class="flex between mb-2">'
               '<div class="section-title" style="margin:0;"><span class="bar" '
               'style="background:linear-gradient(#e11d48,#f43f5e);"></span>'
               '<div><h2>➕ بارگذاری مطلب جدید</h2><p class="sub">ویدیو، جزوه، گام به گام، نمونه سوال امتحانی یا سوالات کتاب را آپلود کنید</p></div></div>'
               '<a href="' + url_for('admin_contents') + '" class="btn btn-outline btn-sm">← لیست مطالب</a></div>'
               '<form class="card side-card form-card" method="post" enctype="multipart/form-data" '
               'action="' + url_for('admin_content_new') + '">'
               '<div class="form-grid">'
               '<div class="form-group"><label>درس *</label>'
               '<select name="subject_id" class="form-control" required>' + subject_opts + '</select></div>'
               '<div class="form-group"><label>نوع مطلب *</label>'
               '<select name="content_type" class="form-control" required>' + type_opts + '</select>'
               '<div class="hint">برای ویدیو، حتماً نوع «ویدیو آموزشی» را انتخاب کنید.</div></div></div>'
               '<div class="form-group"><label>عنوان مطلب *</label>'
               '<input type="text" name="title" class="form-control" '
               'placeholder="مثلاً: جزوهٔ فصل ۲ فیزیک — حرکت بر خط راست" required></div>'
               '<div class="form-grid">'
               '<div class="form-group"><label>منبع / مدرس (اختیاری)</label>'
               '<input type="text" name="source" class="form-control" placeholder="مثلاً: استاد احمدی"></div>'
               '<div class="form-group"><label>نوع منبع</label>'
               '<div class="check-group" style="padding-top:6px;">'
               '<label class="check-item"><input type="radio" name="source_type" value="file" checked> 📁 بارگذاری فایل</label>'
               '<label class="check-item"><input type="radio" name="source_type" value="url"> 🔗 لینک خارجی</label>'
               '</div></div></div>'
               '<div id="file-group"><div class="form-group"><label>انتخاب فایل (ویدیو: mp4/webm — سوال و جزوه: pdf و…)</label>'
               '<input type="file" name="file" class="form-control" id="file-input">'
               '<div class="hint">فایل‌های ویدیو تا ۴ گیگابایت پشتیبانی می‌شوند. فرمت‌های مجاز — ویدیو: mp4, webm, mov, m4v, ogv | اسناد: pdf, png, jpg, zip, doc, docx, txt</div>'
               '</div></div>'
               '<div id="url-group" style="display:none;"><div class="form-group"><label>لینک (آدرس اینترنتی)</label>'
               '<input type="url" name="url" class="form-control" dir="ltr" style="text-align:left;" '
               'placeholder="https://youtube.com/watch?v=… یا https://example.com/file.pdf">'
               '<div class="hint">💡 آدرس یوتیوب یا لینک مستقیم فایل (مثلاً PDF) را بگذارید؛ سایت به‌صورت خودکار فایل را روی سرور خودتان ذخیره می‌کند تا <b>فقط لینک سایت خودتان</b> برای بازدیدکننده نمایش داده شود.</div>'
               '</div></div>'
               '<div class="form-group"><label>توضیح کوتاه (اختیاری)</label>'
               '<textarea name="description" class="form-control" '
               'placeholder="مثلاً: شامل ۱۵ سوال تشریحی با پاسخ، مناسب امتحان نوبت اول"></textarea></div>'
               '<button type="submit" class="btn btn-accent" style="font-size:1rem; padding:12px 28px;">🚀 انتشار مطلب</button>'
               '</form></div></section>')
    return page_base('بارگذاری مطلب جدید', content)


@app.route(ADMIN_PREFIX + '/content/<int:cid>/delete', methods=['POST'])
@admin_required
def admin_content_delete(cid):
    db = get_db()
    row = db.execute('SELECT * FROM contents WHERE id = ?', (cid,)).fetchone()
    if row and row['file_path']:
        try:
            os.remove(os.path.join(UPLOAD_DIR, row['file_path']))
        except OSError:
            pass
    db.execute('DELETE FROM contents WHERE id = ?', (cid,))
    db.commit()
    flash('مطلب حذف شد.', 'success')
    return redirect(url_for('admin_contents'))


@app.route(ADMIN_PREFIX + '/content/<int:cid>/fetch-youtube', methods=['POST'])
@admin_required
def admin_content_fetch_youtube(cid):
    job_id = start_url_fetch(cid)
    if job_id is None:
        flash('این مطلب لینک معتبری ندارد یا قبلاً ذخیره شده است.', 'error')
    else:
        flash('دریافت از لینک شروع شد؛ پس از پایان، فقط لینک سایت خودتان نمایش داده می‌شود.', 'success')
    return redirect(url_for('admin_contents'))


@app.route(ADMIN_PREFIX + '/content/<int:cid>/yt-status')
def admin_content_yt_status(cid):
    """وضعیت دانلود — عمومی است تا صفحهٔ مطلب بتواند پیشرفت را نشان دهد"""
    job = get_latest_job(cid)
    if not job:
        return {'status': 'none', 'progress': '', 'error': ''}
    return {'status': job['status'], 'progress': job.get('progress', ''),
            'error': job.get('error', '')}


# ---------- پلن‌های اشتراک (پنل) ----------
@app.route(ADMIN_PREFIX + '/plans', methods=['GET', 'POST'])
@admin_required
def admin_plans():
    db = get_db()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        months = request.form.get('months', type=int) or 1
        price = request.form.get('price', type=int) or 0
        discount = request.form.get('discount_percent', type=int) or 0
        active = 1 if request.form.get('active') == '1' else 0
        if not name or price <= 0 or months <= 0:
            flash('نام، مدت و قیمت معتبر وارد کنید.', 'error')
        else:
            db.execute('INSERT INTO plans (name, months, price, discount_percent, active) VALUES (?,?,?,?,?)',
                       (name, months, price, max(0, min(100, discount)), active))
            db.commit()
            flash('پلن با موفقیت اضافه شد.', 'success')
        return redirect(url_for('admin_plans'))
    plans_rows = db.execute('SELECT * FROM plans ORDER BY months').fetchall()
    rows = ''.join(
        '<tr><td style="font-weight:800;">' + e(p['name']) + '</td>'
        '<td>' + str(p['months']) + ' ماه</td>'
        '<td>' + str(p['price']) + ' تومان</td>'
        '<td>' + str(p['discount_percent']) + '٪</td>'
        '<td>' + str(plan_final_price(p)) + ' تومان</td>'
        '<td>' + ('<span class="badge-type" style="background:#059669;">فعال</span>'
                  if p['active'] else '<span class="badge-type" style="background:#667085;">غیرفعال</span>') + '</td>'
        '<td style="white-space:nowrap;">'
        '<a href="' + url_for('admin_plan_edit', pid=p['id']) + '" class="btn btn-outline btn-sm">ویرایش</a> '
        '<form method="post" action="' + url_for('admin_plan_delete', pid=p['id']) + '" '
        'data-confirm="پلن «' + e(p['name']) + '» حذف شود؟" style="display:inline;">'
        '<button type="submit" class="btn btn-danger btn-sm">حذف</button></form></td></tr>'
        for p in plans_rows) or \
        '<tr><td colspan="7" style="text-align:center; color:var(--muted);">پلنی ثبت نشده است</td></tr>'
    content = ('<section class="section" style="padding-top:34px;"><div class="container">'
               '<div class="flex between mb-2"><div class="section-title" style="margin:0;">'
               '<span class="bar"></span><div><h2>پلن‌های اشتراک</h2>'
               '<p class="sub">تعیین نام، مدت، قیمت (تومان) و درصد تخفیف</p></div></div>'
               '<a href="' + url_for('admin_dashboard') + '" class="btn btn-outline btn-sm">← پنل مدیریت</a></div>'
               '<div class="grid" style="grid-template-columns: 1fr 1.4fr; align-items:start;">'
               '<form class="card side-card" method="post" action="' + url_for('admin_plans') + '">'
               '<h3 style="font-size:1.05rem; margin-bottom:14px;">➕ افزودن پلن جدید</h3>'
               '<div class="form-group"><label>نام پلن</label>'
               '<input type="text" name="name" class="form-control" placeholder="مثلاً: پلن شش‌ماهه" required></div>'
               '<div class="form-grid">'
               '<div class="form-group"><label>مدت (ماه)</label>'
               '<input type="number" name="months" class="form-control" value="1" min="1" required></div>'
               '<div class="form-group"><label>قیمت (تومان)</label>'
               '<input type="number" name="price" class="form-control" value="50000" min="0" required></div></div>'
               '<div class="form-grid">'
               '<div class="form-group"><label>درصد تخفیف</label>'
               '<input type="number" name="discount_percent" class="form-control" value="0" min="0" max="100"></div>'
               '<div class="form-group"><label>وضعیت</label>'
               '<select name="active" class="form-control">'
               '<option value="1">فعال</option><option value="0">غیرفعال</option></select></div></div>'
               '<button type="submit" class="btn btn-primary">ذخیرهٔ پلن</button></form>'
               '<div class="table-wrap"><table class="table"><thead><tr>'
               '<th>نام</th><th>مدت</th><th>قیمت</th><th>تخفیف</th><th>قیمت نهایی</th><th>وضعیت</th><th>عملیات</th>'
               '</tr></thead><tbody>' + rows + '</tbody></table></div></div></div></section>')
    return page_base('پلن‌های اشتراک', content)


@app.route(ADMIN_PREFIX + '/plans/<int:pid>/edit', methods=['GET', 'POST'])
@admin_required
def admin_plan_edit(pid):
    db = get_db()
    p = db.execute('SELECT * FROM plans WHERE id = ?', (pid,)).fetchone()
    if not p:
        abort(404)
    if request.method == 'POST':
        name = request.form.get('name', '').strip() or p['name']
        months = request.form.get('months', type=int) or p['months']
        price = request.form.get('price', type=int) or p['price']
        discount = max(0, min(100, request.form.get('discount_percent', type=int) or 0))
        active = 1 if request.form.get('active') == '1' else 0
        db.execute('UPDATE plans SET name=?, months=?, price=?, discount_percent=?, active=? WHERE id=?',
                   (name, months, price, discount, active, pid))
        db.commit()
        flash('تغییرات ذخیره شد.', 'success')
        return redirect(url_for('admin_plans'))
    content = ('<section class="section" style="padding-top:34px;">'
               '<div class="container" style="max-width:560px;">'
               '<div class="crumbs mb-2" style="color:var(--muted); font-size:.82rem;">'
               '<a href="' + url_for('admin_dashboard') + '">پنل مدیریت</a> ← '
               '<a href="' + url_for('admin_plans') + '">پلن‌ها</a> ← ویرایش</div>'
               '<form class="card side-card" method="post">'
               '<h3 style="font-size:1.05rem; margin-bottom:14px;">✏️ ویرایش پلن «' + e(p['name']) + '»</h3>'
               '<div class="form-group"><label>نام پلن</label>'
               '<input type="text" name="name" class="form-control" value="' + e(p['name']) + '" required></div>'
               '<div class="form-grid">'
               '<div class="form-group"><label>مدت (ماه)</label>'
               '<input type="number" name="months" class="form-control" value="' + str(p['months']) + '" min="1" required></div>'
               '<div class="form-group"><label>قیمت (تومان)</label>'
               '<input type="number" name="price" class="form-control" value="' + str(p['price']) + '" min="0" required></div></div>'
               '<div class="form-grid">'
               '<div class="form-group"><label>درصد تخفیف</label>'
               '<input type="number" name="discount_percent" class="form-control" value="' + str(p['discount_percent']) + '" min="0" max="100"></div>'
               '<div class="form-group"><label>وضعیت</label>'
               '<select name="active" class="form-control">'
               '<option value="1"' + (' selected' if p['active'] else '') + '>فعال</option>'
               '<option value="0"' + ('' if p['active'] else ' selected') + '>غیرفعال</option></select></div></div>'
               '<div class="flex"><button type="submit" class="btn btn-primary">ذخیرهٔ تغییرات</button>'
               '<a href="' + url_for('admin_plans') + '" class="btn btn-outline">انصراف</a></div>'
               '</form></div></section>')
    return page_base('ویرایش پلن', content)


@app.route(ADMIN_PREFIX + '/plans/<int:pid>/delete', methods=['POST'])
@admin_required
def admin_plan_delete(pid):
    db = get_db()
    # اگر پلن تراکنش دارد، قابل حذف نیست — باید اول غیرفعال شود
    cnt = db.execute('SELECT COUNT(*) AS c FROM transactions WHERE plan_id = ?', (pid,)).fetchone()['c']
    if cnt:
        flash('این پلن دارای تراکنش است و قابل حذف نیست؛ آن را غیرفعال کنید.', 'error')
    else:
        db.execute('DELETE FROM plans WHERE id = ?', (pid,))
        db.commit()
        flash('پلن حذف شد.', 'success')
    return redirect(url_for('admin_plans'))


# ---------- تراکنش‌ها و خریداران (پنل) ----------
@app.route(ADMIN_PREFIX + '/transactions')
@admin_required
def admin_transactions():
    db = get_db()
    rows = db.execute(
        'SELECT t.*, u.name AS user_name, u.email AS user_email, p.name AS plan_name '
        'FROM transactions t JOIN users u ON u.id = t.user_id '
        'LEFT JOIN plans p ON p.id = t.plan_id ORDER BY t.id DESC LIMIT 300').fetchall()
    status_map = {'pending': ('در انتظار پرداخت', '#d97706'),
                  'success': ('موفق', '#059669'),
                  'failed': ('ناموفق', '#e11d48')}
    tr_rows = ''.join(
        '<tr><td>' + str(t['id']) + '</td>'
        '<td>' + e(t['user_name']) + '<br><small style="color:var(--muted);">' + e(t['user_email']) + '</small></td>'
        '<td>' + e(t['plan_name'] or '-') + '</td>'
        '<td>' + str(t['amount']) + ' تومان</td>'
        '<td>' + e(fa_date(t['created_at'])) + '</td>'
        '<td><span class="badge-type" style="background:' + status_map.get(t['status'], ('-', '#667085'))[1] + ';">' +
        status_map.get(t['status'], ('-', '#667085'))[0] + '</span></td>'
        '<td>' + (e(t['ref_id']) if t['ref_id'] else '-') + '</td></tr>'
        for t in rows) or \
        '<tr><td colspan="7" style="text-align:center; color:var(--muted);">تراکنشی ثبت نشده است</td></tr>'
    total_success = db.execute(
        "SELECT COUNT(*) AS c, COALESCE(SUM(amount),0) AS s FROM transactions WHERE status='success'").fetchone()
    content = ('<section class="section" style="padding-top:34px;"><div class="container">'
               '<div class="flex between mb-2"><div class="section-title" style="margin:0;">'
               '<span class="bar"></span><div><h2>خریداران و تراکنش‌ها</h2>'
               '<p class="sub">پرداخت‌های موفق: ' + str(total_success['c']) + ' مورد — مجموع: ' +
               str(total_success['s']) + ' تومان</p></div></div>'
               '<a href="' + url_for('admin_dashboard') + '" class="btn btn-outline btn-sm">← پنل مدیریت</a></div>'
               '<div class="table-wrap"><table class="table"><thead><tr>'
               '<th>شماره</th><th>خریدار</th><th>پلن</th><th>مبلغ</th><th>تاریخ</th><th>وضعیت</th><th>کد پیگیری</th>'
               '</tr></thead><tbody>' + tr_rows + '</tbody></table></div>'
               '</div></section>')
    return page_base('خریداران و تراکنش‌ها', content)


# ============================================================================
# اجرا
# ============================================================================
# هنگام import (چه با python app.py چه با gunicorn app:app) دیتابیس را
# خودکار می‌سازیم تا هیچ مرحلهٔ دستی لازم نباشد.
ensure_init()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
