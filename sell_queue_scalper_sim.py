import base64
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
import time
import concurrent.futures
import threading
import urllib.parse
import requests
from requests.adapters import HTTPAdapter

# ==============================================================================
# ۱. تنظیمات اصلی ربات شکارچی ریزش صف فروش و نوسان‌گیر کف (نسخه تست صوری / Paper Trading)
# ==============================================================================
# حالت شبیه‌سازی (True = فقط ثبت صوری معاملات روی داده‌های ۱۰۰٪ واقعی بازار بدون ارسال سفارش واقعی)
SIMULATION_MODE = True

# مشخصات کارگزاری مفید برای خواندن یا تمدید خودکار توکن (مشترک با فایل token.txt)
MOFID_USERNAME = os.environ.get("MOFID_USERNAME", "").strip() or "09138156671"
MOFID_PASSWORD = os.environ.get("MOFID_PASSWORD", "").strip() or "Asasmofid88"
MIN_TOKEN_VALIDITY_MINUTES = 45
AUTH_TOKEN = ""

# تنظیمات مدیریت سرمایه و هدف سود بهینه‌شده (نسخه ۳ — بهبود نسبت سود به کارمزد + تریلینگ تا صف خرید + صف فروش شناور):
CAPITAL_FRACTION_PER_TRADE = 1.0 / 3.0  # اختصاص معادل یک‌سوم (۱/۳) سرمایه پایه به هر معامله (حدود ۱۰۰ میلیون تومان)
MAX_CONCURRENT_POSITIONS = 50  # در حالت تست صوری: تا ۵۰ پوزیشن همزمان آزاد است تا هیچ سیگنالی به خاطر پر بودن اسلات‌ها از دست نرود
UNLIMITED_VIRTUAL_CASH_IN_SIM = True  # در حالت صوری: تخصیص بودجه مجازی مستقل (۱/۳ سرمایه پایه) به هر سیگنال حتی در صورت قفل بودن نقدینگی در پوزیشن‌های قبلی
TARGET_NET_PROFIT_PCT_EQUITY = 0.0120  # هدف سود خالص موج دوم برای سهام پرشتاب: +1.20% خالص پس از کسر کارمزد (همراه با تریلینگ پویا تا سقف روزانه +4.8% خالص)
TARGET_NET_PROFIT_PCT_ETF = 0.0075  # هدف سود خالص موج دوم برای صندوق‌های ETF: +0.75% خالص
TARGET_NET_PROFIT_PCT = TARGET_NET_PROFIT_PCT_EQUITY  # مقدار پیش‌فرض مرجع
SAFE_PROFIT_ARM_NET_PCT_EQUITY = 0.0010  # مرحله ۱ (نقطه سر‌به‌سر کارمزد کارگزاری + ۰.۱۰٪ سود خالص = ~۱.۳۵٪ رشد از کف): به محض پوشش کارمزد، معامله قفل شده و ارزیابی شتاب انجام می‌شود
SAFE_PROFIT_ARM_NET_PCT_ETF = 0.0010  # مرحله ۱ در صندوق‌ها: پوشش کامل کارمزد کارگزاری + ۰.۱۰٪ سود خالص
NEAR_TARGET_HIGH_PROFIT_NET_PCT = 0.0065  # قفل سود حساس نزدیک هدف (وقتی سهم به +0.65% سود خالص رسید، با کوچک‌ترین برگشت ۰.۲۰٪ سود را قفل می‌کند)
NEAR_TARGET_PULLBACK_PCT = 0.20  # حداکثر عقب‌نشینی مجاز وقتی سهم در یک‌قدمی هدف قرار دارد
TRAILING_PROFIT_ARM_PROGRESS_RATIO = 0.20  # فعال‌سازی فوری محافظ کارمزد به محض عبور از نقطه سر‌به‌سر کارمزد
TRAILING_PROFIT_PULLBACK_PCT = 0.22  # درصد عقب‌نشینی از قله در مرحله ۱ برای قفل سود بالای کارمزد
FAST_SURGE_MAX_SECONDS_TO_BREAKEVEN = 480.0  # اگر سهم ظرف کمتر از ۸ دقیقه از کف به بالای نقطه کارمزد برسد و تقاضا قوی باشد، وارد موج صعودی (+1.2% تا +4.8%) می‌شود؛ وگرنه در همان نقطه کارمزد+ سود سیو می‌شود
STAGNANT_POSITION_BREAKEVEN_SEC = 720.0  # اگر پس از ۱۲ دقیقه هنوز به هدف نرسیده باشد، هدف فروش روی نقطه سر‌به‌سر کارمزد (۰.۰٪ خالص) می‌آید
STAGNANT_POSITION_MAX_HOLD_SEC = 1200.0  # حداکثر زمان نگهداری پوزیشن راکد بدون رشد (۲۰ دقیقه)؛ خروج در بهترین تقاضای تابلو برای جلوگیری از قفل شدن سرمایه
EOD_BREAKEVEN_MODE_TIME_STR = "12:00:00"  # از ساعت ۱۲:۰۰ به بعد، هدف تمام پوزیشن‌های باز به نقطه سر‌به‌سر کارمزد کاهش می‌یابد
EOD_MANDATORY_FLATTEN_TIME_STR = "12:22:00"  # تسویه قطعی و اجباری تمام پوزیشن‌های باز در ساعت ۱۲:۲۲ تا در پایان بازار (۱۲:۳۰) هیچ پوزیشن بازی باقی نماند (۰ پوزیشن باز)
MAX_ALLOWED_DAILY_BAND_PCT_EQUITY = 7.5  # حداکثر دامنه نوسان مجاز روزانه برای سهام عادی (حذف نمادهای بازگشایی بدون دامنه مثل لسرما -28%)
MAX_ALLOWED_DAILY_BAND_PCT_ETF = 11.5  # حداکثر دامنه نوسان مجاز روزانه برای صندوق‌ها
FLOATING_WALL_STOP_LOSS_GROSS_PCT = 1.20  # حد ضرر اضطراری در استراتژی دیوار عرضه شناور (خروج فوری در صورت افت ۱.۲۰٪ زیر قیمت خرید برای جلوگیری از قفل در صف فروش)
AUTO_ARCHIVE_PREV_DAY_OPEN_POSITIONS = True  # آرشیو و بستن خودکار پوزیشن‌های باز مانده از روزهای قبل در ابتدای اجرا (همراه با گزارش وضعیت آن‌ها) تا تست روز جدید مختل نشود
TRAILING_ABOVE_TARGET_PULLBACK_PCT = 0.45  # درصد عقب‌نشینی از قله در مرحله ۲ (بالاتر از هدف پایه +1.2%) برای دنبال کردن موج صعودی تا صف خرید (+6.15%)
MIN_BUY_QUEUE_HOLD_RATIO = 0.60  # در صورت قفل شدن سهم در صف خرید سقف روزانه (+3%)، نگهداری پوزیشن تا زمانی که حداقل ۶۰٪ اوج صف خرید پابرجاست
FALLBACK_TOTAL_CAPITAL_RIALS = 3000000000  # سرمایه پیش‌فرض شبیه‌سازی (۳ میلیارد ریال = ۳۰۰ میلیون تومان) در صورتی که موجودی نقد حساب صفر باشد
USE_ACTUAL_ACCOUNT_BALANCE = True  # خواندن موجودی واقعی حساب از سرور مفید (در صورت وجود موجودی کافی)

# پارامترهای الگوریتم تشخیص «ریزش پرشتاب صف فروش کف» و «صف فروش شناور (دیوار عرضه سنگین)» (نسخه ۴ — ویژه پهنای باند نامحدود و اتصال پایدار):
HIGH_BANDWIDTH_CLOUD_MODE = True  # حالت پهنای باند نامحدود ابری/گیت‌هاب: اسکن موازی کل بازار با استخر اتصال پایدار (Keep-Alive Pool)
BROAD_SCAN_INTERVAL_SEC = 1.0  # اسکن سراسری کل بازار هر ۱.۰ ثانیه (۲.۵ برابر سریع‌تر از نسخه قبلی)
FAST_WATCH_INTERVAL_SEC = 0.25  # رصد فوق‌سریع نمادهای در آستانه فروریزی هر ۰.۲۵ ثانیه (۴ بار در ثانیه!)
FULL_MARKET_MAP_REFRESH_SEC = 4.0  # به‌روزرسانی نقشه کل بازار هر ۴ ثانیه (به جای ۳۰ ثانیه) برای کشف آنی هر صف فروش یا دیوار عرضه جدید
PARALLEL_BATCH_WORKERS = 8  # تعداد تردهای موازی برای دریافت همزمان دسته‌های ۱۰۰ تایی marketdata/v2 در کسری از ثانیه
MIN_INITIAL_SELL_QUEUE_VALUE_RIALS = 4000000000  # حداقل ارزش اوج صف فروش برای سهام (۴ میلیارد ریال = ۴۰۰ میلیون تومان؛ جلوگیری از صف‌های کم‌عمق مثل کمینا)
MIN_INITIAL_SELL_QUEUE_VALUE_ETF_RIALS = 2000000000  # حداقل ارزش اوج صف فروش برای صندوق‌های ETF (۲ میلیارد ریال = ۲۰۰ میلیون تومان)
MIN_PEAK_QUEUE_TO_BUDGET_RATIO = 4.0  # ارزش اوج صف فروش سهام باید حداقل ۴ برابر بودجه خرید ربات باشد تا سفارش ما بخش عمده صف نباشد
MIN_QUEUE_DROP_PCT_FROM_PEAK = 85.0  # ورود در صف‌های عادی: حداقل ۸۵٪ صف فروش نسبت به اوج صف خورده شده باشد
HEAVY_QUEUE_VALUE_THRESHOLD_RIALS = 50000000000  # آستانه صف فروش سنگین (۵۰ میلیارد ریال = ۵ میلیارد تومان؛ مثل کپارس ۱۵.۶ میلیارد تومانی)
HEAVY_QUEUE_MIN_DROP_PCT_FROM_PEAK = 78.0  # در صف‌های سنگین (>= ۵ میلیارد تومان)، ورود از ۷۸٪ ریزش مجاز است تا قبل از بلعیده شدن یک‌ضرب تیک آخر جا نمانیم
HEAVY_QUEUE_MAX_REMAINING_VALUE_RIALS = 30000000000  # حداکثر ارزش ریالی باقی‌مانده صف در حالت ورود ۷۸٪ صف‌های سنگین (۳ میلیارد تومان)
MAX_TRADES_PER_SYMBOL_PER_DAY = 1  # حداکثر ۱ بار شکار برای هر نماد در هر روز معاملاتی (حذف ۱۰۰٪ تله ورود دوم مثل معامله ساعت 09:29 لخانه)
MAX_REMAINING_QUEUE_RATIO = 0.15  # حجم باقی‌مانده صف فروش در لحظه ورود حداکثر ۱۵٪ اوج صف باشد
MIN_DEPLETION_PCT_PER_SEC = 2.8  # حداقل سرعت آب رفتن صف فروش در بازه ۸۵٪ تا ۸۸٪ ریزش
MIN_DEPLETION_PCT_PER_SEC_DEEP_DROP = 1.75  # حداقل سرعت آب رفتن صف فروش برای صف‌های با ریزش ۸۸٪ تا ۹۳٪
MIN_DEPLETION_PCT_PER_SEC_ULTRA_DEEP = 1.10  # حداقل سرعت برای صف‌هایی که >= ۹۳٪ با معامله واقعی جمع شده‌اند و کمتر از ۳.۵ ثانیه به اتمام صف مانده است
ULTRA_DEEP_MIN_BUY_POWER_EQUITY = 0.30  # حداقل قدرت خریدار حقیقی در حالت ریزش فوق‌عمیق >= ۹۳٪ (چون ind-inst روی سرور مفید ۱ تا ۲ دقیقه کش دارد)
SWOLLEN_SECOND_WAVE_RATIO = 2.50  # تشخیص صف متورم بار دوم (>= 2.5x موج اول)
SWOLLEN_WAVE_MIN_DROP_PCT = 93.0  # در صف متورم بار دوم، حداقل ۹۳٪ صف باید جمع شده باشد
SWOLLEN_WAVE_MIN_BUY_POWER = 0.45  # در صف متورم بار دوم با ریزش >= ۹۳٪ و معامله واقعی، جبران کش ۱ دقیقه‌ای ind-inst
SHORT_BURST_WINDOW_SEC = 8.0  # پنجره کوتاه ۸ ثانیه آخر برای سنجش شتاب لحظه آخر فروریزی صف
ACTIVE_MOMENTUM_WINDOW_SEC = 5.2  # پنجره ضدتوهم سرعت (۵.۲ ثانیه اخیر): هماهنگ با گام به‌روزرسانی ۴ ثانیه‌ای marketdata/v2 هسته مفید
MIN_SAMPLES_BEFORE_ENTRY = 5  # حداقل ۵ نمونه متوالی در صف فروش قبل از صدور سیگنال خرید
MIN_TRACKING_DURATION_SEC = 4.5  # حداقل ۴.۵ ثانیه رصد مستمر نماد قبل از صدور سیگنال خرید
MAX_ESTIMATED_SECONDS_TO_WIPEOUT = 4.5  # حداکثر زمان تخمینی تا بلعیده شدن کامل صف فروش با سرعت فعلی (۴.۵ ثانیه — ورود دقیق در لحظه آخر)
MIN_REAL_TRADE_MATCH_RATIO = 0.70  # حداقل نسبت حجم معامله واقعی به حجم کاسته‌شده از صف (حداقل ۷۰٪ باید خرید واقعی باشد نه حذف صوری سفارش)
MIN_INDIVIDUAL_BUY_POWER_RATIO_EQUITY = 1.00  # حداقل قدرت خریدار حقیقی پایه برای سهام عادی (>= 1.00)
MIN_INDIVIDUAL_BUY_POWER_RATIO_ETF = 0.85  # حداقل قدرت خریدار حقیقی برای صندوق‌های ETF در صف فروش کف
MIN_INDIVIDUAL_BUY_POWER_RATIO = 1.00  # مقدار پیش‌فرض مرجع
INSTITUTIONAL_SUPPORT_MIN_SHARE = 0.25  # حمایت حقوقی فقط زمانی پذیرفته می‌شود که حداقل ۲۵٪ خرید واقعی باشد و حداقل ۹۳٪ صف جمع شده باشد
INSTITUTIONAL_SUPPORT_MIN_IND_POWER = 0.55  # کف قدرت خریدار حقیقی در حضور حمایت فعال حقوقی و ریزش >= ۹۳٪ صف (حذف تله‌های ضعیف مثل کپارس ۰.۴۶ و شفارا ۰.۶۷ در ۸۷٪)
EXPLOSIVE_SWEEP_MIN_VEL_PCT = 6.5  # سرعت جارو شدن انفجاری موج اول (>= 6.5%/s با خرید واقعی >= 90% و ریزش >= 93% — شکار درازک و خنور)
EXPLOSIVE_SWEEP_MIN_IND_POWER = 0.60  # کف قدرت خریدار حقیقی در جارو شدن انفجاری >= ۹۳٪ موج اول
MAX_OVERHEAD_SUPPLY_RATIO = 0.25  # فیلتر «خلأ فروشنده بالای کف» (Order-Book Supply Vacuum): حجم عرضه ۵ پله بالا تا قیمت هدف حداکثر ۲۵٪ اوج صف فروش باشد (مثل درازک و داروند)

# تنظیمات موتور «صف فروش شناور / دیوار عرضه سنگین» (فعلاً غیرفعال طبق نقشه راه ۴ مرحله‌ای برای تمرکز ۱۰۰٪ روی صف فروش کف روزانه):
ENABLE_FLOATING_SELL_QUEUE = False  # غیرفعال (False): تمرکز ۱۰۰٪ روی شکار دقیق صف‌های فروش واقعی در کف روزانه (FLOOR_SELL_QUEUE)
MIN_FLOATING_WALL_VALUE_ETF_RIALS = 3000000000  # حداقل ارزش دیوار فروش شناور در صندوق‌های ETF (۳ میلیارد ریال = ۳۰۰ میلیون تومان)
MIN_FLOATING_WALL_VALUE_EQUITY_RIALS = 6000000000  # حداقل ارزش دیوار فروش شناور در سهام (۶ میلیارد ریال = ۶۰۰ میلیون تومان)
FLOATING_WALL_MIN_ASK_BID_RATIO = 6.0  # حجم دیوار فروش در بهترین مظنه فروش باید حداقل ۶ برابر حجم بهترین تقاضای خرید باشد
MIN_FLOATING_WALL_DROP_PCT = 65.0  # حداقل ۶۵٪ دیوار فروش شناور در همان قیمت باید بلعیده شده باشد
MAX_FLOATING_WALL_REMAINING_RATIO = 0.32  # حداکثر ۳۲٪ از اوج دیوار فروش شناور باقی مانده باشد
MIN_FLOATING_WALL_DEPLETION_PCT_PER_SEC = 3.0  # حداقل سرعت خورده شدن دیوار فروش شناور (۳.۰٪ در ثانیه)
MIN_FLOATING_WALL_REAL_TRADE_RATIO = 0.75  # حداقل ۷۵٪ کاهش دیوار فروش شناور باید با معاملات واقعی (نه حذف سفارش) انجام شده باشد
FLOATING_WALL_MAX_BAND_POSITION_ETF = 0.70  # دیوار فروش شناور صندوق حداکثر تا ۷۰٪ بازه نوسان روزانه (از کف تا سقف) باشد تا جای رشد کافی تا سقف داشته باشد
FLOATING_WALL_MAX_BAND_POSITION_EQUITY = 0.55  # دیوار فروش شناور سهام حداکثر تا ۵۵٪ بازه نوسان روزانه (نیمه پایینی دامنه) باشد

# بازه زمانی مجاز شکار در ساعات رسمی بازار (پرهیز از ۲ دقیقه اول بازگشایی و ۲۵ دقیقه پایانی بازار برای جلوگیری از قفل شدن آخر وقت مثل کمینا):
MARKET_START_TIME_STR = "09:02:00"
NEW_ENTRY_CUTOFF_TIME_STR = "12:00:00"
MARKET_CLOSE_TIME_STR = "12:30:00"
RUN_OUTSIDE_MARKET_HOURS_FOR_DIAGNOSTIC = True  # اگر خارج از ساعت بازار اجرا شود، یک دور اسکن تشخیصی کامل روی کل بازار انجام می‌دهد و منتظر ۰۹:۰۰ می‌ماند

# ==============================================================================
# ۲. مسیر فایل‌های خروجی، لاگ و وضعیت پایدار (در همان پوشه اسکریپت - BASE_DIR)
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = BASE_DIR
TOKEN_FILE = os.path.join(BASE_DIR, "token.txt")
COOKIES_CACHE_FILE = os.path.join(DATA_DIR, "emofid_sso_cookies.json")

TODAY_LOG_DATE_STR = datetime.datetime.now().strftime("%Y-%m-%d")
SIM_LOG_FILENAME = f"sell_queue_sim_log_{TODAY_LOG_DATE_STR}.txt"
GDRIVE_LOGS_SUBFOLDER_NAME = "logs"

SIM_LOG_TXT = os.path.join(DATA_DIR, SIM_LOG_FILENAME)
SIM_TRADES_CSV = os.path.join(DATA_DIR, "sell_queue_sim_trades.csv")
SIM_STATE_JSON = os.path.join(DATA_DIR, "sell_queue_sim_state.json")

# ==============================================================================
# ۲.۵. ماژول همگام‌سازی خودکار، ضدبازنویسی و غیرمسدودکننده با گوگل درایو
# ==============================================================================
DEFAULT_GDRIVE_FOLDER_ID = "1RmnUrwKYhy2FYQUlcsaTX6nXhIgDzvXv"
SARKHATI_SHARED_FOLDER_ID = "1n0cW933TdKQRczVB0wunYtMrDRLbKXQn"
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
            params={
                "q": q,
                "fields": "files(id, name, modifiedTime)",
                "orderBy": "modifiedTime desc",
                "pageSize": 5,
            },
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
            boundary = "===GDriveSyncBoundary7MA4YWxkTrZu0gW==="
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


