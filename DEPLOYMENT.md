# 🚀 راهنمای استقرار «کلاس دهم» (نسخهٔ Pure Python)

سایت با **Flask 3 + SQLite** و بدون پوشهٔ templates (HTML داخل پایتون) ساخته شده.
این راهنما برای اجرای **production** روی سرویس‌های رایج آماده شده است.

---

## ۱) آماده‌سازی کد (از قبل انجام شده)

در `app.py` این موارد برای production اضافه شده:

| تغییر | توضیح |
|---|---|
| `DATA_DIR` | دیتابیس و آپلودها در این مسیر ساخته می‌شوند؛ روی هاست به دیسک پایدار اشاره می‌دهید تا بعد از deploy اطلاعات نرود. |
| `ensure_init()` | هنگام import خودکار دیتابیس ساخته/seed می‌شود — برای gunicorn و wsgi بدون مرحلهٔ دستی. |
| `ProxyFix` | پشت Nginx قرار می‌گیریم؛ لینک‌ها به‌درستی https ساخته می‌شوند. |
| کوکی امن | `HttpOnly` + `SameSite=Lax` + اختیاری `Secure` با `COOKIE_SECURE=1`. |
| `PORT` از محیط | `PORT` پیش‌فرض 5000. |
| `SECRET_KEY` از محیط | `SECRET_KEY` در .env / متغیر محیطی. |

---

## ۲) متغیرهای محیطی (فایل `.env.example`)

| متغیر | لازم؟ | توضیح |
|---|---|---|
| `SECRET_KEY` | ✅ حتماً | رشتهٔ تصادفی: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ADMIN_PASSWORD` | ✅ | رمز پنل مدیریت (پیش‌فرض dahom123) |
| `PORT` | ✅ | پورت (در PaaS خودکار ست می‌شود) |
| `DATA_DIR` | در هاست ✅ | مسیر پایدار دیتابیس و آپلودها |
| `ADMIN_PANEL_PATH` | اختیاری | تغییر مسیر پنل (پیش‌فرض panel) |
| `COOKIE_SECURE` | روی https ✅ | `1` وقتی پشت HTTPS هستید |
| `ZARINPAL_MERCHANT_ID` | ✅ برای پرداخت | مرچنت‌کد درگاه زرین‌پال — از پنل زرین‌پال بگیرید |
| `ZARINPAL_SANDBOX` | ✅ | `1` تست / `0` واقعی |

---

## ۳) گزینهٔ A — Render (ساده‌ترین، رایگان)

1. پروژه را به گیت‌هاب بدهید (فایل‌های `render.yaml` و `requirements.txt` خودکار خوانده می‌شوند).
2. در [render.com](https://render.com) → **New +** → **Blueprint** → ریپوی خودتان را انتخاب کنید.
3. منتظر build بمانید؛ آدرس مثل `https://class-dahom.onrender.com` می‌شود.
4. در داشبورد سرویس → **Environment** مقدار `ADMIN_PASSWORD` را عوض کنید.
5. پنل: `https://class-dahom.onrender.com/panel`

> دیسک ۱۰ گیگابایتی روی `/opt/render/project/src/data` مانت می‌شود؛ `DATA_DIR` همان است.

---

## ۴) گزینهٔ B — VPS اوبونتو (Nginx + Gunicorn + systemd)

### قدم ۱: کپی پروژه
```bash
sudo mkdir -p /opt/dahom
# فایل‌های پروژه (بدون پوشهٔ venv) را به /opt/dahom منتقل کنید
# مثلاً با scp:  scp -r dahom-pure/* root@IP:/opt/dahom/
```

### قدم ۲: راه‌اندازی خودکار
```bash
cd /opt/dahom
sudo APP_DIR=/opt/dahom DOMAIN=dahom.example.com bash deploy/setup_vps.sh
```
اگر دامنه ندارید، با IP هم کار می‌کند:
```bash
sudo bash deploy/setup_vps.sh
```

