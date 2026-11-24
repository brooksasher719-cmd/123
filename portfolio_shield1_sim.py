#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نگهبان هوشمند پرتفوی مفید — سپر اول: محافظ سهامِ در صف خرید، سرخطی‌ها و عرضه‌های اولیه (نسخه تست صوری / Paper Trading)
========================================================================================================================
ویژگی‌های کلیدی این نسخه (طراحی‌شده بر اساس کاتالوگ‌های HAR اوربیس و بورس‌ویو در پوشه for API):
۱) شناسایی ۱۰۰٪ خودکار سهام موجود در پرتفوی کاربر (از طریق /assetmodule/api/performance و /gateway/user/portfolio)
   و استثنا کردن خودکار صندوق‌های درآمد ثابت پارک نقدینگی (مانند آوند IRT3AVNF0001).
۲) تشخیص هوشمند «سهام خریداری‌شده از صف خرید روزهای قبل (توسط کد سرخطی)» با ترکیب ۴ منبع:
   - کندل‌های روزانه ۱۰ روز اخیر (/chart/api/v2/datafeed/history و /gateway/stockPattern) و شمارش روزهای متوالی صف خرید
   - مقایسه درصد سود محقق‌نشده کاربر در پرتفوی با مجموع سود سلسله روزهای صف خرید سهم (تشخیص ورود در میانه صف با سرخطی)
   - بررسی تاریخچه سفارش‌های خرید کاربر (/easy/api/orderHistory/orderReport) در بازه سرخطی 08:44:50 تا 08:45:30
   - بررسی فایل تاریخچه سرخطی (ml_order_history.csv) در پوشه سرخطی گوگل درایو
۳) شروع پایش از ساعت 08:45:00 صبح (ابتدای سفارش‌گذاری پیش‌گشایش) برای سهام سرخطی:
   - حتی اگر در ساعت 08:50 صبح (پیش‌گشایش) صف خرید بریزد یا خریداران با شتاب بالا سفارش‌های خود را حذف کنند،
     نگهبان منتظر ساعت 09:00 نمی‌ماند و در همان پیش‌گشایش دستور فروش صوری در سقف را ثبت می‌کند.
۴) ماتریس ۵ لایه‌ای تصمیم‌گیری در بازار پیوسته (09:00:00 تا 12:30:00):
   - لایه ۱ (SAFE_LOCKED): نگهداری امن تا زمانی که صف خرید مستحکم است (بدون وابستگی به ارزش ریالی ثابت، متناسب با تعداد سهام کاربر).
   - لایه ۲ (TRIGGER_1_REAL_QUEUE_EROSION): ریزش >= 70% از اوج صف خرید همراه با حداقل 50% معامله واقعی در بازار.
   - لایه ۳ (TRIGGER_2_FLASH_DUMP_VELOCITY): حمله رگباری فروشنده؛ خورده شدن >= 50% صف با معاملات واقعی و زمان تخمینی اتمام صف <= 8 ثانیه.
   - لایه ۴ (TRIGGER_3_BUYER_CANCEL_PANIC): تشخیص «پشیمانی خریداران» از روی سرعت و شتاب بسیار زیادِ حذف سفارش‌ها در پنجره ۵ و ۱۰ ثانیه‌ای.
   - لایه ۵ پشتیبان قطعی (TRIGGER_4_SARKHATI_NO_QUEUE_FAILSAFE): اگر کد با محاسبات لایه‌های قبلی نقطه اوج را درک نکرد،
     برای سهام خریداری‌شده با سرخطی (که سود کاربر کمتر از سود روزهای صف خرید سهم است یا سابقه سرخطی دارد)،
     در هر نقطه‌ای که دیگر صف خریدی نبیند بلافاصله در همان قیمت (به‌صورت صوری) می‌فروشد تا از سود کاسته نشود.
۵) راستی‌آزمایی ۱۰۰٪ واقع‌گرایانه پر شدن سفارش در حالت صوری (Real Fill Verification) + رصد پس از خروج تا ساعت 12:30.
۶) نسخه ۲.۱ (ساختار لاگ روزانه + سینک غیرمسدودکننده + محافظت ضدبازنویسی):
   - ذخیره لاگ هر روز به‌صورت جداگانه در زیرپوشه ابری logs (بدون دست زدن به فایل آرشیو قبلی و با حفظ تجمعی signals.csv و state.json)
   - انتقال سینک گوگل درایو به ترد پس‌زمینه غیر-daemon با قفل اتمیک و هندلر SIGTERM جهت جلوگیری از فریز حلقه ۰.۵ ثانیه‌ای