def pull_cumulative_files_from_gdrive_on_startup():
    global _STATE_SYNC_INITIALIZED
    access_token, folder_id = _get_gdrive_access_token()
    if not access_token:
        return False
    synced_any = False

    # ۱) فایل‌های تجمعی اصلی در پوشه ریشه
    for fname, local_path in (
        ("sell_queue_sim_state.json", SIM_STATE_JSON),
        ("sell_queue_sim_trades.csv", SIM_TRADES_CSV),
        ("token.txt", TOKEN_FILE),
    ):
        ok_f, fid = _gdrive_find_file_id_checked(access_token, folder_id, fname)
        if not ok_f:
            continue
        if not fid:
            if fname == "sell_queue_sim_state.json":
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
                if fname == "sell_queue_sim_state.json":
                    _STATE_SYNC_INITIALIZED = True
            except Exception:
                pass

    # ۲) فایل لاگ امروز از پوشه logs (در صورت اجرای مجدد در همان روز)
    ok_dir, logs_fid = _gdrive_find_or_create_subfolder(access_token, folder_id, GDRIVE_LOGS_SUBFOLDER_NAME)
    if ok_dir and logs_fid:
        ok_l, fid_l = _gdrive_find_file_id_checked(access_token, logs_fid, SIM_LOG_FILENAME)
        if ok_l and fid_l:
            remote_log = _gdrive_download_text(access_token, fid_l)
            if remote_log and remote_log.strip():
                try:
                    with _LOCAL_FILE_LOCK:
                        if not os.path.exists(SIM_LOG_TXT) or len(remote_log.encode("utf-8")) >= os.path.getsize(SIM_LOG_TXT):
                            tmp_l = SIM_LOG_TXT + ".pull.tmp"
                            with open(tmp_l, "w", encoding="utf-8") as f:
                                f.write(remote_log)
                            os.replace(tmp_l, SIM_LOG_TXT)
                            synced_any = True
                except Exception:
                    pass

    if synced_any:
        print(f"[+] همگام‌سازی اولیه با گوگل درایو (لاگ روزانه: {GDRIVE_LOGS_SUBFOLDER_NAME}/{SIM_LOG_FILENAME}) با موفقیت انجام شد.")
    return synced_any


def push_cumulative_files_to_gdrive():
    global _STATE_SYNC_INITIALIZED
    access_token, folder_id = _get_gdrive_access_token()
    if not access_token:
        return False

    st_txt = None
    local_csv = None
    local_log = None
    with _LOCAL_FILE_LOCK:
        if os.path.exists(SIM_STATE_JSON):
            try:
                with open(SIM_STATE_JSON, "r", encoding="utf-8") as f:
                    st_txt = f.read()
            except Exception:
                st_txt = None
        if os.path.exists(SIM_TRADES_CSV):
            try:
                with open(SIM_TRADES_CSV, "r", encoding="utf-8-sig") as f:
                    local_csv = f.read()
            except Exception:
                local_csv = None
    if os.path.exists(SIM_LOG_TXT):
        try:
            with open(SIM_LOG_TXT, "r", encoding="utf-8", errors="replace") as f:
                local_log = f.read()
        except Exception:
            local_log = None

    # ۱) آپلود امن sell_queue_sim_state.json (محافظت در برابر بازنویسی با state عقب‌تر)
    if st_txt and st_txt.strip():
        try:
            ok_st, fid_st = _gdrive_find_file_id_checked(access_token, folder_id, "sell_queue_sim_state.json")
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
                            if int(r_obj.get("closed_trades_count") or 0) > int(l_obj.get("closed_trades_count") or 0):
                                allow_upload_state = False
                            else:
                                _STATE_SYNC_INITIALIZED = True
                        except Exception:
                            allow_upload_state = False
                if allow_upload_state:
                    _gdrive_upload_text(
                        access_token, folder_id, "sell_queue_sim_state.json", st_txt, "application/json", known_file_id=fid_st
                    )
        except Exception:
            pass

    # ۲) آپلود و ادغام امن sell_queue_sim_trades.csv (اگر دانلود نسخه درایو خطا داد، بازنویسی متوقف می‌شود)
    if local_csv and local_csv.strip():
        try:
            ok_csv, fid_csv = _gdrive_find_file_id_checked(access_token, folder_id, "sell_queue_sim_trades.csv")
            if ok_csv:
                remote_csv = _gdrive_download_text(access_token, fid_csv) if fid_csv else ""
                if fid_csv and remote_csv is None:
                    pass
                else:
                    if remote_csv and remote_csv.strip():
                        r_lines = [ln for ln in remote_csv.lstrip("\ufeff").splitlines() if ln.strip()]
                        l_lines = [ln for ln in local_csv.lstrip("\ufeff").splitlines() if ln.strip()]
                        header = l_lines[0] if l_lines else (r_lines[0] if r_lines else "")
                        seen_ids = set()
                        merged_rows = [header] if header else []
                        for src_lines in (r_lines[1:], l_lines[1:]):
                            for row_ln in src_lines:
                                tid = row_ln.split(",", 1)[0].strip()
                                if tid and tid not in seen_ids:
                                    seen_ids.add(tid)
                                    merged_rows.append(row_ln)
                        final_csv = "\ufeff" + "\n".join(merged_rows) + "\n"
                    else:
                        final_csv = local_csv
                    _gdrive_upload_text(
                        access_token, folder_id, "sell_queue_sim_trades.csv", final_csv, "text/csv", known_file_id=fid_csv
                    )
        except Exception:
            pass

    # ۳) آپلود امن لاگ روزانه سبک در پوشه logs
    if local_log and local_log.strip():
        try:
            ok_dir, logs_fid = _gdrive_find_or_create_subfolder(access_token, folder_id, GDRIVE_LOGS_SUBFOLDER_NAME)
            if ok_dir and logs_fid:
                ok_log, fid_log = _gdrive_find_file_id_checked(access_token, logs_fid, SIM_LOG_FILENAME)
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
                            access_token, logs_fid, SIM_LOG_FILENAME, combined_log, "text/plain", known_file_id=fid_log
                        )
        except Exception:
            pass

    return True


def _gdrive_sync_worker():
    global _GDRIVE_SYNC_ACTIVE, _GDRIVE_SYNC_PENDING
    while True:
        with _GDRIVE_SYNC_LOCK:
            try:
                push_cumulative_files_to_gdrive()
            except Exception:
                pass
        with _GDRIVE_SYNC_STATE_LOCK:
            if _GDRIVE_SYNC_PENDING:
                _GDRIVE_SYNC_PENDING = False
                continue
            _GDRIVE_SYNC_ACTIVE = False
            break


def request_gdrive_sync_async():
    """اجرای غیرمسدودکننده سینک درایو با صف تجمیعی و ترد غیر-daemon برای جلوگیری از قطع ناقص"""
    global _GDRIVE_SYNC_ACTIVE, _GDRIVE_SYNC_PENDING, _GDRIVE_SYNC_THREAD
    with _GDRIVE_SYNC_STATE_LOCK:
        if _GDRIVE_SYNC_ACTIVE:
            _GDRIVE_SYNC_PENDING = True
            return
        _GDRIVE_SYNC_ACTIVE = True
        _GDRIVE_SYNC_PENDING = False
        t = threading.Thread(target=_gdrive_sync_worker, name="GDriveSafeSync", daemon=False)
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
            push_cumulative_files_to_gdrive()
        except Exception:
            pass

# اندپوینت‌های رسمی کارگزاری مفید (Orbis + Atlas)
OIDC_ISSUER = "https://login.emofid.com"
OIDC_AUTHORIZE_URL = f"{OIDC_ISSUER}/connect/authorize"
OIDC_TOKEN_URL = f"{OIDC_ISSUER}/connect/token"
OIDC_CLIENT_ID = "easy_pkce"
OIDC_REDIRECT_URI = "https://m.easytrader.ir/auth-callback"
OIDC_SCOPE = "easy2_api mts_api openid profile login_delegation-api"

API_BASE = "https://api-mts.orbis.easytrader.ir"
SELLING_QUEUE_URL = f"{API_BASE}/easy/api/market-live/selling-queue"
MOST_SUPPLY_URL = f"{API_BASE}/easy/api/market-live/most-supply"
MARKET_MAP_URL = f"{API_BASE}/symbols/api/MarketData/market-map"
MARKET_DATA_V2_URL = f"{API_BASE}/symbols/api/marketdata/v2"
SYMBOLS_ALL_URL = f"{API_BASE}/symbols/api/symbols/all"
MARKET_SHEET_ALL_URL_TPL = f"{API_BASE}/ms/api/MarketSheet/all/{{isin}}"
MARKET_SHEET_SUM_URL_TPL = f"{API_BASE}/ms/api/MarketSheet/sum/{{isin}}"
IND_INST_URL_TPL = f"{API_BASE}/easy/api/symbol-analysis/ind-inst?isin={{isin}}"
IND_INST_TRADE_POST_URL = f"{API_BASE}/symbols/api/MarketData/indInstTrade"
ACCOUNT_MONEY_URL = f"{API_BASE}/easy/api/money"
SAME_LOGIN_URL = f"{API_BASE}/easy/api/account/same-login"
START_SESSION_URL = f"{API_BASE}/easy/api/startsession"
ATLAS_SELLING_QUEUE_URL = (
    "https://mofidonline.com/apigateway/api/v1/SymbolHotList/SellingQueue"
)
ATLAS_SYMBOL_NAMES_URL = (
    "https://mofidonline.com/apigateway/api/v1/Symbols/SymbolNames"
)
ATLAS_REMAIN_URL = (
    "https://mofidonline.com/apigateway/api/v1/Accounting/Remain"
)

CSV_COLUMNS = [
    "trade_id",
    "date",
    "symbol_name",
    "symbol_isin",
    "market_type",
    "status",
    "entry_time",
    "buy_fill_time",
    "sell_order_time",
    "exit_time",
    "hold_duration_sec",
    "buy_price_rials",
    "target_sell_price_rials",
    "actual_exit_price_rials",
    "quantity",
    "buy_commission_rate",
    "sell_commission_rate",
    "gross_buy_Dynamic_rials",
    "buy_commission_rials",
    "total_buy_cost_rials",
    "gross_sell_value_rials",
    "sell_commission_rials",
    "net_sell_proceeds_rials",
    "net_profit_rials",
    "net_profit_tomans",
    "net_profit_pct",
    "peak_sell_queue_vol",
    "entry_sell_queue_vol",
    "queue_drop_pct_at_entry",
    "depletion_rate_pct_per_sec",
    "est_seconds_to_wipeout",
    "real_trade_match_ratio",
    "ind_buy_power_ratio",
    "volume_ahead_at_sell_price",
    "max_price_after_entry",
    "min_price_after_entry",
    "notes",
]


class SimTeeLogger:
    """ثبت همزمان خروجی ترمینال در فایل لاگ روزانه"""

    def __init__(self, orig_stream, log_path):
        self.orig_stream = orig_stream
        self.log_file = None
        self._lock = threading.Lock()
        try:
            self.log_file = open(log_path, "a", encoding="utf-8")
            self.log_file.write(
                f"\n{'='*78}\n=== شروع نشست شکارچی صف فروش (حالت صوری/تست) در تاریخ: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n{'='*78}\n"
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
# ۳. مدیریت خودکار توکن احراز هویت (اشتراک با token.txt بدون نیاز به مرورگر)
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
    code_verifier = (
        base64.urlsafe_b64encode(verifier_bytes).decode("ascii").rstrip("=")
    )
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = (
        base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    )
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
            user_Field = "Username"
            pass_Field = "Password"
            for k in list(form_data.keys()):
                kl = k.lower()
                if "user" in kl or "mobile" in kl or "phone" in kl:
                    user_Field = k
                elif "pass" in kl:
                    pass_Field = k
            form_data[user_Field] = str(MOFID_USERNAME).strip()
            form_data[pass_Field] = str(MOFID_PASSWORD).strip()
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


# ==============================================================================
# ۴. توابع دقیق محاسبه کارمزد، قیمت هدف فروش (+۰.۵٪ سود خالص) و پله قیمتی
# ==============================================================================
def get_default_commission_rates(isin_code):
    """نرخ‌های کارمزد خرید و فروش استاندارد در صورتی که سرور نرخ اختصاصی نماد را برنگرداند"""
    prefix = (isin_code or "").upper()[:4]
    if prefix == "IRO1":
        return 0.003712, 0.008800  # سهام بورس: خرید ۰.۳۷۱۲٪ | فروش ۰.۸۸٪ (شامل ۰.۵٪ مالیات)
    elif prefix in ("IRO3", "IRO7"):
        return 0.003632, 0.008720  # سهام فرابورس و پایه: خرید ۰.۳۶۳۲٪ | فروش ۰.۸۷۲٪
    elif prefix.startswith("IRT"):
        return 0.001160, 0.0011875  # صندوق‌های قابل معامله سهامی/اهرمی (خرید ۰.۱۱۶٪ و فروش ۰.۱۱۸۷۵٪؛ کل کارمزد ~۰.۲۳۵٪)
    return 0.003712, 0.008800


def get_symbol_target_net_profit_pct(isin_code, queue_mode="FLOOR_SELL_QUEUE"):
    """تعیین هدف سود خالص پایه بر اساس نوع ورقه (سهام یا صندوق کم‌کارمزد) و نوع صف"""
    is_etf = (isin_code or "").upper().startswith("IRT")
    if is_etf:
        return TARGET_NET_PROFIT_PCT_ETF
    if queue_mode == "FLOATING_ASK_WALL":
        return max(0.0100, TARGET_NET_PROFIT_PCT_EQUITY - 0.0020)
    return TARGET_NET_PROFIT_PCT_EQUITY


def get_symbol_safe_arm_net_pct(isin_code):
    """تعیین نقطه فعال‌سازی مرحله ۱ قفل سود امن (معادل هدف قدیمی +0.55% در سهام و +0.40% در صندوق‌ها)"""
    if (isin_code or "").upper().startswith("IRT"):
        return SAFE_PROFIT_ARM_NET_PCT_ETF
    return SAFE_PROFIT_ARM_NET_PCT_EQUITY


def detect_tick_size(price_val, isin_code, reported_tick=None):
    if reported_tick and int(reported_tick) > 0:
        return int(reported_tick)
    if (isin_code or "").upper().startswith("IRT"):
        return 1
    return 10 if int(price_val or 0) >= 1000 else 1


def compute_target_sell_price_for_net_profit(
    buy_price, buy_comm_rate, sell_comm_rate, target_net_pct, tick_size=10
):
    """
    محاسبه دقیق قیمت فروش به گونه‌ای که پس از کسر کامل کارمزد خرید و کارمزد فروش،
    حداقل target_net_pct (مثلاً +0.50% = 0.005) سود خالص به دست آید:
    NetProceeds = P_sell * (1 - sell_comm_rate)
    TotalCost = P_buy * (1 + buy_comm_rate)
    NetProceeds >= TotalCost * (1 + target_net_pct)
    => P_sell >= P_buy * (1 + buy_comm_rate) * (1 + target_net_pct) / (1 - sell_comm_rate)
    """
    raw_target = (
        float(buy_price)
        * (1.0 + float(buy_comm_rate))
        * (1.0 + float(target_net_pct))
        / max(0.0001, (1.0 - float(sell_comm_rate)))
    )
    tick = max(1, int(tick_size or 1))
    rounded_target = int(math.ceil((raw_target - 1e-9) / float(tick)) * tick)
    if rounded_target <= int(buy_price):
        rounded_target = int(buy_price) + tick
    return rounded_target


def compute_trade_financials(
    buy_price, sell_price, quantity, buy_comm_rate, sell_comm_rate
):
    """محاسبه ریال‌به‌ریال بهای تمام‌شده خرید، کارمزدها، خالص دریافتی فروش و سود خالص"""
    qty = int(quantity)
    bp = int(buy_price)
    sp = int(sell_price)
    gross_buy = bp * qty
    buy_comm = int(round(gross_buy * float(buy_comm_rate)))
    total_cost = gross_buy + buy_comm

    gross_sell = sp * qty
    sell_comm = int(round(gross_sell * float(sell_comm_rate)))
    net_proceeds = gross_sell - sell_comm

    net_profit_rials = net_proceeds - total_cost
    net_profit_pct = (
        (net_profit_rials / float(total_cost)) * 100.0 if total_cost > 0 else 0.0
    )
    return {
        "gross_buy_rials": gross_buy,
        "buy_comm_rials": buy_comm,
        "total_buy_cost_rials": total_cost,
        "gross_sell_rials": gross_sell,
        "sell_comm_rials": sell_comm,
        "net_sell_proceeds_rials": net_proceeds,
        "net_profit_rials": net_profit_rials,
        "net_profit_tomans": round(net_profit_rials / 10.0),
        "net_profit_pct": round(net_profit_pct, 3),
    }


# ==============================================================================
# ۵. مدیریت وضعیت پایدار پرتفوی شبیه‌سازی (ذخیره اتمیک و بازیابی بین روزهای مختلف)
# ==============================================================================
def load_sim_state():
    if os.path.exists(SIM_STATE_JSON):
        try:
            with _LOCAL_FILE_LOCK:
                with open(SIM_STATE_JSON, "r", encoding="utf-8") as f:
                    data = json.load(f)
            if isinstance(data, dict) and "open_positions" in data:
                return data
        except Exception:
            pass
    return {
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "initial_capital_rials": None,
        "available_cash_rials": None,
        "total_trades_count": 0,
        "closed_trades_count": 0,
        "win_trades_count": 0,
        "loss_trades_count": 0,
        "cumulative_realized_profit_rials": 0,
        "cumulative_commissions_paid_rials": 0,
        "open_positions": {},
        "completed_trades_summary": [],
    }


def save_sim_state(state):
    try:
        tmp_path = SIM_STATE_JSON + ".tmp"
        with _LOCAL_FILE_LOCK:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
                f.flush()
            os.replace(tmp_path, SIM_STATE_JSON)
    except Exception as e:
        print(f"[!] خطا در ذخیره وضعیت شبیه‌سازی: {e}")


def append_trade_to_csv(row_dict):
    try:
        with _LOCAL_FILE_LOCK:
            file_exists = os.path.exists(SIM_TRADES_CSV) and os.path.getsize(SIM_TRADES_CSV) > 0
            with open(SIM_TRADES_CSV, "a", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                if not file_exists:
                    writer.writeheader()
                clean_row = {k: row_dict.get(k, "") for k in CSV_COLUMNS}
                writer.writerow(clean_row)
                f.flush()
    except Exception as e:
        print(f"[!] خطا در ثبت فایل CSV معاملات صوری: {e}")

# ==============================================================================
# ۶. استعلام آنلاین موجودی حساب و اسکن سراسری تمام نمادهای بازار
# ==============================================================================
def fetch_real_account_balance_rials(session, headers):
    get_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
    if USE_ACTUAL_ACCOUNT_BALANCE and headers.get("Authorization"):
        try:
            resp = session.get(ACCOUNT_MONEY_URL, headers=get_headers, timeout=2.5)
            if resp.status_code == 200 and resp.text:
                m = resp.json()
                if isinstance(m, dict):
                    inner = m.get("data") if isinstance(m.get("data"), dict) else m
                    if isinstance(inner, dict):
                        bp_t2 = int(round(float(inner.get("buyPowerT2") or 0)))
                        block_t2 = max(0, int(round(float(inner.get("blockT2") or inner.get("block") or 0))))
                        avand_cr = max(0, int(round(float(inner.get("avandCredit") or 0))))
                        credit_cr = max(0, int(round(float(inner.get("credit") or inner.get("creditRemain") or 0))))
                        credit_val = avand_cr + credit_cr
                        if (bp_t2 + block_t2) >= credit_val and credit_val > 0:
                            cash_val = max(0, (bp_t2 + block_t2) - credit_val)
                        else:
                            cash_val = max(0, int(round(float(inner.get("buyPowerT0") or inner.get("t0") or inner.get("remain") or 0))))
                        total_power = max(0, bp_t2) if inner.get("buyPowerT2") is not None else max(0, cash_val + credit_val - block_t2)
                        if total_power >= 50000000:
                            blk_txt = f" - بلوکه شده: {block_t2:,}" if block_t2 > 0 else ""
                            return (
                                total_power,
                                f"قدرت خرید آزاد حساب کارگزاری مفید (مانده: {cash_val:,} + اعتبار آوند: {credit_val:,}{blk_txt} ریال)",
                            )
        except Exception:
            pass

        try:
            r_at = session.get(
                ATLAS_REMAIN_URL,
                headers={
                    "Authorization": headers.get("Authorization", ""),
                    "x-appname": "atlas",
                    "Accept": "application/json",
                },
                timeout=2.0,
            )
            if r_at.status_code == 200 and r_at.text:
                at_d = r_at.json()
                inner = at_d.get("data") if isinstance(at_d, dict) and isinstance(at_d.get("data"), dict) else at_d
                if isinstance(inner, dict):
                    real_bal = max(0, int(round(float(inner.get("realBalance") or 0))))
                    avand_cr = max(0, int(round(float(inner.get("avandCredit") or 0))))
                    credit_cr = max(0, int(round(float(inner.get("credit") or 0))))
                    blocked_bal = max(0, int(round(float(inner.get("blockedBalance") or 0))))
                    acc_bal = int(round(float(inner.get("accountBalance") or 0)))
                    tp = max(0, acc_bal) if inner.get("accountBalance") is not None else max(0, real_bal + avand_cr + credit_cr - blocked_bal)
                    if tp >= 50000000:
                        blk_txt = f" - بلوکه شده: {blocked_bal:,}" if blocked_bal > 0 else ""
                        return (
                            tp,
                            f"قدرت خرید آزاد حساب کارگزاری مفید (مانده: {real_bal:,} + اعتبار آوند: {avand_cr + credit_cr:,}{blk_txt} ریال)",
                        )
        except Exception:
            pass

    return FALLBACK_TOTAL_CAPITAL_RIALS, "سرمایه پیش‌فرض شبیه‌سازی (قابل تنظیم)"


def _is_valid_equity_or_etf_isin(isin, name=""):
    if not isin or len(isin) != 12:
        return False
    if not isin.startswith(("IRO1", "IRO3", "IRO7", "IRT1", "IRT3")):
        return False
    if not isin.endswith("0001"):
        return False
    if name:
        clean_n = str(name).strip()
        if clean_n.endswith("ح") or clean_n.startswith(("ض", "ط")):
            return False
    return True


def fetch_all_market_symbols_universe(session, headers):
    """
    دریافت ۱۰۰٪ آنلاین لیست کل نمادهای فعال سهام و صندوق‌ها از ۳ منبع موازی:
    ۱) POST /symbols/api/symbols/all (با پارامتر الزامی {"hash": ""} و خواندن کلید symbols)
    ۲) GET /apigateway/api/v1/Symbols/SymbolNames (درگاه اطلس مفیدآنلاین)
    ۳) GET /symbols/api/MarketData/market-map (نقشه زنده بازار ایزی‌تریدر)
    """
    universe = {}
    get_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}

    try:
        resp = session.post(
            SYMBOLS_ALL_URL,
            data=json.dumps({"hash": ""}).encode("utf-8"),
            headers=headers,
            timeout=3.5,
        )
        if resp.status_code == 200 and resp.text:
            data = json.loads(resp.text)
            sym_list = (
                data.get("symbols")
                if isinstance(data, dict)
                else (data if isinstance(data, list) else [])
            )
            if isinstance(sym_list, list):
                for item in sym_list:
                    if not isinstance(item, dict):
                        continue
                    isin = str(
                        item.get("symbolIsin")
                        or item.get("isin")
                        or item.get("symbolISIN")
                        or ""
                    ).strip()
                    name = str(
                        item.get("symbolName")
                        or item.get("Name")
                        or item.get("name")
                        or item.get("symbol")
                        or ""
                    ).strip()
                    if not _is_valid_equity_or_etf_isin(isin, name):
                        continue
                    universe[isin] = {
                        "symbolIsin": isin,
                        "symbolName": name or isin,
                        "maxValidBuyVolume": item.get("maxValidBuyVolume"),
                        "minValidBuyVolume": item.get("minValidBuyVolume") or 1,
                    }
    except Exception:
        pass

    try:
        r_at = session.get(
            ATLAS_SYMBOL_NAMES_URL,
            headers={"x-appname": "atlas", "Accept": "application/json"},
            timeout=3.5,
        )
        if r_at.status_code == 200 and r_at.text:
            sn_map = (
                json.loads(r_at.text).get("data", {}).get("symbolNames", {})
            )
            if isinstance(sn_map, dict):
                for isin, s_name in sn_map.items():
                    isin_s = str(isin or "").strip()
                    name_s = str(s_name or "").strip()
                    if not _is_valid_equity_or_etf_isin(isin_s, name_s):
                        continue
                    if isin_s not in universe:
                        universe[isin_s] = {
                            "symbolIsin": isin_s,
                            "symbolName": name_s or isin_s,
                            "maxValidBuyVolume": None,
                            "minValidBuyVolume": 1,
                        }
                    elif name_s and universe[isin_s].get("symbolName") == isin_s:
                        universe[isin_s]["symbolName"] = name_s
    except Exception:
        pass

    try:
        r_mm = session.get(MARKET_MAP_URL, headers=get_headers, timeout=3.0)
        if r_mm.status_code == 200 and r_mm.text:
            mm_list = json.loads(r_mm.text)
            if isinstance(mm_list, list):
                for item in mm_list:
                    if not isinstance(item, dict):
                        continue
                    isin_s = str(
                        item.get("symbolISIN") or item.get("symbolIsin") or ""
                    ).strip()
                    name_s = str(item.get("symbolName") or "").strip()
                    if not _is_valid_equity_or_etf_isin(isin_s, name_s):
                        continue
                    if isin_s not in universe:
                        universe[isin_s] = {
                            "symbolIsin": isin_s,
                            "symbolName": name_s or isin_s,
                            "maxValidBuyVolume": None,
                            "minValidBuyVolume": 1,
                        }
    except Exception:
        pass

    return universe


_LAST_FULL_MARKET_MAP_TS = 0.0
_CACHED_NEGATIVE_ISINS = set()
_THREAD_LOCAL_HTTP = threading.local()


def _get_thread_local_session():
    """تولید و نگهداری یک requests.Session ایزوله برای هر ترد در استخر موازی (تضمین Thread-Safety کامل)"""
    sess = getattr(_THREAD_LOCAL_HTTP, "session", None)
    if sess is None:
        sess = requests.Session()
        adapter = HTTPAdapter(pool_connections=16, pool_maxsize=16)
        sess.mount("https://", adapter)
        sess.mount("http://", adapter)
        _THREAD_LOCAL_HTTP.session = sess
    return sess


_SHARED_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=12)
_HOT_TELEMETRY_CACHE = {}
_LIVE_MARKET_REGIME = {
    "regime": "NEUTRAL",
    "regime_fa": "متعادل/خنثی",
    "positive_breadth_pct": 50.0,
    "equal_weight_index_pct": 0.0,
    "leveraged_etf_avg_pct": 0.0,
    "active_symbols_count": 0,
    "updated_ts": 0.0,
}
LEVERAGED_ETF_ISINS = {
    "IRT1AHRM0001",  # اهرم
    "IRT3TVAF0001",  # توان
    "IRT3MOJF0001",  # موج
    "IRT1SHTF0001",  # شتاب
    "IRT3JHSH0001",  # جهش
    "IRT1BIDR0001",  # بیدار
    "IRT1NRNJ0001",  # نارنج
}


