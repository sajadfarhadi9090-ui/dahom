# -*- coding: utf-8 -*-
"""
نقطهٔ ورود WSGI برای هاست‌هایی که از Passenger / mod_wsgi استفاده می‌کنند
(مثل cPanel با Python App، یا برخی هاست‌های اشتراکی).
استفاده با gunicorn لازم نیست (gunicorn مستقیم app:app را می‌خواند).
"""
import os
# اگر هاست فایل .env دارد، این‌جا لودش می‌کنیم (در صورت نبود python-dotenv خطا ندهد)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
except Exception:
    pass

from app import app as application  # noqa: E402

if __name__ == '__main__':
    application.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