### قدم ۳: چک
```bash
systemctl status dahom          # سرویس
journalctl -u dahom -f          # لاگ زنده
curl -I http://127.0.0.1:5000   # جواب 200
```
سایت: `http://IP` — پنل: `http://IP/panel`

### دستی (اگر اسکریپت را نخواستید)
```bash
# نصب
sudo apt update && sudo apt install -y python3-venv nginx
cd /opt/dahom
python3 -m venv venv && venv/bin/pip install -r requirements.txt
sudo cp deploy/dahom.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now dahom
sudo cp deploy/nginx.conf /etc/nginx/sites-available/dahom
sudo ln -s /etc/nginx/sites-available/dahom /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### SSL (HTTPS)
```bash
sudo certbot --nginx -d dahom.example.com
```
سپس در `.env` مقدار `COOKIE_SECURE=1` بگذارید و `systemctl restart dahom`.

---

## ۵) گزینهٔ C — Liara (هاست ایرانی)

```bash
# نصب CLI و لاگین
npm i -g @liara/cli && liara login
cd dahom-pure
liara deploy --port 5000 --platform python \
  --app class-dahom \
  --env SECRET_KEY=... --env ADMIN_PASSWORD=... \
  --build-cmd "pip install -r requirements.txt" \
  --run-cmd "gunicorn -w 1 --threads 4 -b 0.0.0.0:5000 app:app"
```
یا فایل `liara.json` را آپلود کنید و `liara deploy`. آدرس می‌شود: `https://class-dahom.liara.run`

> ⚠️ **مهم برای ایران:** قابلیت «دانلود خودکار از یوتیوب/لینک» نیاز دارد سرور به آن سایت‌ها دسترسی داشته باشد. روی هاست داخل ایران، دانلود از یوتیوب معمولاً کار نمی‌کند؛ ویدیوها را مستقیم آپلود کنید. برای این قابلیت، هاست خارج از ایران (Render/VPS خارجی) بهتر است.

---

## ۶) گزینهٔ D — Railway

1. پروژه را به گیت‌هاب بدهید؛ در Railway → **New Project → Deploy from GitHub**.
2. در **Variables** بگذارید: `SECRET_KEY`، `ADMIN_PASSWORD`، `PORT=5000`.
3. در **Settings → Commands**:
   - Build: `pip install -r requirements.txt`
   - Start: `gunicorn -w 1 --threads 4 -b 0.0.0.0:$PORT app:app`
4. یک **Volume** با mount path مثلاً `/app/data` بسازید و `DATA_DIR=/app/data` ست کنید (برای ماندگاری آپلودها و دیتابیس).

---

## ۷) گزینهٔ E — هاست cPanel / Python App

بیشتر هاست‌های اشتراکی با **Setup Python App** (Passenger) کار می‌کنند:

1. در cPanel → **Setup Python App** → Python 3.10+، root دایرکتوری پروژه، آدرس.
2. در بخش **Application startup file** فایل `wsgi.py` را بدهید (از قبل در پروژه هست).
3. **Entry point**: `application`
4. **Passenger log file**: `passenger.log`
5. کتابخانه‌ها: `pip install -r requirements.txt` از ترمینال هاست.
6. یک فایل `.env` در پوشهٔ پروژه بسازید (کپی از `.env.example`).
7. مطمئن شوید پوشهٔ `uploads` و فایل `dahom.db` **نوشتنی** هستند (permission 755/775).

---

## ۸) نکات امنیتی

- **SECRET_KEY حتماً عوض شود** — اگر لو برود، سشن‌ها جعل می‌شوند.
- **ADMIN_PASSWORD قوی** + بعد از ورود از صفحهٔ `/panel/settings` عوضش کنید.
- **HTTPS اجباری** (certbot روی VPS؛ روی PaaS رایگان است) + `COOKIE_SECURE=1`.
- مجوز پوشه‌ها: کاربر سرویس (مثلاً `dahom`) فقط باید به `uploads` و دیتابیس دسترسی نوشتن داشته باشد؛ بقیه فقط خواندنی.
- پنل `/panel` را با `ADMIN_PANEL_PATH` به یک مسیر غیرقابل حدس تغییر دهید.
- `debug` همیشه False (در کد هست).
- از سایت عمومی هیچ لینکی به پنل نیست — آدرس را جایی عمومی ننویسید.