def update_live_market_regime_from_map(market_map_list):
    """
    محاسبه زنده «رژیم کل بازار» (صعودی BULLISH / متعادل NEUTRAL / نزولی BEARISH)
    از روی نقشه لحظه‌ای کل بازار (market-map) بدون هیچ درخواست اضافی
    """
    global _LIVE_MARKET_REGIME
    if not isinstance(market_map_list, list) or not market_map_list:
        return _LIVE_MARKET_REGIME

    pos_cnt = 0
    neg_cnt = 0
    total_eq_cnt = 0
    sum_eq_var = 0.0
    lev_vars = []

    for x in market_map_list:
        if not isinstance(x, dict):
            continue
        isin = str(x.get("symbolISIN") or x.get("symbolIsin") or "").strip().upper()
        if not _is_valid_equity_or_etf_isin(isin):
            continue
        st_code = str(x.get("stateCode") or "").strip()
        last_p = int(x.get("lastTradedPrice") or 0)
        prev_p = int(x.get("feeOfPreviousDaysClosingPrice") or 0)
        if last_p <= 0 or (st_code and not st_code.startswith("A")):
            continue

        p_var = float(x.get("priceVar") or 0.0)
        if p_var == 0.0 and prev_p > 0 and last_p != prev_p:
            p_var = ((last_p - prev_p) / float(prev_p)) * 100.0

        if isin in LEVERAGED_ETF_ISINS:
            lev_vars.append(p_var)

        if not isin.startswith("IRT"):
            total_eq_cnt += 1
            sum_eq_var += p_var
            if p_var > 0.15:
                pos_cnt += 1
            elif p_var < -0.15:
                neg_cnt += 1

    if total_eq_cnt < 30:
        return _LIVE_MARKET_REGIME

    breadth_pct = round((pos_cnt / float(total_eq_cnt)) * 100.0, 1)
    eq_index_pct = round(sum_eq_var / float(total_eq_cnt), 2)
    lev_avg_pct = round(sum(lev_vars) / float(len(lev_vars)), 2) if lev_vars else eq_index_pct

    if breadth_pct < 33.0 or eq_index_pct <= -0.35 or (lev_avg_pct <= -1.0 and breadth_pct < 42.0):
        regime = "BEARISH"
        regime_fa = f"نزولی (مثبت‌ها: {breadth_pct:.0f}% | هم‌وزن: {eq_index_pct:+.2f}% | اهرمی‌ها: {lev_avg_pct:+.2f}%)"
    elif (breadth_pct >= 55.0 and eq_index_pct >= 0.35) or (lev_avg_pct >= 1.20 and breadth_pct >= 48.0):
        regime = "BULLISH"
        regime_fa = f"صعودی (مثبت‌ها: {breadth_pct:.0f}% | هم‌وزن: {eq_index_pct:+.2f}% | اهرمی‌ها: {lev_avg_pct:+.2f}%)"
    else:
        regime = "NEUTRAL"
        regime_fa = f"متعادل/خنثی (مثبت‌ها: {breadth_pct:.0f}% | هم‌وزن: {eq_index_pct:+.2f}% | اهرمی‌ها: {lev_avg_pct:+.2f}%)"

    _LIVE_MARKET_REGIME = {
        "regime": regime,
        "regime_fa": regime_fa,
        "positive_breadth_pct": breadth_pct,
        "equal_weight_index_pct": eq_index_pct,
        "leveraged_etf_avg_pct": lev_avg_pct,
        "active_symbols_count": total_eq_cnt,
        "updated_ts": time.time(),
    }
    return _LIVE_MARKET_REGIME


def configure_persistent_high_speed_session(session):
    adapter = HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=1)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"Connection": "keep-alive"})
    return session


def scan_selling_queue_candidates(
    session,
    headers,
    universe_map,
    tracked_isins=None,
    force_full_map=False,
):
    global _LAST_FULL_MARKET_MAP_TS, _CACHED_NEGATIVE_ISINS
    get_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
    get_headers["Accept-Encoding"] = "gzip, deflate"
    get_headers["Connection"] = "keep-alive"

    candidate_isins = set()
    if tracked_isins:
        candidate_isins.update(tracked_isins)

    def _fetch_orbis_list(url):
        found = set()
        try:
            r = _get_thread_local_session().get(url, headers=get_headers, timeout=1.8)
            if r.status_code == 200 and r.text:
                arr = r.json()
                if isinstance(arr, list):
                    for x in arr:
                        if isinstance(x, dict):
                            isin = str(x.get("symbolIsin") or x.get("symbolISIN") or "").strip()
                            if _is_valid_equity_or_etf_isin(isin):
                                found.add(isin)
        except Exception:
            pass
        return found

    def _fetch_atlas_list():
        found = set()
        try:
            r_at = _get_thread_local_session().get(
                ATLAS_SELLING_QUEUE_URL,
                headers={
                    "x-appname": "atlas",
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip, deflate",
                    "Connection": "keep-alive",
                },
                timeout=1.6,
            )
            if r_at.status_code == 200 and r_at.text:
                at_json = r_at.json()
                items = at_json.get("data") if isinstance(at_json, dict) else at_json
                if isinstance(items, list):
                    for x in items:
                        if isinstance(x, dict):
                            isin = str(x.get("symbolIsin") or x.get("isin") or "").strip()
                            if _is_valid_equity_or_etf_isin(isin):
                                found.add(isin)
        except Exception:
            pass
        return found

    f_sq = _SHARED_THREAD_POOL.submit(_fetch_orbis_list, SELLING_QUEUE_URL)
    f_ms = _SHARED_THREAD_POOL.submit(_fetch_orbis_list, MOST_SUPPLY_URL)
    f_at = _SHARED_THREAD_POOL.submit(_fetch_atlas_list)

    now_ts = time.time()
    map_active_isins = []
    if force_full_map or (now_ts - _LAST_FULL_MARKET_MAP_TS >= FULL_MARKET_MAP_REFRESH_SEC) or not _CACHED_NEGATIVE_ISINS:
        try:
            r_map = session.get(MARKET_MAP_URL, headers=get_headers, timeout=2.2)
            if r_map.status_code == 200 and r_map.text:
                m_arr = r_map.json()
                if isinstance(m_arr, list):
                    update_live_market_regime_from_map(m_arr)
                    new_watch = set()
                    for x in m_arr:
                        if not isinstance(x, dict):
                            continue
                        isin = str(x.get("symbolISIN") or x.get("symbolIsin") or "").strip()
                        if not _is_valid_equity_or_etf_isin(isin):
                            continue
                        st_code = str(x.get("stateCode") or "").strip()
                        p_var = float(x.get("priceVar") or 0.0)
                        last_p = int(x.get("lastTradedPrice") or 0)
                        close_p = int(x.get("closingPrice") or 0)
                        prev_p = int(x.get("feeOfPreviousDaysClosingPrice") or 0)
                        is_etf = isin.upper().startswith("IRT")

                        if p_var <= -0.5 or (prev_p > 0 and last_p > 0 and ((last_p - prev_p) / float(prev_p)) <= -0.005):
                            new_watch.add(isin)
                        elif ENABLE_FLOATING_SELL_QUEUE and is_etf and (st_code.startswith("A") or last_p > 0) and p_var <= 2.0:
                            new_watch.add(isin)
                        elif HIGH_BANDWIDTH_CLOUD_MODE and ENABLE_FLOATING_SELL_QUEUE and st_code.startswith("A") and last_p > 0 and p_var <= 0.8:
                            new_watch.add(isin)
                        elif st_code.startswith("A") or last_p > 0 or close_p > 0:
                            map_active_isins.append(isin)
                    _CACHED_NEGATIVE_ISINS = new_watch
                    _LAST_FULL_MARKET_MAP_TS = now_ts
        except Exception:
            pass

    for fut in (f_sq, f_ms, f_at):
        try:
            candidate_isins.update(fut.result(timeout=2.0))
        except Exception:
            pass

    candidate_isins.update(_CACHED_NEGATIVE_ISINS)

    if force_full_map and len(candidate_isins) < 50:
        if map_active_isins:
            candidate_isins.update(map_active_isins[:300])
        elif universe_map:
            candidate_isins.update(list(universe_map.keys())[:300])

    isin_list = sorted(candidate_isins)
    detailed_snapshots = {}
    batch_size = 100
    post_headers = dict(headers)
    post_headers["Accept-Encoding"] = "gzip, deflate"
    post_headers["Connection"] = "keep-alive"

    chunks = [isin_list[i : i + batch_size] for i in range(0, len(isin_list), batch_size)]

    def _fetch_v2_chunk(chunk_items):
        out = {}
        try:
            resp = _get_thread_local_session().post(
                MARKET_DATA_V2_URL,
                data=json.dumps(chunk_items).encode("utf-8"),
                headers=post_headers,
                timeout=2.2,
            )
            if resp.status_code == 200 and resp.text:
                arr = resp.json()
                if isinstance(arr, list):
                    for item in arr:
                        if isinstance(item, dict) and item.get("symbolIsin"):
                            out[str(item["symbolIsin"])] = item
        except Exception:
            pass
        return out

    if len(chunks) == 1:
        detailed_snapshots.update(_fetch_v2_chunk(chunks[0]))
    elif len(chunks) > 1:
        futures = [_SHARED_THREAD_POOL.submit(_fetch_v2_chunk, ch) for ch in chunks]
        try:
            for fut in concurrent.futures.as_completed(futures, timeout=4.5):
                try:
                    detailed_snapshots.update(fut.result())
                except Exception:
                    pass
        except Exception:
            pass

    return detailed_snapshots


def overlay_realtime_marketsheet_on_snapshots(session, headers, target_isins, snaps_dict):
    if not target_isins:
        return
    get_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
    get_headers["Accept-Encoding"] = "gzip, deflate"
    get_headers["Connection"] = "keep-alive"

    def _fetch_one_ms(isin_c):
        try:
            r = _get_thread_local_session().get(
                MARKET_SHEET_ALL_URL_TPL.format(isin=isin_c),
                headers=get_headers,
                timeout=0.9,
            )
            if r.status_code == 200 and r.text:
                return isin_c, r.json()
        except Exception:
            pass
        return isin_c, None

    futs = [_SHARED_THREAD_POOL.submit(_fetch_one_ms, isin_c) for isin_c in list(target_isins)[:12]]
    for f in futs:
        try:
            isin_c, ms = f.result(timeout=1.1)
            if not isinstance(ms, dict):
                continue
            snap = snaps_dict.get(isin_c)
            if not isinstance(snap, dict):
                continue
            s_sheets = [x for x in (ms.get("sellSheets") or []) if isinstance(x, dict) and int(x.get("volume") or 0) > 0]
            b_sheets = [x for x in (ms.get("buySheets") or []) if isinstance(x, dict) and int(x.get("volume") or 0) > 0]
            if s_sheets:
                s_sheets.sort(key=lambda x: int(x.get("price") or 0))
                snap["bestSellPrice"] = int(s_sheets[0].get("price") or 0)
                snap["bestSellQuantity"] = int(s_sheets[0].get("volume") or 0)
                snap["bestSellOrderCount"] = int(s_sheets[0].get("amount") or 0)
            else:
                snap["bestSellQuantity"] = 0
                snap["bestSellOrderCount"] = 0
            if b_sheets:
                b_sheets.sort(key=lambda x: int(x.get("price") or 0), reverse=True)
                snap["bestBuyPrice"] = int(b_sheets[0].get("price") or 0)
                snap["bestBuyQuantity"] = int(b_sheets[0].get("volume") or 0)
                snap["bestBuyOrderCount"] = int(b_sheets[0].get("amount") or 0)
            else:
                snap["bestBuyQuantity"] = 0
                snap["bestBuyOrderCount"] = 0
        except Exception:
            pass


