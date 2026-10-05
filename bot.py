import os
import sys
import time
import json
import uuid
import sqlite3
import logging
import urllib.request
import urllib.parse
import urllib.error

# Configure logging
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
handlers = [logging.StreamHandler(sys.stdout)]
log_path = os.environ.get("LOG_FILE") or (
    "/data/referral_bot/bot.log" if os.path.exists("/data/referral_bot") else os.path.join(BASE_DIR, "bot.log")
)
try:
    handlers.append(logging.FileHandler(log_path))
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=handlers
)
logger = logging.getLogger("APICONFIGGBOT")

# Configuration
def load_bot_token():
    token = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    if token:
        return token.strip()
    for env_file in ["bot_token.env", "/data/referral_bot/bot_token.env", "/data/.hermes/telegram_token.env"]:
        if os.path.exists(env_file):
            with open(env_file) as f:
                for line in f:
                    if line.startswith("BOT_TOKEN=") or line.startswith("TELEGRAM_BOT_TOKEN="):
                        val = line.strip().split("=", 1)[1].strip()
                        if val:
                            return val
    return ""

BOT_TOKEN = load_bot_token()
BOT_USERNAME = os.environ.get("BOT_USERNAME", "APICONFIGGBOT")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", -1003924644142))
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@APICONFIGG")
CHANNEL_INVITE = os.environ.get("CHANNEL_INVITE", "https://t.me/APICONFIGG")
ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", 5765828495))
INVITES_REQUIRED = int(os.environ.get("INVITES_REQUIRED", 5))
DB_PATH = os.environ.get("DB_PATH") or (
    "/data/referral_bot/bot.db" if os.path.exists("/data/referral_bot") else os.path.join(BASE_DIR, "bot.db")
)

# Panel API Configuration
PANEL_API_URL = os.environ.get("PANEL_API_URL", "").strip()
PANEL_API_KEY = os.environ.get("PANEL_API_KEY", "").strip()

# Auto-correct if user accidentally swapped URL and API key in environment variables
if (PANEL_API_KEY.startswith("http://") or PANEL_API_KEY.startswith("https://")) and not (PANEL_API_URL.startswith("http://") or PANEL_API_URL.startswith("https://")):
    PANEL_API_URL, PANEL_API_KEY = PANEL_API_KEY, PANEL_API_KEY

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Initialize Database
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            referrer_id INTEGER,
            invited_count INTEGER DEFAULT 0,
            claimed_count INTEGER DEFAULT 0,
            joined_at INTEGER
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS invites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter_id INTEGER,
            invited_id INTEGER UNIQUE,
            created_at INTEGER
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS issued_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            config TEXT,
            issued_at INTEGER
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    defaults = [
        ("panel_url", PANEL_API_URL),
        ("panel_api_key", PANEL_API_KEY),
        ("config_name", "⚡️「 Api-configg-Reward 」🎁"),
        ("traffic_gb", "10.0"),
        ("expire_days", "30")
    ]
    for k, v in defaults:
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()
    logger.info("Database initialized successfully.")

def get_setting(key: str, default: str = "") -> str:
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        conn.close()
        if row is not None:
            return row[0]
    except Exception as e:
        logger.error(f"Error reading setting {key}: {e}")
    return default

def set_setting(key: str, value: str):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error saving setting {key}: {e}")