---

## ۹) چک‌لیست تست بعد از استقرار

- [ ] صفحهٔ اصلی باز می‌شود (رشته‌ها، آمار، جستجو)
- [ ] صفحات ۳ رشته و ۲۱ درس سالم‌اند
- [ ] بانک مطالب + فیلتر نوع/درس + جستجو
- [ ] ورود به پنل `/panel` با رمز جدید
- [ ] آپلود PDF → نمایش برای همه؛ دانلود فقط با اشتراک (بدون اشتراک: دکمهٔ 🔒)
- [ ] آپلود ویدیو → پخش آنلاین برای همه؛ دانلود فقط با اشتراک
- [ ] قرار دادن لینک → دانلود خودکار در پس‌زمینه؛ لینک مبدأ به بازدیدکننده نمایش داده نمی‌شود
- [ ] ثبت‌نام دانش‌آموز + ورود/خروج + صفحهٔ «حساب من»
- [ ] صفحهٔ پلن‌ها (`/plans`) و خرید → انتقال به درگاه زرین‌پال (سندباکس)
- [ ] کالبک زرین‌پال (`/payment/callback`) → فعال‌سازی خودکار اشتراک و ثبت کد پیگیری
- [ ] پنل: مدیریت پلن‌ها (`/panel/plans`) و لیست خریداران/تراکنش‌ها (`/panel/transactions`)
- [ ] بدون نمایش تاریخ/ساعت در صفحات عمومی
- [ ] پخش ویدیو با Range (عقب/جلو بردن) درست است
- [ ] بعد از restart سرور، آپلودها و دیتابیس سر جایش است (DATA_DIR/دیسک پایدار)
- [ ] HTTPS فعال و همهٔ لینک‌ها https هستند

> ✅ این امکانات در کد پیاده شده‌اند: ثبت‌نام/ورود دانش‌آموز، پلن‌های اشتراک، پرداخت زرین‌پال (تست/واقعی)، کنترل دانلود بر اساس اشتراک و لیست خریداران/تراکنش‌ها در پنل.
> برای فعال‌سازی پرداخت: `ZARINPAL_MERCHANT_ID` را پر کنید؛ با `ZARINPAL_SANDBOX=1` ابتدا با درگاه تست امتحان کنید و بعد `0` بگذارید.
> ⚠️ کالبک زرین‌پال به آدرس `/payment/callback` می‌آید — باید از بیرون قابل دسترسی باشد (در سندباکس هم همین آدرس را در درگاه تست ثبت می‌کنید).

---

## ۱۰) عیب‌یابی سریع

| مشکل | راه‌حل |
|---|---|
| `Permission denied` روی dahom.db/uploads | `sudo chown -R dahom:dahom /opt/dahom` (یا کاربر سرویس هاست) |
| `Address already in use` | پورت 5000 اشغال است؛ سرویس قبلی را متوقف کنید یا `PORT` را عوض کنید |
| آپلود ویدیوی بزرگ قطع می‌شود | `client_max_body_size 4096M` در nginx + `--timeout 120` در gunicorn |
| دانلود از یوتیوب خطا می‌دهد | سرور به یوتیوب دسترسی ندارد (هاست داخل ایران)؛ فایل را مستقیم آپلود کنید |
| ویدیو عقب/جلو نمی‌رود | مطمئن شوید nginx `proxy_buffering off` را برای `/media/` دارد |
| بعد از deploy اطلاعات پاک شد | `DATA_DIR` به دیسک پایدار اشاره نکرده؛ آپلودها و dahom.db را پشتیبان بگیرید |