def fetch_symbol_deep_telemetry(session, headers, isin_code):
    get_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
    get_headers["Accept-Encoding"] = "gzip, deflate"
    get_headers["Connection"] = "keep-alive"

    telemetry = {
        "ind_buy_power_ratio": 1.0,
        "live_window_ind_buy_power": 0.0,
        "live_window_ins_share": 0.0,
        "ind_buy_vol": 0,
        "ind_sell_vol": 0,
        "ins_buy_vol": 0,
        "ins_sell_vol": 0,
        "sell_sheets": [],
        "buy_sheets": [],
        "total_5lvl_buy_vol": 0,
        "total_5lvl_sell_vol": 0,
    }

    def _get_ind_inst():
        try:
            return _get_thread_local_session().get(
                IND_INST_URL_TPL.format(isin=isin_code), headers=get_headers, timeout=1.2
            )
        except Exception:
            return None

    def _get_ind_inst_desktop_3s():
        try:
            post_h = dict(headers)
            post_h["Content-Type"] = "application/json"
            return _get_thread_local_session().post(
                IND_INST_TRADE_POST_URL,
                data=json.dumps({"isin": isin_code}).encode("utf-8"),
                headers=post_h,
                timeout=1.1,
            )
        except Exception:
            return None

    def _get_market_sheet():
        try:
            return _get_thread_local_session().get(
                MARKET_SHEET_ALL_URL_TPL.format(isin=isin_code), headers=get_headers, timeout=1.2
            )
        except Exception:
            return None

    fut_ii = _SHARED_THREAD_POOL.submit(_get_ind_inst)
    fut_ii_3s = _SHARED_THREAD_POOL.submit(_get_ind_inst_desktop_3s)
    fut_ms = _SHARED_THREAD_POOL.submit(_get_market_sheet)

    try:
        r_ii = fut_ii.result(timeout=1.5)
        if r_ii is not None and r_ii.status_code == 200 and r_ii.text:
            arr = r_ii.json()
            if isinstance(arr, list) and len(arr) > 0 and isinstance(arr[0], dict):
                d = arr[0]
                telemetry["ind_buy_vol"] = int(d.get("indBuyVol") or 0)
                telemetry["ind_sell_vol"] = int(d.get("indSellVol") or 0)
                telemetry["ins_buy_vol"] = int(d.get("insBuyVol") or 0)
                telemetry["ins_sell_vol"] = int(d.get("insSellVol") or 0)
                buy_per = float(d.get("buyPerInd") or 0.0)
                sell_per = float(d.get("sellPerInd") or 0.0)
                raw_pow = float(d.get("indBuyPow") or 0.0)
                bid_pres = float(d.get("bidPres") or 0.0)
                telemetry["bid_pressure"] = round(bid_pres, 2)
                if sell_per > 0 and buy_per > 0:
                    telemetry["ind_buy_power_ratio"] = round(buy_per / sell_per, 2)
                elif raw_pow > 0:
                    telemetry["ind_buy_power_ratio"] = round(
                        raw_pow if raw_pow < 50.0 else (raw_pow / 100.0), 2
                    )

                now_t = time.time()
                prev_base = _HOT_TELEMETRY_CACHE.get(isin_code)
                if prev_base is None or (now_t - prev_base["ts"] > 180.0):
                    _HOT_TELEMETRY_CACHE[isin_code] = {
                        "ts": now_t,
                        "ind_buy_vol": telemetry["ind_buy_vol"],
                        "ins_buy_vol": telemetry["ins_buy_vol"],
                        "ind_buy_cnt": int(d.get("indBuyCount") or d.get("buyCountInd") or 0),
                        "ind_sell_cnt": int(d.get("indSellCount") or d.get("sellCountInd") or 0),
                    }
                else:
                    d_ind_buy = max(0, telemetry["ind_buy_vol"] - prev_base["ind_buy_vol"])
                    d_ins_buy = max(0, telemetry["ins_buy_vol"] - prev_base["ins_buy_vol"])
                    if (d_ind_buy + d_ins_buy) > 0:
                        telemetry["live_window_ins_share"] = round(
                            d_ins_buy / float(d_ind_buy + d_ins_buy), 2
                        )
    except Exception:
        pass

    try:
        r_ii3 = fut_ii_3s.result(timeout=1.3)
        if r_ii3 is not None and r_ii3.status_code == 200 and r_ii3.text:
            dt_3s = r_ii3.json()
            if isinstance(dt_3s, dict):
                ib_v3 = int(dt_3s.get("indBuyVolume") or 0)
                ib_n3 = int(dt_3s.get("indBuyNumber") or 0)
                is_v3 = int(dt_3s.get("indSellVolume") or 0)
                is_n3 = int(dt_3s.get("indSellNumber") or 0)
                ins_b3 = int(dt_3s.get("insBuyVolume") or 0)
                ins_s3 = int(dt_3s.get("insSellVolume") or 0)
                if ib_v3 > 0 and ib_n3 > 0 and is_v3 > 0 and is_n3 > 0:
                    pow_3s = round((ib_v3 / float(ib_n3)) / (is_v3 / float(is_n3)), 2)
                    telemetry["ind_buy_power_ratio"] = max(float(telemetry.get("ind_buy_power_ratio") or 0.0), pow_3s)
                    telemetry["ind_buy_power_3s_desktop"] = pow_3s
                telemetry["ind_buy_vol"] = max(telemetry["ind_buy_vol"], ib_v3)
                telemetry["ind_sell_vol"] = max(telemetry["ind_sell_vol"], is_v3)
                telemetry["ins_buy_vol"] = max(telemetry["ins_buy_vol"], ins_b3)
                telemetry["ins_sell_vol"] = max(telemetry["ins_sell_vol"], ins_s3)
    except Exception:
        pass

    try:
        r_ms = fut_ms.result(timeout=1.5)
        if r_ms is not None and r_ms.status_code == 200 and r_ms.text:
            ms = r_ms.json()
            if isinstance(ms, dict):
                s_sheets = ms.get("sellSheets") or []
                b_sheets = ms.get("buySheets") or []
                telemetry["sell_sheets"] = s_sheets
                telemetry["buy_sheets"] = b_sheets
                telemetry["total_5lvl_sell_vol"] = sum(
                    int(r.get("volume") or 0) for r in s_sheets if isinstance(r, dict)
                )
                telemetry["total_5lvl_buy_vol"] = sum(
                    int(r.get("volume") or 0) for r in b_sheets if isinstance(r, dict)
                )
                telemetry["total_5lvl_sell_cnt"] = sum(
                    int(r.get("amount") or 0) for r in s_sheets if isinstance(r, dict)
                )
                telemetry["total_5lvl_buy_cnt"] = sum(
                    int(r.get("amount") or 0) for r in b_sheets if isinstance(r, dict)
                )
    except Exception:
        pass

    return telemetry


# ==============================================================================
# ۷. موتور ردیاب سرعت ریزش صف فروش و شبیه‌ساز دقیق معاملات (Paper Trading Engine)
# ==============================================================================
class SellQueueCollapseTracker:
    def __init__(self, sim_state=None):
        self.history_by_isin = {}
        self.peak_queue_by_isin = {}
        self.first_wave_peak_by_isin = {}
        self.had_deep_drop_wave_by_isin = set()
        self.in_second_or_later_wave_by_isin = set()
        self.floating_wall_by_isin = {}
        self.rejection_log_ts = {}
        self.sim_state = sim_state
        if isinstance(sim_state, dict):
            today_str = datetime.datetime.now().strftime("%Y-%m-%d")
            if sim_state.get("peak_queues_date") == today_str and isinstance(sim_state.get("peak_queue_by_isin"), dict):
                for k, v in sim_state["peak_queue_by_isin"].items():
                    try:
                        if int(v) > 0:
                            self.peak_queue_by_isin[str(k)] = int(v)
                    except Exception:
                        pass

    def sync_peaks_to_state(self):
        if isinstance(self.sim_state, dict):
            self.sim_state["peak_queues_date"] = datetime.datetime.now().strftime("%Y-%m-%d")
            self.sim_state["peak_queue_by_isin"] = dict(self.peak_queue_by_isin)

    def seed_peak_only(self, isin, best_sell_price, low_allowed, best_sell_qty, best_buy_qty):
        if low_allowed > 0 and best_sell_price == low_allowed and best_sell_qty > 0 and best_buy_qty == 0:
            prev_p = self.peak_queue_by_isin.get(isin, 0)
            if best_sell_qty > prev_p:
                self.peak_queue_by_isin[isin] = best_sell_qty
                self.sync_peaks_to_state()

    def _update_floating_ask_wall(
        self,
        isin,
        now_ts,
        snap,
        universe_meta,
        low_allowed,
        high_allowed,
        last_price,
        close_price,
        best_sell_price,
        best_sell_qty,
        best_buy_price,
        best_buy_qty,
        total_traded,
        tick_size,
        buy_c,
        sell_c,
    ):
        if not ENABLE_FLOATING_SELL_QUEUE:
            return None
        if best_sell_price <= low_allowed or best_sell_qty <= 0 or best_sell_price >= high_allowed:
            self.floating_wall_by_isin.pop(isin, None)
            return None

        is_etf = isin.upper().startswith("IRT")
        mkt_regime = _LIVE_MARKET_REGIME.get("regime", "NEUTRAL")
        if mkt_regime == "BEARISH" and not is_etf:
            self.floating_wall_by_isin.pop(isin, None)
            return None

        band_span = max(1, high_allowed - low_allowed)
        band_pos = (best_sell_price - low_allowed) / float(band_span)
        if is_etf:
            if mkt_regime == "BEARISH":
                if band_pos < 0.06 or band_pos > 0.55 or last_price < best_sell_price:
                    self.floating_wall_by_isin.pop(isin, None)
                    return None
            else:
                max_band_pos = 0.75 if mkt_regime == "BULLISH" else 0.65
                if band_pos > max_band_pos:
                    self.floating_wall_by_isin.pop(isin, None)
                    return None
        else:
            max_band_pos = 0.60 if mkt_regime == "BULLISH" else 0.45
            if band_pos > max_band_pos:
                self.floating_wall_by_isin.pop(isin, None)
                return None

        target_net_pct = get_symbol_target_net_profit_pct(isin, queue_mode="FLOATING_ASK_WALL")
        target_sell_p = compute_target_sell_price_for_net_profit(
            best_sell_price, buy_c, sell_c, target_net_pct, tick_size=tick_size
        )
        if target_sell_p >= int(high_allowed * 0.996):
            self.floating_wall_by_isin.pop(isin, None)
            return None

        min_wall_val_rials = (
            MIN_FLOATING_WALL_VALUE_ETF_RIALS if is_etf else MIN_FLOATING_WALL_VALUE_EQUITY_RIALS
        )
        curr_wall_val_rials = best_sell_qty * best_sell_price
        ask_bid_ratio = best_sell_qty / float(max(1, best_buy_qty))

        wall_state = self.floating_wall_by_isin.get(isin)
        if wall_state is None or wall_state.get("wall_price") != best_sell_price:
            if curr_wall_val_rials >= min_wall_val_rials and ask_bid_ratio >= FLOATING_WALL_MIN_ASK_BID_RATIO:
                self.floating_wall_by_isin[isin] = {
                    "wall_price": best_sell_price,
                    "peak_vol": best_sell_qty,
                    "initial_ask_bid_ratio": round(ask_bid_ratio, 2),
                    "hist": [
                        {
                            "ts": now_ts,
                            "sell_q_vol": best_sell_qty,
                            "total_traded": total_traded,
                            "last_price": last_price,
                        }
                    ],
                }
            else:
                self.floating_wall_by_isin.pop(isin, None)
            return None

        hist = wall_state["hist"]
        hist.append(
            {
                "ts": now_ts,
                "sell_q_vol": best_sell_qty,
                "total_traded": total_traded,
                "last_price": last_price,
            }
        )
        hist[:] = [h for h in hist if now_ts - h["ts"] <= 45.0]
        if best_sell_qty > wall_state["peak_vol"]:
            wall_state["peak_vol"] = best_sell_qty
        if ask_bid_ratio > wall_state.get("initial_ask_bid_ratio", 0.0):
            wall_state["initial_ask_bid_ratio"] = round(ask_bid_ratio, 2)

        peak_vol = int(wall_state["peak_vol"])
        peak_val_rials = peak_vol * best_sell_price
        if peak_val_rials < min_wall_val_rials or len(hist) < 2:
            return None

        oldest = hist[0]
        dt_window = max(0.2, now_ts - oldest["ts"])
        vol_drop_window = oldest["sell_q_vol"] - best_sell_qty
        traded_delta_window = max(0, total_traded - oldest["total_traded"])

        short_candidates = [
            h for h in hist[:-1] if (now_ts - h["ts"]) <= SHORT_BURST_WINDOW_SEC and (now_ts - h["ts"]) >= 1.5
        ]
        short_ref = short_candidates[0] if short_candidates else oldest
        dt_short = max(0.2, now_ts - short_ref["ts"])
        vol_drop_short = short_ref["sell_q_vol"] - best_sell_qty
        traded_delta_short = max(0, total_traded - short_ref["total_traded"])

        active_refs = [
            h for h in hist[:-1] if (now_ts - h["ts"]) <= ACTIVE_MOMENTUM_WINDOW_SEC and (now_ts - h["ts"]) >= 0.35
        ]
        active_ref = active_refs[0] if active_refs else (hist[-2] if len(hist) >= 2 else oldest)
        recent_3s_drop = active_ref["sell_q_vol"] - best_sell_qty
        recent_3s_traded = max(0, total_traded - active_ref["total_traded"])
        short_match_ok = (vol_drop_short > 0 and (traded_delta_short / float(vol_drop_short)) >= 0.70)
        is_actively_draining_now = (recent_3s_drop > 0 and (recent_3s_traded > 0 or short_match_ok))

        drop_from_peak_pct = (
            ((peak_vol - best_sell_qty) / float(peak_vol)) * 100.0 if peak_vol > 0 else 0.0
        )
        rem_ratio = best_sell_qty / float(peak_vol) if peak_vol > 0 else 1.0

        vel_full = (
            ((vol_drop_window / float(peak_vol)) * 100.0) / dt_window
            if (peak_vol > 0 and vol_drop_window > 0)
            else 0.0
        )
        vel_short = (
            ((vol_drop_short / float(peak_vol)) * 100.0) / dt_short
            if (peak_vol > 0 and vol_drop_short > 0)
            else 0.0
        )
        depletion_pct_per_sec = max(vel_full, vel_short)

        burn_full = vol_drop_window / dt_window if vol_drop_window > 0 else 0.0
        burn_short = vol_drop_short / dt_short if vol_drop_short > 0 else 0.0
        burn_rate_shares_per_sec = max(burn_full, burn_short)
        est_sec_to_wipeout = (
            best_sell_qty / burn_rate_shares_per_sec if burn_rate_shares_per_sec > 0 else 999.0
        )

        match_full = (
            min(1.0, traded_delta_window / float(vol_drop_window)) if vol_drop_window > 0 else 0.0
        )
        match_short = (
            min(1.0, traded_delta_short / float(vol_drop_short)) if vol_drop_short > 0 else 0.0
        )
        real_trade_match_ratio = max(match_full, match_short)

        sym_name = (
            (universe_meta or {}).get("symbolName")
            or str(snap.get("symbolName") or snap.get("symbolFa") or isin)
        )
        max_valid_buy = int(
            snap.get("maxValidBuyVolume")
            or (universe_meta or {}).get("maxValidBuyVolume")
            or 100000
        )

        return {
            "isin": isin,
            "symbol_name": sym_name,
            "queue_mode": "FLOATING_ASK_WALL",
            "entry_price": best_sell_price,
            "low_allowed": low_allowed,
            "high_allowed": high_allowed,
            "last_price": last_price,
            "close_price": close_price,
            "tick_size": tick_size,
            "buy_comm_rate": buy_c,
            "sell_comm_rate": sell_c,
            "target_net_profit_pct": target_net_pct,
            "target_sell_price": target_sell_p,
            "required_gross_bounce_pct": round(
                ((target_sell_p - best_sell_price) / float(best_sell_price)) * 100.0, 2
            ),
            "peak_sell_queue_vol": peak_vol,
            "current_sell_queue_vol": best_sell_qty,
            "drop_from_peak_pct": round(drop_from_peak_pct, 1),
            "remaining_queue_ratio": round(rem_ratio, 3),
            "depletion_pct_per_sec": round(depletion_pct_per_sec, 2),
            "burn_rate_shares_per_sec": round(burn_rate_shares_per_sec),
            "est_sec_to_wipeout": round(est_sec_to_wipeout, 1),
            "real_trade_match_ratio": round(real_trade_match_ratio, 2),
            "max_valid_buy_vol": max_valid_buy,
            "total_traded_shares": total_traded,
            "samples_count": len(hist),
            "tracking_duration_sec": round(dt_window, 1),
            "first_wave_peak_vol": peak_vol,
            "is_swollen_second_wave": False,
            "swollen_wave_ratio": 1.0,
            "initial_ask_bid_ratio": wall_state.get("initial_ask_bid_ratio", 0.0),
            "recent_3s_drop": recent_3s_drop,
            "recent_3s_traded": recent_3s_traded,
            "is_actively_draining_now": is_actively_draining_now,
        }

    def update_symbol_snapshot(self, isin, snap, universe_meta=None):
        now_ts = time.time()
        state_code = str(snap.get("stateCode") or snap.get("symbolState") or "").strip()
        if state_code and not state_code.startswith("A"):
            return None

        low_allowed = int(snap.get("lowAllowedPrice") or 0)
        high_allowed = int(snap.get("highAllowedPrice") or 0)
        last_price = int(snap.get("lastTradedPrice") or 0)
        close_price = int(snap.get("closingPrice") or snap.get("closePrice") or 0)
        best_sell_price = int(
            snap.get("bestSellPrice") or snap.get("topSellPrice") or 0
        )
        best_sell_qty = int(
            snap.get("bestSellQuantity") or snap.get("topSellVolume") or 0
        )
        best_buy_qty = int(
            snap.get("bestBuyQuantity") or snap.get("topBuyVolume") or 0
        )
        best_buy_price = int(
            snap.get("bestBuyPrice") or snap.get("topBuyPrice") or 0
        )
        total_traded = int(snap.get("totalNumberOfSharesTraded") or 0)
        tick_size = detect_tick_size(
            low_allowed, isin, snap.get("priceTickSize")
        )

        if low_allowed <= 0 or high_allowed <= low_allowed:
            return None
        daily_band_pct = ((high_allowed - low_allowed) / float(low_allowed)) * 100.0
        max_allowed_band = (
            MAX_ALLOWED_DAILY_BAND_PCT_ETF
            if isin.upper().startswith("IRT")
            else MAX_ALLOWED_DAILY_BAND_PCT_EQUITY
        )
        if daily_band_pct > max_allowed_band:
            return None

        def_buy_c, def_sell_c = get_default_commission_rates(isin)
        try:
            buy_c = float(snap.get("buyRatio") or 0.0)
            if buy_c <= 0 or buy_c > 0.02:
                buy_c = def_buy_c
        except Exception:
            buy_c = def_buy_c
        try:
            sell_c = float(snap.get("sellRatio") or 0.0)
            if sell_c <= 0 or sell_c > 0.02:
                sell_c = def_sell_c
        except Exception:
            sell_c = def_sell_c

        target_net_pct = get_symbol_target_net_profit_pct(isin, queue_mode="FLOOR_SELL_QUEUE")
        target_sell_p = compute_target_sell_price_for_net_profit(
            low_allowed, buy_c, sell_c, target_net_pct, tick_size=tick_size
        )

        is_in_sell_queue = (
            best_sell_price == low_allowed
            and best_sell_qty > 0
            and best_buy_qty == 0
        )

        hist = self.history_by_isin.setdefault(isin, [])
        if is_in_sell_queue:
            self.floating_wall_by_isin.pop(isin, None)
            if target_sell_p >= int(high_allowed * 0.996):
                return None

            hist.append(
                {
                    "ts": now_ts,
                    "sell_q_vol": best_sell_qty,
                    "total_traded": total_traded,
                    "last_price": last_price,
                }
            )
            hist[:] = [h for h in hist if now_ts - h["ts"] <= 45.0]

            prev_peak = self.peak_queue_by_isin.get(isin, 0)
            min_valid_q_val = (
                MIN_INITIAL_SELL_QUEUE_VALUE_ETF_RIALS
                if isin.upper().startswith("IRT")
                else MIN_INITIAL_SELL_QUEUE_VALUE_RIALS
            )
            prev_peak_was_valid = (prev_peak * low_allowed) >= min_valid_q_val
            if prev_peak_was_valid and isin in self.had_deep_drop_wave_by_isin and best_sell_qty >= prev_peak * 0.60:
                self.in_second_or_later_wave_by_isin.add(isin)
            if prev_peak_was_valid and best_sell_qty <= prev_peak * 0.25:
                self.had_deep_drop_wave_by_isin.add(isin)
                if isin not in self.first_wave_peak_by_isin:
                    self.first_wave_peak_by_isin[isin] = prev_peak
            if best_sell_qty > prev_peak:
                if isin not in self.had_deep_drop_wave_by_isin:
                    self.first_wave_peak_by_isin[isin] = best_sell_qty
                elif prev_peak_was_valid and isin not in self.first_wave_peak_by_isin:
                    self.first_wave_peak_by_isin[isin] = prev_peak
                self.peak_queue_by_isin[isin] = best_sell_qty
                self.sync_peaks_to_state()
        else:
            prev_peak_w = self.peak_queue_by_isin.get(isin, 0)
            if (
                prev_peak_w > 0
                and len(hist) >= 3
                and (now_ts - hist[-1]["ts"]) <= 4.5
                and isin not in self.in_second_or_later_wave_by_isin
                and (best_sell_price == 0 or best_sell_price <= low_allowed + tick_size)
                and (last_price == low_allowed or (0 < best_buy_price <= low_allowed + tick_size))
            ):
                oldest_w = hist[0]
                last_q_vol_before_wipeout = int(hist[-1].get("sell_q_vol") or prev_peak_w) if hist else int(prev_peak_w)
                dt_w = max(0.25, now_ts - oldest_w["ts"])
                vol_drop_w = prev_peak_w
                traded_delta_w = max(0, total_traded - oldest_w["total_traded"])
                match_ratio_w = min(1.0, traded_delta_w / float(max(1, oldest_w["sell_q_vol"])))
                vel_w = 100.0 / dt_w
                self.had_deep_drop_wave_by_isin.add(isin)
                self.in_second_or_later_wave_by_isin.add(isin)
                hist.clear()
                self.sync_peaks_to_state()
                if match_ratio_w >= 0.80 and vel_w >= 2.2:
                    sym_name_w = (
                        (universe_meta or {}).get("symbolName")
                        or str(snap.get("symbolName") or isin)
                    )
                    return {
                        "isin": isin,
                        "symbol_name": sym_name_w,
                        "queue_mode": "FLOOR_SELL_QUEUE",
                        "low_allowed": low_allowed,
                        "high_allowed": high_allowed,
                        "entry_price": low_allowed if best_sell_price == low_allowed else (low_allowed + tick_size),
                        "last_price": last_price,
                        "closing_price": close_price,
                        "best_sell_price": best_sell_price,
                        "current_sell_queue_vol": max(best_sell_qty, last_q_vol_before_wipeout),
                        "peak_sell_queue_vol": prev_peak_w,
                        "first_wave_peak_vol": self.first_wave_peak_by_isin.get(isin, prev_peak_w),
                        "drop_from_peak_pct": 100.0,
                        "remaining_queue_ratio": 0.0,
                        "depletion_pct_per_sec": round(vel_w, 2),
                        "burn_rate_shares_per_sec": round(vol_drop_w / dt_w, 1),
                        "est_sec_to_wipeout": 0.0,
                        "real_trade_match_ratio": round(match_ratio_w, 2),
                        "total_traded_shares": total_traded,
                        "buy_comm_rate": buy_c,
                        "sell_comm_rate": sell_c,
                        "tick_size": tick_size,
                        "target_sell_price": target_sell_p,
                        "max_valid_buy_vol": int(
                            (universe_meta or {}).get("maxValidBuyVolume")
                            or snap.get("maxValidBuyVolume")
                            or 50000000
                        ),
                        "samples_count": max(MIN_SAMPLES_BEFORE_ENTRY, 5),
                        "tracking_duration_sec": round(max(MIN_TRACKING_DURATION_SEC, dt_w), 1),
                        "is_second_or_later_wave": False,
                        "is_swollen_second_wave": False,
                        "swollen_wave_ratio": 1.0,
                        "recent_3s_drop": oldest_w["sell_q_vol"],
                        "recent_3s_traded": traded_delta_w,
                        "is_actively_draining_now": True,
                    }
            if best_buy_price >= low_allowed and best_buy_qty > 0:
                min_valid_q_val = (
                    MIN_INITIAL_SELL_QUEUE_VALUE_ETF_RIALS
                    if isin.upper().startswith("IRT")
                    else MIN_INITIAL_SELL_QUEUE_VALUE_RIALS
                )
                if (prev_peak_w * low_allowed) >= min_valid_q_val:
                    self.had_deep_drop_wave_by_isin.add(isin)
                    self.in_second_or_later_wave_by_isin.add(isin)
                else:
                    self.peak_queue_by_isin[isin] = 0
                hist.clear()
                self.sync_peaks_to_state()
            return self._update_floating_ask_wall(
                isin,
                now_ts,
                snap,
                universe_meta,
                low_allowed,
                high_allowed,
                last_price,
                close_price,
                best_sell_price,
                best_sell_qty,
                best_buy_price,
                best_buy_qty,
                total_traded,
                tick_size,
                buy_c,
                sell_c,
            )

        peak_vol = self.peak_queue_by_isin.get(isin, best_sell_qty)
        peak_val_rials = peak_vol * low_allowed
        min_req_q_val = (
            MIN_INITIAL_SELL_QUEUE_VALUE_ETF_RIALS
            if isin.upper().startswith("IRT")
            else MIN_INITIAL_SELL_QUEUE_VALUE_RIALS
        )
        if peak_val_rials < min_req_q_val or len(hist) < 2:
            return None

        oldest = hist[0]
        dt_window = max(0.2, now_ts - oldest["ts"])
        vol_drop_window = oldest["sell_q_vol"] - best_sell_qty
        traded_delta_window = max(0, total_traded - oldest["total_traded"])

        short_candidates = [
            h for h in hist[:-1] if (now_ts - h["ts"]) <= SHORT_BURST_WINDOW_SEC and (now_ts - h["ts"]) >= 1.5
        ]
        short_ref = short_candidates[0] if short_candidates else oldest
        dt_short = max(0.2, now_ts - short_ref["ts"])
        vol_drop_short = short_ref["sell_q_vol"] - best_sell_qty
        traded_delta_short = max(0, total_traded - short_ref["total_traded"])

        active_refs = [
            h for h in hist[:-1] if (now_ts - h["ts"]) <= ACTIVE_MOMENTUM_WINDOW_SEC and (now_ts - h["ts"]) >= 0.35
        ]
        active_ref = active_refs[0] if active_refs else (hist[-2] if len(hist) >= 2 else oldest)
        recent_3s_drop = active_ref["sell_q_vol"] - best_sell_qty
        recent_3s_traded = max(0, total_traded - active_ref["total_traded"])
        short_match_ok = (
            (vol_drop_short > 0 and (traded_delta_short / float(vol_drop_short)) >= 0.70)
            or (vol_drop_window > 0 and (traded_delta_window / float(vol_drop_window)) >= 0.85)
        )
        is_actively_draining_now = (recent_3s_drop > 0 and (recent_3s_traded > 0 or short_match_ok))

        drop_from_peak_pct = (
            ((peak_vol - best_sell_qty) / float(peak_vol)) * 100.0
            if peak_vol > 0
            else 0.0
        )
        rem_ratio = best_sell_qty / float(peak_vol) if peak_vol > 0 else 1.0

        vel_full = (
            ((vol_drop_window / float(peak_vol)) * 100.0) / dt_window
            if (peak_vol > 0 and vol_drop_window > 0)
            else 0.0
        )
        vel_short = (
            ((vol_drop_short / float(peak_vol)) * 100.0) / dt_short
            if (peak_vol > 0 and vol_drop_short > 0)
            else 0.0
        )
        depletion_pct_per_sec = max(vel_full, vel_short)

        burn_full = vol_drop_window / dt_window if vol_drop_window > 0 else 0.0
        burn_short = vol_drop_short / dt_short if vol_drop_short > 0 else 0.0
        burn_rate_shares_per_sec = max(burn_full, burn_short)

        est_sec_to_wipeout = (
            best_sell_qty / burn_rate_shares_per_sec
            if burn_rate_shares_per_sec > 0
            else 999.0
        )
        match_full = (
            min(1.0, traded_delta_window / float(vol_drop_window))
            if vol_drop_window > 0
            else 0.0
        )
        match_short = (
            min(1.0, traded_delta_short / float(vol_drop_short))
            if vol_drop_short > 0
            else 0.0
        )
        real_trade_match_ratio = max(match_full, match_short)

        sym_name = (
            (universe_meta or {}).get("symbolName")
            or str(snap.get("symbolName") or snap.get("symbolFa") or isin)
        )
        max_valid_buy = int(
            snap.get("maxValidBuyVolume")
            or (universe_meta or {}).get("maxValidBuyVolume")
            or 100000
        )

        return {
            "isin": isin,
            "symbol_name": sym_name,
            "queue_mode": "FLOOR_SELL_QUEUE",
            "entry_price": low_allowed,
            "low_allowed": low_allowed,
            "high_allowed": high_allowed,
            "last_price": last_price,
            "close_price": close_price,
            "tick_size": tick_size,
            "buy_comm_rate": buy_c,
            "sell_comm_rate": sell_c,
            "target_net_profit_pct": target_net_pct,
            "target_sell_price": target_sell_p,
            "required_gross_bounce_pct": round(
                ((target_sell_p - low_allowed) / float(low_allowed)) * 100.0, 2
            ),
            "peak_sell_queue_vol": peak_vol,
            "current_sell_queue_vol": best_sell_qty,
            "drop_from_peak_pct": round(drop_from_peak_pct, 1),
            "remaining_queue_ratio": round(rem_ratio, 3),
            "depletion_pct_per_sec": round(depletion_pct_per_sec, 2),
            "burn_rate_shares_per_sec": round(burn_rate_shares_per_sec),
            "est_sec_to_wipeout": round(est_sec_to_wipeout, 1),
            "real_trade_match_ratio": round(real_trade_match_ratio, 2),
            "max_valid_buy_vol": max_valid_buy,
            "total_traded_shares": total_traded,
            "samples_count": len(hist),
            "tracking_duration_sec": round(dt_window, 1),
            "first_wave_peak_vol": self.first_wave_peak_by_isin.get(isin, peak_vol),
            "is_swollen_second_wave": (
                isin in self.in_second_or_later_wave_by_isin
                and self.first_wave_peak_by_isin.get(isin, 0) > 0
                and (peak_vol / float(self.first_wave_peak_by_isin[isin])) >= SWOLLEN_SECOND_WAVE_RATIO
            ),
            "swollen_wave_ratio": round(
                peak_vol / float(self.first_wave_peak_by_isin.get(isin, peak_vol) or peak_vol), 2
            ),
            "recent_3s_drop": recent_3s_drop,
            "recent_3s_traded": recent_3s_traded,
            "is_actively_draining_now": is_actively_draining_now,
        }