"""

import base64
import concurrent.futures
import csv
import datetime
import hashlib
from html.parser import HTMLParser
import json
import math
import os
import re
import secrets
import signal
import sys
import threading
import time
import urllib.parse
import requests
from requests.adapters import HTTPAdapter

# ==============================================================================
# ۱. تنظیمات اصلی «سپر اول نگهبان پرتفوی» (حالت تست صوری / Simulation Mode)
# ==============================================================================
SIMULATION_MODE = True  # True = فقط ثبت صوری و راستی‌آزمایی پر شدن روی داده‌های زنده بدون ارسال هیچ سفارش واقعی فروش

# مشخصات کارگزاری مفید برای خواندن یا تمدید خودکار توکن ۱۲ ساعته (مشترک با سرخطی و شکارچی)
MOFID_USERNAME = os.environ.get("MOFID_USERNAME", "").strip() or "09138156671"
MOFID_PASSWORD = os.environ.get("MOFID_PASSWORD", "").strip() or "Asasmofid88"
MIN_TOKEN_VALIDITY_MINUTES = 45
AUTH_TOKEN = ""
DEFAULT_EMOFID_SSO_COOKIES = {}  # حذف کوکی‌های منقضی‌شده قدیمی؛ احراز هویت کاملاً پویا با توکن ۱۲ ساعته انجام می‌شود

# نمادهای مستثنی در پرتفوی (صندوق‌های درآمد ثابت پارک نقدینگی و پشتوانه اعتبار که هرگز نباید فروخته شوند)
IGNORED_PORTFOLIO_ISINS = {
    "IRT3AVNF0001",  # صندوق سرمایه‌گذاری با درآمد ثابت آوند
    "IRT1KARD0001",  # کاردان
    "IRT1LBKH0001",  # لبخند
    # نکته: شناسه IRT3HAMF0001 متعلق به صندوق سهامی همسنگ است و از لیست سیاه حذف شد؛ صندوق درآمد ثابت حامی از طریق IGNORED_SYMBOL_KEYWORDS شناسایی و مستثنی می‌شود.
}
IGNORED_SYMBOL_KEYWORDS = ("آوند", "اوند", "حامی", "کاردان")

# بازه‌های زمانی پایش (به وقت رسمی تهران IRST - UTC+03:30)
PREMARKET_START_TIME_STR = "08:45:00"  # شروع رصد پیش‌گشایش برای سهام سرخطی
PREMARKET_SETTLE_TIME_STR = "08:46:30"  # زمان شکل‌گیری اولیه صف پیش‌گشایش پس از شلیک سرخطی‌ها
CONTINUOUS_START_TIME_STR = "09:00:00"  # شروع معاملات پیوسته بازار
CONTINUOUS_SAFE_GRACE_TIME_STR = "09:00:06"  # ۶ ثانیه تنفس حراج بازگشایی رأس ۰۹:۰۰ برای تثبیت تابلوی پیوسته
MARKET_CLOSE_TIME_STR = "12:30:00"  # پایان بازار
RUN_DIAGNOSTIC_OUTSIDE_HOURS = True  # اجرای اسکن تشخیصی کامل پرتفوی و سابقه چند روز اخیر حتی خارج از ساعت بازار

# فرکانس نمونه‌برداری زنده از تابلوی سهام پرتفوی
PORTFOLIO_POLL_INTERVAL_SEC = 0.50  # پایش نیم‌ثانیه‌ای (۲ بار در ثانیه) به دلیل کم بودن تعداد سهام پرتفوی!
DEEP_TELEMETRY_INTERVAL_SEC = 2.00  # استعلام حقیقی/حقوقی و عمق ۵ پله هر ۲ ثانیه

# پارامترهای پیش‌گشایش (08:45:00 تا 08:59:59) ویژه سهام خریداری‌شده از صف خرید روزهای قبل (سرخطی):
PREMARKET_PANIC_DROP_PCT = 55.0  # اگر در پیش‌گشایش بیش از ۵۵٪ اوج صف خرید پیش‌گشایش حذف شود
PREMARKET_CANCEL_BURST_10S_PCT = 20.0  # و سرعت حذف سفارش در ۱۰ ثانیه اخیر >= ۲۰٪ اوج صف باشد -> خروج پیش‌گشایش

# پارامترهای ماتریس ۵ لایه‌ای در بازار پیوسته (09:00:00 تا 12:30:00) — بدون وابستگی به ارزش ریالی ثابت صف:
# لایه ۲: فرسایش واقعی صف با معاملات سنگین (Real Queue Erosion)
LAYER2_EROSION_DROP_FROM_PEAK_PCT = 70.0  # کاهش حداقل ۷۰٪ از اوج صف خرید معتبر روز (باقی‌مانده <= ۳۰٪ اوج)
LAYER2_MIN_REAL_TRADED_RATIO = 0.50  # حداقل ۵۰٪ از کاهش صف از لحظه اوج باید با معاملات واقعی خورده شده باشد
LAYER2_USER_QTY_SAFETY_MULTIPLE = 15.0  # ضریب ایمنی نسبت به تعداد سهام خودِ کاربر در پرتفوی

# لایه ۳: حمله رگباری / شتاب تخلیه آبشاری (Flash Dump Velocity — اصلاح‌شده از ۳۵٪ به ۵۰٪ طبق نظر کاربر)
LAYER3_FLASH_MIN_DROP_FROM_PEAK_PCT = 50.0  # حداقل ۵۰٪ از اوج صف خرید باید خورده شده باشد (افزایش از ۳۵٪ به ۵۰٪)
LAYER3_FLASH_MAX_SECONDS_TO_WIPEOUT = 8.0  # زمان تخمینی تا صفر شدن کامل صف خرید با نرخ بلعیده شدن ۵ ثانیه اخیر <= ۸ ثانیه
LAYER3_FLASH_MIN_REAL_TRADE_RATIO_5S = 0.60  # حداقل ۶۰٪ ریزش ۵ ثانیه اخیر ناشی از معامله واقعی باشد

# لایه ۴: پشیمانی دسته‌جمعی خریداران با سرعت و شتاب بالای حذف سفارش (Buyer Remorse Rapid Cancel Panic)
LAYER4_CANCEL_MIN_TOTAL_DROP_PCT = 60.0  # مجموع افت صف نسبت به اوج به حداقل ۶۰٪ رسیده باشد
LAYER4_CANCEL_10S_DROP_PCT_OF_PEAK = 35.0  # در ۱۰ ثانیه اخیر، حداقل ۳۵٪ کل اوج صف صرفاً با «حذف سفارش» غیب شده باشد
LAYER4_CANCEL_MIN_VELOCITY_PCT_PER_SEC = 3.5  # سرعت حذف سفارش >= ۳.۵٪ اوج صف در هر ثانیه همراه با شتاب مثبت (Acceleration > 0)

# لایه ۵: حالت پشتیبان قطعی سهام سرخطی (Hard Fallback / No-Queue Fail-Safe)
LAYER5_SARKHATI_FAILSAFE_CONFIRM_SEC = 2.0  # اگر سهم سرخطی است و به هر دلیلی صف خرید ندارد، حداکثر پس از ۲ ثانیه تأیید در همان قیمت می‌فروشد!
NON_SARKHATI_POST_BREAK_GRACE_SEC = 4.0  # برای سهام عادی (غیرسرخطی) که امروز صف خرید شده و صفش باز شده، ۴ ثانیه فرصت بازگشت

# پارامترهای تشخیص قفل مجدد پس از فروش (Whipsaw / Re-Lock Detector)
RELOCK_MIN_RATIO_OF_PREV_PEAK = 0.50  # اگر پس از فروش، دوباره صف خرید تشکیل شد و به ۵۰٪ اوج قبلی رسید
RELOCK_SUSTAIN_SECONDS = 60.0  # و ۶۰ ثانیه پایدار ماند -> ثبت رویداد قفل مجدد (Re-Lock)


def get_tehran_now():
    """محاسبه دقیق ساعت رسمی تهران (IRST = UTC+03:30) مستقل از تایم‌زون سرور گیت‌هاب یا ویندوز"""
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    tehran_tz = datetime.timezone(datetime.timedelta(hours=3, minutes=30))
    return utc_now.astimezone(tehran_tz)


# ==============================================================================
# ۲. مسیر فایل‌ها و ماژول همگام‌سازی خودکار، ضدبازنویسی و غیرمسدودکننده با گوگل درایو
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = BASE_DIR
TOKEN_FILE = os.path.join(BASE_DIR, "token.txt")

TODAY_LOG_DATE_STR = get_tehran_now().strftime("%Y-%m-%d")
GUARDIAN_LOG_FILENAME = f"guardian_shield1_log_{TODAY_LOG_DATE_STR}.txt"
GDRIVE_LOGS_SUBFOLDER_NAME = "logs"

GUARDIAN_LOG_TXT = os.path.join(DATA_DIR, GUARDIAN_LOG_FILENAME)
GUARDIAN_SIGNALS_CSV = os.path.join(DATA_DIR, "guardian_shield1_signals.csv")
GUARDIAN_STATE_JSON = os.path.join(DATA_DIR, "guardian_shield1_state.json")

# شناسه پوشه اختصاصی نگهبان پرتفوی (portfolio_guardian در داخل فولدر sarkhati)
DEFAULT_GDRIVE_FOLDER_ID = "1KkgW8YvKu6ZR2UjPHXHJRlQQhlnE7NE8"
SARKHATI_PARENT_FOLDER_ID = "1n0cW933TdKQRczVB0wunYtMrDRLbKXQn"
DEFAULT_GDRIVE_CLIENT_ID = ""
DEFAULT_GDRIVE_CLIENT_SECRET = ""
DEFAULT_GDRIVE_REFRESH_TOKEN = ""

_LOCAL_FILE_LOCK = threading.Lock()
_GDRIVE_SYNC_LOCK = threading.Lock()
_GDRIVE_SYNC_STATE_LOCK = threading.Lock()
_GDRIVE_SYNC_ACTIVE = False
_GDRIVE_SYNC_PENDING = False
_GDRIVE_SYNC_THREAD = None
_STATE_SYNC_INITIALIZED = False
_CACHED_LOGS_FOLDER_ID = None


def _get_gdrive_access_token():
    client_id = os.environ.get("GDRIVE_CLIENT_ID", "").strip() or DEFAULT_GDRIVE_CLIENT_ID
    client_secret = os.environ.get("GDRIVE_CLIENT_SECRET", "").strip() or DEFAULT_GDRIVE_CLIENT_SECRET
    refresh_token = os.environ.get("GDRIVE_REFRESH_TOKEN", "").strip() or DEFAULT_GDRIVE_REFRESH_TOKEN
    folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip() or DEFAULT_GDRIVE_FOLDER_ID

    if not (client_id and client_secret and refresh_token):
        return None, folder_id

    try:
        r = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=10.0,
        )
        if r.status_code == 200:
            return r.json().get("access_token"), folder_id
    except Exception:
        pass
    return None, folder_id


def _gdrive_find_file_id_checked(access_token, folder_id, filename):
    """برگرداندن (ok, file_id) تا خطای شبکه هرگز با نبودن فایل اشتباه گرفته نشود"""
    try:
        q = f"'{folder_id}' in parents and name = '{filename}' and trashed = false"
        r = requests.get(
            "https://www.googleapis.com/drive/v3/files",
            params={"q": q, "fields": "files(id, name, modifiedTime)", "orderBy": "modifiedTime desc", "pageSize": 5},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
        if r.status_code == 200:
            files = r.json().get("files") or []
            return True, (files[0]["id"] if files else None)
    except Exception:
        pass
    return False, None


def _gdrive_find_file_id(access_token, folder_id, filename):
    ok, fid = _gdrive_find_file_id_checked(access_token, folder_id, filename)
    return fid if ok else None


def _gdrive_find_or_create_subfolder(access_token, parent_folder_id, subfolder_name):
    """یافتن یا ساخت یک‌باره پوشه logs در گوگل درایو"""
    global _CACHED_LOGS_FOLDER_ID
    if subfolder_name == GDRIVE_LOGS_SUBFOLDER_NAME and _CACHED_LOGS_FOLDER_ID:
        return True, _CACHED_LOGS_FOLDER_ID
    try:
        q = (
            f"'{parent_folder_id}' in parents "
            f"and name = '{subfolder_name}' "
            f"and mimeType = 'application/vnd.google-apps.folder' "
            f"and trashed = false"
        )
        r = requests.get(
            "https://www.googleapis.com/drive/v3/files",
            params={"q": q, "fields": "files(id, name)", "pageSize": 5},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
        if r.status_code != 200:
            return False, None
        files = r.json().get("files") or []
        if files:
            fid = files[0]["id"]
            if subfolder_name == GDRIVE_LOGS_SUBFOLDER_NAME:
                _CACHED_LOGS_FOLDER_ID = fid
            return True, fid

        r_create = requests.post(
            "https://www.googleapis.com/drive/v3/files",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            data=json.dumps({
                "name": subfolder_name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_folder_id],
            }).encode("utf-8"),
            timeout=10.0,
        )
        if r_create.status_code in (200, 201):
            fid = r_create.json().get("id")
            if fid:
                if subfolder_name == GDRIVE_LOGS_SUBFOLDER_NAME:
                    _CACHED_LOGS_FOLDER_ID = fid
                return True, fid
    except Exception:
        pass
    return False, None


def _gdrive_download_text(access_token, file_id):
    if not file_id:
        return None
    try:
        r = requests.get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            params={"alt": "media"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15.0,
        )
        if r.status_code == 200:
            return r.content.decode("utf-8", errors="replace")
    except Exception:
        pass
    return None


def _gdrive_upload_text(access_token, folder_id, filename, text_content, mime_type="text/plain", known_file_id="__AUTO__"):
    if known_file_id == "__AUTO__":
        ok_find, file_id = _gdrive_find_file_id_checked(access_token, folder_id, filename)
        if not ok_find:
            return False
    else:
        file_id = known_file_id

    data_bytes = text_content.encode("utf-8")
    try:
        if file_id:
            r = requests.patch(
                f"https://www.googleapis.com/upload/drive/v3/files/{file_id}",
                params={"uploadType": "media"},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": f"{mime_type}; charset=utf-8",
                },
                data=data_bytes,
                timeout=20.0,
            )
            if r.status_code not in (200, 201):
                sys.stderr.write(f"[!] GDrive patch upload failed ({filename}): HTTP {r.status_code} | {r.text[:200]}\n")
            return r.status_code in (200, 201)
        else:
            meta = json.dumps({"name": filename, "parents": [folder_id]}).encode("utf-8")
            boundary = "===GDriveGuardianBoundary7MA4YWxk==="
            body = (
                f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode("utf-8")
                + meta
                + f"\r\n--{boundary}\r\nContent-Type: {mime_type}; charset=UTF-8\r\n\r\n".encode("utf-8")
                + data_bytes
                + f"\r\n--{boundary}--\r\n".encode("utf-8")
            )
            r = requests.post(
                "https://www.googleapis.com/upload/drive/v3/files",
                params={"uploadType": "multipart"},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": f"multipart/related; boundary={boundary}",
                },
                data=body,
                timeout=20.0,
            )
            if r.status_code not in (200, 201):
                sys.stderr.write(f"[!] GDrive multipart upload failed ({filename}): HTTP {r.status_code} | {r.text[:200]}\n")
            return r.status_code in (200, 201)
    except Exception as e_up:
        sys.stderr.write(f"[!] GDrive upload exception ({filename}): {e_up}\n")
        return False


SARKHATI_ML_HISTORY_TEXT_CACHE = ""


def pull_files_from_gdrive_on_startup():
    """همگام‌سازی اولیه وضعیت نگهبان، توکن مشترک، لاگ روزانه امروز و تاریخچه سرخطی از گوگل درایو"""
    global SARKHATI_ML_HISTORY_TEXT_CACHE, _STATE_SYNC_INITIALIZED
    access_token, folder_id = _get_gdrive_access_token()
    if not access_token:
        return False

    synced_any = False
    # ۱) فایل‌های تجمعی اصلی در پوشه ریشه نگهبان
    for fname, local_path in (
        ("guardian_shield1_state.json", GUARDIAN_STATE_JSON),
        ("guardian_shield1_signals.csv", GUARDIAN_SIGNALS_CSV),
        ("token.txt", TOKEN_FILE),
    ):
        ok_f, fid = _gdrive_find_file_id_checked(access_token, folder_id, fname)
        if not ok_f:
            continue
        if not fid and fname == "token.txt":
            ok_t, fid = _gdrive_find_file_id_checked(access_token, SARKHATI_PARENT_FOLDER_ID, "token.txt")
            if not ok_t:
                continue
        if not fid:
            if fname == "guardian_shield1_state.json":
                _STATE_SYNC_INITIALIZED = True
            continue
        remote_txt = _gdrive_download_text(access_token, fid)
        if remote_txt and len(remote_txt.strip()) > 0:
            try:
                with _LOCAL_FILE_LOCK:
                    if not os.path.exists(local_path) or len(remote_txt.encode("utf-8")) >= os.path.getsize(local_path):
                        tmp_p = local_path + ".pull.tmp"
                        with open(tmp_p, "w", encoding="utf-8") as f:
                            f.write(remote_txt)
                        os.replace(tmp_p, local_path)
                        synced_any = True
                if fname == "guardian_shield1_state.json":
                    _STATE_SYNC_INITIALIZED = True
            except Exception:
                pass

    # ۲) فایل لاگ امروز از زیرپوشه logs (در صورت اجرای مجدد در همان روز)
    ok_dir, logs_fid = _gdrive_find_or_create_subfolder(access_token, folder_id, GDRIVE_LOGS_SUBFOLDER_NAME)
    if ok_dir and logs_fid:
        ok_l, fid_l = _gdrive_find_file_id_checked(access_token, logs_fid, GUARDIAN_LOG_FILENAME)
        if ok_l and fid_l:
            remote_log = _gdrive_download_text(access_token, fid_l)
            if remote_log and remote_log.strip():
                try:
                    with _LOCAL_FILE_LOCK:
                        if not os.path.exists(GUARDIAN_LOG_TXT) or len(remote_log.encode("utf-8")) >= os.path.getsize(GUARDIAN_LOG_TXT):
                            tmp_l = GUARDIAN_LOG_TXT + ".pull.tmp"
                            with open(tmp_l, "w", encoding="utf-8") as f:
                                f.write(remote_log)
                            os.replace(tmp_l, GUARDIAN_LOG_TXT)
                            synced_any = True
                except Exception:
                    pass

    # ۳) خواندن تاریخچه سفارش‌های سرخطی (ml_order_history.csv) از پوشه اصلی سرخطی برای تشخیص دقیق سهام خریداری‌شده با سرخطی
    fid_ml_csv = _gdrive_find_file_id(access_token, SARKHATI_PARENT_FOLDER_ID, "ml_order_history.csv")
    if fid_ml_csv:
        ml_csv_txt = _gdrive_download_text(access_token, fid_ml_csv)
        if ml_csv_txt:
            SARKHATI_ML_HISTORY_TEXT_CACHE = ml_csv_txt

    if synced_any:
        print(f"[+] همگام‌سازی اولیه با پوشه نگهبان در گوگل درایو (لاگ روزانه: {GDRIVE_LOGS_SUBFOLDER_NAME}/{GUARDIAN_LOG_FILENAME}) با موفقیت انجام شد.")
    return synced_any


def push_guardian_files_to_gdrive():
    """آپلود امن و ضدبازنویسی لاگ روزانه (در پوشه logs)، جدول سیگنال‌ها و وضعیت نگهبان در گوگل درایو"""
    global _STATE_SYNC_INITIALIZED
    access_token, folder_id = _get_gdrive_access_token()
    if not access_token:
        return False

    st_txt = None
    local_csv = None
    local_log = None
    with _LOCAL_FILE_LOCK:
        if os.path.exists(GUARDIAN_STATE_JSON):
            try:
                with open(GUARDIAN_STATE_JSON, "r", encoding="utf-8") as f:
                    st_txt = f.read()
            except Exception:
                st_txt = None
        if os.path.exists(GUARDIAN_SIGNALS_CSV):
            try:
                with open(GUARDIAN_SIGNALS_CSV, "r", encoding="utf-8-sig") as f:
                    local_csv = f.read()
            except Exception:
                local_csv = None
    if os.path.exists(GUARDIAN_LOG_TXT):
        try:
            with open(GUARDIAN_LOG_TXT, "r", encoding="utf-8", errors="replace") as f:
                local_log = f.read()
        except Exception:
            local_log = None

    # ۱) آپلود امن guardian_shield1_state.json (محافظت ضدبازنویسی روی خطای شبکه یا state عقب‌تر)
    if st_txt and st_txt.strip():
        try:
            ok_st, fid_st = _gdrive_find_file_id_checked(access_token, folder_id, "guardian_shield1_state.json")
            if ok_st:
                allow_upload_state = True
                if fid_st and not _STATE_SYNC_INITIALIZED:
                    remote_st = _gdrive_download_text(access_token, fid_st)
                    if remote_st is None:
                        allow_upload_state = False
                    else:
                        try:
                            r_obj = json.loads(remote_st)
                            l_obj = json.loads(st_txt)
                            r_hist_cnt = len(r_obj.get("historical_signals") or []) + len(r_obj.get("today_signals_by_isin") or {})
                            l_hist_cnt = len(l_obj.get("historical_signals") or []) + len(l_obj.get("today_signals_by_isin") or {})
                            if r_hist_cnt > l_hist_cnt:
                                allow_upload_state = False
                            else:
                                _STATE_SYNC_INITIALIZED = True
                        except Exception:
                            allow_upload_state = False
                if allow_upload_state:
                    _gdrive_upload_text(
                        access_token, folder_id, "guardian_shield1_state.json", st_txt, "application/json", known_file_id=fid_st
                    )
        except Exception:
            pass

    # ۲) آپلود و ادغام امن guardian_shield1_signals.csv (اگر دانلود نسخه درایو خطا داد، بازنویسی متوقف می‌شود)
    if local_csv and local_csv.strip():
        try:
            ok_csv, fid_csv = _gdrive_find_file_id_checked(access_token, folder_id, "guardian_shield1_signals.csv")
            if ok_csv:
                remote_csv = _gdrive_download_text(access_token, fid_csv) if fid_csv else ""
                if fid_csv and remote_csv is None:
                    pass
                else:
                    if remote_csv and remote_csv.strip():
                        r_lines = [ln for ln in remote_csv.lstrip("\ufeff").splitlines() if ln.strip()]
                        l_lines = [ln for ln in local_csv.lstrip("\ufeff").splitlines() if ln.strip()]
                        header = l_lines[0] if l_lines else (r_lines[0] if r_lines else "")
                        seen_ids = {}
                        order_keys = []
                        for src_lines in (r_lines[1:], l_lines[1:]):
                            for row_ln in src_lines:
                                sid = row_ln.split(",", 1)[0].strip()
                                if sid and sid not in ("SHIELD1-20261114-085114-0001", "SHIELD1-20261117-092046-0001"):
                                    if sid not in seen_ids:
                                        order_keys.append(sid)
                                    seen_ids[sid] = row_ln  # آخرین وضعیت (شامل قیمت ۱۲:۳۰) جایگزین می‌شود
                        merged_rows = ([header] if header else []) + [seen_ids[k] for k in order_keys]
                        final_csv = "\ufeff" + "\n".join(merged_rows) + "\n"
                    else:
                        final_csv = local_csv
                    _gdrive_upload_text(
                        access_token, folder_id, "guardian_shield1_signals.csv", final_csv, "text/csv", known_file_id=fid_csv
                    )
        except Exception:
            pass

    # ۳) آپلود امن لاگ روزانه سبک در زیرپوشه logs (بدون دست زدن به guardian_shield1_log.txt آرشیوی)
    if local_log and local_log.strip():
        try:
            ok_dir, logs_fid = _gdrive_find_or_create_subfolder(access_token, folder_id, GDRIVE_LOGS_SUBFOLDER_NAME)
            if ok_dir and logs_fid:
                ok_log, fid_log = _gdrive_find_file_id_checked(access_token, logs_fid, GUARDIAN_LOG_FILENAME)
                if ok_log:
                    remote_log = _gdrive_download_text(access_token, fid_log) if fid_log else ""
                    if fid_log and remote_log is None:
                        pass
                    else:
                        if remote_log and remote_log.strip() and not local_log.startswith(remote_log[:min(200, len(remote_log))]):
                            combined_log = remote_log.rstrip() + "\n\n" + local_log.lstrip()
                        else:
                            combined_log = local_log
                        _gdrive_upload_text(
                            access_token, logs_fid, GUARDIAN_LOG_FILENAME, combined_log, "text/plain", known_file_id=fid_log
                        )
        except Exception:
            pass

    return True


def _gdrive_sync_worker():
    global _GDRIVE_SYNC_ACTIVE, _GDRIVE_SYNC_PENDING
    while True:
        with _GDRIVE_SYNC_LOCK:
            try:
                push_guardian_files_to_gdrive()
            except Exception:
                pass
        with _GDRIVE_SYNC_STATE_LOCK:
            if _GDRIVE_SYNC_PENDING:
                _GDRIVE_SYNC_PENDING = False
                continue
            _GDRIVE_SYNC_ACTIVE = False
            break


def request_gdrive_sync_async():
    """اجرای غیرمسدودکننده سینک درایو با صف تجمیعی و ترد غیر-daemon برای جلوگیری از فریز حلقه ۰.۵ ثانیه‌ای"""
    global _GDRIVE_SYNC_ACTIVE, _GDRIVE_SYNC_PENDING, _GDRIVE_SYNC_THREAD
    with _GDRIVE_SYNC_STATE_LOCK:
        if _GDRIVE_SYNC_ACTIVE:
            _GDRIVE_SYNC_PENDING = True
            return
        _GDRIVE_SYNC_ACTIVE = True
        _GDRIVE_SYNC_PENDING = False
        t = threading.Thread(target=_gdrive_sync_worker, name="GuardianGDriveSafeSync", daemon=False)
        _GDRIVE_SYNC_THREAD = t
        t.start()


def flush_and_wait_gdrive_sync(timeout=35.0):
    """انتظار برای اتمام ترد پس‌زمینه و اجرای یک سینک نهایی قطعی (Blocking) هنگام خروج/کرش"""
    with _GDRIVE_SYNC_STATE_LOCK:
        t = _GDRIVE_SYNC_THREAD
    if t is not None and t.is_alive():
        t.join(timeout=timeout)
    with _GDRIVE_SYNC_LOCK:
        try:
            push_guardian_files_to_gdrive()
        except Exception:
            pass

# ==============================================================================
# ۳. اندپوینت‌های رسمی Orbis و BourseView کارگزاری مفید (استخراج‌شده از پوشه for API)
# ==============================================================================
OIDC_ISSUER = "https://login.emofid.com"
OIDC_AUTHORIZE_URL = f"{OIDC_ISSUER}/connect/authorize"
OIDC_TOKEN_URL = f"{OIDC_ISSUER}/connect/token"
OIDC_CLIENT_ID = "easy_pkce"
OIDC_REDIRECT_URI = "https://m.easytrader.ir/auth-callback"
OIDC_SCOPE = "easy2_api mts_api openid profile login_delegation-api"

API_BASE = "https://api-mts.orbis.easytrader.ir"
BV_BASE = "https://bv.emofid.com/gateway"

ASSET_PERFORMANCE_URL = f"{API_BASE}/assetmodule/api/performance"
ACTIVE_ORDERS_URL = f"{API_BASE}/core/api/order"
ORDER_REPORT_HISTORY_URL = f"{API_BASE}/easy/api/orderHistory/orderReport"
MARKET_DATA_V2_URL = f"{API_BASE}/symbols/api/marketdata/v2"
SYMBOL_INFO_DATA_URL = f"{API_BASE}/symbols/api/MarketData/symbol-info-data"
CHART_HISTORY_URL = f"{API_BASE}/chart/api/v2/datafeed/history"
MARKET_SHEET_ALL_URL_TPL = f"{API_BASE}/ms/api/MarketSheet/all/{{isin}}"
MARKET_SHEET_SUM_URL_TPL = f"{API_BASE}/ms/api/MarketSheet/sum/{{isin}}"
IND_INST_ORBIS_URL_TPL = f"{API_BASE}/easy/api/symbol-analysis/ind-inst?isin={{isin}}"
IND_INST_TRADE_POST_URL = f"{API_BASE}/symbols/api/MarketData/indInstTrade"
SAME_LOGIN_URL = f"{API_BASE}/easy/api/account/same-login"

BV_USER_PORTFOLIO_URL = f"{BV_BASE}/user/portfolio"
BV_STOCK_PATTERN_URL_TPL = f"{BV_BASE}/stockPattern?isin={{isin}}"
BV_STOCK_BID_ASK_URL_TPL = f"{BV_BASE}/stockBidAsk?symbol={{isin}}"
BV_STOCK_IND_INST_URL_TPL = f"{BV_BASE}/stockIndInst?isin={{isin}}"


def decode_symbol_state_code(state_code_raw):
    """
    رمزگشایی دقیق کد وضعیت نماد (stateCode) بر اساس منطق استخراج‌شده از سورس‌کد ایزی‌تریدر (ITe / nL / _z):
    - "A"  -> مجاز (سبز - باز و قابل معامله در بازار پیوسته و پیش‌گشایش)
    - "AR" -> مجاز-محفوظ (زرد - مرحله پیش‌گشایش/حراج بازگشایی نماد؛ در بازار پیوسته متوقف است)
    - "AS" -> مجاز-متوقف (زرد - متوقف توسط ناظر)
    - "AG" -> مجاز-مسدود (زرد - مسدود)
    - "I"  -> ممنوع (قرمز - بسته/متوقف)
    - "IS" -> ممنوع-متوقف (قرمز - بسته شده توسط ناظر بازار، مثلاً به دلیل رشد بیش از ۵۰٪ یا کنفرانس اطلاعاتی)
    - "IR" -> ممنوع-محفوظ (قرمز - بسته)
    - "IG" -> ممنوع-مسدود (قرمز - بسته)
    خروجی: (persian_title, color_tag, is_open_continuous, is_open_premarket)
    """
    sc = str(state_code_raw or "A").strip().upper()
    mapping = {
        "A": ("مجاز (باز)", "green", True, True),
        "AR": ("مجاز-محفوظ (در انتظار بازگشایی)", "yellow", False, True),
        "AS": ("مجاز-متوقف", "yellow", False, False),
        "AG": ("مجاز-مسدود", "yellow", False, False),
        "I": ("ممنوع (بسته)", "red", False, False),
        "IS": ("ممنوع-متوقف (بسته توسط ناظر بازار)", "red", False, False),
        "IR": ("ممنوع-محفوظ (بسته)", "red", False, False),
        "IG": ("ممنوع-مسدود (بسته)", "red", False, False),
    }
    if sc in mapping:
        return mapping[sc]
    if sc.startswith("I"):
        return (f"ممنوع/بسته ({sc})", "red", False, False)
    if sc.startswith("A") and sc != "A":
        return (f"مجاز-محدود ({sc})", "yellow", False, sc == "AR")
    return ("مجاز (باز)", "green", True, True)


CSV_COLUMNS = [
    "signal_id",
    "date",
    "symbol_name",
    "symbol_isin",
    "is_sarkhati_stock",
    "sarkhati_detection_reason",
    "consecutive_buy_queue_days",
    "streak_cumulative_return_pct",
    "user_quantity",
    "breakeven_price_rials",
    "high_allowed_price_rials",
    "trigger_layer",
    "signal_time",
    "signal_phase",
    "order_price_rials",
    "fill_verification_status",
    "verified_exit_price_rials",
    "verified_fill_time",
    "market_traded_after_signal",
    "remaining_queue_at_signal",
    "peak_buy_queue_vol",
    "queue_drop_from_peak_pct",
    "real_traded_ratio_of_drop",
    "burn_rate_shares_per_sec",
    "est_sec_to_wipeout",
    "cancel_drop_10s_pct",
    "cancel_velocity_pct_per_sec",
    "market_maker_vol_logged",
    "ind_buy_power",
    "ins_sell_vol",
    "net_proceeds_rials",
    "net_realized_profit_rials",
    "net_realized_profit_tomans",
    "net_realized_profit_pct",
    "re_locked_buy_queue",
    "re_lock_time",
    "min_price_after_exit",
    "max_price_after_exit",
    "last_price_1230",
    "close_price_1230",
    "saved_profit_vs_1230_rials",
    "saved_profit_vs_1230_tomans",
    "saved_profit_vs_1230_pct",
    "notes",
]


class GuardianTeeLogger:
    """ثبت همزمان خروجی ترمینال در فایل لاگ روزانه نگهبان (Thread-Safe)"""

    def __init__(self, orig_stream, log_path):
        self.orig_stream = orig_stream
        self.log_file = None
        self._lock = threading.Lock()
        try:
            self.log_file = open(log_path, "a", encoding="utf-8")
            now_ir = get_tehran_now().strftime("%Y-%m-%d %H:%M:%S")
            self.log_file.write(
                f"\n{'='*84}\n=== شروع نشست نگهبان پرتفوی (سپر اول - حالت صوری) در تاریخ: {now_ir} (IRST) ===\n{'='*84}\n"
            )
            self.log_file.flush()
        except Exception:
            self.log_file = None

    def write(self, message):
        try:
            self.orig_stream.write(message)
        except Exception:
            pass
        with self._lock:
            if self.log_file:
                try:
                    self.log_file.write(message)
                    if "\n" in message:
                        self.log_file.flush()
                except Exception:
                    pass

    def flush(self):
        try:
            self.orig_stream.flush()
        except Exception:
            pass
        with self._lock:
            if self.log_file:
                try:
                    self.log_file.flush()
                except Exception:
                    pass

    def close(self):
        with self._lock:
            if self.log_file:
                try:
                    self.log_file.flush()
                    self.log_file.close()
                except Exception:
                    pass
                self.log_file = None


# ==============================================================================
# ۴. احراز هویت خودکار OIDC بدون مرورگر و اشتراک توکن با پوشه سرخطی
# ==============================================================================
class _LoginFormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_form = False
        self.form_action = ""
        self.inputs = {}

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        if tag.lower() == "form":
            method = (attr_dict.get("method") or "").upper()
            if method == "POST" or not self.form_action:
                self.in_form = True
                self.form_action = attr_dict.get("action") or ""
        elif tag.lower() == "input" and self.in_form:
            name = attr_dict.get("name")
            val = attr_dict.get("value", "")
            if name:
                self.inputs[name] = val

    def handle_endtag(self, tag):
        if tag.lower() == "form" and self.in_form:
            self.in_form = False


def decode_jwt_payload_safe(token_str):
    try:
        raw = token_str.strip()
        if raw.lower().startswith("bearer "):
            raw = raw[7:].strip()
        parts = raw.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        pad = (-len(payload_b64)) % 4
        if pad:
            payload_b64 += "=" * pad
        return json.loads(
            base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8")
        )
    except Exception:
        return None


def check_token_remaining_minutes(token_str):
    payload = decode_jwt_payload_safe(token_str)
    if not payload or "exp" not in payload:
        return False, -999.0, payload
    rem_min = (float(payload["exp"]) - time.time()) / 60.0
    return rem_min > MIN_TOKEN_VALIDITY_MINUTES, round(rem_min, 1), payload


def fetch_mofid_token_headless():
    verifier_bytes = secrets.token_bytes(32)
    code_verifier = base64.urlsafe_b64encode(verifier_bytes).decode("ascii").rstrip("=")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    state = secrets.token_urlsafe(16)
    nonce = secrets.token_urlsafe(16)

    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    )

    auth_params = {
        "client_id": OIDC_CLIENT_ID,
        "redirect_uri": OIDC_REDIRECT_URI,
        "response_type": "code",
        "scope": OIDC_SCOPE,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{OIDC_AUTHORIZE_URL}?{urllib.parse.urlencode(auth_params)}"

    try:
        r_init = s.get(auth_url, allow_redirects=True, timeout=10.0)
        final_url = r_init.url
        html_text = r_init.text or ""

        if "code=" not in final_url:
            parser = _LoginFormParser()
            parser.feed(html_text)
            post_url = (
                urllib.parse.urljoin(final_url, parser.form_action)
                if parser.form_action
                else final_url
            )
            form_data = dict(parser.inputs)
            user_field = "Username"
            pass_field = "Password"
            for k in list(form_data.keys()):
                kl = k.lower()
                if "user" in kl or "mobile" in kl or "phone" in kl:
                    user_field = k
                elif "pass" in kl:
                    pass_field = k
            form_data[user_field] = str(MOFID_USERNAME).strip()
            form_data[pass_field] = str(MOFID_PASSWORD).strip()
            if "button" not in form_data and "Button" not in form_data:
                form_data["button"] = "login"

            r_login = s.post(
                post_url,
                data=form_data,
                headers={"Referer": final_url, "Origin": OIDC_ISSUER},
                allow_redirects=False,
                timeout=10.0,
            )
            curr_resp = r_login
            hop = 0
            while curr_resp.status_code in (301, 302, 303, 307, 308) and hop < 8:
                hop += 1
                loc = curr_resp.headers.get("Location") or ""
                if not loc:
                    break
                next_url = urllib.parse.urljoin(curr_resp.url, loc)
                if "code=" in next_url:
                    final_url = next_url
                    break
                curr_resp = s.get(next_url, allow_redirects=False, timeout=10.0)

        if "code=" in final_url:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(final_url).query)
            code_val = (qs.get("code") or [""])[0]
            if code_val:
                r_tok = s.post(
                    OIDC_TOKEN_URL,
                    data={
                        "client_id": OIDC_CLIENT_ID,
                        "code": code_val,
                        "redirect_uri": OIDC_REDIRECT_URI,
                        "code_verifier": code_verifier,
                        "grant_type": "authorization_code",
                    },
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Origin": "https://m.easytrader.ir",
                        "Referer": "https://m.easytrader.ir/",
                    },
                    timeout=10.0,
                )
                if r_tok.status_code == 200:
                    access_jwt = (r_tok.json() or {}).get("access_token")
                    if access_jwt:
                        return f"Bearer {access_jwt}"
    except Exception:
        pass
    finally:
        s.close()
    return None


def ensure_valid_token():
    global AUTH_TOKEN
    candidates = []
    if AUTH_TOKEN and len(AUTH_TOKEN.strip()) > 30:
        candidates.append(AUTH_TOKEN.strip())
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                t = f.read().strip()
            if len(t) > 30:
                candidates.append(t)
        except Exception:
            pass

    for cand in candidates:
        norm = cand if cand.lower().startswith("bearer ") else f"Bearer {cand}"
        ok, rem_m, payload = check_token_remaining_minutes(norm)
        if ok:
            AUTH_TOKEN = norm
            name = (payload or {}).get("display_name") or "کاربر مفید"
            return True, f"معتبر ({name} | اعتبار باقی‌مانده: {int(rem_m // 60)} ساعت و {int(rem_m % 60)} دقیقه)"

    print("[*] توکن فعلی منقضی است؛ در حال دریافت خودکار توکن ۱۲ ساعته جدید بدون مرورگر...")
    new_tok = fetch_mofid_token_headless()
    if new_tok:
        AUTH_TOKEN = new_tok
        try:
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(new_tok)
        except Exception:
            pass
        try:
            acc_tok, folder_id = _get_gdrive_access_token()
            if acc_tok:
                _gdrive_upload_text(acc_tok, folder_id, "token.txt", new_tok, "text/plain")
                _gdrive_upload_text(acc_tok, SARKHATI_PARENT_FOLDER_ID, "token.txt", new_tok, "text/plain")
        except Exception:
            pass
        _, rem_m, payload = check_token_remaining_minutes(new_tok)
        name = (payload or {}).get("display_name") or "کاربر مفید"
        return True, f"توکن جدید دریافت شد ({name} | اعتبار: {int(rem_m // 60)} ساعت و {int(rem_m % 60)} دقیقه)"

    return False, "عدم موفقیت در دریافت توکن"


def build_headers():
    tok = AUTH_TOKEN.strip()
    if tok and not tok.lower().startswith("bearer "):
        tok = f"Bearer {tok}"
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "fa",
        "Authorization": tok,
        "Content-Type": "application/json",
        "Origin": "https://m.easytrader.ir",
        "Referer": "https://m.easytrader.ir/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    }


def configure_persistent_session(session):
    adapter = HTTPAdapter(pool_connections=20, pool_maxsize=40, max_retries=1)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def get_default_commission_rates(isin_code):
    prefix = (isin_code or "").upper()[:4]
    if prefix == "IRO1":
        return 0.003712, 0.008800
    elif prefix in ("IRO3", "IRO5", "IRO7"):
        return 0.003632, 0.008720
    elif prefix.startswith("IRT"):
        return 0.001160, 0.0011875
    return 0.003712, 0.008800


# ==============================================================================
# ۵. فاز ۱: اسکن خودکار پرتفوی، کندل‌های روزهای اخیر و تشخیص سهام خریداری‌شده با سرخطی
# ==============================================================================
def fetch_symbol_multi_day_history(session, headers, isin):
    consecutive_bq_days = 0
    streak_return_pct = 0.0
    recent_summary = []

    now_epoch = int(time.time()) + 86400
    candles = []

    get_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
    from_epoch = now_epoch - (45 * 86400)
    try:
        url = f"{CHART_HISTORY_URL}?symbol={urllib.parse.quote(isin + ':1')}&resolution=1D&from={from_epoch}&to={now_epoch}&countback=30"
        r = session.get(url, headers=get_headers, timeout=4.0)
        if r.status_code == 200 and r.text and r.text.strip().startswith("{"):
            data = r.json() or {}
            t_arr = data.get("t") or []
            o_arr = data.get("o") or []
            h_arr = data.get("h") or []
            l_arr = data.get("l") or []
            c_arr = data.get("c") or []
            v_arr = data.get("v") or []
            n = min(len(t_arr), len(o_arr), len(h_arr), len(l_arr), len(c_arr))
            for i in range(n):
                candles.append(
                    {
                        "t": int(t_arr[i]),
                        "date": datetime.datetime.fromtimestamp(int(t_arr[i]), datetime.timezone.utc).strftime("%Y-%m-%d"),
                        "o": float(o_arr[i]),
                        "h": float(h_arr[i]),
                        "l": float(l_arr[i]),
                        "c": float(c_arr[i]),
                        "v": int(v_arr[i]) if i < len(v_arr) else 0,
                    }
                )
    except Exception:
        pass

    if len(candles) < 2:
        try:
            bv_url = BV_STOCK_PATTERN_URL_TPL.format(isin=isin)
            bv_headers = {
                "User-Agent": headers.get("User-Agent", "Mozilla/5.0"),
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://bv.emofid.com/advanced-chart",
            }
            r_bv = session.get(bv_url, headers=bv_headers, timeout=4.0)
            if r_bv.status_code == 200 and r_bv.text and r_bv.text.strip().startswith("{"):
                dp = (r_bv.json() or {}).get("dailyprice") or []
                dp_rev = list(reversed(dp[:15]))
                for item in dp_rev:
                    c_val = float(item.get("close") or 0)
                    if c_val > 0:
                        candles.append(
                            {
                                "date": str(item.get("datePersian") or item.get("date") or ""),
                                "o": c_val,
                                "h": c_val,
                                "l": c_val,
                                "c": c_val,
                                "v": 0,
                            }
                        )
        except Exception:
            pass

    if len(candles) >= 2:
        streak_start_price = candles[-1]["c"]
        streak_end_price = candles[-1]["c"]
        for idx in range(len(candles) - 1, 0, -1):
            curr_c = candles[idx]
            prev_c = candles[idx - 1]
            if prev_c["c"] <= 0:
                break
            daily_chg_pct = ((curr_c["c"] - prev_c["c"]) / prev_c["c"]) * 100.0
            daily_high_chg_pct = ((curr_c["h"] - prev_c["c"]) / prev_c["c"]) * 100.0
            closed_at_high = abs(curr_c["c"] - curr_c["h"]) <= max(10.0, curr_c["h"] * 0.002)
            flat_ceiling_candle = (
                abs(curr_c["o"] - curr_c["h"]) <= max(10.0, curr_c["h"] * 0.001)
                and abs(curr_c["l"] - curr_c["h"]) <= max(10.0, curr_c["h"] * 0.002)
                and daily_chg_pct >= 1.80
            )
            is_buy_queue_day = (closed_at_high and daily_chg_pct >= 2.35) or flat_ceiling_candle or (daily_high_chg_pct >= 2.75 and daily_chg_pct >= 2.20)
            recent_summary.append(f"{curr_c['date']}: {int(curr_c['c']):,} ({daily_chg_pct:+.2f}%)")
            if is_buy_queue_day:
                consecutive_bq_days += 1
                streak_start_price = prev_c["c"]
            else:
                if idx == len(candles) - 1 and abs(daily_chg_pct) < 0.05:
                    streak_end_price = prev_c["c"]
                    continue
                break

        if consecutive_bq_days > 0 and streak_start_price > 0:
            streak_return_pct = ((streak_end_price - streak_start_price) / streak_start_price) * 100.0
    elif len(candles) == 1:
        c0 = candles[0]
        recent_summary.append(f"{c0['date']}: {int(c0['c']):,} (روز عرضه اولیه — کف: {int(c0['l']):,} / سقف: {int(c0['h']):,})")
    elif isin.upper().startswith("IRO5") and len(candles) == 0:
        recent_summary.append("سهم تازه عرضه اولیه شده (روز اول معاملاتی پس از عرضه اولیه)")

    return {
        "consecutive_buy_queue_days": consecutive_bq_days,
        "streak_cumulative_return_pct": round(streak_return_pct, 2),
        "recent_days_summary": " | ".join(recent_summary[:5]),
    }


def check_user_sarkhati_order_history(session, headers, isin, symbol_name):
    reasons = []

    if SARKHATI_ML_HISTORY_TEXT_CACHE:
        for ln in SARKHATI_ML_HISTORY_TEXT_CACHE.splitlines():
            if isin in ln or (symbol_name and symbol_name in ln):
                if "ACCEPTED_IN_QUEUE" in ln or "True" in ln:
                    reasons.append("ثبت‌شده در تاریخچه سفارش‌های موفق کد سرخطی (ml_order_history.csv)")
                    break

    try:
        payload = {
            "sieveModel": {
                "page": 1,
                "pageSize": 15,
                "filters": [
                    {"column": "symbolIsin", "operator": 0, "value": isin},
                    {
                        "column": "orderState",
                        "operator": 9,
                        "value": [0, 1, 3, 4, 5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 26, 27, 28, 29, 30, 31, 32, 35, 36, 40, 67],
                    },
                ],
                "sort": {"column": "createDateTime", "dir": 1},
            },
            "searchTadbir": True,
        }
        r = session.post(ORDER_REPORT_HISTORY_URL, data=json.dumps(payload).encode("utf-8"), headers=headers, timeout=4.0)
        if r.status_code == 200 and r.text:
            records = (r.json() or {}).get("records") or []
            for rec in records:
                rep = rec.get("orderReport") or {}
                side = int(rep.get("side") if rep.get("side") is not None else -1)
                exec_qty = int(rep.get("executedQuantity") or 0)
                c_dt = str(rep.get("createDateTime") or "")
                if side == 0 and exec_qty > 0:
                    if "T08:44:" in c_dt or "T08:45:" in c_dt or "T08:46:" in c_dt:
                        reasons.append(f"خرید پرشده در تایم سرخطی ({c_dt[:19]}) به تعداد {exec_qty:,} سهم")
                        break
    except Exception:
        pass

    return reasons


def register_orbis_session_properly(session, headers):
    get_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
    try:
        same_login_payload = {
            "uuid": "3f4c0707-7acf-4056-be93-93cc112ffe53",
            "appBuildNo": "57273",
            "width": 1536,
            "height": 960,
            "devicePlatform": "unknown",
            "platformInfo": headers.get("User-Agent", ""),
        }
        session.post(
            SAME_LOGIN_URL,
            data=json.dumps(same_login_payload).encode("utf-8"),
            headers=headers,
            timeout=3.0,
        )
    except Exception:
        pass
    try:
        session.get(f"{API_BASE}/easy/api/startsession", headers=get_headers, timeout=3.0)
    except Exception:
        pass


def fetch_bourseview_authenticated_portfolio():
    bv_sess = requests.Session()
    bv_sess.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
            "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    )
    for k, v in DEFAULT_EMOFID_SSO_COOKIES.items():
        bv_sess.cookies.set(k, v, domain="login.emofid.com")

    try:
        r_login_init = bv_sess.get(
            "https://bv.emofid.com/gateway/auth/mofid/login?returnUrl=/advanced-chart",
            headers={"Referer": "https://bv.emofid.com/map"},
            allow_redirects=True,
            timeout=8.0,
        )
        html_txt = r_login_init.text or ""
        curr_url = r_login_init.url

        if "Username" in html_txt or "Password" in html_txt or "/Login" in curr_url or "/Account/Login" in curr_url:
            parser1 = _LoginFormParser()
            parser1.feed(html_txt)
            post_url1 = urllib.parse.urljoin(curr_url, parser1.form_action) if parser1.form_action else curr_url
            form1 = dict(parser1.inputs)
            u_f, p_f = "Username", "Password"
            for fk in list(form1.keys()):
                if "user" in fk.lower() or "mobile" in fk.lower():
                    u_f = fk
                elif "pass" in fk.lower():
                    p_f = fk
            form1[u_f] = str(MOFID_USERNAME).strip()
            form1[p_f] = str(MOFID_PASSWORD).strip()
            if "button" not in form1 and "Button" not in form1:
                form1["button"] = "login"
            r_sub = bv_sess.post(
                post_url1,
                data=form1,
                headers={"Referer": curr_url, "Origin": OIDC_ISSUER},
                allow_redirects=True,
                timeout=8.0,
            )
            html_txt = r_sub.text or ""
            curr_url = r_sub.url

        parser2 = _LoginFormParser()
        parser2.feed(html_txt)
        if parser2.inputs and ("code" in parser2.inputs or "callback" in (parser2.form_action or "")):
            cb_url = urllib.parse.urljoin(curr_url, parser2.form_action) if parser2.form_action else "https://bv.emofid.com/gateway/auth/mofid/callback"
            bv_sess.post(
                cb_url,
                data=parser2.inputs,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": OIDC_ISSUER,
                    "Referer": f"{OIDC_ISSUER}/",
                },
                allow_redirects=True,
                timeout=8.0,
            )

        r_port = bv_sess.get(
            BV_USER_PORTFOLIO_URL,
            headers={"Referer": "https://bv.emofid.com/advanced-chart", "Accept": "application/json"},
            timeout=6.0,
        )
        if r_port.status_code == 200 and r_port.text and r_port.text.strip().startswith("{"):
            return (r_port.json() or {}).get("portfolios") or []
    except Exception:
        pass
    finally:
        bv_sess.close()
    return []


def discover_and_classify_portfolio(session, headers):
    portfolio_map = {}
    ignored_holdings_info = []
    get_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}

    register_orbis_session_properly(session, headers)

    perf_loaded = False
    for attempt in range(3):
        try:
            r_perf = session.get(ASSET_PERFORMANCE_URL, headers=get_headers, timeout=5.0)
            raw_txt = (r_perf.text or "").strip()
            if r_perf.status_code == 200 and raw_txt.startswith("{"):
                items = (json.loads(raw_txt) or {}).get("items") or []
                perf_loaded = True
                for it in items:
                    isin = str(it.get("symbolIsin") or "").strip()
                    name = str(it.get("symbolName") or "").strip()
                    qty = int(it.get("asset") or 0)
                    if not isin or qty <= 0:
                        continue
                    if isin in IGNORED_PORTFOLIO_ISINS or any(k in name for k in IGNORED_SYMBOL_KEYWORDS):
                        ignored_holdings_info.append(f"{name or isin} ({isin}): {qty:,} واحد (پارک نقدینگی - معاف از فروش)")
                        continue
                    portfolio_map[isin] = {
                        "symbol_isin": isin,
                        "symbol_name": name or isin,
                        "quantity": qty,
                        "breakeven_price_rials": float(it.get("breakevenPoint") or it.get("periodicBuyAveragePrice") or 0.0),
                        "buy_avg_price_rials": float(it.get("periodicBuyAveragePrice") or it.get("totalBuyAveragePrice") or 0.0),
                        "last_buy_date": str(it.get("date") or ""),
                        "persian_buy_date": str(it.get("persianDate") or ""),
                        "daily_bought_vol": int(it.get("dailyBoughtVolume") or 0),
                    }
                break
            else:
                time.sleep(0.35)
        except Exception:
            time.sleep(0.35)

    try:
        ports = fetch_bourseview_authenticated_portfolio()
        for p in ports:
            isin = str(p.get("isin") or "").strip()
            name = str(p.get("name") or "").strip()
            qty = int(p.get("count") or 0)
            p_type = str(p.get("type") or "").lower()
            if not isin or qty <= 0:
                continue
            if isin in IGNORED_PORTFOLIO_ISINS or any(k in name for k in IGNORED_SYMBOL_KEYWORDS) or (p_type == "fund" and isin.startswith("IRT3AVN")):
                if not any(isin in x for x in ignored_holdings_info):
                    ignored_holdings_info.append(f"{name or isin} ({isin}): {qty:,} واحد (پارک نقدینگی - معاف از فروش)")
                continue
            if isin not in portfolio_map:
                close_p = float(p.get("close") or p.get("vwap") or 0.0)
                portfolio_map[isin] = {
                    "symbol_isin": isin,
                    "symbol_name": name or isin,
                    "quantity": qty,
                    "breakeven_price_rials": close_p,
                    "buy_avg_price_rials": close_p,
                    "last_buy_date": "",
                    "persian_buy_date": "",
                    "daily_bought_vol": 0,
                }
            else:
                if not portfolio_map[isin].get("symbol_name") and name:
                    portfolio_map[isin]["symbol_name"] = name
    except Exception:
        pass

    if not portfolio_map and not perf_loaded:
        try:
            payload = {
                "sieveModel": {
                    "page": 1,
                    "pageSize": 100,
                    "filters": [
                        {
                            "column": "orderState",
                            "operator": 9,
                            "value": [5, 8],
                        },
                    ],
                    "sort": {"column": "createDateTime", "dir": 1},
                },
                "searchTadbir": True,
            }
            r_rep = session.post(ORDER_REPORT_HISTORY_URL, data=json.dumps(payload).encode("utf-8"), headers=headers, timeout=5.0)
            if r_rep.status_code == 200 and r_rep.text and r_rep.text.strip().startswith("{"):
                recs = (r_rep.json() or {}).get("records") or []
                net_by_isin = {}
                for rec in sorted(recs, key=lambda x: str((x.get("orderReport") or {}).get("createDateTime") or "")):
                    rep = rec.get("orderReport") or {}
                    isin = str(rep.get("symbolIsin") or "").strip()
                    name = str(rep.get("symbolName") or "").strip()
                    side = int(rep.get("side") if rep.get("side") is not None else -1)
                    exec_q = int(rep.get("executedQuantity") or 0)
                    price = float(rep.get("price") or 0.0)
                    c_dt = str(rep.get("createDateTime") or "")
                    if not isin or exec_q <= 0:
                        continue
                    if isin in IGNORED_PORTFOLIO_ISINS or any(k in name for k in IGNORED_SYMBOL_KEYWORDS):
                        continue
                    st = net_by_isin.setdefault(isin, {"name": name or isin, "qty": 0, "last_price": price, "last_date": c_dt[:10]})
                    if name:
                        st["name"] = name
                    if side == 0:
                        st["qty"] += exec_q
                        if price > 0:
                            st["last_price"] = price
                        if c_dt:
                            st["last_date"] = c_dt[:10]
                    elif side == 1:
                        st["qty"] = max(0, st["qty"] - exec_q)
                for isin, st in net_by_isin.items():
                    if st["qty"] > 0:
                        portfolio_map[isin] = {
                            "symbol_isin": isin,
                            "symbol_name": st["name"],
                            "quantity": st["qty"],
                            "breakeven_price_rials": round(st["last_price"] * 1.0125, 2),
                            "buy_avg_price_rials": st["last_price"],
                            "last_buy_date": st["last_date"],
                            "persian_buy_date": "",
                            "daily_bought_vol": 0,
                        }
        except Exception:
            pass

    if ignored_holdings_info:
        print(f"[+] دارایی‌های پارک نقدینگی موجود در حساب (معاف از فروش سپر اول): {' | '.join(ignored_holdings_info)}")

    if not portfolio_map:
        return {}

    isins_list = list(portfolio_map.keys())
    live_snaps = {}
    try:
        r_md = session.post(MARKET_DATA_V2_URL, data=json.dumps(isins_list).encode("utf-8"), headers=headers, timeout=4.0)
        if r_md.status_code == 200 and r_md.text:
            arr = r_md.json() or []
            if isinstance(arr, list):
                for item in arr:
                    if isinstance(item, dict) and item.get("symbolIsin"):
                        live_snaps[str(item["symbolIsin"])] = item
    except Exception:
        pass

    active_sell_orders_by_isin = {}
    active_buy_orders_by_isin = {}
    try:
        r_ord = session.get(ACTIVE_ORDERS_URL, headers=get_headers, timeout=4.0)
        if r_ord.status_code == 200 and r_ord.text:
            orders = (r_ord.json() or {}).get("orders") or []
            for o in orders:
                st_str = str(o.get("orderStateStr") or "")
                side = int(o.get("side") if o.get("side") is not None else -1)
                o_isin = str(o.get("symbolIsin") or "")
                if st_str in ("InMarket", "OnBoard", "OnSending", "PartiallyExecution"):
                    if side == 1:
                        active_sell_orders_by_isin[o_isin] = o
                    elif side == 0:
                        active_buy_orders_by_isin[o_isin] = o
                        if o_isin and o_isin not in portfolio_map:
                            exec_q = int(o.get("executedQuantity") or 0)
                            if exec_q > 0:
                                p_ord = float(o.get("price") or 0.0)
                                portfolio_map[o_isin] = {
                                    "symbol_isin": o_isin,
                                    "symbol_name": str(o.get("symbolName") or o_isin),
                                    "quantity": exec_q,
                                    "breakeven_price_rials": round(p_ord * 1.0125, 2),
                                    "buy_avg_price_rials": p_ord,
                                    "last_buy_date": get_tehran_now().strftime("%Y-%m-%d"),
                                    "persian_buy_date": "",
                                    "daily_bought_vol": exec_q,
                                }
    except Exception:
        pass

    # استعلام جایگاه لحظه‌ای در صف (orderPlace و volumeAhead) — اصلاح آدرس با API_BASE
    buy_order_places_by_isin = {}
    if active_buy_orders_by_isin:
        try:
            pl_payload = []
            for b_isin, b_ord in active_buy_orders_by_isin.items():
                if b_ord.get("id") and b_ord.get("hon") is not None and b_ord.get("createDateTime"):
                    pl_payload.append({
                        "orderId": str(b_ord["id"]),
                        "symbolIsin": b_isin,
                        "hon": int(b_ord["hon"]),
                        "createDateTime": str(b_ord["createDateTime"]),
                        "side": 0,
                        "price": int(b_ord.get("price") or 0),
                    })
            if pl_payload:
                r_pl = session.post(
                    f"{API_BASE}/ms/api/MarketSheet/order-place?actionType=0",
                    data=json.dumps(pl_payload).encode("utf-8"),
                    headers=headers,
                    timeout=3.5,
                )
                if r_pl.status_code == 200 and r_pl.text:
                    for p_it in ((r_pl.json() or {}).get("orderPlaces") or []):
                        if isinstance(p_it, dict) and p_it.get("symbolIsin"):
                            buy_order_places_by_isin[str(p_it["symbolIsin"])] = p_it
        except Exception:
            pass

    for isin, info in portfolio_map.items():
        snap = live_snaps.get(isin, {})
        high_allowed = int(snap.get("highAllowedPrice") or 0)
        low_allowed = int(snap.get("lowAllowedPrice") or 0)
        last_p = int(snap.get("lastTradedPrice") or snap.get("closingPrice") or 0)
        prev_close = int(snap.get("feeOfPreviousDaysClosingPrice") or snap.get("closingPrice") or last_p)
        best_buy_p = int(snap.get("bestBuyPrice") or 0)
        best_buy_q = int(snap.get("bestBuyQuantity") or 0)
        best_sell_p = int(snap.get("bestSellPrice") or 0)
        best_sell_q = int(snap.get("bestSellQuantity") or 0)

        try:
            r_ms0 = session.get(MARKET_SHEET_ALL_URL_TPL.format(isin=isin), headers=get_headers, timeout=1.5)
            if r_ms0.status_code == 200 and r_ms0.text:
                ms0 = r_ms0.json() or {}
                b_sh0 = [x for x in (ms0.get("buySheets") or []) if isinstance(x, dict) and int(x.get("volume") or 0) > 0]
                s_sh0 = [x for x in (ms0.get("sellSheets") or []) if isinstance(x, dict) and int(x.get("volume") or 0) > 0]
                if b_sh0:
                    b_sh0.sort(key=lambda x: int(x.get("price") or 0), reverse=True)
                    best_buy_p = int(b_sh0[0].get("price") or 0)
                    best_buy_q = int(b_sh0[0].get("volume") or 0)
                else:
                    best_buy_p = 0
                    best_buy_q = 0
                if s_sh0:
                    s_sh0.sort(key=lambda x: int(x.get("price") or 0))
                    best_sell_p = int(s_sh0[0].get("price") or 0)
                    best_sell_q = int(s_sh0[0].get("volume") or 0)
                else:
                    best_sell_p = 0
                    best_sell_q = 0
        except Exception:
            pass

        def_bc, def_sc = get_default_commission_rates(isin)
        try:
            sell_comm = float(snap.get("sellRatio") or 0.0)
            if sell_comm <= 0 or sell_comm > 0.02:
                sell_comm = def_sc
        except Exception:
            sell_comm = def_sc

        vol_30_avg = 0
        try:
            r_si = session.post(SYMBOL_INFO_DATA_URL, data=json.dumps({"isin": isin}).encode("utf-8"), headers=headers, timeout=3.5)
            if r_si.status_code == 200 and r_si.text:
                si = r_si.json() or {}
                vol_30_avg = int(si.get("volume30AVG") or si.get("volume90Avg") or 0)
                if not high_allowed:
                    high_allowed = int(si.get("highAllowedPrice") or 0)
                if not prev_close:
                    prev_close = int(si.get("feeOfPreviousDaysClosingPrice") or si.get("closingPrice") or 0)
        except Exception:
            pass

        hist = fetch_symbol_multi_day_history(session, headers, isin)
        consec_bq_days = hist["consecutive_buy_queue_days"]
        streak_ret_pct = hist["streak_cumulative_return_pct"]

        breakeven = float(info.get("breakeven_price_rials") or 0.0)
        ref_curr_price = float(last_p or prev_close or high_allowed or breakeven)
        if breakeven <= 0 and ref_curr_price > 0:
            breakeven = ref_curr_price
            info["breakeven_price_rials"] = breakeven

        user_profit_pct = ((ref_curr_price - breakeven) / breakeven) * 100.0 if breakeven > 0 else 0.0

        order_reasons = check_user_sarkhati_order_history(session, headers, isin, info["symbol_name"])
        sarkhati_reasons = list(order_reasons)

        competing_sell_init = best_sell_q if (0 < best_sell_p <= high_allowed and best_sell_q > 0) else 0
        has_strong_net_bq = (
            best_buy_p > 0
            and high_allowed > 0
            and best_buy_p == high_allowed
            and best_buy_q > max(info["quantity"] * 2, competing_sell_init * 3)
        )

        if consec_bq_days >= 1:
            sarkhati_reasons.append(
                f"سهم در {consec_bq_days} روز کاری اخیر در صف خرید بوده است (بازدهی سلسله صف: +{streak_ret_pct:.2f}%)"
            )
        if consec_bq_days >= 2 and streak_ret_pct > 0 and user_profit_pct < (streak_ret_pct - 3.25):
            sarkhati_reasons.append(
                f"سود فعلی کاربر ({user_profit_pct:+.2f}%) کمتر از سود کل روزهای صف خرید سهم (+{streak_ret_pct:.2f}%) است -> ورود در میانه صف با سرخطی"
            )

        if has_strong_net_bq:
            sarkhati_reasons.append(
                f"قفل در صف خرید سقف روزانه ({best_buy_q:,} سهم @ {best_buy_p:,} ریال)"
            )

        if isin in active_buy_orders_by_isin:
            b_ord = active_buy_orders_by_isin[isin]
            b_pl = buy_order_places_by_isin.get(isin, {})
            b_rnk = b_pl.get("orderPlace")
            b_vol_ahead = b_pl.get("volumeAhead")
            rnk_str = f" | رتبه فعلی در صف: {int(b_rnk):,} (حجم پیش‌رو: {int(b_vol_ahead or 0):,} سهم)" if b_rnk is not None else ""
            sarkhati_reasons.append(
                f"سفارش خرید سرخطی فعال در صف امروز ({int(b_ord.get('quantity') or 0):,} سهم @ {int(b_ord.get('price') or 0):,} ریال | پرشده: {int(b_ord.get('executedQuantity') or 0):,} سهم{rnk_str})"
            )

        is_sarkhati_stock = len(sarkhati_reasons) > 0

        init_state_code = str(snap.get("stateCode") or snap.get("symbolState") or "A").strip().upper()
        init_state_title, init_state_color, init_open_cont, init_open_pm = decode_symbol_state_code(init_state_code)
        info.update(
            {
                "state_code": init_state_code,
                "state_title_fa": init_state_title,
                "state_color": init_state_color,
                "is_open_continuous": init_open_cont,
                "high_allowed_price_rials": high_allowed,
                "low_allowed_price_rials": low_allowed,
                "last_traded_price_rials": last_p,
                "prev_close_price_rials": prev_close,
                "best_buy_price_rials": best_buy_p,
                "best_buy_quantity": best_buy_q,
                "best_sell_price_rials": best_sell_p,
                "best_sell_quantity": best_sell_q,
                "sell_commission_rate": sell_comm,
                "volume_30_avg": vol_30_avg,
                "user_unrealized_profit_pct": round(user_profit_pct, 2),
                "consecutive_buy_queue_days": consec_bq_days,
                "streak_cumulative_return_pct": streak_ret_pct,
                "recent_days_summary": hist["recent_days_summary"],
                "is_sarkhati_stock": is_sarkhati_stock,
                "sarkhati_detection_reason": " + ".join(sarkhati_reasons) if sarkhati_reasons else "سهم عادی پرتفوی",
                "has_active_real_sell_order": isin in active_sell_orders_by_isin,
                "active_buy_order": active_buy_orders_by_isin.get(isin),
                "active_buy_order_place": buy_order_places_by_isin.get(isin),
            }
        )

    return portfolio_map


def print_startup_portfolio_report(portfolio_map):
    print(
        f"\n{'='*92}\n"
        f"=== گزارش شناسایی خودکار پرتفوی و تحلیل سابقه صف خرید روزهای اخیر (مجموع: {len(portfolio_map)} نماد) ===\n"
        f"{'='*92}"
    )
    if not portfolio_map:
        print("  [!] هیچ سهم فعالی (به جز صندوق‌های پارک نقدینگی مثل آوند) در پرتفوی یافت نشد.")
        print("=" * 92)
        return

    for idx, (isin, info) in enumerate(portfolio_map.items(), start=1):
        mode_badge = (
            "🔥 سهم سرخطی / صف خرید روزهای قبل (پایش فعال از 08:45:00 + لایه ۵ پشتیبان فعال)"
            if info["is_sarkhati_stock"]
            else "🛡️ سهم عادی پرتفوی (پایش به محض قفل شدن در صف خرید)"
        )
        print(
            f"  [{idx}] نماد: {info['symbol_name']} ({isin}) | وضعیت نماد: {info.get('state_title_fa', 'مجاز')} (کد: {info.get('state_code', 'A')}) | تعداد دارایی: {info['quantity']:,} سهم\n"
            f"      - قیمت سر‌به‌سر (با کارمزد): {int(info['breakeven_price_rials']):,} ریال | آخرین قیمت: {info['last_traded_price_rials']:,} ریال | سقف مجاز امروز: {info['high_allowed_price_rials']:,} ریال\n"
            f"      - سود تحقق‌نیافته فعلی کاربر: {info['user_unrealized_profit_pct']:+.2f}% | روزهای متوالی صف خرید اخیر: {info['consecutive_buy_queue_days']} روز (رشد سلسله صف: +{info['streak_cumulative_return_pct']:.2f}%)\n"
            f"      - کندل‌های روزهای اخیر: {info['recent_days_summary'] or 'نامشخص'}\n"
            f"      - وضعیت فعلی تابلو: خرید {info['best_buy_quantity']:,} سهم @ {info['best_buy_price_rials']:,} ریال | فروش {info['best_sell_quantity']:,} سهم @ {info['best_sell_price_rials']:,} ریال\n"
            f"      - طبقه‌بندی نگهبان: {mode_badge}\n"
            f"      - دلیل تشخیص: {info['sarkhati_detection_reason']}"
        )
        if idx < len(portfolio_map):
            print("  " + "-" * 88)
    print("=" * 92)

# ==============================================================================
# ۶. موتور رهگیری لحظه‌ای صف خرید، تشخیص حذف سفارش پرشتاب و ماتریس ۵ لایه‌ای
# ==============================================================================
class BuyQueueShieldTracker:
    """
    رهگیری لحظه‌ای (نیم‌ثانیه‌ای) وضعیت صف خرید، معاملات واقعی، سرعت و شتاب حذف سفارش‌ها
    و اجرای ماتریس ۵ لایه‌ای تصمیم‌گیری در حالت صوری (Paper Trading) برای هر سهم موجود در پرتفوی
    """

    def __init__(self, portfolio_map, sim_state):
        self.portfolio_map = portfolio_map
        self.sim_state = sim_state
        self.trackers = {}
        self.last_deep_telemetry_ts = {}

        for isin, info in portfolio_map.items():
            self.trackers[isin] = {
                "isin": isin,
                "name": info["symbol_name"],
                "user_qty": int(info["quantity"]),
                "breakeven_price": float(info["breakeven_price_rials"]),
                "sell_comm_rate": float(info["sell_commission_rate"]),
                "is_sarkhati_stock": bool(info["is_sarkhati_stock"]),
                "sarkhati_reason": str(info["sarkhati_detection_reason"]),
                "consec_bq_days": int(info["consecutive_buy_queue_days"]),
                "streak_ret_pct": float(info["streak_cumulative_return_pct"]),
                "premarket_peak_queue_vol": 0,
                "premarket_peak_time": "",
                "seen_buy_queue_today": False,
                "peak_buy_queue_vol": 0,
                "peak_buy_queue_time": "",
                "traded_vol_at_peak": 0,
                "history_samples": [],
                "queue_lost_since_ts": None,
                "fake_cancel_ignored_count": 0,
                "state_code": str(info.get("state_code") or "A"),
                "state_title_fa": str(info.get("state_title_fa") or "مجاز (باز)"),
                "is_halted_or_closed": not bool(info.get("is_open_continuous", True)),
                "halt_reason": "",
                "halt_logged_flag": False,
                "market_maker_vol_logged": 0,
                "ind_buy_power": 1.0,
                "ins_sell_vol": 0,
                "ind_buy_vol": 0,
                "ind_buy_num": 0,
                "ind_sell_vol": 0,
                "ind_sell_num": 0,
            }

    def update_deep_telemetry_if_due(self, session, headers, isin):
        now_ts = time.time()
        if now_ts - self.last_deep_telemetry_ts.get(isin, 0.0) < DEEP_TELEMETRY_INTERVAL_SEC:
            return
        self.last_deep_telemetry_ts[isin] = now_ts
        tr = self.trackers.get(isin)
        if not tr:
            return

        try:
            updated_from_3s_api = False
            r_iit = session.post(
                IND_INST_TRADE_POST_URL,
                data=json.dumps({"isin": isin}).encode("utf-8"),
                headers=headers,
                timeout=1.2,
            )
            if r_iit.status_code == 200 and r_iit.text:
                dt_ii = r_iit.json() or {}
                if isinstance(dt_ii, dict):
                    ib_v = int(dt_ii.get("indBuyVolume") or 0)
                    ib_n = int(dt_ii.get("indBuyNumber") or 0)
                    is_v = int(dt_ii.get("indSellVolume") or 0)
                    is_n = int(dt_ii.get("indSellNumber") or 0)
                    ins_s_v = int(dt_ii.get("insSellVolume") or 0)
                    if ib_v > 0 and ib_n > 0 and is_v > 0 and is_n > 0:
                        tr["ind_buy_power"] = round((ib_v / float(ib_n)) / (is_v / float(is_n)), 2)
                    tr["ins_sell_vol"] = ins_s_v
                    tr["ind_buy_vol"] = ib_v
                    tr["ind_buy_num"] = ib_n
                    tr["ind_sell_vol"] = is_v
                    tr["ind_sell_num"] = is_n
                    updated_from_3s_api = True
            if not updated_from_3s_api:
                get_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
                r_ii = session.get(IND_INST_ORBIS_URL_TPL.format(isin=isin), headers=get_headers, timeout=1.4)
                if r_ii.status_code != 200 or not r_ii.text:
                    r_ii = session.get(BV_STOCK_IND_INST_URL_TPL.format(isin=isin), headers=get_headers, timeout=1.4)
                if r_ii.status_code == 200 and r_ii.text:
                    d = r_ii.json() or {}
                    if isinstance(d, list) and d:
                        d = d[0]
                    if isinstance(d, dict):
                        buy_per = float(d.get("buyPerInd") or 0.0)
                        sell_per = float(d.get("sellPerInd") or 0.0)
                        raw_pow = float(d.get("indBuyPow") or 1.0)
                        if sell_per > 0 and buy_per > 0:
                            tr["ind_buy_power"] = round(buy_per / sell_per, 2)
                        else:
                            tr["ind_buy_power"] = round(raw_pow if raw_pow < 50.0 else (raw_pow / 100.0), 2)
                        tr["ins_sell_vol"] = int(d.get("insSellVol") or 0)
                        tr["bid_pressure"] = float(d.get("bidPres") or 0.0)
        except Exception:
            pass

        try:
            get_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
            r_ms = session.get(MARKET_SHEET_ALL_URL_TPL.format(isin=isin), headers=get_headers, timeout=1.8)
            if r_ms.status_code == 200 and r_ms.text:
                ms = r_ms.json() or {}
                buy_sheets = ms.get("buySheets") or []
                if buy_sheets and isinstance(buy_sheets[0], dict):
                    tr["market_maker_vol_logged"] = int(buy_sheets[0].get("marketMaker") or 0)
        except Exception:
            pass

    def process_snapshot_and_evaluate(self, isin, snap, now_ir):
        tr = self.trackers.get(isin)
        if not tr:
            return None

        now_ts = time.time()
        now_str = now_ir.strftime("%H:%M:%S")
        now_ms_str = now_ir.strftime("%H:%M:%S.%f")[:-3]

        high_p = int(snap.get("highAllowedPrice") or self.portfolio_map[isin].get("high_allowed_price_rials") or 0)
        best_buy_p = int(snap.get("bestBuyPrice") or snap.get("topBuyPrice") or 0)
        best_buy_q = int(snap.get("bestBuyQuantity") or snap.get("topBuyVolume") or 0)
        best_sell_p = int(snap.get("bestSellPrice") or snap.get("topSellPrice") or 0)
        best_sell_q = int(snap.get("bestSellQuantity") or snap.get("topSellVolume") or 0)
        last_p = int(snap.get("lastTradedPrice") or snap.get("closingPrice") or 0)
        close_p = int(snap.get("closingPrice") or last_p or 0)
        traded_vol = int(snap.get("totalNumberOfSharesTraded") or 0)

        if high_p <= 0:
            return None

        raw_state_code = str(
            snap.get("stateCode")
            or snap.get("symbolState")
            or self.portfolio_map[isin].get("state_code")
            or "A"
        ).strip().upper()
        state_title_fa, state_color, is_open_cont, is_open_pm = decode_symbol_state_code(raw_state_code)
        tr["state_code"] = raw_state_code
        tr["state_title_fa"] = state_title_fa

        is_in_premarket_window = (PREMARKET_START_TIME_STR <= now_str < CONTINUOUS_START_TIME_STR)
        is_in_continuous_window = (CONTINUOUS_START_TIME_STR <= now_str <= MARKET_CLOSE_TIME_STR)

        explicit_state_halted = (
            (is_in_continuous_window and not is_open_cont)
            or (is_in_premarket_window and not is_open_pm)
            or (not is_in_continuous_window and not is_in_premarket_window and raw_state_code.startswith("I"))
        )

        prev_hist = tr["history_samples"]
        prev_traded_vol = prev_hist[-1]["traded_vol"] if prev_hist else traded_vol
        delta_traded_now = max(0, traded_vol - prev_traded_vol)
        had_active_board_before = (
            tr["peak_buy_queue_vol"] > 0
            or tr["premarket_peak_queue_vol"] > 0
            or bool(prev_hist and (prev_hist[-1]["raw_buy_q"] > 0 or prev_hist[-1]["sell_q"] > 0))
        )
        order_book_purged_by_halt = (
            best_buy_p == 0
            and best_buy_q == 0
            and best_sell_p == 0
            and best_sell_q == 0
            and delta_traded_now == 0
            and (had_active_board_before or is_in_continuous_window)
        )

        if explicit_state_halted or order_book_purged_by_halt:
            tr["is_halted_or_closed"] = True
            tr["queue_lost_since_ts"] = None
            if explicit_state_halted:
                tr["halt_reason"] = f"وضعیت نماد بسته/متوقف است ({state_title_fa} — stateCode={raw_state_code})"
            else:
                tr["halt_reason"] = (
                    "توقف آنی نماد توسط ناظر بازار (تخلیه کامل مظنه‌های خرید و فروش 0@0 بدون معامله — مثلاً رشد بیش از ۵۰٪ / کنفرانس اطلاعاتی)"
                )
            if not tr.get("halt_logged_flag") and (is_in_premarket_window or is_in_continuous_window):
                print(
                    f"\n[⏸️ تشخیص توقف/بسته شدن نماد توسط ناظر بازار] {tr['name']} ({isin}) در ساعت {now_ms_str}\n"
                    f"   - علت: {tr['halt_reason']}\n"
                    f"   - اقدام نگهبان: تعلیق هوشمند شلیک فروش (جلوگیری از اشتباه گرفتن بسته شدن نماد با ریزش صف خرید)"
                )
                tr["halt_logged_flag"] = True
            return None
        else:
            if tr.get("is_halted_or_closed"):
                if tr.get("halt_logged_flag") and (best_buy_q > 0 or best_sell_q > 0):
                    print(
                        f"\n[▶️ بازگشایی مجدد نماد در بازار] {tr['name']} ({isin}) در ساعت {now_ms_str} | وضعیت: {state_title_fa} ({raw_state_code}) -> ازسرگیری پایش ۵ لایه‌ای"
                    )
                tr["is_halted_or_closed"] = False
                tr["halt_reason"] = ""
                tr["halt_logged_flag"] = False
                tr["queue_lost_since_ts"] = None

        competing_sell_q = best_sell_q if (0 < best_sell_p <= high_p and best_sell_q > 0) else 0
        net_ceiling_buy_q = max(0, best_buy_q - competing_sell_q) if best_buy_p == high_p else 0

        if now_str < "09:03:00":
            is_locked_buy_queue = (
                best_buy_p == high_p
                and net_ceiling_buy_q > max(tr["user_qty"] * 2, competing_sell_q * 2)
            )
        else:
            is_locked_buy_queue = (
                best_buy_p == high_p
                and net_ceiling_buy_q > 0
                and (
                    best_sell_q == 0
                    or (best_sell_p == high_p and best_buy_q > max(competing_sell_q * 10, tr["user_qty"] * 5))
                )
            )

        sample = {
            "ts": now_ts,
            "time_str": now_ms_str,
            "buy_q": net_ceiling_buy_q if is_locked_buy_queue else (best_buy_q if best_buy_p == high_p else 0),
            "raw_buy_q": best_buy_q,
            "buy_p": best_buy_p,
            "sell_q": best_sell_q,
            "sell_p": best_sell_p,
            "last_p": last_p,
            "close_p": close_p,
            "traded_vol": traded_vol,
            "high_p": high_p,
        }
        hist = tr["history_samples"]
        hist.append(sample)
        while len(hist) > 80 and (now_ts - hist[0]["ts"]) > 25.0:
            hist.pop(0)

        exited_signals = self.sim_state.get("today_signals_by_isin", {})
        if isin in exited_signals:
            self._update_post_exit_monitoring(isin, exited_signals[isin], sample, is_locked_buy_queue, tr, now_ts, now_ms_str)
            return None

        # بخش الف: پایش ویژه پیش‌گشایش (08:45:00 تا 08:59:59)
        if PREMARKET_START_TIME_STR <= now_str < CONTINUOUS_START_TIME_STR:
            if is_locked_buy_queue and net_ceiling_buy_q > tr["premarket_peak_queue_vol"]:
                tr["premarket_peak_queue_vol"] = net_ceiling_buy_q
                tr["premarket_peak_time"] = now_ms_str

            if not tr["is_sarkhati_stock"]:
                return None

            if now_str >= PREMARKET_SETTLE_TIME_STR:
                pm_peak = tr["premarket_peak_queue_vol"]

                if not is_locked_buy_queue or best_buy_p < high_p:
                    if tr["queue_lost_since_ts"] is None:
                        tr["queue_lost_since_ts"] = now_ts
                    elif (now_ts - tr["queue_lost_since_ts"]) >= LAYER5_SARKHATI_FAILSAFE_CONFIRM_SEC:
                        target_order_p = best_buy_p if (best_buy_p > 0 and best_buy_p < high_p) else high_p
                        return self._trigger_simulated_exit(
                            isin=isin,
                            tr=tr,
                            sample=sample,
                            trigger_layer="PREMARKET_NO_QUEUE_FAILSAFE",
                            signal_phase="PRE_MARKET_0845_0900",
                            order_price=target_order_p,
                            drop_pct=100.0 if pm_peak > 0 else 0.0,
                            real_traded_ratio=0.0,
                            burn_rate=0.0,
                            est_wipeout=0.0,
                            cancel_10s_pct=100.0,
                            cancel_vel_pct=0.0,
                            reason_fa=(
                                f"ریزش/عدم تشکیل صف خرید در پیش‌گشایش (ساعت {now_ms_str}) روی سهم سرخطی "
                                f"(خرید سقف: {best_buy_q:,} در برابر فروش: {competing_sell_q:,})؛ "
                                f"فروش صوری فوری در پیش‌گشایش ({target_order_p:,} ریال) برای جلوگیری از سوختن سود در بازگشایی ۰۹:۰۰"
                            ),
                        )
                else:
                    tr["queue_lost_since_ts"] = None
                    if pm_peak > 0:
                        pm_drop_pct = ((pm_peak - net_ceiling_buy_q) / float(pm_peak)) * 100.0
                        s_10s = self._get_sample_ago(hist, now_ts, 10.0)
                        drop_10s_pct = (
                            ((s_10s["buy_q"] - net_ceiling_buy_q) / float(pm_peak)) * 100.0
                            if (s_10s and s_10s["buy_q"] > net_ceiling_buy_q)
                            else 0.0
                        )
                        if pm_drop_pct >= PREMARKET_PANIC_DROP_PCT and (
                            drop_10s_pct >= PREMARKET_CANCEL_BURST_10S_PCT or net_ceiling_buy_q <= tr["user_qty"] * 5
                        ):
                            return self._trigger_simulated_exit(
                                isin=isin,
                                tr=tr,
                                sample=sample,
                                trigger_layer="PREMARKET_RAPID_CANCEL_PANIC",
                                signal_phase="PRE_MARKET_0845_0900",
                                order_price=high_p,
                                drop_pct=pm_drop_pct,
                                real_traded_ratio=0.0,
                                burn_rate=0.0,
                                est_wipeout=0.0,
                                cancel_10s_pct=drop_10s_pct,
                                cancel_vel_pct=drop_10s_pct / 10.0,
                                reason_fa=(
                                    f"پشیمانی شدید خریداران در پیش‌گشایش ({now_ms_str}): حذف {pm_drop_pct:.1f}% از اوج صف پیش‌گشایش "
                                    f"({drop_10s_pct:.1f}% در ۱۰ ثانیه اخیر) -> ثبت فروش صوری در سقف ({high_p:,} ریال)"
                                ),
                            )
            return None

        # بخش ب: پایش بازار پیوسته (09:00:00 تا 12:30:00) — ماتریس ۵ لایه‌ای
        if now_str < CONTINUOUS_START_TIME_STR or now_str > MARKET_CLOSE_TIME_STR:
            return None

        eff_ceil_q = sample["buy_q"] if is_locked_buy_queue else 0
        if is_locked_buy_queue:
            tr["seen_buy_queue_today"] = True
            tr["is_sarkhati_stock"] = True
            tr["queue_lost_since_ts"] = None
            if eff_ceil_q > tr["peak_buy_queue_vol"]:
                tr["peak_buy_queue_vol"] = eff_ceil_q
                tr["peak_buy_queue_time"] = now_ms_str
                tr["traded_vol_at_peak"] = traded_vol
            elif tr["peak_buy_queue_vol"] > 0 and eff_ceil_q < tr["peak_buy_queue_vol"]:
                tot_drop = tr["peak_buy_queue_vol"] - eff_ceil_q
                tot_traded = max(0, traded_vol - tr["traded_vol_at_peak"])
                if tot_drop > 0 and (tot_traded / float(tot_drop)) < 0.15 and eff_ceil_q >= int(tr["peak_buy_queue_vol"] * 0.55):
                    tr["fake_cancel_ignored_count"] += 1

        peak_q = max(tr["peak_buy_queue_vol"], tr["premarket_peak_queue_vol"])
        curr_ceil_q = eff_ceil_q

        s_5s = self._get_sample_ago(hist, now_ts, 5.0)
        s_10s = self._get_sample_ago(hist, now_ts, 10.0)
        s_3s = self._get_sample_ago(hist, now_ts, 3.0)

        dt_5s = max(0.5, now_ts - s_5s["ts"]) if s_5s else 5.0
        dt_10s = max(1.0, now_ts - s_10s["ts"]) if s_10s else 10.0

        q_drop_5s = max(0, (s_5s["buy_q"] if s_5s else curr_ceil_q) - curr_ceil_q)
        traded_5s = max(0, traded_vol - (s_5s["traded_vol"] if s_5s else traded_vol))
        real_trade_ratio_5s = min(1.0, traded_5s / float(q_drop_5s)) if q_drop_5s > 0 else (1.0 if traded_5s > 0 else 0.0)
        burn_rate_per_sec = traded_5s / dt_5s
        est_sec_to_wipeout = (curr_ceil_q / burn_rate_per_sec) if burn_rate_per_sec > 1.0 else 9999.0

        q_drop_10s = max(0, (s_10s["buy_q"] if s_10s else curr_ceil_q) - curr_ceil_q)
        traded_10s = max(0, traded_vol - (s_10s["traded_vol"] if s_10s else traded_vol))
        pure_cancel_10s = max(0, q_drop_10s - traded_10s)
        pure_cancel_5s_recent = max(0, q_drop_5s - traded_5s)
        pure_cancel_5s_prev = max(0, pure_cancel_10s - pure_cancel_5s_recent)

        cancel_drop_10s_pct = ((pure_cancel_10s / float(peak_q)) * 100.0) if peak_q > 0 else 0.0
        cancel_vel_recent_pct_s = (((pure_cancel_5s_recent / dt_5s) / float(peak_q)) * 100.0) if peak_q > 0 else 0.0
        cancel_vel_prev_pct_s = (((pure_cancel_5s_prev / max(0.5, dt_10s - dt_5s)) / float(peak_q)) * 100.0) if peak_q > 0 else 0.0
        cancel_acceleration = cancel_vel_recent_pct_s - cancel_vel_prev_pct_s

        drop_from_peak_pct = (((peak_q - curr_ceil_q) / float(peak_q)) * 100.0) if peak_q > 0 else 0.0
        total_drop_since_peak = max(0, tr["peak_buy_queue_vol"] - curr_ceil_q)
        total_traded_since_peak = max(0, traded_vol - tr["traded_vol_at_peak"])
        real_traded_ratio_since_peak = (
            min(1.0, total_traded_since_peak / float(total_drop_since_peak))
            if total_drop_since_peak > 0
            else 0.0
        )
        slope_3s_negative = (s_3s is None) or (curr_ceil_q <= s_3s["buy_q"])

        # بررسی لایه‌های ۲، ۳ و ۴ زمانی که سهم هنوز در صف خرید سقف قرار دارد
        if is_locked_buy_queue and peak_q > 0:
            near_user_liquidity_danger = curr_ceil_q <= max(
                int(tr["user_qty"] * LAYER2_USER_QTY_SAFETY_MULTIPLE),
                int(peak_q * (1.0 - LAYER2_EROSION_DROP_FROM_PEAK_PCT / 100.0)),
            )
            if (
                drop_from_peak_pct >= LAYER2_EROSION_DROP_FROM_PEAK_PCT
                and real_traded_ratio_since_peak >= LAYER2_MIN_REAL_TRADED_RATIO
                and near_user_liquidity_danger
                and slope_3s_negative
            ):
                return self._trigger_simulated_exit(
                    isin=isin,
                    tr=tr,
                    sample=sample,
                    trigger_layer="LAYER2_REAL_QUEUE_EROSION",
                    signal_phase="CONTINUOUS_AT_CEILING",
                    order_price=high_p,
                    drop_pct=drop_from_peak_pct,
                    real_traded_ratio=real_traded_ratio_since_peak,
                    burn_rate=burn_rate_per_sec,
                    est_wipeout=est_sec_to_wipeout,
                    cancel_10s_pct=cancel_drop_10s_pct,
                    cancel_vel_pct=cancel_vel_recent_pct_s,
                    reason_fa=(
                        f"فرسایش واقعی صف خرید (لایه ۲): ریزش {drop_from_peak_pct:.1f}% از اوج صف "
                        f"با {real_traded_ratio_since_peak*100:.1f}% معامله واقعی؛ فروش صوری در سقف ({high_p:,} ریال) پیش از اتمام صف"
                    ),
                )

            if (
                drop_from_peak_pct >= LAYER3_FLASH_MIN_DROP_FROM_PEAK_PCT
                and real_trade_ratio_5s >= LAYER3_FLASH_MIN_REAL_TRADE_RATIO_5S
                and est_sec_to_wipeout <= LAYER3_FLASH_MAX_SECONDS_TO_WIPEOUT
            ):
                return self._trigger_simulated_exit(
                    isin=isin,
                    tr=tr,
                    sample=sample,
                    trigger_layer="LAYER3_FLASH_DUMP_VELOCITY",
                    signal_phase="CONTINUOUS_AT_CEILING",
                    order_price=high_p,
                    drop_pct=drop_from_peak_pct,
                    real_traded_ratio=real_trade_ratio_5s,
                    burn_rate=burn_rate_per_sec,
                    est_wipeout=est_sec_to_wipeout,
                    cancel_10s_pct=cancel_drop_10s_pct,
                    cancel_vel_pct=cancel_vel_recent_pct_s,
                    reason_fa=(
                        f"حمله رگباری به صف خرید (لایه ۳): خورده شدن {drop_from_peak_pct:.1f}% صف (حداقل ۵۰٪) "
                        f"با سرعت {int(burn_rate_per_sec):,} سهم/ثانیه (اتمام تخمینی صف: {est_sec_to_wipeout:.1f}s) -> شلیک صوری فوری در سقف ({high_p:,} ریال)"
                    ),
                )

            if (
                drop_from_peak_pct >= LAYER4_CANCEL_MIN_TOTAL_DROP_PCT
                and cancel_drop_10s_pct >= LAYER4_CANCEL_10S_DROP_PCT_OF_PEAK
                and cancel_vel_recent_pct_s >= LAYER4_CANCEL_MIN_VELOCITY_PCT_PER_SEC
                and cancel_acceleration >= 0.0
            ):
                return self._trigger_simulated_exit(
                    isin=isin,
                    tr=tr,
                    sample=sample,
                    trigger_layer="LAYER4_BUYER_CANCEL_PANIC",
                    signal_phase="CONTINUOUS_AT_CEILING",
                    order_price=high_p,
                    drop_pct=drop_from_peak_pct,
                    real_traded_ratio=real_traded_ratio_since_peak,
                    burn_rate=burn_rate_per_sec,
                    est_wipeout=est_sec_to_wipeout,
                    cancel_10s_pct=cancel_drop_10s_pct,
                    cancel_vel_pct=cancel_vel_recent_pct_s,
                    reason_fa=(
                        f"پشیمانی پرشتاب خریداران (لایه ۴): حذف ناگهانی {cancel_drop_10s_pct:.1f}% از کل صف در ۱۰ ثانیه "
                        f"(سرعت حذف: {cancel_vel_recent_pct_s:.2f}%/s با شتاب مثبت +{cancel_acceleration:.2f}%/s² و مجموع افت {drop_from_peak_pct:.1f}%) -> فروش صوری در سقف ({high_p:,} ریال)"
                    ),
                )

        # بررسی لایه ۵ (حالت پشتیبان قطعی سهام سرخطی در هر نقطه‌ای که صف خرید ندید) و لایه خروج سهام عادی
        if not is_locked_buy_queue and now_str >= CONTINUOUS_SAFE_GRACE_TIME_STR:
            if tr["queue_lost_since_ts"] is None:
                tr["queue_lost_since_ts"] = now_ts
            lost_elapsed = now_ts - tr["queue_lost_since_ts"]

            if tr["is_sarkhati_stock"] and lost_elapsed >= LAYER5_SARKHATI_FAILSAFE_CONFIRM_SEC:
                exit_order_p = best_buy_p if best_buy_p > 0 else (last_p if last_p > 0 else high_p)
                return self._trigger_simulated_exit(
                    isin=isin,
                    tr=tr,
                    sample=sample,
                    trigger_layer="LAYER5_SARKHATI_NO_QUEUE_FAILSAFE",
                    signal_phase="CONTINUOUS_POST_QUEUE_FAILSAFE",
                    order_price=exit_order_p,
                    drop_pct=100.0,
                    real_traded_ratio=real_traded_ratio_since_peak,
                    burn_rate=burn_rate_per_sec,
                    est_wipeout=0.0,
                    cancel_10s_pct=cancel_drop_10s_pct,
                    cancel_vel_pct=cancel_vel_recent_pct_s,
                    reason_fa=(
                        f"حالت پشتیبان قطعی سهام سرخطی (لایه ۵): سهم سرخطی فاقد صف خرید است "
                        f"(بهترین خرید تابلو: {best_buy_p:,} ریال | فروشنده: {best_sell_q:,} @ {best_sell_p:,}) -> فروش صوری فوری در {exit_order_p:,} ریال برای حفظ کامل سود"
                    ),
                )

            if (not tr["is_sarkhati_stock"]) and tr["seen_buy_queue_today"] and lost_elapsed >= NON_SARKHATI_POST_BREAK_GRACE_SEC:
                exit_order_p = best_buy_p if best_buy_p > 0 else (last_p if last_p > 0 else high_p)
                return self._trigger_simulated_exit(
                    isin=isin,
                    tr=tr,
                    sample=sample,
                    trigger_layer="POST_BREAK_CONFIRMATION",
                    signal_phase="CONTINUOUS_POST_BREAK",
                    order_price=exit_order_p,
                    drop_pct=100.0,
                    real_traded_ratio=real_traded_ratio_since_peak,
                    burn_rate=burn_rate_per_sec,
                    est_wipeout=0.0,
                    cancel_10s_pct=cancel_drop_10s_pct,
                    cancel_vel_pct=cancel_vel_recent_pct_s,
                    reason_fa=(
                        f"باز شدن کامل صف خرید سهم عادی و عدم بازگشت پس از {NON_SARKHATI_POST_BREAK_GRACE_SEC:.0f} ثانیه -> "
                        f"فروش صوری در بهترین تقاضای تابلو ({exit_order_p:,} ریال)"
                    ),
                )

        return None

    @staticmethod
    def _get_sample_ago(hist, now_ts, target_sec_ago):
        if not hist:
            return None
        best_s = hist[0]
        for s in reversed(hist):
            if (now_ts - s["ts"]) >= target_sec_ago:
                return s
            best_s = s
        return best_s

    def _trigger_simulated_exit(
        self,
        isin,
        tr,
        sample,
        trigger_layer,
        signal_phase,
        order_price,
        drop_pct,
        real_traded_ratio,
        burn_rate,
        est_wipeout,
        cancel_10s_pct,
        cancel_vel_pct,
        reason_fa,
    ):
        """ثبت ۱۰۰٪ صوری سیگنال فروش (بدون ارسال هیچ سفارش واقعی به کارگزاری)"""
        now_ir = get_tehran_now()
        today_str = now_ir.strftime("%Y-%m-%d")
        sig_id = f"SHIELD1-{now_ir.strftime('%Y%m%d-%H%M%S')}-{isin[-4:]}"
        peak_q = max(tr["peak_buy_queue_vol"], tr["premarket_peak_queue_vol"])

        gross_rials = int(round(order_price * tr["user_qty"]))
        sell_comm_rials = int(round(gross_rials * tr["sell_comm_rate"]))
        net_proceeds = gross_rials - sell_comm_rials
        total_cost = int(round(tr["breakeven_price"] * tr["user_qty"]))
        net_profit_rials = net_proceeds - total_cost
        net_profit_pct = ((net_proceeds - total_cost) / float(total_cost)) * 100.0 if total_cost > 0 else 0.0

        sig_record = {
            "signal_id": sig_id,
            "date": today_str,
            "symbol_name": tr["name"],
            "symbol_isin": isin,
            "is_sarkhati_stock": tr["is_sarkhati_stock"],
            "sarkhati_detection_reason": tr["sarkhati_reason"],
            "consecutive_buy_queue_days": tr["consec_bq_days"],
            "streak_cumulative_return_pct": tr["streak_ret_pct"],
            "user_quantity": tr["user_qty"],
            "breakeven_price_rials": round(tr["breakeven_price"], 2),
            "sell_commission_rate": tr["sell_comm_rate"],
            "high_allowed_price_rials": sample["high_p"],
            "trigger_layer": trigger_layer,
            "signal_time": sample["time_str"],
            "signal_epoch": sample["ts"],
            "signal_phase": signal_phase,
            "order_price_rials": order_price,
            "traded_vol_at_signal": sample["traded_vol"],
            "fill_verification_status": "PENDING_SIM_FILL",
            "verified_exit_price_rials": order_price,
            "verified_fill_time": "",
            "market_traded_after_signal": 0,
            "remaining_queue_at_signal": sample["buy_q"],
            "peak_buy_queue_vol": peak_q,
            "queue_drop_from_peak_pct": round(drop_pct, 2),
            "real_traded_ratio_of_drop": round(real_traded_ratio, 4),
            "burn_rate_shares_per_sec": round(burn_rate, 1),
            "est_sec_to_wipeout": round(est_wipeout, 2) if est_wipeout < 9000 else -1.0,
            "cancel_drop_10s_pct": round(cancel_10s_pct, 2),
            "cancel_velocity_pct_per_sec": round(cancel_vel_pct, 3),
            "market_maker_vol_logged": tr["market_maker_vol_logged"],
            "ind_buy_power": round(tr["ind_buy_power"], 2),
            "ins_sell_vol": tr["ins_sell_vol"],
            "net_proceeds_rials": net_proceeds,
            "net_realized_profit_rials": net_profit_rials,
            "net_realized_profit_tomans": round(net_profit_rials / 10.0),
            "net_realized_profit_pct": round(net_profit_pct, 2),
            "re_locked_buy_queue": False,
            "re_lock_time": "",
            "re_lock_candidate_since_ts": None,
            "min_price_after_exit": sample["last_p"] or order_price,
            "max_price_after_exit": sample["last_p"] or order_price,
            "last_price_1230": sample["last_p"] or order_price,
            "close_price_1230": sample["close_p"] or order_price,
            "saved_profit_vs_1230_rials": 0,
            "saved_profit_vs_1230_tomans": 0,
            "saved_profit_vs_1230_pct": 0.0,
            "notes": reason_fa,
        }

        self.sim_state.setdefault("today_signals_by_isin", {})[isin] = sig_record
        save_guardian_state(self.sim_state)
        upsert_signal_to_csv(sig_record)
        try:
            request_gdrive_sync_async()
        except Exception:
            pass

        print(
            f"\n{'!'*88}\n"
            f"[⚡ شلیک فروش صوری سپر اول ({trigger_layer})] شناسه: {sig_id}\n"
            f"  نماد: {tr['name']} ({isin}) | زمان شلیک: {sample['time_str']} | فاز: {signal_phase}\n"
            f"  تعداد سهام پرتفوی: {tr['user_qty']:,} سهم | قیمت سر‌به‌سر: {int(tr['breakeven_price']):,} ریال -> قیمت سفارش فروش صوری: {order_price:,} ریال\n"
            f"  وضعیت صف در لحظه شلیک: باقی‌مانده {sample['buy_q']:,} از اوج {peak_q:,} سهم (-{drop_pct:.1f}%)\n"
            f"  سود خالص قفل‌شده (پس از کسر کارمزد فروش): {net_profit_rials:+,} ریال ({round(net_profit_rials/10.0):+,} تومان | {net_profit_pct:+.2f}%)\n"
            f"  علت دقیق شلیک: {reason_fa}\n"
            f"{'!'*88}"
        )
        return sig_record

    def _update_post_exit_monitoring(self, isin, sig_rec, sample, is_locked_buy_queue, tr, now_ts, now_ms_str):
        changed = False
        elapsed_since_sig = now_ts - float(sig_rec.get("signal_epoch") or now_ts)
        traded_after = max(0, sample["traded_vol"] - int(sig_rec.get("traded_vol_at_signal") or 0))
        if traded_after != sig_rec.get("market_traded_after_signal"):
            sig_rec["market_traded_after_signal"] = traded_after

        if sig_rec.get("fill_verification_status") == "PENDING_SIM_FILL":
            now_str = now_ms_str[:8]
            user_qty = int(sig_rec["user_quantity"])
            ord_p = int(sig_rec["order_price_rials"])

            if sig_rec["signal_phase"] == "PRE_MARKET_0845_0900":
                if now_str >= "09:00:05":
                    actual_open_p = sample["buy_p"] if sample["buy_p"] > 0 else (sample["last_p"] or ord_p)
                    if is_locked_buy_queue or traded_after >= user_qty:
                        sig_rec["fill_verification_status"] = "VERIFIED_OPENING_AUCTION_FILL"
                        sig_rec["verified_exit_price_rials"] = actual_open_p
                    else:
                        sig_rec["fill_verification_status"] = "ADJUSTED_TO_OPENING_BID"
                        sig_rec["verified_exit_price_rials"] = actual_open_p
                    sig_rec["verified_fill_time"] = now_ms_str
                    self._recompute_verified_financials(sig_rec, tr)
                    changed = True
            else:
                if elapsed_since_sig >= 1.0:
                    if (sample["buy_p"] >= ord_p and sample["raw_buy_q"] >= user_qty) or (traded_after >= user_qty):
                        sig_rec["fill_verification_status"] = "VERIFIED_100PCT_CEILING_FILL"
                        sig_rec["verified_exit_price_rials"] = ord_p
                        sig_rec["verified_fill_time"] = now_ms_str
                        changed = True
                        print(
                            f"  [✓ راستی‌آزمایی پر شدن در هسته] سفارش فروش صوری {sig_rec['symbol_name']} ({user_qty:,} سهم @ {ord_p:,} ریال) "
                            f"در ساعت {now_ms_str} با قطعیت ۱۰۰٪ تأیید شد (حجم معامله‌شده پس از شلیک: {traded_after:,} سهم | صف باقی‌مانده: {sample['raw_buy_q']:,} سهم)."
                        )
                    elif elapsed_since_sig >= 5.0:
                        fallback_p = sample["buy_p"] if sample["buy_p"] > 0 else (sample["last_p"] or ord_p)
                        if traded_after > 0 and traded_after < user_qty:
                            fill_ratio = traded_after / float(user_qty)
                            blended_p = int(round(ord_p * fill_ratio + fallback_p * (1.0 - fill_ratio)))
                            sig_rec["fill_verification_status"] = f"PARTIAL_CEILING_BLENDED_{int(fill_ratio*100)}PCT"
                            sig_rec["verified_exit_price_rials"] = blended_p
                        else:
                            sig_rec["fill_verification_status"] = "ADJUSTED_TO_NEXT_BID_LEVEL"
                            sig_rec["verified_exit_price_rials"] = fallback_p
                        sig_rec["verified_fill_time"] = now_ms_str
                        self._recompute_verified_financials(sig_rec, tr)
                        changed = True
                        print(
                            f"  [i راستی‌آزمایی واقع‌گرایانه] سفارش فروش صوری {sig_rec['symbol_name']} با قیمت مؤثر واقعی "
                            f"{sig_rec['verified_exit_price_rials']:,} ریال ({sig_rec['fill_verification_status']}) ثبت نهایی شد."
                        )

        curr_mark_p = sample["buy_p"] if sample["buy_p"] > 0 else sample["last_p"]
        if curr_mark_p > 0:
            if curr_mark_p < int(sig_rec.get("min_price_after_exit") or curr_mark_p):
                sig_rec["min_price_after_exit"] = curr_mark_p
            if curr_mark_p > int(sig_rec.get("max_price_after_exit") or curr_mark_p):
                sig_rec["max_price_after_exit"] = curr_mark_p
            sig_rec["last_price_1230"] = curr_mark_p
            if sample["close_p"] > 0:
                sig_rec["close_price_1230"] = sample["close_p"]

            ver_exit_p = int(sig_rec.get("verified_exit_price_rials") or sig_rec["order_price_rials"])
            user_qty = int(sig_rec["user_quantity"])
            saved_rials = int(round((ver_exit_p - curr_mark_p) * user_qty * (1.0 - tr["sell_comm_rate"])))
            saved_pct = ((ver_exit_p - curr_mark_p) / float(ver_exit_p)) * 100.0 if ver_exit_p > 0 else 0.0
            sig_rec["saved_profit_vs_1230_rials"] = saved_rials
            sig_rec["saved_profit_vs_1230_tomans"] = round(saved_rials / 10.0)
            sig_rec["saved_profit_vs_1230_pct"] = round(saved_pct, 2)

        if not sig_rec.get("re_locked_buy_queue") and elapsed_since_sig >= 15.0:
            prev_peak = max(1, int(sig_rec.get("peak_buy_queue_vol") or 1))
            if is_locked_buy_queue and sample["buy_q"] >= int(prev_peak * RELOCK_MIN_RATIO_OF_PREV_PEAK):
                if sig_rec.get("re_lock_candidate_since_ts") is None:
                    sig_rec["re_lock_candidate_since_ts"] = now_ts
                elif (now_ts - float(sig_rec["re_lock_candidate_since_ts"])) >= RELOCK_SUSTAIN_SECONDS:
                    sig_rec["re_locked_buy_queue"] = True
                    sig_rec["re_lock_time"] = now_ms_str
                    changed = True
                    print(
                        f"  [🔄 هشدار قفل مجدد صف خرید (Re-Lock)] نماد {sig_rec['symbol_name']} در ساعت {now_ms_str} "
                        f"مجدداً با حجم {sample['buy_q']:,} سهم در صف خرید قفل شد (تله نوسانی بازیگردان)."
                    )
            else:
                sig_rec["re_lock_candidate_since_ts"] = None

        if changed:
            save_guardian_state(self.sim_state)
            upsert_signal_to_csv(sig_rec)
            try:
                request_gdrive_sync_async()
            except Exception:
                pass

    @staticmethod
    def _recompute_verified_financials(sig_rec, tr):
        ver_p = int(sig_rec["verified_exit_price_rials"])
        qty = int(sig_rec["user_quantity"])
        gross = int(round(ver_p * qty))
        comm = int(round(gross * tr["sell_comm_rate"]))
        net_proc = gross - comm
        cost = int(round(tr["breakeven_price"] * qty))
        net_prof = net_proc - cost
        net_pct = ((net_proc - cost) / float(cost)) * 100.0 if cost > 0 else 0.0
        sig_rec["net_proceeds_rials"] = net_proc
        sig_rec["net_realized_profit_rials"] = net_prof
        sig_rec["net_realized_profit_tomans"] = round(net_prof / 10.0)
        sig_rec["net_realized_profit_pct"] = round(net_pct, 2)


# ==============================================================================
# ۷. ذخیره‌سازی اتمیک وضعیت پایدار، جدول CSV و گزارش تحلیلی پایان بازار
# ==============================================================================
def load_guardian_state():
    today_str = get_tehran_now().strftime("%Y-%m-%d")
    default_state = {
        "last_run_date": today_str,
        "today_signals_by_isin": {},
        "historical_signals": [],
    }
    if os.path.exists(GUARDIAN_STATE_JSON):
        try:
            with _LOCAL_FILE_LOCK:
                with open(GUARDIAN_STATE_JSON, "r", encoding="utf-8") as f:
                    data = json.load(f)
            if isinstance(data, dict):
                td_sigs = data.get("today_signals_by_isin") or {}
                for k_isin in list(td_sigs.keys()):
                    s_obj = td_sigs[k_isin]
                    if isinstance(s_obj, dict) and (
                        s_obj.get("signal_id") in ("SHIELD1-20261114-085114-0001", "SHIELD1-20261117-092046-0001")
                        or (
                            s_obj.get("trigger_layer") == "PREMARKET_NO_QUEUE_FAILSAFE"
                            and int(s_obj.get("peak_buy_queue_vol") or 0) == 0
                            and int(s_obj.get("remaining_queue_at_signal") or 0) > 1000000
                        )
                        or (
                            s_obj.get("trigger_layer") == "LAYER5_SARKHATI_NO_QUEUE_FAILSAFE"
                            and "بهترین خرید تابلو: 0 ریال | فروشنده: 0 @ 0" in str(s_obj.get("notes") or "")
                        )
                    ):
                        del td_sigs[k_isin]
                if data.get("last_run_date") != today_str:
                    old_sigs = data.get("today_signals_by_isin") or {}
                    hist = data.get("historical_signals") or []
                    for _, s_val in old_sigs.items():
                        hist.append(s_val)
                    data["historical_signals"] = hist[-200:]
                    data["today_signals_by_isin"] = {}
                    data["last_run_date"] = today_str
                return data
        except Exception:
            pass
    return default_state


def save_guardian_state(sim_state):
    try:
        tmp_path = GUARDIAN_STATE_JSON + ".tmp"
        with _LOCAL_FILE_LOCK:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(sim_state, f, ensure_ascii=False, indent=2)
                f.flush()
            os.replace(tmp_path, GUARDIAN_STATE_JSON)
    except Exception:
        pass


def upsert_signal_to_csv(sig_rec):
    with _LOCAL_FILE_LOCK:
        rows_by_id = {}
        order_ids = []
        if os.path.exists(GUARDIAN_SIGNALS_CSV):
            try:
                with open(GUARDIAN_SIGNALS_CSV, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        sid = r.get("signal_id")
                        if sid:
                            if sid not in rows_by_id:
                                order_ids.append(sid)
                            rows_by_id[sid] = r
            except Exception:
                pass

        sid = sig_rec["signal_id"]
        if sid not in rows_by_id:
            order_ids.append(sid)
        clean_row = {col: sig_rec.get(col, "") for col in CSV_COLUMNS}
        rows_by_id[sid] = clean_row

        try:
            tmp_csv = GUARDIAN_SIGNALS_CSV + ".tmp"
            with open(tmp_csv, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writeheader()
                for k in order_ids:
                    writer.writerow(rows_by_id[k])
                f.flush()
            os.replace(tmp_csv, GUARDIAN_SIGNALS_CSV)
        except Exception:
            pass


def print_periodic_and_final_summary(shield_tracker, sim_state, title_prefix="گزارش وضعیت لحظه‌ای"):
    now_ir = get_tehran_now().strftime("%Y-%m-%d %H:%M:%S")
    exited_map = sim_state.get("today_signals_by_isin") or {}
    print(
        f"\n{'='*92}\n"
        f"=== {title_prefix} سپر اول نگهبان پرتفوی ({now_ir} IRST) | سیگنال‌های فروش صوری امروز: {len(exited_map)} ===\n"
        f"{'='*92}"
    )
    for isin, tr in shield_tracker.trackers.items():
        hist = tr["history_samples"]
        last_s = hist[-1] if hist else {}
        curr_q = int(last_s.get("buy_q") or 0)
        peak_q = max(tr["peak_buy_queue_vol"], tr["premarket_peak_queue_vol"])
        drop_pct = (((peak_q - curr_q) / float(peak_q)) * 100.0) if peak_q > 0 else 0.0

        if isin in exited_map:
            sig = exited_map[isin]
            upsert_signal_to_csv(sig)
            print(
                f"  [فروخته‌شده در حالت صوری] {tr['name']} ({isin}) | لایه شلیک: {sig['trigger_layer']} در ساعت {sig['signal_time']}\n"
                f"      - قیمت فروش تأییدشده: {sig['verified_exit_price_rials']:,} ریال ({sig['fill_verification_status']}) | سود خالص قفل‌شده: {sig['net_realized_profit_tomans']:+,} تومان ({sig['net_realized_profit_pct']:+.2f}%)\n"
                f"      - قیمت فعلی/پایان بازار: {sig['last_price_1230']:,} ریال (کف پس از فروش: {sig['min_price_after_exit']:,}) | سود محافظت‌شده از ریزش: {sig['saved_profit_vs_1230_tomans']:+,} تومان ({sig['saved_profit_vs_1230_pct']:+.2f}%)\n"
                f"      - وضعیت قفل مجدد صف خرید پس از فروش: {'بله (در ساعت ' + sig['re_lock_time'] + ')' if sig['re_locked_buy_queue'] else 'خیر (خروج موفق در قله)'}"
            )
        else:
            if tr.get("is_halted_or_closed"):
                status_tag = f"⏸️ متوقف/بسته توسط ناظر بازار ({tr.get('state_title_fa', 'ممنوع/متوقف')} — کد: {tr.get('state_code', 'IS')})"
            elif curr_q > 0:
                status_tag = "قفل در صف خرید امن (SAFE_LOCKED)"
            else:
                status_tag = "بدون صف خرید"
            print(
                f"  [در حال نگه‌داری و رصد] {tr['name']} ({isin}) | نوع: {'سرخطی/صف روز قبل' if tr['is_sarkhati_stock'] else 'عادی'} | وضعیت: {status_tag}\n"
                f"      - صف خرید فعلی: {curr_q:,} سهم | اوج صف امروز: {peak_q:,} سهم (افت از اوج: {drop_pct:.1f}%) | حذف‌های صوری نادیده‌گرفته‌شده: {tr['fake_cancel_ignored_count']} مورد"
            )
    print("=" * 92)


def main():
    sim_state = None

    def _handle_sigterm(signum, frame):
        raise KeyboardInterrupt("SIGTERM received")

    try:
        signal.signal(signal.SIGTERM, _handle_sigterm)
    except Exception:
        pass

    try:
        pull_files_from_gdrive_on_startup()
    except Exception:
        pass

    tee_logger = GuardianTeeLogger(sys.stdout, GUARDIAN_LOG_TXT)
    sys.stdout = tee_logger
    try:
        now_ir = get_tehran_now()
        is_manual_dispatch = (
            os.environ.get("GITHUB_EVENT_NAME", "") in ("workflow_dispatch", "push")
            or os.environ.get("FORCE_RUN_ON_WEEKEND") == "1"
        )
        if now_ir.weekday() in (3, 4) and not is_manual_dispatch:
            print("[*] امروز پنج‌شنبه/جمعه (تعطیل رسمی بورس ایران) است؛ اجرای خودکار بسته می‌شود.")
            return

        print(
            f"[+] سپر اول نگهبان پرتفوی (نسخه ۲.۱ — حالت ۱۰۰٪ صوری/تست بدون ارسال سفارش واقعی | "
            f"لاگ روزانه: {GDRIVE_LOGS_SUBFOLDER_NAME}/{GUARDIAN_LOG_FILENAME} | سینک ایمن غیرمسدودکننده)"
        )
        tok_ok, tok_msg = ensure_valid_token()
        print(f"[{'+' if tok_ok else '!'}] وضعیت توکن احراز هویت کارگزاری مفید: {tok_msg}")
        if not tok_ok:
            return

        headers = build_headers()
        session = configure_persistent_session(requests.Session())
        try:
            session.post(SAME_LOGIN_URL, data=b"{}", headers=headers, timeout=2.5)
        except Exception:
            pass

        sim_state = load_guardian_state()
        portfolio_map = discover_and_classify_portfolio(session, headers)
        print_startup_portfolio_report(portfolio_map)

        if not portfolio_map:
            save_guardian_state(sim_state)
            return

        shield_tracker = BuyQueueShieldTracker(portfolio_map, sim_state)
        isins_list = list(portfolio_map.keys())

        try:
            r_init = session.post(MARKET_DATA_V2_URL, data=json.dumps(isins_list).encode("utf-8"), headers=headers, timeout=4.0)
            if r_init.status_code == 200 and r_init.text:
                for item in (r_init.json() or []):
                    if isinstance(item, dict) and item.get("symbolIsin"):
                        isin_k = str(item["symbolIsin"])
                        shield_tracker.update_deep_telemetry_if_due(session, headers, isin_k)
                        shield_tracker.process_snapshot_and_evaluate(isin_k, item, get_tehran_now())
        except Exception:
            pass

        now_str = get_tehran_now().strftime("%H:%M:%S")
        if now_str > MARKET_CLOSE_TIME_STR or (now_ir.weekday() in (3, 4)):
            print(
                f"\n[*] ساعت فعلی تهران ({now_str}) خارج از بازه معاملات زنده بورس ({PREMARKET_START_TIME_STR} تا {MARKET_CLOSE_TIME_STR}) است.\n"
                f"    اسکن تشخیصی پرتفوی، بررسی کندل‌های روزهای اخیر و همگام‌سازی با گوگل درایو با موفقیت انجام شد."
            )
            print_periodic_and_final_summary(shield_tracker, sim_state, title_prefix="گزارش تشخیصی خارج از ساعت بازار")
            save_guardian_state(sim_state)
            return

        print(
            f"\n[*] حلقه پایش زنده «سپر اول نگهبان پرتفوی» (حالت صوری) فعال شد:\n"
            f"    - بازه پیش‌گشایش سهام سرخطی: {PREMARKET_START_TIME_STR} تا {CONTINUOUS_START_TIME_STR}\n"
            f"    - بازه بازار پیوسته (ماتریس ۵ لایه‌ای): {CONTINUOUS_START_TIME_STR} تا {MARKET_CLOSE_TIME_STR}\n"
            f"    - فرکانس نمونه‌برداری: هر {PORTFOLIO_POLL_INTERVAL_SEC} ثانیه روی {len(isins_list)} نماد پرتفوی..."
        )

        last_status_ts = time.time()
        last_gdrive_sync_ts = time.time()
        last_token_check_ts = time.time()

        while True:
            now_ir = get_tehran_now()
            now_str = now_ir.strftime("%H:%M:%S")

            if now_str > MARKET_CLOSE_TIME_STR:
                print(f"\n[+] پایان ساعت معاملات بازار ({now_str} IRST)؛ جمع‌بندی نهایی عملکرد سپر اول نگهبان پرتفوی...")
                print_periodic_and_final_summary(shield_tracker, sim_state, title_prefix="گزارش نهایی پایان بازار (۱۲:۳۰)")
                save_guardian_state(sim_state)
                break

            if time.time() - last_token_check_ts >= 900.0:
                ensure_valid_token()
                headers = build_headers()
                last_token_check_ts = time.time()

            if now_str < "08:44:50":
                if time.time() - last_status_ts >= 60.0:
                    print(f"[{now_str} IRST] در انتظار شروع سفارش‌گیری پیش‌گشایش ({PREMARKET_START_TIME_STR})...")
                    last_status_ts = time.time()
                time.sleep(2.0)
                continue

            try:
                r_md = session.post(
                    MARKET_DATA_V2_URL,
                    data=json.dumps(isins_list).encode("utf-8"),
                    headers=headers,
                    timeout=2.0,
                )
                if r_md.status_code == 200 and r_md.text:
                    items = r_md.json() or []
                    if isinstance(items, list):
                        get_h = {k: v for k, v in headers.items() if k.lower() != "content-type"}
                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            isin_k = str(item.get("symbolIsin") or "")
                            if isin_k in shield_tracker.trackers:
                                try:
                                    r_ms_live = session.get(MARKET_SHEET_ALL_URL_TPL.format(isin=isin_k), headers=get_h, timeout=0.9)
                                    if r_ms_live.status_code == 200 and r_ms_live.text:
                                        ms_live = r_ms_live.json() or {}
                                        b_sh = [x for x in (ms_live.get("buySheets") or []) if isinstance(x, dict) and int(x.get("volume") or 0) > 0]
                                        s_sh = [x for x in (ms_live.get("sellSheets") or []) if isinstance(x, dict) and int(x.get("volume") or 0) > 0]
                                        if b_sh:
                                            b_sh.sort(key=lambda x: int(x.get("price") or 0), reverse=True)
                                            item["bestBuyPrice"] = int(b_sh[0].get("price") or 0)
                                            item["bestBuyQuantity"] = int(b_sh[0].get("volume") or 0)
                                            shield_tracker.trackers[isin_k]["market_maker_vol_logged"] = int(b_sh[0].get("marketMaker") or 0)
                                        else:
                                            item["bestBuyPrice"] = 0
                                            item["bestBuyQuantity"] = 0
                                        if s_sh:
                                            s_sh.sort(key=lambda x: int(x.get("price") or 0))
                                            item["bestSellPrice"] = int(s_sh[0].get("price") or 0)
                                            item["bestSellQuantity"] = int(s_sh[0].get("volume") or 0)
                                        else:
                                            item["bestSellPrice"] = 0
                                            item["bestSellQuantity"] = 0
                                except Exception:
                                    pass
                                shield_tracker.update_deep_telemetry_if_due(session, headers, isin_k)
                                shield_tracker.process_snapshot_and_evaluate(isin_k, item, now_ir)
            except Exception:
                pass

            if time.time() - last_status_ts >= 300.0:
                print_periodic_and_final_summary(shield_tracker, sim_state)
                last_status_ts = time.time()

            if time.time() - last_gdrive_sync_ts >= 300.0:
                try:
                    save_guardian_state(sim_state)
                    tee_logger.flush()
                    request_gdrive_sync_async()
                except Exception:
                    pass
                last_gdrive_sync_ts = time.time()

            time.sleep(PORTFOLIO_POLL_INTERVAL_SEC)

    except KeyboardInterrupt:
        print("\n[!] اجرای نگهبان پرتفوی متوقف شد؛ ذخیره وضعیت نهایی و همگام‌سازی با گوگل درایو...")
    finally:
        sys.stdout = tee_logger.orig_stream
        tee_logger.close()
        try:
            if sim_state is not None:
                save_guardian_state(sim_state)
            flush_and_wait_gdrive_sync(timeout=35.0)
        except Exception:
            pass


if __name__ == "__main__":
    main()