def test_panel_connection(url: str, api_key: str):
    if not url:
        return False, "", "آدرس پنل تنظیم نشده است"

    url = url.strip().rstrip("/")
    api_key = api_key.strip()

    # Auto-swap if arguments were passed in reverse order
    if (api_key.startswith("http://") or api_key.startswith("https://")) and not (url.startswith("http://") or url.startswith("https://")):
        url, api_key = api_key, url

    if not (url.startswith("http://") or url.startswith("https://")):
        return False, url, f"آدرس نامعتبر است: باید با https:// شروع شود (دریافتی: {url[:20]}...)"

    if url.endswith("/spider"):
        url = url[:-7]
    elif url.endswith("/dashboard"):
        url = url[:-10]

    test_endpoint = f"{url}/api/inbounds"
    try:
        req = urllib.request.Request(
            test_endpoint,
            headers={"X-API-Key": api_key, "User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return True, url, "OK"
            return False, url, f"Status code: {resp.status}"
    except urllib.error.HTTPError as e:
        return False, url, f"HTTP Error {e.code}: {e.reason}"
    except Exception as e:
        return False, url, str(e)

# Telegram API wrapper
def telegram_call(method: str, data: dict = None, timeout: int = 15):
    url = f"{TELEGRAM_API}/{method}"
    headers = {"Content-Type": "application/json"}
    body = json.dumps(data).encode('utf-8') if data else None
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode('utf-8') if hasattr(e, 'read') else str(e)
        logger.error(f"Telegram API {method} error: {e.code} - {err_msg}")
        return {"ok": False, "error": err_msg}
    except Exception as e:
        logger.error(f"Telegram request failed ({method}): {e}")
        return {"ok": False, "error": str(e)}

def send_message(chat_id: int, text: str, reply_markup: dict = None, parse_mode: str = "HTML"):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    if reply_markup:
        data["reply_markup"] = reply_markup
    return telegram_call("sendMessage", data)

def answer_callback(callback_query_id: str, text: str = None, show_alert: bool = False):
    data = {"callback_query_id": callback_query_id}
    if text:
        data["text"] = text
        data["show_alert"] = show_alert
    return telegram_call("answerCallbackQuery", data)

# Channel Membership Verification
def is_user_channel_member(user_id: int) -> bool:
    res = telegram_call("getChatMember", {"chat_id": CHANNEL_ID, "user_id": user_id})
    if res.get("ok"):
        status = res["result"].get("status")
        # creator, administrator, member, restricted (with is_member=True)
        if status in ("creator", "administrator", "member"):
            return True
        if status == "restricted" and res["result"].get("is_member"):
            return True
    return False

# UI Keyboards
def force_join_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "📢 عضویت در کانال @APICONFIGG", "url": CHANNEL_INVITE}],
            [{"text": "✅ عضو شدم (تأیید عضویت)", "callback_data": "check_join"}]
        ]
    }

def main_menu_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "🔗 لینک دعوت من (زیرمجموعه‌گیری)", "callback_data": "my_ref"}],
            [
                {"text": "🎁 دریافت کانفیگ اختصاصی", "callback_data": "claim_config"},
                {"text": "📊 آمار دعوت‌های من", "callback_data": "my_stats"}
            ],
            [
                {"text": "📢 کانال سرورها", "url": CHANNEL_INVITE},
                {"text": "❓ راهنما و آموزش اتصال", "callback_data": "help"}
            ]
        ]
    }

def back_to_menu_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "🔙 بازگشت به منوی اصلی", "callback_data": "main_menu"}]
        ]
    }