_LAST_REJECTION_LOG_BY_ISIN = {}
_LAST_WATCH_LOG_BY_ISIN = {}


def _log_near_miss_rejection(candidate, reason_msg):
    isin = candidate["isin"]
    now_t = time.time()
    curr_q = int(candidate.get("current_sell_queue_vol") or 0)
    prev_t, prev_reason, prev_q = _LAST_REJECTION_LOG_BY_ISIN.get(isin, (0.0, "", -1))
    reason_changed = (prev_reason != reason_msg)
    queue_changed = (prev_q != curr_q)
    min_gap = 6.0 if queue_changed else 45.0
    if reason_changed or (now_t - prev_t) >= min_gap:
        _LAST_REJECTION_LOG_BY_ISIN[isin] = (now_t, reason_msg, curr_q)
        now_s = datetime.datetime.now().strftime("%H:%M:%S")
        print(
            f"[{now_s}] [عدم ورود — {candidate['symbol_name']}] "
            f"ریزش صف: -{candidate['drop_from_peak_pct']:.1f}% | سرعت: {candidate['depletion_pct_per_sec']:.2f}%/s | "
            f"اتمام: {candidate['est_sec_to_wipeout']:.1f}s | خرید واقعی: {candidate['real_trade_match_ratio']*100:.0f}% -> علت رد: {reason_msg}"
        )


def _log_watch_collapse_throttled(candidate):
    """چاپ دقیقاً با فرمت سازگار با Audit، ولی بدون تکرار خط‌های یکسانِ صفِ متوقف"""
    isin = candidate["isin"]
    now_t = time.time()
    curr_q = int(candidate.get("current_sell_queue_vol") or 0)
    drop_p = float(candidate.get("drop_from_peak_pct") or 0.0)
    vel_p = float(candidate.get("depletion_pct_per_sec") or 0.0)

    prev = _LAST_WATCH_LOG_BY_ISIN.get(isin)
    should_log = False
    if prev is None:
        should_log = True
    else:
        prev_t, prev_q, max_drop_logged, max_vel_logged = prev
        if curr_q != prev_q and ((now_t - prev_t) >= 2.0 or abs(drop_p - max_drop_logged) >= 3.0):
            should_log = True
        elif drop_p >= max_drop_logged + 2.0 or vel_p >= max_vel_logged + 0.5:
            should_log = True
        elif (now_t - prev_t) >= 30.0:
            should_log = True

    if should_log:
        prev_max_d = prev[2] if prev else 0.0
        prev_max_v = prev[3] if prev else 0.0
        _LAST_WATCH_LOG_BY_ISIN[isin] = (now_t, curr_q, max(prev_max_d, drop_p), max(prev_max_v, vel_p))
        live_t_str = datetime.datetime.now().strftime("%H:%M:%S")
        print(
            f"[{live_t_str}] رصد ریزش صف فروش: {candidate['symbol_name']} | "
            f"باقی‌مانده صف: {candidate['current_sell_queue_vol']:,} از {candidate['peak_sell_queue_vol']:,} سهم "
            f"(-{candidate['drop_from_peak_pct']:.1f}% | سرعت: {candidate['depletion_pct_per_sec']:.2f}%/s | اتمام تخمینی: {candidate['est_sec_to_wipeout']:.1f}s)"
        )


def evaluate_and_execute_simulated_entry(
    session, headers, candidate, sim_state
):
    isin = candidate["isin"]
    if isin in sim_state["open_positions"]:
        return False
    if len(sim_state["open_positions"]) >= MAX_CONCURRENT_POSITIONS:
        return False

    today_iso_str = datetime.datetime.now().strftime("%Y-%m-%d")
    trades_today_for_isin = sum(
        1
        for t_item in (sim_state.get("completed_trades_summary") or [])
        if isinstance(t_item, dict)
        and t_item.get("date") == today_iso_str
        and (t_item.get("isin") == isin or t_item.get("symbol") == candidate.get("symbol_name"))
    )
    if trades_today_for_isin >= MAX_TRADES_PER_SYMBOL_PER_DAY:
        if candidate["drop_from_peak_pct"] >= 80.0:
            _log_near_miss_rejection(
                candidate,
                f"ممنوعیت ورود مجدد در یک روز: نماد «{candidate['symbol_name']}» امروز یک‌بار شکار شده و بازگشت مجدد آن به صف فروش تله عرضه است",
            )
        return False

    queue_mode = candidate.get("queue_mode", "FLOOR_SELL_QUEUE")
    entry_p = int(candidate.get("entry_price") or candidate["low_allowed"])
    is_etf = isin.upper().startswith("IRT")

    initial_cap = int(sim_state["initial_capital_rials"])
    avail_cash = int(sim_state["available_cash_rials"])
    one_third_budget = int(initial_cap * CAPITAL_FRACTION_PER_TRADE)
    trade_budget = (
        one_third_budget
        if (SIMULATION_MODE and UNLIMITED_VIRTUAL_CASH_IN_SIM)
        else min(avail_cash, one_third_budget)
    )

    peak_val_rials = int(candidate["peak_sell_queue_vol"]) * entry_p
    min_req_val = (
        MIN_INITIAL_SELL_QUEUE_VALUE_ETF_RIALS if is_etf else MIN_INITIAL_SELL_QUEUE_VALUE_RIALS
    )
    if not is_etf:
        min_req_val = max(min_req_val, int(trade_budget * MIN_PEAK_QUEUE_TO_BUDGET_RATIO))
    if peak_val_rials < min_req_val:
        if candidate["drop_from_peak_pct"] >= 75.0:
            _log_near_miss_rejection(
                candidate,
                f"ارزش اوج صف ({round(peak_val_rials/10.0):,} تومان) کمتر از حداقل عمق مجاز ({round(min_req_val/10.0):,} تومان)",
            )
        return False

    mkt_regime = _LIVE_MARKET_REGIME.get("regime", "NEUTRAL")
    if queue_mode == "FLOATING_ASK_WALL":
        if mkt_regime == "BEARISH" and not is_etf:
            return False
        if candidate["drop_from_peak_pct"] < MIN_FLOATING_WALL_DROP_PCT:
            return False
        if candidate["remaining_queue_ratio"] > MAX_FLOATING_WALL_REMAINING_RATIO:
            return False
        req_vel = (
            3.5
            if (mkt_regime == "BEARISH" and is_etf)
            else MIN_FLOATING_WALL_DEPLETION_PCT_PER_SEC
        )
        min_match_ratio = (
            0.80
            if mkt_regime in ("BEARISH", "NEUTRAL")
            else MIN_FLOATING_WALL_REAL_TRADE_RATIO
        )
    else:
        rem_val_rials = int(candidate["current_sell_queue_vol"]) * entry_p
        is_heavy_queue_fast_drain = (
            peak_val_rials >= HEAVY_QUEUE_VALUE_THRESHOLD_RIALS
            and rem_val_rials <= HEAVY_QUEUE_MAX_REMAINING_VALUE_RIALS
            and candidate["real_trade_match_ratio"] >= 0.75
        )
        eff_min_drop_pct = (
            HEAVY_QUEUE_MIN_DROP_PCT_FROM_PEAK
            if is_heavy_queue_fast_drain
            else MIN_QUEUE_DROP_PCT_FROM_PEAK
        )
        eff_max_rem_ratio = 0.22 if is_heavy_queue_fast_drain else MAX_REMAINING_QUEUE_RATIO
        if candidate["drop_from_peak_pct"] < eff_min_drop_pct:
            return False
        if candidate["remaining_queue_ratio"] > eff_max_rem_ratio:
            return False

        is_ultra_deep_assist = (
            candidate["drop_from_peak_pct"] >= 93.0
            and candidate["est_sec_to_wipeout"] <= 3.5
            and candidate["real_trade_match_ratio"] >= 0.90
        )
        if is_ultra_deep_assist:
            req_vel = MIN_DEPLETION_PCT_PER_SEC_ULTRA_DEEP
        elif candidate["drop_from_peak_pct"] >= 88.0:
            req_vel = MIN_DEPLETION_PCT_PER_SEC_DEEP_DROP
        else:
            req_vel = MIN_DEPLETION_PCT_PER_SEC
        min_match_ratio = MIN_REAL_TRADE_MATCH_RATIO

    if queue_mode == "FLOOR_SELL_QUEUE" and not candidate.get("is_actively_draining_now", True):
        if candidate["drop_from_peak_pct"] >= 85.0 and candidate["depletion_pct_per_sec"] >= req_vel:
            _log_near_miss_rejection(
                candidate,
                "توقف شتاب لحظه‌ای در ۳ ثانیه اخیر (صف پس از ریزش اولیه متوقف شده و معامله فعالی در ۳ ثانیه آخر ندارد)",
            )
        return False

    if candidate["depletion_pct_per_sec"] < req_vel:
        if (
            candidate["drop_from_peak_pct"] >= 75.0
            and candidate["depletion_pct_per_sec"] >= 0.50
            and candidate["est_sec_to_wipeout"] <= 15.0
        ):
            _log_near_miss_rejection(
                candidate,
                f"سرعت ریزش ({candidate['depletion_pct_per_sec']:.2f}%/s) کمتر از حد مجاز ({req_vel:.2f}%/s)",
            )
        return False

    if (
        queue_mode == "FLOOR_SELL_QUEUE"
        and candidate.get("is_swollen_second_wave")
        and candidate["drop_from_peak_pct"] < SWOLLEN_WAVE_MIN_DROP_PCT
    ):
        if candidate["drop_from_peak_pct"] >= 75.0:
            _log_near_miss_rejection(
                candidate,
                f"صف متورم بار دوم ({candidate.get('swollen_wave_ratio')} برابر موج اول)؛ نیازمند حداقل {SWOLLEN_WAVE_MIN_DROP_PCT:.0f}% ریزش صف (فعلی: {candidate['drop_from_peak_pct']:.1f}%)",
            )
        return False

    if candidate["est_sec_to_wipeout"] > MAX_ESTIMATED_SECONDS_TO_WIPEOUT:
        _log_near_miss_rejection(
            candidate,
            f"زمان تخمینی اتمام صف ({candidate['est_sec_to_wipeout']:.1f}s) بیش از سقف {MAX_ESTIMATED_SECONDS_TO_WIPEOUT}s",
        )
        return False

    if (
        int(candidate.get("samples_count") or 0) < MIN_SAMPLES_BEFORE_ENTRY
        or float(candidate.get("tracking_duration_sec") or 0.0) < MIN_TRACKING_DURATION_SEC
    ):
        _log_near_miss_rejection(
            candidate,
            f"تعداد نمونه/مدت رصد پس از شروع ناکافی است ({candidate.get('samples_count')} نمونه در {candidate.get('tracking_duration_sec')} ثانیه؛ نیازمند حداقل {MIN_SAMPLES_BEFORE_ENTRY} نمونه و {MIN_TRACKING_DURATION_SEC}s)",
        )
        return False

    if candidate["real_trade_match_ratio"] < min_match_ratio:
        _log_near_miss_rejection(
            candidate,
            f"نسبت معامله واقعی به کاهش صف ({candidate['real_trade_match_ratio']*100:.0f}%) کمتر از {min_match_ratio*100:.0f}% (حذف صوری سفارش فروشندگان)",
        )
        return False

    deep = fetch_symbol_deep_telemetry(session, headers, isin)
    ind_bp = float(deep.get("ind_buy_power_ratio") or 0.0)
    ind_buy_v = int(deep.get("ind_buy_vol") or 0)
    ins_buy_v = int(deep.get("ins_buy_vol") or 0)
    total_ii_buy = ind_buy_v + ins_buy_v
    ins_buy_share = max(
        (ins_buy_v / float(total_ii_buy)) if total_ii_buy > 0 else 0.0,
        float(deep.get("live_window_ins_share") or 0.0),
    )

    buy_power_bypass_note = ""
    if queue_mode == "FLOATING_ASK_WALL":
        if is_etf:
            if mkt_regime == "BEARISH":
                req_buy_power = 1.15
            elif mkt_regime == "NEUTRAL":
                req_buy_power = 1.05
            else:
                req_buy_power = 0.90
        else:
            if mkt_regime == "NEUTRAL":
                req_buy_power = 1.35
            else:
                req_buy_power = 1.15
        buy_power_bypass_note = f"رژیم بازار: {_LIVE_MARKET_REGIME.get('regime_fa', mkt_regime)}"
    else:
        req_buy_power = (
            MIN_INDIVIDUAL_BUY_POWER_RATIO_ETF
            if is_etf
            else MIN_INDIVIDUAL_BUY_POWER_RATIO_EQUITY
        )
        if not is_etf:
            now_hm = datetime.datetime.now().strftime("%H:%M:%S")
            bid_pres_live = float(deep.get("bid_pressure") or 0.0)
            if bid_pres_live >= 1.50 and ind_bp >= 0.75 and candidate["real_trade_match_ratio"] >= 0.90:
                ind_bp = round(max(ind_bp, min(bid_pres_live, 1.25)), 2)
            if candidate.get("is_swollen_second_wave"):
                req_buy_power = max(1.00, SWOLLEN_WAVE_MIN_BUY_POWER)
            elif (
                now_hm <= "09:09:30"
                and not candidate.get("is_second_or_later_wave")
                and candidate["drop_from_peak_pct"] >= 88.0
                and candidate["depletion_pct_per_sec"] >= 6.0
                and candidate["est_sec_to_wipeout"] <= 2.0
                and candidate["real_trade_match_ratio"] >= 0.95
                and peak_val_rials <= 12000000000
            ):
                req_buy_power = 0.48
                buy_power_bypass_note = f"جارو شدن انفجاری دقایق اول بازار ({candidate['depletion_pct_per_sec']:.2f}%/s با ۱۰۰٪ خرید واقعی — الگوی فسدید)"
            else:
                req_buy_power = MIN_INDIVIDUAL_BUY_POWER_RATIO_EQUITY

    if ind_bp < req_buy_power:
        _log_near_miss_rejection(
            candidate,
            f"قدرت خریدار حقیقی ({ind_bp:.2f}) کمتر از حداقل مجاز ({req_buy_power:.2f})",
        )
        return False

    target_sp = int(candidate["target_sell_price"])
    overhead_sell_vol = 0
    vol_at_target_price = 0
    for s_row in deep.get("sell_sheets", []):
        if isinstance(s_row, dict):
            sp_lvl = int(s_row.get("price") or 0)
            sv_lvl = int(s_row.get("volume") or 0)
            if entry_p < sp_lvl <= target_sp:
                overhead_sell_vol += sv_lvl
            if sp_lvl == target_sp:
                vol_at_target_price += sv_lvl

    if overhead_sell_vol > candidate["peak_sell_queue_vol"] * MAX_OVERHEAD_SUPPLY_RATIO:
        _log_near_miss_rejection(
            candidate,
            f"حجم عرضه سر راه تا قیمت هدف ({overhead_sell_vol:,} سهم) بیش از حد مجاز",
        )
        return False

    unit_cost_with_comm = entry_p * (1.0 + candidate["buy_comm_rate"])
    desired_qty = int(trade_budget // unit_cost_with_comm)
    desired_qty = min(desired_qty, int(candidate["max_valid_buy_vol"]))

    fillable_qty = min(desired_qty, int(candidate["current_sell_queue_vol"]))
    if fillable_qty <= 0 or (fillable_qty * entry_p) < 5000000:
        return False

    breakeven_price_rials = compute_target_sell_price_for_net_profit(
        entry_p,
        candidate["buy_comm_rate"],
        candidate["sell_comm_rate"],
        0.0002,
        tick_size=candidate["tick_size"],
    )
    safe_arm_net_pct = get_symbol_safe_arm_net_pct(isin)
    safe_arm_price_rials = compute_target_sell_price_for_net_profit(
        entry_p,
        candidate["buy_comm_rate"],
        candidate["sell_comm_rate"],
        safe_arm_net_pct,
        tick_size=candidate["tick_size"],
    )

    fin = compute_trade_financials(
        entry_p,
        target_sp,
        fillable_qty,
        candidate["buy_comm_rate"],
        candidate["sell_comm_rate"],
    )
    ceil_fin = compute_trade_financials(
        entry_p,
        candidate["high_allowed"],
        fillable_qty,
        candidate["buy_comm_rate"],
        candidate["sell_comm_rate"],
    )

    now_dt = datetime.datetime.now()
    trade_id = f"SIM-{now_dt.strftime('%Y%m%d-%H%M%S')}-{isin[4:8] if len(isin) >= 8 else isin[-4:]}"
    sim_state["total_trades_count"] = int(sim_state.get("total_trades_count", 0)) + 1
    sim_state["available_cash_rials"] = avail_cash - fin["total_buy_cost_rials"]

    mode_label = (
        "صف فروش شناور (دیوار عرضه)"
        if queue_mode == "FLOATING_ASK_WALL"
        else "صف فروش کف روزانه"
    )
    note_extra = f" | {buy_power_bypass_note}" if buy_power_bypass_note else ""

    pos_obj = {
        "trade_id": trade_id,
        "date": now_dt.strftime("%Y-%m-%d"),
        "symbol_name": candidate["symbol_name"],
        "symbol_isin": isin,
        "market_type": isin[:4],
        "queue_mode": queue_mode,
        "status": "OPEN_WAITING_SELL_TARGET",
        "entry_time": now_dt.strftime("%H:%M:%S.%f")[:-3],
        "entry_epoch": time.time(),
        "buy_fill_time": now_dt.strftime("%H:%M:%S.%f")[:-3],
        "sell_order_time": (
            now_dt + datetime.timedelta(milliseconds=120)
        ).strftime("%H:%M:%S.%f")[:-3],
        "exit_time": "",
        "hold_duration_sec": 0,
        "buy_price_rials": entry_p,
        "breakeven_price_rials": breakeven_price_rials,
        "safe_arm_price_rials": safe_arm_price_rials,
        "target_sell_price_rials": target_sp,
        "high_allowed_price_rials": int(candidate["high_allowed"]),
        "actual_exit_price_rials": 0,
        "quantity": fillable_qty,
        "buy_commission_rate": candidate["buy_comm_rate"],
        "sell_commission_rate": candidate["sell_comm_rate"],
        "gross_buy_Dynamic_rials": fin["gross_buy_rials"],
        "buy_commission_rials": fin["buy_comm_rials"],
        "total_buy_cost_rials": fin["total_buy_cost_rials"],
        "expected_net_profit_rials": fin["net_profit_rials"],
        "expected_net_profit_tomans": fin["net_profit_tomans"],
        "expected_net_profit_pct": fin["net_profit_pct"],
        "peak_sell_queue_vol": candidate["peak_sell_queue_vol"],
        "entry_sell_queue_vol": candidate["current_sell_queue_vol"],
        "queue_drop_pct_at_entry": candidate["drop_from_peak_pct"],
        "depletion_rate_pct_per_sec": candidate["depletion_pct_per_sec"],
        "est_seconds_to_wipeout": candidate["est_sec_to_wipeout"],
        "real_trade_match_ratio": candidate["real_trade_match_ratio"],
        "ind_buy_power_ratio": ind_bp,
        "volume_ahead_at_sell_price": vol_at_target_price,
        "remaining_volume_ahead_at_target": vol_at_target_price,
        "last_total_traded_shares": candidate["total_traded_shares"],
        "max_price_after_entry": entry_p,
        "min_price_after_entry": entry_p,
        "trailing_above_target_active": False,
        "peak_buy_queue_at_ceiling": 0,
        "notes": f"ورود صوری در {mode_label} و فعال‌سازی هدف پایه +{fin['net_profit_pct']:.2f}% خالص به همراه تریلینگ پویا تا سقف روزانه (+{ceil_fin['net_profit_pct']:.2f}% خالص){note_extra}",
    }

    sim_state["open_positions"][isin] = pos_obj
    save_sim_state(sim_state)
    try:
        request_gdrive_sync_async()
    except Exception:
        pass

    print(
        f"\n{'*'*78}\n"
        f"[★ شکار صوری {mode_label} — ورود در آخرین لحظه] شناسه: {trade_id}\n"
        f"  نماد: {candidate['symbol_name']} ({isin}) | زمان ورود: {pos_obj['entry_time']}\n"
        f"  وضعیت صف: اوج صف {candidate['peak_sell_queue_vol']:,} سهم -> باقی‌مانده در لحظه ورود: {candidate['current_sell_queue_vol']:,} سهم ({candidate['drop_from_peak_pct']:.1f}% جمع شده)\n"
        f"  سرعت بلعیده شدن: {candidate['depletion_pct_per_sec']:.2f}%/s | اتمام: {candidate['est_sec_to_wipeout']:.1f}s | خرید واقعی: {candidate['real_trade_match_ratio']*100:.0f}% | قدرت خریدار حقیقی: {ind_bp}{note_extra}\n"
        f"  خرید صوری (۱/۳ دارایی): {fillable_qty:,} سهم در قیمت {entry_p:,} ریال | بهای تمام‌شده با کارمزد خرید ({candidate['buy_comm_rate']*100:.4f}%): {fin['total_buy_cost_rials']:,} ریال\n"
        f"  اهداف فروش هوشمند (۲ مرحله‌ای + تریلینگ تا سقف):\n"
        f"    ۱) نقطه فعال‌سازی محافظ سود امن: {safe_arm_price_rials:,} ریال | ۲) هدف پایه: {target_sp:,} ریال (+{fin['net_profit_pct']:.2f}% خالص = +{fin['net_profit_tomans']:,} تومان)\n"
        f"    ۳) سقف روزانه (در صورت ادامه موج صعودی / صف خرید): {candidate['high_allowed']:,} ریال (+{ceil_fin['net_profit_pct']:.2f}% خالص = +{ceil_fin['net_profit_tomans']:,} تومان)\n"
        f"{'*'*78}"
    )
    return True


def update_open_simulated_positions(session, headers, sim_state):
    open_pos = sim_state.get("open_positions", {})
    if not open_pos:
        return

    isins = list(open_pos.keys())
    snapshots = {}
    try:
        resp = session.post(
            MARKET_DATA_V2_URL,
            data=json.dumps(isins).encode("utf-8"),
            headers=headers,
            timeout=2.0,
        )
        if resp.status_code == 200 and resp.text:
            arr = resp.json()
            if isinstance(arr, list):
                for item in arr:
                    if isinstance(item, dict) and item.get("symbolIsin"):
                        snapshots[str(item["symbolIsin"])] = item
        overlay_realtime_marketsheet_on_snapshots(session, headers, isins, snapshots)
    except Exception:
        pass

    now_str = datetime.datetime.now().strftime("%H:%M:%S")

    for isin in list(isins):
        pos = open_pos.get(isin)
        snap = snapshots.get(isin)
        if not pos or not snap:
            continue

        last_p = int(snap.get("lastTradedPrice") or 0)
        best_buy_p = int(snap.get("bestBuyPrice") or snap.get("topBuyPrice") or 0)
        best_buy_q = int(
            snap.get("bestBuyQuantity") or snap.get("topBuyVolume") or 0
        )
        best_sell_p = int(snap.get("bestSellPrice") or snap.get("topSellPrice") or 0)
        best_sell_q = int(
            snap.get("bestSellQuantity") or snap.get("topSellVolume") or 0
        )
        high_allowed = int(
            snap.get("highAllowedPrice")
            or pos.get("high_allowed_price_rials")
            or 0
        )
        total_traded = int(snap.get("totalNumberOfSharesTraded") or 0)
        buy_p_entry = int(pos["buy_price_rials"])
        target_sp = int(pos["target_sell_price_rials"])
        qty = int(pos["quantity"])

        has_live_bid = (best_buy_p > 0 and best_buy_q > 0)
        cand_exit_p = best_buy_p if has_live_bid else last_p
        ref_high_p = best_buy_p if has_live_bid else (last_p if (best_sell_q == 0 and last_p >= buy_p_entry) else buy_p_entry)
        if ref_high_p >= buy_p_entry:
            pos["max_price_after_entry"] = max(
                int(pos.get("max_price_after_entry") or buy_p_entry), ref_high_p
            )
        if cand_exit_p > 0:
            pos["min_price_after_entry"] = min(
                int(pos.get("min_price_after_entry") or cand_exit_p), cand_exit_p
            )

        max_p_seen = int(pos.get("max_price_after_entry") or buy_p_entry)
        hold_elapsed = time.time() - float(pos.get("entry_epoch") or time.time())
        breakeven_p = int(pos.get("breakeven_price_rials") or 0)
        if breakeven_p <= 0:
            breakeven_p = compute_target_sell_price_for_net_profit(
                buy_p_entry, pos["buy_commission_rate"], pos["sell_commission_rate"], 0.0002
            )
            pos["breakeven_price_rials"] = breakeven_p

        if hold_elapsed >= STAGNANT_POSITION_BREAKEVEN_SEC or now_str >= EOD_BREAKEVEN_MODE_TIME_STR:
            if target_sp > breakeven_p and not pos.get("trailing_above_target_active"):
                target_sp = breakeven_p

        today_iso = datetime.datetime.now().strftime("%Y-%m-%d")
        prev_pos_date = str(pos.get("last_tracked_date") or pos.get("date") or today_iso)
        if prev_pos_date != today_iso or total_traded < int(pos.get("last_total_traded_shares") or 0):
            pos["last_tracked_date"] = today_iso
            pos["last_total_traded_shares"] = total_traded
            delta_traded = 0
        else:
            delta_traded = max(
                0, total_traded - int(pos.get("last_total_traded_shares") or total_traded)
            )
            pos["last_total_traded_shares"] = total_traded

        target_touched = False
        if best_buy_p >= target_sp and best_buy_q >= qty:
            target_touched = True
        elif last_p > target_sp and delta_traded > 0:
            target_touched = True
        elif last_p == target_sp and delta_traded > 0:
            rem_ahead = int(pos.get("remaining_volume_ahead_at_target") or 0) - delta_traded
            pos["remaining_volume_ahead_at_target"] = max(0, rem_ahead)
            if rem_ahead + qty <= delta_traded or rem_ahead <= 0:
                target_touched = True

        if target_touched or max_p_seen >= target_sp:
            pos["trailing_above_target_active"] = True

        order_filled = False
        exit_p = target_sp
        exit_status = "CLOSED_PROFIT_TARGET_HIT"
        exit_reason_note = ""

        if pos.get("trailing_above_target_active"):
            is_at_ceiling_buy_queue = (
                high_allowed > 0
                and best_buy_p == high_allowed
                and best_buy_q > 0
                and best_sell_q == 0
            )
            if is_at_ceiling_buy_queue:
                prev_ceil_q = int(pos.get("peak_buy_queue_at_ceiling") or 0)
                if best_buy_q > prev_ceil_q:
                    pos["peak_buy_queue_at_ceiling"] = best_buy_q
                    prev_ceil_q = best_buy_q
                if (
                    (prev_ceil_q > 0 and best_buy_q < int(prev_ceil_q * MIN_BUY_QUEUE_HOLD_RATIO))
                    or now_str >= "12:24:00"
                ):
                    order_filled = True
                    exit_p = high_allowed
                    exit_status = "CLOSED_CEILING_BUY_QUEUE_EXIT"
                    exit_reason_note = f"خروج در سقف روزانه و صف خرید ({high_allowed:,} ریال)"
                else:
                    continue
            elif high_allowed > 0 and (best_buy_p >= high_allowed or last_p >= high_allowed) and best_sell_q > 0:
                order_filled = True
                exit_p = high_allowed
                exit_status = "CLOSED_DAILY_CEILING_HIT"
                exit_reason_note = f"فروش در سقف مجاز روزانه ({high_allowed:,} ریال)"
            else:
                pullback_from_peak_pct = (
                    ((max_p_seen - cand_exit_p) / float(max_p_seen)) * 100.0
                    if (cand_exit_p > 0 and max_p_seen > 0)
                    else 0.0
                )
                strong_upward_momentum = (
                    cand_exit_p >= target_sp
                    and pullback_from_peak_pct < TRAILING_ABOVE_TARGET_PULLBACK_PCT
                    and (
                        best_buy_q >= max(qty, int(best_sell_q * 1.1))
                        or last_p >= max_p_seen
                    )
                    and now_str < "12:24:00"
                )
                if strong_upward_momentum:
                    continue
                else:
                    order_filled = True
                    exit_p = max(target_sp, cand_exit_p)
                    exit_status = (
                        "CLOSED_DYNAMIC_TRAILING_ABOVE_TARGET"
                        if exit_p > target_sp
                        else "CLOSED_PROFIT_TARGET_HIT"
                    )
                    exit_reason_note = (
                        f"تریلینگ موج صعودی تا قله {max_p_seen:,} ریال و خروج در {exit_p:,} ریال"
                        if exit_p > target_sp
                        else f"فروش موفق در قیمت هدف پایه ({exit_p:,} ریال)"
                    )

        if not order_filled:
            safe_arm_p = int(pos.get("safe_arm_price_rials") or 0)
            if safe_arm_p <= 0:
                safe_arm_p = breakeven_p
            if max_p_seen >= safe_arm_p and max_p_seen > buy_p_entry and cand_exit_p >= breakeven_p and has_live_bid:
                pullback_pct = ((max_p_seen - cand_exit_p) / float(max_p_seen)) * 100.0 if cand_exit_p > 0 else 0.0
                peak_fin = compute_trade_financials(
                    buy_p_entry,
                    max_p_seen,
                    qty,
                    pos["buy_commission_rate"],
                    pos["sell_commission_rate"],
                )
                fin_check = compute_trade_financials(
                    buy_p_entry,
                    cand_exit_p,
                    qty,
                    pos["buy_commission_rate"],
                    pos["sell_commission_rate"],
                )
                weak_surge_above_commission = (
                    hold_elapsed >= FAST_SURGE_MAX_SECONDS_TO_BREAKEVEN
                    or (best_sell_q > 0 and best_sell_q > int(best_buy_q * 1.25))
                    or cand_exit_p == breakeven_p
                )
                req_pb = (
                    NEAR_TARGET_PULLBACK_PCT
                    if (peak_fin["net_profit_pct"] / 100.0) >= NEAR_TARGET_HIGH_PROFIT_NET_PCT
                    else TRAILING_PROFIT_PULLBACK_PCT
                )
                if (weak_surge_above_commission or pullback_pct >= req_pb) and fin_check["net_profit_rials"] >= 0:
                    order_filled = True
                    exit_p = cand_exit_p
                    exit_status = "CLOSED_STAGE1_PROFIT_SAVE"
                    exit_reason_note = f"قفل سود بالای کارمزد کارگزاری (قله: {max_p_seen:,} ریال = +{peak_fin['net_profit_pct']:.2f}% خالص) و خروج امن در {exit_p:,} ریال"

        if not order_filled:
            if now_str >= EOD_MANDATORY_FLATTEN_TIME_STR and cand_exit_p > 0:
                order_filled = True
                exit_p = cand_exit_p
                exit_status = "CLOSED_EOD_MANDATORY_FLATTEN"
                exit_reason_note = f"تسویه اجباری پایان بازار (ساعت {now_str}) برای تضمین صفر بودن پوزیشن‌های باز در انتهای روز"
            elif hold_elapsed >= STAGNANT_POSITION_MAX_HOLD_SEC and has_live_bid and best_buy_p >= buy_p_entry:
                order_filled = True
                exit_p = best_buy_p
                exit_status = "CLOSED_STAGNANT_TIME_STOP"
                exit_reason_note = f"خروج زمانی پوزیشن راکد پس از {round(hold_elapsed/60.0, 1)} دقیقه توقف بدون جهش قیمتی"
            elif pos.get("queue_mode") == "FLOATING_ASK_WALL" and hold_elapsed >= 20.0 and cand_exit_p > 0 and cand_exit_p < buy_p_entry:
                drop_below_entry_pct = ((buy_p_entry - cand_exit_p) / float(buy_p_entry)) * 100.0
                if drop_below_entry_pct >= FLOATING_WALL_STOP_LOSS_GROSS_PCT:
                    order_filled = True
                    exit_p = cand_exit_p
                    exit_status = "CLOSED_FLOATING_WALL_STOP_LOSS"
                    exit_reason_note = f"خروج اضطراری حد ضرر دیوار عرضه شناور (افت -{drop_below_entry_pct:.2f}% زیر قیمت ورود)"

        if order_filled:
            now_dt = datetime.datetime.now()
            fin = compute_trade_financials(
                pos["buy_price_rials"],
                exit_p,
                qty,
                pos["buy_commission_rate"],
                pos["sell_commission_rate"],
            )
            hold_sec = round(time.time() - float(pos.get("entry_epoch") or time.time()), 1)

            pos["status"] = exit_status
            pos["exit_time"] = now_dt.strftime("%H:%M:%S.%f")[:-3]
            pos["hold_duration_sec"] = hold_sec
            pos["actual_exit_price_rials"] = exit_p
            pos["gross_sell_value_rials"] = fin["gross_sell_rials"]
            pos["sell_commission_rials"] = fin["sell_comm_rials"]
            pos["net_sell_proceeds_rials"] = fin["net_sell_proceeds_rials"]
            pos["net_profit_rials"] = fin["net_profit_rials"]
            pos["net_profit_tomans"] = fin["net_profit_tomans"]
            pos["net_profit_pct"] = fin["net_profit_pct"]
            pos["notes"] = f"{exit_reason_note} پس از {hold_sec} ثانیه با سود خالص {fin['net_profit_pct']:+.2f}%"

            sim_state["available_cash_rials"] = (
                int(sim_state.get("available_cash_rials") or 0)
                + fin["net_sell_proceeds_rials"]
            )
            sim_state["closed_trades_count"] = int(sim_state.get("closed_trades_count", 0)) + 1
            if fin["net_profit_rials"] >= 0:
                sim_state["win_trades_count"] = int(sim_state.get("win_trades_count", 0)) + 1
            else:
                sim_state["loss_trades_count"] = int(sim_state.get("loss_trades_count", 0)) + 1
            sim_state["cumulative_realized_profit_rials"] = (
                int(sim_state.get("cumulative_realized_profit_rials", 0))
                + fin["net_profit_rials"]
            )
            sim_state["cumulative_commissions_paid_rials"] = (
                int(sim_state.get("cumulative_commissions_paid_rials", 0))
                + fin["buy_comm_rials"]
                + fin["sell_comm_rials"]
            )

            append_trade_to_csv(pos)
            sim_state.setdefault("completed_trades_summary", []).append(
                {
                    "trade_id": pos["trade_id"],
                    "date": pos["date"],
                    "symbol": pos["symbol_name"],
                    "buy_price": pos["buy_price_rials"],
                    "sell_price": exit_p,
                    "qty": qty,
                    "net_profit_rials": fin["net_profit_rials"],
                    "net_profit_tomans": fin["net_profit_tomans"],
                    "net_profit_pct": fin["net_profit_pct"],
                    "hold_sec": hold_sec,
                }
            )
            del open_pos[isin]
            save_sim_state(sim_state)
            try:
                request_gdrive_sync_async()
            except Exception:
                pass

            print(
                f"\n{'#'*78}\n"
                f"[✓ خروج موفق صوری ({exit_status})] شناسه: {pos['trade_id']}\n"
                f"  نماد: {pos['symbol_name']} ({isin}) | زمان فروش: {pos['exit_time']} (مدت نگهداری: {hold_sec} ثانیه)\n"
                f"  قیمت خرید: {pos['buy_price_rials']:,} ریال -> قیمت فروش: {exit_p:,} ریال (قله دیده‌شده: {max_p_seen:,} ریال) | تعداد: {qty:,} سهم\n"
                f"  کل کارمزد پرداختی (خرید + فروش): {(fin['buy_comm_rials'] + fin['sell_comm_rials']):,} ریال\n"
                f"  سود خالص قطعی این معامله: {fin['net_profit_rials']:+,} ریال ({fin['net_profit_tomans']:+,} تومان | {fin['net_profit_pct']:+.2f}%)\n"
                f"  سود خالص تجمعی کل معاملات بسته شده: {sim_state['cumulative_realized_profit_rials']:+,} ریال ({round(sim_state['cumulative_realized_profit_rials']/10.0):+,} تومان)\n"
                f"{'#'*78}"
            )


def print_portfolio_status_report(sim_state, current_snapshots=None):
    init_cap = int(sim_state.get("initial_capital_rials") or FALLBACK_TOTAL_CAPITAL_RIALS)
    avail_cash = int(sim_state.get("available_cash_rials") or init_cap)
    realized_pnl = int(sim_state.get("cumulative_realized_profit_rials") or 0)
    total_comm = int(sim_state.get("cumulative_commissions_paid_rials") or 0)
    closed_cnt = int(sim_state.get("closed_trades_count") or 0)
    win_cnt = int(sim_state.get("win_trades_count") or 0)
    open_pos = sim_state.get("open_positions", {})

    unrealized_pnl = 0
    open_details = []
    for isin, pos in open_pos.items():
        snap = (current_snapshots or {}).get(isin, {})
        mark_p = int(
            snap.get("bestBuyPrice")
            or snap.get("lastTradedPrice")
            or pos["buy_price_rials"]
        )
        m_fin = compute_trade_financials(
            pos["buy_price_rials"],
            mark_p,
            pos["quantity"],
            pos["buy_commission_rate"],
            pos["sell_commission_rate"],
        )
        unrealized_pnl += m_fin["net_profit_rials"]
        open_details.append(
            f"{pos['symbol_name']} ({pos['quantity']:,} سهم @ {pos['buy_price_rials']:,} -> هدف {pos['target_sell_price_rials']:,} | قیمت فعلی: {mark_p:,} | سود/زیان لحظه‌ای با کسر کارمزد: {m_fin['net_profit_tomans']:+,} تومان)"
        )

    print(
        f"\n-------------------- ترازنامه لحظه‌ای ربات شکارچی صف فروش (رژیم بازار: {_LIVE_MARKET_REGIME.get('regime_fa', 'نامشخص')}) --------------------\n"
        f"  سرمایه اولیه شبیه‌سازی: {init_cap:,} ریال ({round(init_cap/10.0):,} تومان) | نقدینگی آزاد فعلی: {avail_cash:,} ریال\n"
        f"  تعداد معاملات بسته‌شده: {closed_cnt} معامله (موفق: {win_cnt}) | پوزیشن‌های باز فعلی: {len(open_pos)} از {MAX_CONCURRENT_POSITIONS}\n"
        f"  سود خالص تحقق‌یافته: {realized_pnl:+,} ریال ({round(realized_pnl/10.0):+,} تومان) | کارمزد کل لحاظ‌شده: {total_comm:,} ریال\n"
        f"  سود/زیان تحقق‌نیافته پوزیشن‌های باز (پس از کسر کارمزد): {unrealized_pnl:+,} ریال ({round(unrealized_pnl/10.0):+,} تومان)"
    )
    for od in open_details:
        print(f"  -> [پوزیشن باز] {od}")
    print("-" * 89)


def run_diagnostic_market_scan_once(session, headers, universe_map, tracker):
    print("\n[*] در حال اجرای اسکن تشخیصی روی کل نمادهای بازار برای شناسایی صف‌های فروش و محاسبه نقطه +0.5% سود خالص...")
    snaps = scan_selling_queue_candidates(session, headers, universe_map, force_full_map=True)
    sell_queue_rows = []
    all_valid_rows = []
    for isin, snap in snaps.items():
        low_p = int(snap.get("lowAllowedPrice") or 0)
        high_p = int(snap.get("highAllowedPrice") or 0)
        last_p = int(snap.get("lastTradedPrice") or 0)
        best_sell_p = int(snap.get("bestSellPrice") or snap.get("topSellPrice") or 0)
        best_sell_q = int(snap.get("bestSellQuantity") or snap.get("topSellVolume") or 0)
        best_buy_q = int(snap.get("bestBuyQuantity") or snap.get("topBuyVolume") or 0)
        if low_p <= 0 or high_p <= low_p:
            continue

        def_bc, def_sc = get_default_commission_rates(isin)
        try:
            bc = float(snap.get("buyRatio") or 0.0)
            if bc <= 0 or bc > 0.02:
                bc = def_bc
        except Exception:
            bc = def_bc
        try:
            sc = float(snap.get("sellRatio") or 0.0)
            if sc <= 0 or sc > 0.02:
                sc = def_sc
        except Exception:
            sc = def_sc
        tick = detect_tick_size(low_p, isin, snap.get("priceTickSize"))
        sym_target_pct = get_symbol_target_net_profit_pct(isin, queue_mode="FLOOR_SELL_QUEUE")
        target_sp = compute_target_sell_price_for_net_profit(
            low_p, bc, sc, sym_target_pct, tick_size=tick
        )
        gross_bounce_pct = ((target_sp - low_p) / float(low_p)) * 100.0
        max_band_pct = ((high_p - low_p) / float(low_p)) * 100.0
        q_val_rials = best_sell_q * low_p
        name = (
            (universe_map.get(isin) or {}).get("symbolName")
            or str(snap.get("symbolName") or isin)
        )
        row_item = {
            "name": name,
            "isin": isin,
            "low_p": low_p,
            "high_p": high_p,
            "sell_q_vol": best_sell_q,
            "sell_q_val_tomans": round(q_val_rials / 10.0),
            "buy_comm_pct": round(bc * 100.0, 4),
            "sell_comm_pct": round(sc * 100.0, 4),
            "target_sp": target_sp,
            "gross_bounce_pct": round(gross_bounce_pct, 2),
            "max_band_pct": round(max_band_pct, 2),
            "reachable": target_sp < int(high_p * 0.996),
        }
        all_valid_rows.append(row_item)
        if tracker is not None:
            tracker.seed_peak_only(isin, best_sell_p, low_p, best_sell_q, best_buy_q)
        if (best_sell_p == low_p and best_sell_q > 0 and best_buy_q == 0) or last_p == low_p:
            sell_queue_rows.append(row_item)

    sell_queue_rows.sort(key=lambda x: x["sell_q_val_tomans"], reverse=True)
    print(
        f"[+] تعداد کل نمادهای دریافت‌شده در اسکن لحظه‌ای: {len(snaps)} نماد | نمادهای فعلی در کف / صف فروش: {len(sell_queue_rows)} نماد"
    )
    if sell_queue_rows:
        print(
            "\n=== نمونه ۱۵ نماد برتر فعلی در کف / صف فروش و محاسبه دقیق قیمت فروش برای +۰.۵۰٪ سود خالص (پس از کسر کارمزدها) ==="
        )
        for idx, r in enumerate(sell_queue_rows[:15], start=1):
            reach_txt = "واجد شرایط" if r["reachable"] else "سقف روزانه محدود"
            print(
                f"  [{idx:2d}] {r['name']} ({r['isin']}) | قیمت کف: {r['low_p']:,} ریال | حجم صف فروش: {r['sell_q_vol']:,} سهم ({r['sell_q_val_tomans']:,} تومان) | "
                f"کارمزد خرید+فروش: {r['buy_comm_pct'] + r['sell_comm_pct']:.3f}% -> قیمت هدف فروش (+0.5% خالص): {r['target_sp']:,} ریال "
                f"(نیازمند +{r['gross_bounce_pct']:.2f}% از کف در برابر سقف +{r['max_band_pct']:.1f}% امروز -> {reach_txt})"
            )
    elif all_valid_rows:
        print(
            "\n[*] تابلوی بازار در حال حاضر قبل از پیش‌گشایش (۰۸:۴۵) یا فاقد صف فروش فعال است؛\n"
            "=== نمایش ۱۵ نماد فعال از تابلو به همراه محاسبه آماده قیمت خرید در کف امروز و قیمت فروش برای +۰.۵۰٪ سود خالص ==="
        )
        for idx, r in enumerate(all_valid_rows[:15], start=1):
            reach_txt = "واجد شرایط" if r["reachable"] else "سقف روزانه محدود"
            print(
                f"  [{idx:2d}] {r['name']} ({r['isin']}) | قیمت کف امروز: {r['low_p']:,} ریال | سقف امروز: {r['high_p']:,} ریال | "
                f"کارمزد خرید+فروش: {r['buy_comm_pct'] + r['sell_comm_pct']:.3f}% -> قیمت هدف فروش (+0.5% خالص در صورت خرید در کف): {r['target_sp']:,} ریال "
                f"(نیازمند +{r['gross_bounce_pct']:.2f}% از کف در برابر بازه +{r['max_band_pct']:.1f}% امروز -> {reach_txt})"
            )


def archive_and_close_stale_previous_day_positions(session, headers, sim_state):
    if not AUTO_ARCHIVE_PREV_DAY_OPEN_POSITIONS:
        return
    open_pos = sim_state.get("open_positions", {})
    if not open_pos:
        return

    today_iso = datetime.datetime.now().strftime("%Y-%m-%d")
    stale_isins = [
        isin for isin, pos in open_pos.items()
        if str(pos.get("date") or "") and str(pos.get("date")) < today_iso
    ]
    if not stale_isins:
        return

    snapshots = {}
    try:
        resp = session.post(
            MARKET_DATA_V2_URL,
            data=json.dumps(stale_isins).encode("utf-8"),
            headers=headers,
            timeout=2.5,
        )
        if resp.status_code == 200 and resp.text:
            arr = resp.json()
            if isinstance(arr, list):
                for item in arr:
                    if isinstance(item, dict) and item.get("symbolIsin"):
                        snapshots[str(item["symbolIsin"])] = item
    except Exception:
        pass

    print(
        f"\n{'='*86}\n"
        f"=== گزارش تعیین تکلیف و آرشیو {len(stale_isins)} پوزیشن باز مانده از روز قبل (برای شروع تمیز تست) ===\n"
        f"{'='*86}"
    )
    archived_list = sim_state.setdefault("archived_previous_positions", [])
    for idx, isin in enumerate(stale_isins, start=1):
        pos = open_pos.pop(isin)
        snap = snapshots.get(isin, {})
        mark_p = int(
            snap.get("bestBuyPrice")
            or snap.get("lastTradedPrice")
            or snap.get("closingPrice")
            or pos["buy_price_rials"]
        )
        m_fin = compute_trade_financials(
            pos["buy_price_rials"],
            mark_p,
            pos["quantity"],
            pos["buy_commission_rate"],
            pos["sell_commission_rate"],
        )
        pos["status"] = "ARCHIVED_PREV_DAY_POSITION"
        pos["archived_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pos["mark_price_at_archive_rials"] = mark_p
        pos["unrealized_net_pct_at_archive"] = m_fin["net_profit_pct"]
        pos["unrealized_net_tomans_at_archive"] = m_fin["net_profit_tomans"]
        archived_list.append(pos)
        print(
            f"  [{idx:2d}] {pos['symbol_name']} ({isin}) | تاریخ ورود: {pos.get('date')} ({pos.get('queue_mode')}) | "
            f"خرید: {pos['buy_price_rials']:,} | سقف دیده‌شده دیروز: {pos.get('max_price_after_entry', pos['buy_price_rials']):,} | "
            f"قیمت فعلی تابلو: {mark_p:,} ریال ({m_fin['net_profit_pct']:+.2f}% خالص = {m_fin['net_profit_tomans']:+,} تومان) -> آرشیو و آزاد شد"
        )

    sim_state["available_cash_rials"] = int(sim_state.get("initial_capital_rials") or FALLBACK_TOTAL_CAPITAL_RIALS)
    save_sim_state(sim_state)
    try:
        push_cumulative_files_to_gdrive()
    except Exception:
        pass
    print("=" * 86)


_ARCHIVED_LIVE_FATE_LOGGED_TODAY = False


def log_archived_prev_day_live_fate_once(session, headers, sim_state):
    global _ARCHIVED_LIVE_FATE_LOGGED_TODAY
    if _ARCHIVED_LIVE_FATE_LOGGED_TODAY:
        return
    archived_list = sim_state.get("archived_previous_positions") or []
    if not archived_list:
        _ARCHIVED_LIVE_FATE_LOGGED_TODAY = True
        return

    today_d = datetime.date.today()
    recent_archived = []
    for p_arch in archived_list[-15:]:
        p_date_str = str(p_arch.get("date") or "").strip()
        try:
            p_d = datetime.datetime.strptime(p_date_str, "%Y-%m-%d").date()
            if 1 <= (today_d - p_d).days <= 4:
                recent_archived.append(p_arch)
        except Exception:
            continue
    if not recent_archived:
        _ARCHIVED_LIVE_FATE_LOGGED_TODAY = True
        return
    isins = list(dict.fromkeys(p.get("symbol_isin") for p in recent_archived if p.get("symbol_isin")))
    if not isins:
        _ARCHIVED_LIVE_FATE_LOGGED_TODAY = True
        return

    snapshots = {}
    try:
        resp = session.post(
            MARKET_DATA_V2_URL,
            data=json.dumps(isins).encode("utf-8"),
            headers=headers,
            timeout=2.5,
        )
        if resp.status_code == 200 and resp.text:
            arr = resp.json()
            if isinstance(arr, list):
                for item in arr:
                    if isinstance(item, dict) and item.get("symbolIsin"):
                        snapshots[str(item["symbolIsin"])] = item
    except Exception:
        return

    _ARCHIVED_LIVE_FATE_LOGGED_TODAY = True
    print(
        f"\n{'='*86}\n"
        f"=== گزارش سرنوشت پوزیشن‌های آرشیوشده روز قبل در بازار زنده امروز (ساعت {datetime.datetime.now().strftime('%H:%M:%S')}) ===\n"
        f"{'='*86}"
    )
    for idx, pos in enumerate(recent_archived, start=1):
        isin = pos.get("symbol_isin", "")
        snap = snapshots.get(isin, {})
        mark_p = int(
            snap.get("bestBuyPrice")
            or snap.get("lastTradedPrice")
            or pos.get("mark_price_at_archive_rials")
            or pos["buy_price_rials"]
        )
        m_fin = compute_trade_financials(
            pos["buy_price_rials"],
            mark_p,
            pos["quantity"],
            pos["buy_commission_rate"],
            pos["sell_commission_rate"],
        )
        print(
            f"  [{idx:2d}] {pos['symbol_name']} ({isin}) | خرید دیروز: {pos['buy_price_rials']:,} | هدف: {pos['target_sell_price_rials']:,} | "
            f"قیمت زنده امروز: {mark_p:,} ریال -> سود/زیان فرضی در صورت نگهداری: {m_fin['net_profit_pct']:+.2f}% خالص ({m_fin['net_profit_tomans']:+,} تومان)"
        )
    print("=" * 86)


def run_postmarket_retrospective_audit_of_today_candidates(session, headers, universe_map):
    if not os.path.exists(SIM_LOG_TXT):
        return
    try:
        with open(SIM_LOG_TXT, "r", encoding="utf-8", errors="replace") as f:
            log_text = f.read()
    except Exception:
        return

    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    idx = log_text.find(today_str)
    if idx == -1:
        matches = list(
            re.finditer(
                r"=== شروع نشست شکارچی صف فروش \(حالت صوری/تست\) در تاریخ: (\d{4}-\d{2}-\d{2})",
                log_text,
            )
        )
        if not matches:
            return
        audit_date = matches[-1].group(1)
        idx = log_text.find(audit_date)
    else:
        audit_date = today_str

    def normalize_fa(s):
        return str(s or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").strip()

    sub_log = log_text[idx:]
    cand_stats = {}
    pat_watch = re.compile(
        r"\[(\d\d:\d\d:\d\d)\] رصد ریزش صف فروش: ([^|]+)\| باقی‌مانده صف: ([\d,]+) از ([\d,]+) سهم \(-([\d.]+)% \| سرعت: ([\d.]+)%/s \| اتمام تخمینی: ([\d.]+)s\)"
    )
    pat_rej = re.compile(
        r"\[(\d\d:\d\d:\d\d)\] \[عدم ورود — ([^\]]+)\] ریزش صف: -([\d.]+)% \| سرعت: ([\d.]+)%/s \| اتمام: ([\d.]+)s \| خرید واقعی: (\d+)% -> علت رد: (.*)"
    )
    for ln in sub_log.splitlines():
        m1 = pat_watch.search(ln)
        if m1:
            ts, sym, rem, peak, drop, vel, est = m1.groups()
            s_clean = normalize_fa(sym)
            st = cand_stats.setdefault(
                s_clean,
                {
                    "symbol_name": sym.strip(),
                    "first_ts": ts,
                    "last_ts": ts,
                    "peak_queue": int(peak.replace(",", "")),
                    "max_drop_pct": float(drop),
                    "max_vel_pct_s": float(vel),
                    "min_est_sec": float(est),
                    "reject_count": 0,
                    "first_reject_reason": "",
                    "last_reject_reason": "",
                },
            )
            st["last_ts"] = ts
            st["peak_queue"] = max(st["peak_queue"], int(peak.replace(",", "")))
            st["max_drop_pct"] = max(st["max_drop_pct"], float(drop))
            st["max_vel_pct_s"] = max(st["max_vel_pct_s"], float(vel))
            st["min_est_sec"] = min(st["min_est_sec"], float(est))

        m2 = pat_rej.search(ln)
        if m2:
            ts, sym, drop, vel, est, match_pct, reason = m2.groups()
            s_clean = normalize_fa(sym)
            st = cand_stats.setdefault(
                s_clean,
                {
                    "symbol_name": sym.strip(),
                    "first_ts": ts,
                    "last_ts": ts,
                    "peak_queue": 0,
                    "max_drop_pct": float(drop),
                    "max_vel_pct_s": float(vel),
                    "min_est_sec": float(est),
                    "reject_count": 0,
                    "first_reject_reason": "",
                    "last_reject_reason": "",
                },
            )
            st["last_ts"] = ts
            st["max_drop_pct"] = max(st["max_drop_pct"], float(drop))
            st["max_vel_pct_s"] = max(st["max_vel_pct_s"], float(vel))
            st["min_est_sec"] = min(st["min_est_sec"], float(est))
            st["reject_count"] += 1
            if not st["first_reject_reason"]:
                st["first_reject_reason"] = f"({ts} | -{drop}% | {vel}%/s): {reason}"
            st["last_reject_reason"] = f"({ts} | -{drop}% | {vel}%/s): {reason}"

    if not cand_stats:
        return

    name_to_isin = {}
    for isin_k, u_info in (universe_map or {}).items():
        nm = normalize_fa(u_info.get("symbolName") or "")
        if nm:
            name_to_isin[nm] = isin_k

    target_isins = []
    isin_to_skey = {}
    for skey in cand_stats:
        isin_m = name_to_isin.get(skey)
        if isin_m:
            target_isins.append(isin_m)
            isin_to_skey[isin_m] = skey

    if not target_isins:
        return

    eod_snaps = {}
    try:
        post_headers = dict(headers)
        post_headers["Accept-Encoding"] = "gzip, deflate"
        for i in range(0, len(target_isins), 100):
            ch = target_isins[i : i + 100]
            r = session.post(
                MARKET_DATA_V2_URL,
                data=json.dumps(ch).encode("utf-8"),
                headers=post_headers,
                timeout=4.0,
            )
            if r.status_code == 200 and r.text:
                for item in (r.json() or []):
                    if isinstance(item, dict) and item.get("symbolIsin"):
                        eod_snaps[str(item["symbolIsin"])] = item
    except Exception:
        pass

    print(
        f"\n{'='*94}\n"
        f"=== گزارش پس‌آزمایی پایان بازار ({audit_date}): سرنوشت واقعی {len(eod_snaps)} نماد در حال ریزش صف فروش ===\n"
        f"{'='*94}"
    )
    audit_rows = []
    winners_count = 0
    for isin_k, item in eod_snaps.items():
        skey = isin_to_skey.get(isin_k)
        if not skey:
            continue
        st = cand_stats[skey]
        low_allow = int(item.get("lowAllowedPrice") or 0)
        high_allow = int(item.get("highAllowedPrice") or 0)
        high_p = int(item.get("highPrice") or item.get("maxDailyTradedPrice") or 0)
        last_p = int(item.get("lastTradedPrice") or 0)
        close_p = int(item.get("closingPrice") or 0)
        sell_q_eod = int(item.get("bestSellQuantity") or item.get("topSellVolume") or 0)
        buy_q_eod = int(item.get("bestBuyQuantity") or item.get("topBuyVolume") or 0)
        buy_c, sell_c = get_default_commission_rates(isin_k)
        comm_total_pct = (buy_c + sell_c) * 100.0

        max_gross_bounce_pct = (
            (((high_p - low_allow) / float(low_allow)) * 100.0)
            if (low_allow > 0 and high_p >= low_allow)
            else 0.0
        )
        max_net_profit_pct = max_gross_bounce_pct - comm_total_pct
        eod_gross_pct = (
            (((last_p - low_allow) / float(low_allow)) * 100.0)
            if (low_allow > 0 and last_p > 0)
            else 0.0
        )
        eod_net_profit_pct = eod_gross_pct - comm_total_pct
        if eod_net_profit_pct > 0.0:
            winners_count += 1

        row_d = {
            "date": audit_date,
            "symbol_name": st["symbol_name"],
            "symbol_isin": isin_k,
            "first_watch_time": st["first_ts"],
            "last_sell_queue_time": st["last_ts"],
            "peak_sell_queue_vol": st["peak_queue"],
            "max_queue_drop_pct": round(st["max_drop_pct"], 1),
            "max_depletion_vel_pct_s": round(st["max_vel_pct_s"], 2),
            "reject_count": st["reject_count"],
            "low_allowed_price": low_allow,
            "high_traded_price_today": high_p,
            "last_price_1230": last_p,
            "closing_price_1230": close_p,
            "eod_sell_queue_vol": sell_q_eod,
            "eod_buy_queue_vol": buy_q_eod,
            "max_gross_bounce_from_floor_pct": round(max_gross_bounce_pct, 2),
            "max_potential_net_profit_pct": round(max_net_profit_pct, 2),
            "eod_1230_net_profit_pct": round(eod_net_profit_pct, 2),
            "first_reject_reason": st["first_reject_reason"],
        }
        audit_rows.append(row_d)

    audit_rows.sort(
        key=lambda x: (x["eod_1230_net_profit_pct"], x["max_potential_net_profit_pct"], x["max_queue_drop_pct"]),
        reverse=True,
    )
    for idx_r, r in enumerate(audit_rows[:35], start=1):
        status_ico = (
            "✅ سودده قطعی تا پایان بازار"
            if r["eod_1230_net_profit_pct"] > 0.0
            else ("⚠️ نوسان مقطعی و بازگشت به کف" if r["max_potential_net_profit_pct"] >= 0.50 else "❌ قفل در کف / صف فروش")
        )
        print(
            f"  [{idx_r:2d}] {r['symbol_name']} ({r['symbol_isin']}) -> {status_ico} | ریزش صف: -{r['max_queue_drop_pct']:.1f}% (سرعت: {r['max_depletion_vel_pct_s']:.2f}%/s)\n"
            f"       کف: {r['low_allowed_price']:,} | سقف معامله‌شده امروز: {r['high_traded_price_today']:,} (سود خالص قله: {r['max_potential_net_profit_pct']:+.2f}%) | "
            f"آخرین قیمت ۱۲:۳۰: {r['last_price_1230']:,} (خالص ۱۲:۳۰: {r['eod_1230_net_profit_pct']:+.2f}%) | صف فروش ۱۲:۳۰: {r['eod_sell_queue_vol']:,}\n"
            f"       علت رد در بازار: {r['first_reject_reason'] or 'نرسیدن به ۸۵٪ ریزش'}"
        )
    print(
        f"\n[+] خلاصه پس‌آزمایی امروز: از {len(audit_rows)} نماد رصدشده، {winners_count} نماد پس از جمع شدن صف فروش وارد سود خالص مثبت شدند."
    )
    print("=" * 94)

    try:
        access_token, folder_id = _get_gdrive_access_token()
        if access_token and audit_rows:
            cols = list(audit_rows[0].keys())
            today_audit_date = str(audit_rows[0].get("date") or "").strip()
            ok_aud, prev_fid = _gdrive_find_file_id_checked(access_token, folder_id, "sell_queue_rejected_audit.csv")
            if not ok_aud:
                print("[!] هشدار: خطا در جستجوی فایل audit روی درایو؛ برای حفظ سوابق قبلی، آپلود این مرحله لغو شد.")
                return
            existing_lines = []
            if prev_fid:
                prev_txt = _gdrive_download_text(access_token, prev_fid)
                if prev_txt is None:
                    print("[!] هشدار: خطا در دانلود فایل audit قبلی از درایو؛ برای جلوگیری از پاک شدن سوابق قبلی، آپلود لغو شد.")
                    return
                prev_lines = [ln.strip() for ln in prev_txt.lstrip("\ufeff").splitlines() if ln.strip()]
                if len(prev_lines) > 1:
                    for ln in prev_lines[1:]:
                        row_date = ln.split(",", 1)[0].strip()
                        if row_date and row_date != today_audit_date:
                            existing_lines.append(ln)
            csv_buf = ["\ufeff" + ",".join(cols)] + existing_lines
            for r in audit_rows:
                vals = [str(r.get(k, "")).replace(",", " ") for k in cols]
                csv_buf.append(",".join(vals))
            _gdrive_upload_text(
                access_token,
                folder_id,
                "sell_queue_rejected_audit.csv",
                "\n".join(csv_buf) + "\n",
                "text/csv",
                known_file_id=prev_fid,
            )
    except Exception:
        pass


def main():
    sim_state = None

    def _handle_sigterm(signum, frame):
        raise KeyboardInterrupt("SIGTERM received")

    try:
        signal.signal(signal.SIGTERM, _handle_sigterm)
    except Exception:
        pass

    try:
        pull_cumulative_files_from_gdrive_on_startup()
    except Exception:
        pass
    tee_logger = SimTeeLogger(sys.stdout, SIM_LOG_TXT)
    sys.stdout = tee_logger
    try:
        is_manual_dispatch = os.environ.get("GITHUB_EVENT_NAME", "") in ("workflow_dispatch", "push") or os.environ.get("FORCE_RUN_ON_WEEKEND") == "1"
        if datetime.datetime.now().weekday() in (3, 4) and not is_manual_dispatch:
            print("[*] امروز پنج‌شنبه/جمعه (تعطیل رسمی بازار بورس) است؛ اجرای زمان‌بندی‌شده بدون اجرا بسته می‌شود.")
            return
        tok_ok, tok_msg = ensure_valid_token()
        print(f"[{'+' if tok_ok else '!'}] وضعیت توکن احراز هویت: {tok_msg}")

        headers = build_headers()
        session = configure_persistent_high_speed_session(requests.Session())

        try:
            session.post(SAME_LOGIN_URL, data=b"{}", headers=headers, timeout=2.0)
        except Exception:
            pass

        sim_state = load_sim_state()
        cap_rials, cap_src = fetch_real_account_balance_rials(session, headers)
        if sim_state.get("initial_capital_rials") is None:
            sim_state["initial_capital_rials"] = cap_rials
            sim_state["available_cash_rials"] = cap_rials
            save_sim_state(sim_state)

        init_cap = int(sim_state["initial_capital_rials"])
        per_trade_cap = int(init_cap * CAPITAL_FRACTION_PER_TRADE)
        print(
            f"[+] سرمایه کل منظور شده برای تست صوری ({cap_src}): {init_cap:,} ریال ({round(init_cap/10.0):,} تومان)"
        )
        print(
            f"[+] بودجه اختصاصی هر معامله (۱/۳ دارایی): {per_trade_cap:,} ریال ({round(per_trade_cap/10.0):,} تومان) | حداکثر پوزیشن همزمان: {MAX_CONCURRENT_POSITIONS}"
        )
        print(
            f"[+] هدف سود خالص پایه: سهام +{TARGET_NET_PROFIT_PCT_EQUITY*100:.2f}% | صندوق‌های ETF کم‌کارمزد +{TARGET_NET_PROFIT_PCT_ETF*100:.2f}% (به همراه تریلینگ پویا تا سقف روزانه و صف خرید +4.8%)"
        )
        print(
            f"[+] موتور شکار متمرکز (نسخه ۶.۲ — لاگ روزانه + اصلاح آدرس آپلود multipart + سینک ایمن غیرمسدودکننده): شکار خالص صف فروش کف روزانه (حداقل عمق {MIN_INITIAL_SELL_QUEUE_VALUE_RIALS//10:,} تومان | دیوار عرضه شناور: {'فعال' if ENABLE_FLOATING_SELL_QUEUE else 'غیرفعال'}) | قفل کارمزد + تسویه قطعی {EOD_MANDATORY_FLATTEN_TIME_STR}"
        )
        print(f"[+] فایل لاگ روزانه: {SIM_LOG_TXT} (پوشه ابری: {GDRIVE_LOGS_SUBFOLDER_NAME}/{SIM_LOG_FILENAME})")
        print(f"[+] فایل دیتاست معاملات صوری (CSV تجمعی): {SIM_TRADES_CSV}")
        print(f"[+] فایل وضعیت پایدار پرتفوی بین روزها (تجمعی): {SIM_STATE_JSON}")

        universe_map = fetch_all_market_symbols_universe(session, headers)
        print(
            f"[+] لیست جامع نمادهای بازار دریافت شد: {len(universe_map):,} نماد فعال بورس، فرابورس و صندوق‌ها."
        )

        archive_and_close_stale_previous_day_positions(session, headers, sim_state)
        tracker = SellQueueCollapseTracker(sim_state=sim_state)
        if RUN_OUTSIDE_MARKET_HOURS_FOR_DIAGNOSTIC:
            run_diagnostic_market_scan_once(session, headers, universe_map, tracker)
            print_portfolio_status_report(sim_state)

        last_status_print_ts = time.time()
        last_gdrive_sync_ts = time.time()
        last_token_check_ts = time.time()
        last_broad_scan_ts = 0.0
        snaps = {}
        hot_watchlist_isins = set()

        print(
            f"\n[*] حلقه پایش زنده بازار فعال شد (بازه معاملات: {MARKET_START_TIME_STR} تا {MARKET_CLOSE_TIME_STR})..."
        )
        while True:
            now_dt = datetime.datetime.now()
            now_str = now_dt.strftime("%H:%M:%S")

            if time.time() - last_token_check_ts > 900:
                ensure_valid_token()
                headers = build_headers()
                last_token_check_ts = time.time()

            is_weekend_ir = datetime.datetime.now().weekday() in (3, 4)
            if is_weekend_ir or now_str < "08:59:50" or now_str > MARKET_CLOSE_TIME_STR:
                if now_str > MARKET_CLOSE_TIME_STR or is_weekend_ir:
                    print(
                        f"\n[*] ساعت فعلی ({now_str}) خارج از بازه معاملات زنده بورس (09:00:00 تا {MARKET_CLOSE_TIME_STR}) است؛\n"
                        f"    اسکن تشخیصی تابلو و همگام‌سازی خودکار با گوگل درایو با موفقیت انجام شد.\n"
                        f"    (توجه: در اجرای خودکار صبح‌های شنبه تا چهارشنبه، ربات از 08:50 تا 12:30 به مدت ۳ ساعت و ۴۰ دقیقه روشن می‌ماند و معاملات را انجام می‌دهد):"
                    )
                    snaps_end = scan_selling_queue_candidates(
                        session, headers, universe_map, force_full_map=True
                    )
                    print_portfolio_status_report(sim_state, snaps_end)
                    tee_logger.flush()
                    try:
                        run_postmarket_retrospective_audit_of_today_candidates(session, headers, universe_map)
                    except Exception as e_aud:
                        print(f"[!] هشدار در اجرای پس‌آزمایی پایان بازار: {e_aud}")
                    break
                if time.time() - last_status_print_ts >= 60.0:
                    print(
                        f"[{now_str}] در انتظار شروع معاملات پیوسته بازار (شروع رصد اوج صف‌های فروش از 09:00:00 و شروع شکار از {MARKET_START_TIME_STR})..."
                    )
                    last_status_print_ts = time.time()
                time.sleep(3.0)
                continue

            if now_str >= "09:05:00" and not _ARCHIVED_LIVE_FATE_LOGGED_TODAY:
                log_archived_prev_day_live_fate_once(session, headers, sim_state)

            if sim_state.get("open_positions"):
                update_open_simulated_positions(session, headers, sim_state)

            already_updated_hot_snaps = {}
            if hot_watchlist_isins and now_str <= NEW_ENTRY_CUTOFF_TIME_STR:
                try:
                    hot_list_sorted = sorted(hot_watchlist_isins)
                    post_headers = dict(headers)
                    post_headers["Accept-Encoding"] = "gzip, deflate"
                    fut_v2_hot = _SHARED_THREAD_POOL.submit(
                        lambda *a, **kw: _get_thread_local_session().post(*a, **kw),
                        MARKET_DATA_V2_URL,
                        data=json.dumps(hot_list_sorted).encode("utf-8"),
                        headers=post_headers,
                        timeout=1.2,
                    )
                    hot_snaps_local = {k: dict(snaps.get(k) or {"symbolIsin": k}) for k in hot_list_sorted}
                    try:
                        resp_hot = fut_v2_hot.result(timeout=1.3)
                        if resp_hot is not None and resp_hot.status_code == 200 and resp_hot.text:
                            arr_hot = resp_hot.json()
                            if isinstance(arr_hot, list):
                                for item in arr_hot:
                                    if isinstance(item, dict) and item.get("symbolIsin"):
                                        hot_snaps_local[str(item["symbolIsin"])] = item
                    except Exception:
                        pass
                    overlay_realtime_marketsheet_on_snapshots(session, headers, hot_list_sorted, hot_snaps_local)
                    new_hot = set()
                    for isin, item in hot_snaps_local.items():
                        try:
                            prev_q = int((snaps.get(isin) or {}).get("bestSellQuantity") or -1)
                            new_q = int(item.get("bestSellQuantity") or 0)
                            snaps[isin] = item
                            already_updated_hot_snaps[isin] = item
                            cand = tracker.update_symbol_snapshot(
                                isin, item, universe_map.get(isin)
                            )
                            if cand:
                                if cand["drop_from_peak_pct"] >= 20.0:
                                    new_hot.add(isin)
                                live_t_str = datetime.datetime.now().strftime("%H:%M:%S")
                                if prev_q != new_q and cand["drop_from_peak_pct"] >= 50.0 and cand["depletion_pct_per_sec"] >= 1.5:
                                    _log_watch_collapse_throttled(cand)
                                if MARKET_START_TIME_STR <= live_t_str <= NEW_ENTRY_CUTOFF_TIME_STR:
                                    evaluate_and_execute_simulated_entry(
                                        session, headers, cand, sim_state
                                    )
                        except Exception as e_hot_sym:
                            print(f"[!] هشدار در پردازش لحظه‌ای نماد {isin}: {e_hot_sym}")
                    hot_watchlist_isins = new_hot
                except Exception as e_hot_loop:
                    print(f"[!] هشدار در حلقه پایش سریع واچ‌لیست: {e_hot_loop}")

            if time.time() - last_broad_scan_ts >= BROAD_SCAN_INTERVAL_SEC:
                active_tracked = set(tracker.peak_queue_by_isin.keys()) | set(hot_watchlist_isins)
                snaps = scan_selling_queue_candidates(
                    session, headers, universe_map, tracked_isins=active_tracked
                )
                for h_isin, h_snap in already_updated_hot_snaps.items():
                    if h_isin in snaps and isinstance(snaps[h_isin], dict):
                        for ms_k in ("bestSellPrice", "bestSellQuantity", "bestSellOrderCount", "bestBuyPrice", "bestBuyQuantity", "bestBuyOrderCount"):
                            if ms_k in h_snap:
                                snaps[h_isin][ms_k] = h_snap[ms_k]
                last_broad_scan_ts = time.time()
                active_collapsing = []
                for isin, snap in snaps.items():
                    if isin in already_updated_hot_snaps:
                        continue
                    try:
                        cand = tracker.update_symbol_snapshot(
                            isin, snap, universe_map.get(isin)
                        )
                        if not cand:
                            continue
                        if cand["drop_from_peak_pct"] >= 20.0 and cand["depletion_pct_per_sec"] >= 0.8:
                            if isin not in hot_watchlist_isins:
                                _SHARED_THREAD_POOL.submit(fetch_symbol_deep_telemetry, session, headers, isin)
                            hot_watchlist_isins.add(isin)
                            active_collapsing.append(cand)
                        live_b_str = datetime.datetime.now().strftime("%H:%M:%S")
                        if MARKET_START_TIME_STR <= live_b_str <= NEW_ENTRY_CUTOFF_TIME_STR:
                            evaluate_and_execute_simulated_entry(
                                session, headers, cand, sim_state
                            )
                    except Exception as e_b_sym:
                        print(f"[!] هشدار در اسکن سراسری نماد {isin}: {e_b_sym}")

                if active_collapsing:
                    active_collapsing.sort(
                        key=lambda x: x["depletion_pct_per_sec"], reverse=True
                    )
                    top_c = active_collapsing[0]
                    _log_watch_collapse_throttled(top_c)

            status_interval_sec = 60.0 if sim_state.get("open_positions") else 900.0
            if time.time() - last_status_print_ts >= status_interval_sec:
                print_portfolio_status_report(sim_state, snaps)
                last_status_print_ts = time.time()

            if time.time() - last_gdrive_sync_ts >= 300.0:
                try:
                    save_sim_state(sim_state)
                    tee_logger.flush()
                    request_gdrive_sync_async()
                except Exception:
                    pass
                last_gdrive_sync_ts = time.time()

            time.sleep(
                FAST_WATCH_INTERVAL_SEC
                if hot_watchlist_isins
                else BROAD_SCAN_INTERVAL_SEC
            )

    except KeyboardInterrupt:
        print("\n[!] اجرای برنامه متوقف شد؛ ذخیره وضعیت نهایی و همگام‌سازی با گوگل درایو...")
    finally:
        sys.stdout = tee_logger.orig_stream
        tee_logger.close()
        try:
            if sim_state is not None:
                save_sim_state(sim_state)
            flush_and_wait_gdrive_sync(timeout=35.0)
        except Exception:
            pass


if __name__ == "__main__":
    main()