# DB Operations
def get_user(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id, first_name, username, referrer_id, invited_count, claimed_count, joined_at FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return {
            "user_id": row[0],
            "first_name": row[1],
            "username": row[2],
            "referrer_id": row[3],
            "invited_count": row[4],
            "claimed_count": row[5],
            "joined_at": row[6]
        }
    return None

def register_user(user_id: int, first_name: str, username: str, referrer_id: int = None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = int(time.time())
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    exists = cur.fetchone()
    is_new = False
    valid_referral = False

    if not exists:
        is_new = True
        cur.execute(
            "INSERT INTO users (user_id, first_name, username, referrer_id, invited_count, claimed_count, joined_at) VALUES (?, ?, ?, ?, 0, 0, ?)",
            (user_id, first_name, username, referrer_id, now)
        )
        if referrer_id and referrer_id != user_id:
            try:
                cur.execute("INSERT INTO invites (inviter_id, invited_id, created_at) VALUES (?, ?, ?)", (referrer_id, user_id, now))
                cur.execute("UPDATE users SET invited_count = invited_count + 1 WHERE user_id = ?", (referrer_id,))
                valid_referral = True
            except sqlite3.IntegrityError:
                pass
    else:
        cur.execute("UPDATE users SET first_name = ?, username = ? WHERE user_id = ?", (first_name, username, user_id))

    conn.commit()
    conn.close()
    return is_new, valid_referral

def create_config_from_panel(user_id: int, claim_num: int):
    panel_url = get_setting("panel_url", PANEL_API_URL).strip().rstrip("/")
    panel_key = get_setting("panel_api_key", PANEL_API_KEY).strip()
    if not panel_url or not panel_key:
        logger.warning("Panel URL or API Key is not configured.")
        return None

    # Auto-swap if accidentally inverted
    if (panel_key.startswith("http://") or panel_key.startswith("https://")) and not (panel_url.startswith("http://") or panel_url.startswith("https://")):
        panel_url, panel_key = panel_key, panel_url

    if not (panel_url.startswith("http://") or panel_url.startswith("https://")):
        logger.error(f"Invalid panel_url: {panel_url}")
        return None

    if panel_url.endswith("/spider"):
        panel_url = panel_url[:-7]
    elif panel_url.endswith("/dashboard"):
        panel_url = panel_url[:-10]

    traffic_gb = 10.0
    expire_days = 30
    config_name = "⚡️「 Api-configg-Reward 」🎁"

    url = f"{panel_url}/api/users"
    config_uuid = str(uuid.uuid4())
    username = f"Reward_{user_id}_{claim_num}"
    payload = {
        "username": username,
        "config_uuid": config_uuid,
        "traffic_limit_gb": traffic_gb,
        "expire_days": expire_days
    }
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": panel_key,
        "User-Agent": "Mozilla/5.0"
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data.get("ok") and data.get("config"):
                config_str = data["config"]
                # Customize config fragment name
                if "#" in config_str:
                    config_str = config_str.split("#")[0] + "#" + config_name
                else:
                    config_str = config_str + "#" + config_name

                now = int(time.time())
                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                cur.execute("UPDATE users SET claimed_count = claimed_count + 1 WHERE user_id = ?", (user_id,))
                cur.execute("INSERT INTO issued_configs (user_id, config, issued_at) VALUES (?, ?, ?)", (user_id, config_str, now))
                conn.commit()
                conn.close()
                logger.info(f"Generated live dedicated config from panel API for user {user_id}: {config_name}")
                return config_str
            else:
                logger.warning(f"Panel response missing config: {data}")
    except Exception as e:
        logger.error(f"Error creating config from panel API: {e}")
    return None

def create_vip_config(traffic_gb: float = 20.0, expire_days: int = 30):
    panel_url = get_setting("panel_url", PANEL_API_URL).strip().rstrip("/")
    panel_key = get_setting("panel_api_key", PANEL_API_KEY).strip()
    if not panel_url or not panel_key:
        return None, "تنظیمات پنل یا کلید API خالی است!"

    # Auto-swap if accidentally inverted
    if (panel_key.startswith("http://") or panel_key.startswith("https://")) and not (panel_url.startswith("http://") or panel_url.startswith("https://")):
        panel_url, panel_key = panel_key, panel_url

    if not (panel_url.startswith("http://") or panel_url.startswith("https://")):
        return None, f"آدرس پنل نامعتبر است: {panel_url}"

    if panel_url.endswith("/spider"):
        panel_url = panel_url[:-7]
    elif panel_url.endswith("/dashboard"):
        panel_url = panel_url[:-10]

    tag_name = "⚡️「 Api-config-VIP 」👑"
    url = f"{panel_url}/api/users"
    config_uuid = str(uuid.uuid4())
    username = f"VIP_Admin_{int(time.time())}"
    payload = {
        "username": username,
        "config_uuid": config_uuid,
        "traffic_limit_gb": traffic_gb,
        "expire_days": expire_days
    }
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": panel_key,
        "User-Agent": "Mozilla/5.0"
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data.get("ok") and data.get("config"):
                config_str = data["config"]
                if "#" in config_str:
                    config_str = config_str.split("#")[0] + "#" + tag_name
                else:
                    config_str = config_str + "#" + tag_name

                logger.info(f"Generated VIP dedicated config: {tag_name}")
                return config_str, None
            else:
                return None, f"پاسخ سرور پنل: {data}"
    except Exception as e:
        logger.error(f"Error creating VIP config: {e}")
        return None, str(e)

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM users")
    total_users = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM invites")
    total_invites = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM issued_configs")
    claimed_configs = cur.fetchone()[0]
    conn.close()
    return {
        "total_users": total_users,
        "total_invites": total_invites,
        "claimed_configs": claimed_configs
    }

# Message Handlers
def handle_start(user, chat_id, param=""):
    user_id = user["id"]
    first_name = user.get("first_name", "کاربر")
    username = user.get("username", "")

    referrer_id = None
    if param.startswith("ref_"):
        try:
            ref_val = int(param.replace("ref_", "").strip())
            if ref_val != user_id:
                referrer_id = ref_val
        except ValueError:
            pass

    is_new, valid_ref = register_user(user_id, first_name, username, referrer_id)

    # Notify Referrer if valid
    if is_new and valid_ref and referrer_id:
        ref_user = get_user(referrer_id)
        if ref_user:
            cur_count = ref_user["invited_count"]
            claimed = ref_user["claimed_count"]
            needed = (claimed + 1) * INVITES_REQUIRED
            remaining = max(0, needed - cur_count)

            notify_text = (
                f"🎉 <b>یک دوست جدید با لینک اختصاصی شما به ربات پیوست!</b>\n\n"
                f"👤 نام کاربر: <b>{first_name}</b>\n"
                f"📊 تعداد کل دعوت‌های شما: <b>{cur_count} نفر</b>\n"
            )
            if remaining == 0:
                notify_text += (
                    f"\n🎊 <b>تبریک! شما به سقف {INVITES_REQUIRED} دعوت رسیدید!</b>\n"
                    f"هم‌اکنون می‌توانید با زدن دکمه‌ی «🎁 دریافت کانفیگ اختصاصی» سرور پرسرعت خود را تحویل بگیرید! 🔥"
                )
            else:
                notify_text += f"⏳ فقط <b>{remaining} نفر</b> دیگر تا دریافت کانفیگ رایگان باقی مانده است. 🚀"

            send_message(referrer_id, notify_text)

    # Check Channel Membership
    if not is_user_channel_member(user_id):
        join_text = (
            f"سلام <b>{first_name}</b> عزیز! خوش اومدی ⚡️\n\n"
            f"برای استفاده از ربات و دریافت <b>کانفیگ اختصاصی و پرسرعت هدیه</b>، "
            f"لطفاً ابتدا در کانال رسمی ما عضو شوید و سپس دکمه‌ی <b>«تأیید عضویت»</b> را لمس کنید:\n\n"
            f"📢 <b>{CHANNEL_USERNAME}</b>"
        )
        send_message(chat_id, join_text, reply_markup=force_join_keyboard())
        return

    # Show Main Menu
    welcome_text = (
        f"سلام <b>{first_name}</b> عزیز، خوش آمدید! ⚡️💎\n\n"
        f"اینجا می‌توانید با دعوت دوستان خود به ربات، <b>کانفیگ‌های اختصاصی، پرسرعت و رایگان</b> دریافت کنید.\n\n"
        f"🎁 <b>قانون پاداش:</b> به ازای هر <b>{INVITES_REQUIRED} نفر</b> دعوت، یک کانفیگ نامحدود و پرسرعت به شما تعلق می‌گیرد!\n\n"
        f"از منوی زیر گزینه مورد نظرتان را انتخاب کنید: 👇"
    )
    send_message(chat_id, welcome_text, reply_markup=main_menu_keyboard())

def handle_callback(cb):
    cb_id = cb["id"]
    from_user = cb["from"]
    user_id = from_user["id"]
    chat_id = cb["message"]["chat"]["id"]
    data = cb.get("data", "")

    # Always answer callback to clear spinner
    answer_callback(cb_id)

    # Enforce Channel Join
    if not is_user_channel_member(user_id):
        join_text = (
            f"⚠️ شما هنوز در کانال رسمی <b>{CHANNEL_USERNAME}</b> عضو نشده‌اید!\n\n"
            f"لطفاً ابتدا عضو کانال شوید و سپس مجدداً تلاش کنید: 👇"
        )
        send_message(chat_id, join_text, reply_markup=force_join_keyboard())
        return

    if data == "check_join" or data == "main_menu":
        welcome_text = (
            f"⚡️ <b>به پنل کاربری خوش آمدید!</b>\n\n"
            f"به ازای هر <b>{INVITES_REQUIRED} دعوت</b>، یک کانفیگ اختصاصی پرسرعت هدیه بگیرید.\n"
            f"گزینه مورد نظرتان را انتخاب کنید: 👇"
        )
        send_message(chat_id, welcome_text, reply_markup=main_menu_keyboard())

    elif data == "my_ref":
        ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
        banner_text = (
            f"🔗 <b>لینک اختصاصی دعوت شما آماده است!</b>\n\n"
            f"کافیست پیام زیر را برای دوستان یا گروه‌های خود فوروارد کنید:\n"
            f"────────────────────\n"
            f"🚀 <b>اینترنت آزاد، پرسرعت و بدون قطعی!</b>\n\n"
            f"با عضویت در ربات ما، کانفیگ‌های پرسرعت روزانه و اختصاصی هدیه بگیرید ⚡️\n\n"
            f"👉 همین الان استارت بزن:\n"
            f"<code>{ref_link}</code>\n"
            f"────────────────────\n\n"
            f"💡 <i>به ازای هر ۵ نفری که با لینک شما عضو شوند، ۱ کانفیگ اختصاصی به شما تعلق می‌گیرد!</i>"
        )
        send_message(chat_id, banner_text, reply_markup=back_to_menu_keyboard())

    elif data == "my_stats":
        u = get_user(user_id)
        if not u:
            register_user(user_id, from_user.get("first_name", ""), from_user.get("username", ""))
            u = get_user(user_id)

        inv_count = u["invited_count"]
        claimed = u["claimed_count"]
        needed_for_next = (claimed + 1) * INVITES_REQUIRED
        progress_in_tier = inv_count - (claimed * INVITES_REQUIRED)
        progress_in_tier = max(0, min(INVITES_REQUIRED, progress_in_tier))
        remaining = max(0, needed_for_next - inv_count)

        # Progress bar
        filled = int((progress_in_tier / INVITES_REQUIRED) * 10)
        bar = "█" * filled + "░" * (10 - filled)

        stats_text = (
            f"📊 <b>آمار زیرمجموعه‌گیری شما:</b>\n\n"
            f"👥 کل دوستان دعوت‌شده: <b>{inv_count} نفر</b>\n"
            f"🎁 کانفیگ‌های دریافت شده: <b>{claimed} عدد</b>\n"
            f"⏳ نفرات لازم تا کانفیگ بعدی: <b>{remaining} نفر</b>\n\n"
            f"📈 پیشرفت فعلی: <code>[{bar}]</code> {progress_in_tier}/{INVITES_REQUIRED}\n\n"
        )
        if remaining == 0 and inv_count >= needed_for_next:
            stats_text += "🎉 <b>شما واجد شرایط دریافت کانفیگ هستید! دکمه «دریافت کانفیگ» را بزنید.</b>"
        else:
            stats_text += f"💡 با دعوت <b>{remaining} نفر دیگر</b>، کانفیگ اختصاصی بعدی خود را دریافت کنید."

        send_message(chat_id, stats_text, reply_markup=back_to_menu_keyboard())

    elif data == "claim_config":
        u = get_user(user_id)
        if not u:
            register_user(user_id, from_user.get("first_name", ""), from_user.get("username", ""))
            u = get_user(user_id)

        inv_count = u["invited_count"]
        claimed = u["claimed_count"]
        eligible_claims = inv_count // INVITES_REQUIRED

        if eligible_claims <= claimed:
            needed = (claimed + 1) * INVITES_REQUIRED
            remaining = needed - inv_count
            fail_text = (
                f"❌ <b>شما هنوز به سقف ۵ دعوت نرسیده‌اید!</b>\n\n"
                f"📊 تعداد دعوت‌های فعلی شما: <b>{inv_count} نفر</b>\n"
                f"⏳ شما برای دریافت کانفیگ بعدی به <b>{remaining} دعوت دیگر</b> نیاز دارید.\n\n"
                f"از بخش «🔗 لینک دعوت من» لینک خود را بردارید و برای دوستانتان بفرستید! 🚀"
            )
            send_message(chat_id, fail_text, reply_markup=back_to_menu_keyboard())
            return

        # Issue dedicated live config from Panel API
        config_data = create_config_from_panel(user_id, claimed + 1)

        if not config_data:
            empty_pool_text = (
                f"🎉 <b>تبریک! شما ۵ نفر را دعوت کرده‌اید و واجد شرایط دریافت کانفیگ هستید.</b>\n\n"
                f"⚠️ در حال حاضر سرور صدور آنی با ترافیک بالا مواجه شده است!\n"
                f"درخواست شما ثبت شد؛ لطفاً دقایقی دیگر مجدداً دکمه «🎁 دریافت کانفیگ اختصاصی» را لمس کنید تا کانفیگ شما تحویل داده شود. ❤️"
            )
            send_message(chat_id, empty_pool_text, reply_markup=back_to_menu_keyboard())
            # Alert admin
            send_message(
                ADMIN_USER_ID,
                f"⚠️ <b>هشدار به ادمین:</b> کاربر <code>{user_id}</code> (@{from_user.get('username', 'ندارد')}) واجد شرایط دریافت کانفیگ است ولی صدور لایو از پنل با خطا مواجه شد!"
            )
            return

        # Success deliver config
        success_text = (
            f"🎉 <b>تبریک! کانفیگ اختصاصی شما آماده شد:</b> ⚡️🎁\n\n"
            f"👇 برای کپی تک‌ضرب، روی کادر زیر بزنید:\n"
            f"```{config_data}```\n\n"
            f"📱 <b>نرم‌افزارهای سازگار:</b>\n"
            f"• اندروید: V2rayNG / NekoBox\n"
            f"• آی‌او‌اس: Streisand / Foxray / V2Box\n"
            f"• ویندوز: v2rayN / Nekoray\n\n"
            f"🔥 <i>با دعوت ۵ نفر دیگر، مجدداً می‌توانید یک کانفیگ تازه و مجزا دریافت کنید!</i>"
        )
        send_message(chat_id, success_text, parse_mode="Markdown", reply_markup=back_to_menu_keyboard())

    elif data == "help":
        help_text = (
            f"❓ <b>راهنما و نحوه کار با ربات:</b>\n\n"
            f"1️⃣ <b>چگونه کانفیگ رایگان بگیرم؟</b>\n"
            f"کافیست روی دکمه «🔗 لینک دعوت من» بزنید، لینک را کپی کرده و برای دوستانتان بفرستید. وقتی ۵ نفر با لینک شما وارد ربات شوند، دکمه «🎁 دریافت کانفیگ اختصاصی» برای شما فعال می‌شود.\n\n"
            f"2️⃣ <b>آیا می‌توانم چند کانفیگ بگیرم؟</b>\n"
            f"بله! این سیستم نامحدود است. به ازای هر ۵ نفری که دعوت می‌کنید، یک کانفیگ مجزا به شما اهدا می‌شود (مثلاً ۱۰ نفر = ۲ کانفیگ، ۱۵ نفر = ۳ کانفیگ).\n\n"
            f"3️⃣ <b>آیا عضویت دوستان در کانال الزامی است؟</b>\n"
            f"بله، دوستان شما برای اینکه دعوتشان معتبر شمرده شود باید عضو کانال رسمی ما باشند.\n\n"
            f"📢 کانال رسمی ما: <b>{CHANNEL_USERNAME}</b>"
        )
        send_message(chat_id, help_text, reply_markup=back_to_menu_keyboard())

# Admin Commands
def handle_admin_commands(msg):
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    text = msg.get("text", "").strip()

    if user_id != ADMIN_USER_ID:
        return False

    if text == "/admin" or text == "/stats":
        stats = get_stats()
        panel_url = get_setting("panel_url", PANEL_API_URL or "تنظیم‌نشده")
        panel_key = get_setting("panel_api_key", PANEL_API_KEY or "")
        ok, _, conn_err = test_panel_connection(panel_url, panel_key)
        status_str = "🟢 متصل" if ok else f"🔴 قطعی ({conn_err})"

        admin_text = (
            f"👑 <b>پنل مدیریت ربات رفرال API CONFIG:</b>\n\n"
            f"👥 کل کاربران ثبت‌شده: <b>{stats['total_users']} نفر</b>\n"
            f"🔗 کل زیرمجموعه‌ها: <b>{stats['total_invites']} دعوت موفق</b>\n"
            f"🎁 کل کانفیگ‌های اهدا شده: <b>{stats['claimed_configs']} عدد</b>\n\n"
            f"🌐 <b>پنل متصل:</b> <code>{panel_url}</code>\n"
            f"📡 <b>وضعیت اتصال:</b> {status_str}\n\n"
            f"🛠 <b>دستورات مدیریتی:</b>\n"
            f"• <code>/vip</code> : 👑 ساخت آنی کانفیگ ویژه VIP\n"
            f"• <code>/panel</code> : مشاهده تنظیمات پنل اسپایدر\n"
            f"• <code>/setpanel لینک کلید</code> : تغییر پنل متصل"
        )
        send_message(chat_id, admin_text)
        return True

    elif text == "/panel":
        panel_url = get_setting("panel_url", PANEL_API_URL or "تنظیم‌نشده")
        panel_key = get_setting("panel_api_key", PANEL_API_KEY or "")

        ok, _, conn_err = test_panel_connection(panel_url, panel_key)
        status_text = "🟢 متصل و فعال" if ok else f"🔴 خطای اتصال ({conn_err})"
        masked_key = panel_key[:8] + "••••••••" if len(panel_key) > 8 else panel_key

        panel_text = (
            f"🌐 <b>تنظیمات اتصال پنل اسپایدر به ربات:</b>\n\n"
            f"🔗 آدرس پنل: <code>{panel_url}</code>\n"
            f"🔑 کلید API: <code>{masked_key}</code>\n"
            f"📡 وضعیت وب‌سرویس: <b>{status_text}</b>\n\n"
            f"⚙️ <b>مشخصات کانفیگ‌های خودکار:</b>\n"
            f"• حجم: <b>10 گیگابایت</b>\n"
            f"• انقضا: <b>30 روزه</b>\n"
            f"• تگ هدیه: <code>⚡️「 Api-configg-Reward 」🎁</code>\n"
            f"• تگ ویژه VIP: <code>⚡️「 Api-config-VIP 」👑</code>\n\n"
            f"🔄 <b>تغییر پنل و کلید API:</b>\n"
            f"برای لینک کردن یک پنل جدید، کافیست دستور زیر را بفرستید:\n"
            f"<code>/setpanel آدرس_پنل کلید_api</code>\n\n"
            f"مثال:\n"
            f"<code>/setpanel https://your-domain.up.railway.app spdr_your_api_key</code>"
        )
        send_message(chat_id, panel_text)
        return True

    elif text.startswith("/setpanel"):
        parts = text.split()
        if len(parts) < 3:
            send_message(
                chat_id,
                "⚠️ <b>نحوه استفاده از دستور:</b>\n"
                "<code>/setpanel آدرس_پنل کلید_api</code>\n\n"
                "مثال:\n"
                "<code>/setpanel https://your-domain.up.railway.app spdr_your_api_key</code>"
            )
            return True

        arg1 = parts[1].strip()
        arg2 = parts[2].strip()
        if (arg2.startswith("http://") or arg2.startswith("https://")) and not (arg1.startswith("http://") or arg1.startswith("https://")):
            new_url, new_key = arg2, arg1
        else:
            new_url, new_key = arg1, arg2

        send_message(chat_id, "⏳ در حال بررسی و تست اتصال به پنل جدید...")

        ok, clean_url, err = test_panel_connection(new_url, new_key)
        if ok:
            set_setting("panel_url", clean_url)
            set_setting("panel_api_key", new_key)
            send_message(
                chat_id,
                f"✅ <b>اتصال با موفقیت برقرار و ذخیره شد!</b>\n\n"
                f"🌐 آدرس پنل: <code>{clean_url}</code>\n"
                f"🔑 کلید API: <code>{new_key[:8]}••••••••</code>\n"
                f"🟢 از این لحظه تمام کانفیگ‌های پاداش خودکار از این پنل صادر خواهند شد. 🔥"
            )
        else:
            send_message(
                chat_id,
                f"❌ <b>خطا در برقراری ارتباط با پنل!</b>\n\n"
                f"علت خطا: <code>{err}</code>\n\n"
                f"⚠️ تنظیمات قبلی حفظ شد تا عملکرد ربات مختل نشود. لطفاً آدرس پنل و API Key را بازبینی کنید."
            )
        return True

    elif text.startswith("/vip"):
        parts = text.split()
        gb = 20.0
        days = 30
        if len(parts) > 1:
            try:
                gb = float(parts[1])
            except ValueError:
                pass
        if len(parts) > 2:
            try:
                days = int(parts[2])
            except ValueError:
                pass

        send_message(chat_id, f"⏳ در حال ساخت کانفیگ اختصاصی VIP ({gb}GB / {days} روزه)...")
        vip_cfg, err = create_vip_config(traffic_gb=gb, expire_days=days)
        if vip_cfg:
            vip_text = (
                f"👑 <b>کانفیگ اختصاصی VIP آماده شد!</b> ⚡️✨\n\n"
                f"💾 حجم: <b>{gb} گیگابایت</b>\n"
                f"⏳ مدت اعتبار: <b>{days} روز</b>\n"
                f"🏷 تگ سرور: <code>⚡️「 Api-config-VIP 」👑</code>\n\n"
                f"👇 برای کپی تک‌ضرب، روی کادر زیر بزنید:\n"
                f"```{vip_cfg}```\n\n"
                f"🔥 <i>سرور فوق‌سریع VIP با حداکثر اولویت پهنای باند و بدون محدودیت سرعت!</i>"
            )
            send_message(chat_id, vip_text, parse_mode="Markdown")
        else:
            send_message(chat_id, f"❌ <b>خطا در ساخت کانفیگ VIP!</b>\n\nدلیل خطا: <code>{err}</code>")
        return True

    return False

# Main Polling Loop
def main():
    logger.info("Starting APICONFIGGBOT polling engine...")
    init_db()

    offset = 0
    # Clear old updates backlog
    updates = telegram_call("getUpdates", {"offset": -1, "timeout": 1})
    if updates.get("ok") and updates.get("result"):
        offset = updates["result"][-1]["update_id"] + 1
        logger.info(f"Flushed initial backlog, starting from offset {offset}")

    while True:
        try:
            res = telegram_call("getUpdates", {"offset": offset, "timeout": 25}, timeout=35)
            if not res.get("ok"):
                time.sleep(2)
                continue

            for upd in res.get("result", []):
                upd_id = upd["update_id"]
                offset = max(offset, upd_id + 1)

                if "message" in upd:
                    msg = upd["message"]
                    chat_id = msg["chat"]["id"]
                    text = msg.get("text", "")

                    # Check admin commands
                    if handle_admin_commands(msg):
                        continue

                    # Handle /start
                    if text.startswith("/start"):
                        parts = text.split(maxsplit=1)
                        param = parts[1].strip() if len(parts) > 1 else ""
                        handle_start(msg["from"], chat_id, param)

                    else:
                        # Fallback guide message
                        send_message(chat_id, "برای دسترسی به گزینه‌ها از منوی زیر استفاده کنید: 👇", reply_markup=main_menu_keyboard())

                elif "callback_query" in upd:
                    handle_callback(upd["callback_query"])

        except Exception as e:
            logger.error(f"Polling loop exception: {e}")
            time.sleep(3)

if __name__ == "__main__":
    main()
