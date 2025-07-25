import logging
import json
import threading
import os
import re
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

# --- CONFIGURATION (تنظیمات اصلی) ---
# توکن ربات خود را در متغیرهای محیطی (Environment Variables) پلتفرم هاستینگ خود قرار دهید
TOKEN = os.environ.get("TELEGRAM_TOKEN", "7689216297:AAHVucWhXpGlp15Ulk2zsppst1gDH9PCZnQ") 
# آیدی عددی ادمین ربات
ADMIN_ID = int(os.environ.get("ADMIN_ID", 6929024145))
# یوزرنیم ربات بدون @
BOT_USERNAME = os.environ.get("BOT_USERNAME", "irangram_chatbot")

# --- DATABASE & CONSTANTS (پایگاه داده و مقادیر ثابت) ---
# فایل‌های JSON برای ذخیره‌سازی دائمی اطلاعات استفاده می‌شوند
USERS_DB_FILE = "users.json"
REPORTS_DB_FILE = "reports.json"
CONFIG_FILE = "config.json"
STARTING_COINS = 20
DAILY_GIFT_COINS = 20
REFERRAL_BONUS_COINS = 50
GENDER_SEARCH_COST = 2

# --- FLASK WEBSERVER (وب‌سرور برای زنده نگه داشتن ربات) ---
# این وب سرور ساده باعث می شود پلتفرم هایی مانند Render سرویس شما را فعال نگه دارند
app = Flask(__name__)
@app.route('/')
def index():
    return "Bot is alive and running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- LOGGING (تنظیمات لاگ) ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- STATE DEFINITIONS (تعریف وضعیت‌های مکالمه) ---
# وضعیت‌ها برای ساخت پروفایل اولیه
PROFILE_NAME, PROFILE_GENDER, PROFILE_AGE = range(3)
# وضعیت‌ها برای ویرایش پروفایل و گزارش
EDIT_NAME, EDIT_GENDER, EDIT_AGE, EDIT_BIO, EDIT_PHOTO, REPORT_REASON = range(3, 9)


# --- DATABASE & CONFIG MANAGEMENT (مدیریت فایل‌های JSON) ---
# این توابع مسئول خواندن و نوشتن اطلاعات روی فایل‌ها هستند و ذخیره‌سازی دائمی را تضمین می‌کنند
def load_data(filename, default_type=dict):
    """اطلاعات را از یک فایل JSON بارگذاری می‌کند."""
    try:
        with open(filename, "r", encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # اگر فایل وجود نداشت یا خالی بود، یک دیکشنری یا لیست خالی برمی‌گرداند
        return default_type()

def save_data(data, filename):
    """اطلاعات را در یک فایل JSON ذخیره می‌کند. این کار باعث ماندگاری داده‌ها می‌شود."""
    with open(filename, "w", encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# بارگذاری داده‌ها در هنگام شروع به کار ربات
user_data = load_data(USERS_DB_FILE)
reports_data = load_data(REPORTS_DB_FILE, default_type=list)
config_data = load_data(CONFIG_FILE)

# --- GLOBAL VARIABLES (متغیرهای سراسری) ---
# این دیکشنری‌ها وضعیت‌های لحظه‌ای ربات را در حافظه نگه می‌دارند تا سرعت عمل بالا باشد
user_partners = {}  # {user_id: partner_id}
# صف انتظار برای چت
waiting_pool = {"random": [], "male": [], "female": []}


# --- KEYBOARD & UI HELPERS (توابع کمکی برای ساخت کیبورد) ---
def get_main_menu(user_id):
    """منوی اصلی ربات را بر اساس سکه‌های کاربر ایجاد می‌کند"""
    coins = user_data.get(str(user_id), {}).get('coins', 0)
    keyboard = [
        [InlineKeyboardButton(f"🪙 سکه‌های شما: {coins}", callback_data="my_coins"), InlineKeyboardButton("🎁 هدیه روزانه", callback_data="daily_gift")],
        [InlineKeyboardButton("🔍 جستجوی شانسی (رایگان)", callback_data="search_random")],
        [
            InlineKeyboardButton(f"🧑‍💻 جستجوی پسر ({GENDER_SEARCH_COST} سکه)", callback_data="search_male"),
            InlineKeyboardButton(f"👩‍💻 جستجوی دختر ({GENDER_SEARCH_COST} سکه)", callback_data="search_female"),
        ],
        [InlineKeyboardButton("🔗 دعوت دوستان", callback_data="invite_friends")],
        [InlineKeyboardButton("👤 پروفایل من", callback_data="my_profile"), InlineKeyboardButton("🏆 تالار مشاهیر", callback_data="hall_of_fame")],
        [InlineKeyboardButton("❓ راهنما", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_in_chat_keyboard(partner_id):
    """کیبورد دکمه‌های شیشه‌ای داخل چت را ایجاد می‌کند"""
    keyboard = [
        [
            InlineKeyboardButton("👍 لایک", callback_data=f"like_{partner_id}"),
            InlineKeyboardButton("👤 پروفایلش", callback_data=f"view_partner_{partner_id}"),
            InlineKeyboardButton("🚨 گزارش", callback_data=f"report_{partner_id}"),
        ],
        [InlineKeyboardButton("❌ قطع مکالمه و جستجوی بعدی", callback_data="next_chat")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_profile_edit_menu():
    """منوی ویرایش پروفایل را ایجاد می‌کند"""
    keyboard = [
        [InlineKeyboardButton("✏️ ویرایش نام", callback_data="edit_name"), InlineKeyboardButton("⚧ ویرایش جنسیت", callback_data="edit_gender")],
        [InlineKeyboardButton("🔢 ویرایش سن", callback_data="edit_age"), InlineKeyboardButton("📝 ویرایش بیوگرافی", callback_data="edit_bio")],
        [InlineKeyboardButton("🖼️ تغییر عکس پروفایل", callback_data="edit_photo")],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_gender_keyboard(prefix="set_gender"):
    """کیبورد انتخاب جنسیت را ایجاد می‌کند"""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("پسر 🧑", callback_data=f"{prefix}_male"), 
        InlineKeyboardButton("دختر 👩", callback_data=f"{prefix}_female")
    ]])

def get_cancel_search_keyboard():
    """دکمه لغو جستجو را برای کاربرانی که در صف انتظار هستند ایجاد می‌کند"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو جستجو", callback_data="cancel_search")]])

# --- UTILITY & FILTERING (توابع کاربردی) ---
def is_message_forbidden(text: str) -> bool:
    """بررسی می‌کند که آیا پیام حاوی شماره تلفن، آیدی تلگرام یا لینک است یا خیر"""
    phone_regex = r'\+?\d[\d\s-]{8,12}\d'
    id_regex = r'@[a-zA-Z0-9_]{5,}'
    link_regex = r't\.me/|https?://'
    return bool(re.search(phone_regex, text) or re.search(id_regex, text, re.IGNORECASE) or re.search(link_regex, text, re.IGNORECASE))

def get_user_profile_text(user_id, target_user_id):
    """متن پروفایل یک کاربر را برای نمایش به کاربر دیگر ایجاد می‌کند"""
    profile = user_data.get(str(target_user_id), {})
    if not profile:
        return "پروفایل این کاربر یافت نشد."
    
    is_liked_by = str(user_id) in profile.get('following', [])

    text = (
        f"👤 پروفایل کاربر:\n\n"
        f"🔹 نام: {profile.get('name', 'ثبت نشده')}\n"
        f"🔹 جنسیت: {'پسر' if profile.get('gender') == 'male' else 'دختر' if profile.get('gender') == 'female' else 'ثبت نشده'}\n"
        f"🔹 سن: {profile.get('age', 'ثبت نشده')}\n"
        f"📝 بیو: {profile.get('bio', 'بیوگرافی ثبت نشده است.')}\n"
        f"👍 تعداد لایک‌ها: {len(profile.get('liked_by', []))}\n"
    )
    if is_liked_by:
        text += "\n✨ این کاربر شما را لایک کرده است!"
        
    return text

# --- CORE BOT LOGIC (منطق اصلی ربات) ---

# START & REGISTRATION
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /start را مدیریت می‌کند، کاربر جدید را ثبت‌نام و کاربر قدیمی را خوش‌آمد می‌گوید"""
    user = update.effective_user
    user_id = str(user.id)
    
    if context.args and user_id not in user_data:
        try:
            payload = context.args[0]
            if payload.startswith('ref_') and str(payload.split('_')[1]) != user_id:
                context.user_data['referred_by'] = payload.split('_')[1]
        except Exception as e:
            logger.error(f"Error processing referral link for user {user_id}: {e}")

    if user_id not in user_data:
        user_data[user_id] = {
            "name": user.first_name, "banned": False, "coins": STARTING_COINS,
            "following": [], "liked_by": [], "blocked_users": [],
            "last_daily_gift": None, "bio": "", "age": None, "gender": None,
            "photo": None, "referrals": 0
        }
        if 'referred_by' in context.user_data:
            user_data[user_id]['referred_by'] = context.user_data['referred_by']
        
        save_data(user_data, USERS_DB_FILE)
        
        await update.message.reply_text(
            "🎉 سلام! به «ایران‌گرام» خوش اومدی!\n\n"
            "برای شروع، لطفاً پروفایلت رو با دستور /profile کامل کن."
        )
        return await profile_command(update, context)

    if user_data[user_id].get('banned', False):
        await update.message.reply_text("🚫 شما توسط مدیریت از ربات مسدود شده‌اید.")
        return

    welcome_text = f"سلام {user.first_name}! دوباره به «ایران‌گرام» خوش اومدی 👋\n\nاز منوی زیر استفاده کن."
    await update.message.reply_text(welcome_text, reply_markup=get_main_menu(user_id))

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """شروع مکالمه برای ساخت پروفایل"""
    await update.message.reply_text("لطفاً نام خود را وارد کنید (این نام به دیگران نمایش داده می‌شود):", reply_markup=ReplyKeyboardRemove())
    return PROFILE_NAME

async def received_profile_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['profile_name'] = update.message.text
    await update.message.reply_text("جنسیت خود را انتخاب کنید:", reply_markup=get_gender_keyboard("profile_gender"))
    return PROFILE_GENDER

async def received_profile_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['profile_gender'] = query.data.split('_')[-1]
    await query.edit_message_text("عالی! حالا لطفاً سن خود را به عدد وارد کنید (مثلا: 25):")
    return PROFILE_AGE

async def received_profile_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = str(update.effective_user.id)
    try:
        age = int(update.message.text)
        if not 13 <= age <= 80:
            await update.message.reply_text("سن وارد شده معتبر نیست. لطفاً یک عدد بین 13 تا 80 وارد کنید.")
            return PROFILE_AGE
        
        user_data[user_id].update({
            "name": context.user_data['profile_name'],
            "gender": context.user_data['profile_gender'],
            "age": age
        })

        if 'referred_by' in user_data[user_id]:
            referrer_id = user_data[user_id].pop('referred_by')
            if referrer_id in user_data:
                user_data[referrer_id]['coins'] += REFERRAL_BONUS_COINS
                user_data[referrer_id]['referrals'] += 1
                try:
                    await context.bot.send_message(
                        referrer_id,
                        f"🎉 تبریک! یک نفر با لینک شما عضو شد. {REFERRAL_BONUS_COINS} سکه هدیه گرفتی!"
                    )
                except TelegramError as e:
                    logger.warning(f"Could not send referral bonus message to {referrer_id}: {e}")

        save_data(user_data, USERS_DB_FILE)
        await update.message.reply_text(
            "✅ پروفایل شما با موفقیت تکمیل شد!\nحالا می‌تونی چت رو شروع کنی.",
            reply_markup=get_main_menu(user_id)
        )
        context.user_data.clear()
        return ConversationHandler.END
    except (ValueError, KeyError):
        await update.message.reply_text("ورودی نامعتبر است. لطفاً سن را فقط به صورت عدد وارد کنید.")
        return PROFILE_AGE

# CHATTING LOGIC
async def search_partner(update: Update, context: ContextTypes.DEFAULT_TYPE, search_type: str):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    profile = user_data.get(str(user_id), {})
    if not all(profile.get(key) for key in ['name', 'gender', 'age']):
        await query.message.reply_text("❌ برای شروع چت، اول باید پروفایل خود را با دستور /profile کامل کنی!")
        return

    if user_id in user_partners:
        await query.message.reply_text("شما در حال حاضر در یک چت هستید!")
        return
        
    for queue in waiting_pool.values():
        if user_id in queue:
            await query.message.reply_text("شما از قبل در صف انتظار هستید!", reply_markup=get_cancel_search_keyboard())
            return

    if search_type in ["male", "female"]:
        if user_data[str(user_id)]['coins'] < GENDER_SEARCH_COST:
            await query.message.reply_text(f"🪙 سکه کافی نداری! برای این جستجو به {GENDER_SEARCH_COST} سکه نیاز داری.")
            return
        user_data[str(user_id)]['coins'] -= GENDER_SEARCH_COST
        save_data(user_data, USERS_DB_FILE)
        await query.message.reply_text(f"💰 {GENDER_SEARCH_COST} سکه از حساب شما کسر شد.", reply_markup=get_main_menu(user_id))

    my_gender = user_data[str(user_id)]['gender']
    partner_id = find_partner_in_pool(user_id, my_gender, search_type)

    if partner_id:
        user_partners[user_id] = partner_id
        user_partners[partner_id] = user_id
        
        for uid, pid in [(user_id, partner_id), (partner_id, user_id)]:
            try:
                await context.bot.send_message(
                    uid, "✅ یک هم‌صحبت برای شما پیدا شد!", reply_markup=get_in_chat_keyboard(pid)
                )
            except TelegramError as e:
                logger.error(f"Failed to send message to {uid}: {e}")
                await end_chat_for_both(uid, pid, context, "⚠️ به دلیل مشکل فنی، چت لغو شد.")
                return
    else:
        waiting_pool[search_type if search_type != 'random' else my_gender].append(user_id)
        await query.message.reply_text("⏳ شما در صف انتظار قرار گرفتید...", reply_markup=get_cancel_search_keyboard())

def find_partner_in_pool(user_id, my_gender, search_type):
    """منطق پیدا کردن هم‌صحبت از صف‌های انتظار"""
    if search_type in ["male", "female"]:
        if waiting_pool[search_type]:
            return waiting_pool[search_type].pop(0)
    else: # random search
        opposite_gender = "female" if my_gender == "male" else "male"
        if waiting_pool[opposite_gender]:
            return waiting_pool[opposite_gender].pop(0)
        if waiting_pool["random"]:
            return waiting_pool["random"].pop(0)
        if waiting_pool[my_gender]:
             return waiting_pool[my_gender].pop(0)
    return None

async def end_chat_for_both(user_id, partner_id, context, message_for_partner):
    """چت را برای هر دو کاربر پایان می‌دهد"""
    user_partners.pop(user_id, None)
    user_partners.pop(partner_id, None)
    
    try:
        await context.bot.send_message(partner_id, message_for_partner, reply_markup=get_main_menu(partner_id))
    except TelegramError as e:
        logger.warning(f"Could not notify partner {partner_id} about chat end: {e}")

async def next_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id in user_partners:
        partner_id = user_partners[user_id]
        await end_chat_for_both(user_id, partner_id, context, "❌ طرف مقابل چت را ترک کرد.")
        await query.message.edit_text("شما چت را ترک کردید.", reply_markup=get_main_menu(user_id))
    else:
        await query.answer("شما در حال حاضر در چت نیستید.", show_alert=True)

async def cancel_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    for queue in waiting_pool.values():
        if user_id in queue:
            queue.remove(user_id)
            await query.message.edit_text("جستجوی شما لغو شد.", reply_markup=get_main_menu(user_id))
            return
            
    await query.answer("شما در صف انتظار نیستید.", show_alert=True)

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text

    if is_message_forbidden(text):
        try:
            await update.message.delete()
            await update.message.reply_text("🚫 ارسال شماره تلفن، آیدی یا لینک ممنوع است.", quote=False)
        except TelegramError as e:
            logger.warning(f"Could not delete forbidden message from {user_id}: {e}")
        return
    
    if user_id in user_partners:
        partner_id = user_partners[user_id]
        try:
            await context.bot.send_message(partner_id, text)
        except TelegramError as e:
            logger.warning(f"Failed to forward message from {user_id} to {partner_id}: {e}")
            await update.message.reply_text("⚠️ هم‌صحبت شما دیگر در دسترس نیست. چت پایان یافت.")
            await end_chat_for_both(user_id, partner_id, context, "⚠️ کاربر مقابل دیگر در دسترس نیست. چت پایان یافت.")
    else:
        await update.message.reply_text("شما به کسی وصل نیستی. از منوی زیر استفاده کن:", reply_markup=get_main_menu(user_id))

async def handle_media_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in user_partners:
        await update.message.reply_text("شما به کسی وصل نیستی.", reply_markup=get_main_menu(user_id))
        return

    partner_id = user_partners[user_id]
    message = update.message
    try:
        if message.photo:
            await context.bot.send_photo(partner_id, message.photo[-1].file_id, caption=message.caption)
        elif message.voice:
            await context.bot.send_voice(partner_id, message.voice.file_id)
        elif message.video:
            await context.bot.send_video(partner_id, message.video.file_id, caption=message.caption)
        elif message.sticker:
            await context.bot.send_sticker(partner_id, message.sticker.file_id)
        elif message.animation:
            await context.bot.send_animation(partner_id, message.animation.file_id)
    except TelegramError as e:
        logger.warning(f"Failed to forward media from {user_id} to {partner_id}: {e}")
        await update.message.reply_text("⚠️ ارسال پیام به هم‌صحبت شما با مشکل مواجه شد.")
        await end_chat_for_both(user_id, partner_id, context, "⚠️ کاربر مقابل دیگر در دسترس نیست. چت پایان یافت.")

# --- CALLBACK QUERY HANDLERS (مدیریت دکمه‌های شیشه‌ای) ---
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data
    command, _, param = data.partition('_')
    
    COMMAND_MAP = {
        "search": lambda u, c: search_partner(u, c, param),
        "my": handle_my_commands, "daily": daily_gift, "invite": invite_friends,
        "hall": hall_of_fame, "help": help_command, "main": main_menu_from_callback,
        "like": like_partner, "view": view_partner_profile, "report": report_partner,
        "next": next_chat, "cancel": cancel_search, "edit": start_edit_profile,
        "admin": admin_panel, "broadcast": broadcast_message, "stats": show_stats,
    }
    
    if command in COMMAND_MAP:
        await COMMAND_MAP[command](update, context)
    else:
        await query.answer("دستور ناشناخته.", show_alert=True)

async def main_menu_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("منوی اصلی:", reply_markup=get_main_menu(query.from_user.id))

async def handle_my_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    command = query.data
    user_id = str(query.from_user.id)
    
    if command == "my_profile":
        profile = user_data.get(user_id, {})
        text = get_user_profile_text(user_id, user_id)
        photo_id = profile.get('photo')
        
        # برای جلوگیری از خطای "message is not modified" پیام را حذف و دوباره ارسال می‌کنیم
        await query.message.delete()
        if photo_id:
             await query.message.reply_photo(photo_id, caption=text, reply_markup=get_profile_edit_menu())
        else:
            await query.message.reply_text(text, reply_markup=get_profile_edit_menu())

    elif command == "my_coins":
        coins = user_data.get(user_id, {}).get('coins', 0)
        await query.answer(f"🪙 شما در حال حاضر {coins} سکه دارید.", show_alert=True)

async def daily_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    last_gift_str = user_data[user_id].get('last_daily_gift')
    now = datetime.now()
    
    if last_gift_str:
        time_since_gift = now - datetime.fromisoformat(last_gift_str)
        if time_since_gift < timedelta(hours=24):
            remaining = timedelta(hours=24) - time_since_gift
            hours, rem = divmod(remaining.seconds, 3600)
            minutes, _ = divmod(rem, 60)
            await query.answer(f"شما قبلاً هدیه گرفته‌اید! {hours} ساعت و {minutes} دقیقه دیگر تلاش کنید.", show_alert=True)
            return
            
    user_data[user_id]['coins'] += DAILY_GIFT_COINS
    user_data[user_id]['last_daily_gift'] = now.isoformat()
    save_data(user_data, USERS_DB_FILE)
    
    await query.answer(f"🎁 تبریک! {DAILY_GIFT_COINS} سکه به شما اضافه شد.", show_alert=True)
    await query.edit_message_reply_markup(reply_markup=get_main_menu(user_id))

async def invite_friends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    invite_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    invite_text = config_data.get("invite_text", f"🔥 با این لینک دوستات رو به ربات دعوت کن و با هر عضویت جدید، {REFERRAL_BONUS_COINS} سکه هدیه بگیر! 🔥")
    final_text = f"{invite_text}\n\nلینک دعوت شما:\n`{invite_link}`"
    await query.message.reply_text(final_text, parse_mode=ParseMode.MARKDOWN)

async def hall_of_fame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    valid_users = {uid: data for uid, data in user_data.items() if 'liked_by' in data and 'name' in data}
    sorted_users = sorted(valid_users.items(), key=lambda item: len(item[1].get('liked_by', [])), reverse=True)
    
    text = "🏆 **تالار مشاهیر - ۱۰ کاربر برتر** 🏆\n\n"
    text += "\n".join([f"{i+1}. **{data.get('name', 'ناشناس')}** - {len(data.get('liked_by', []))} لایک 👍" for i, (uid, data) in enumerate(sorted_users[:10])]) or "هنوز کسی در تالار مشاهیر نیست."
    await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    help_text = (
        "**❓ راهنمای ربات**\n\n"
        "🔹 **جستجوی شانسی:** شما را به یک کاربر آنلاین وصل می‌کند.\n"
        "🔹 **جستجوی جنسیت:** با پرداخت سکه، با جنسیت مورد نظر چت می‌کنید.\n"
        "🔹 **هدیه روزانه:** هر ۲۴ ساعت، سکه رایگان دریافت کنید.\n"
        "🔹 **دعوت دوستان:** با دعوت دوستانتان سکه هدیه بگیرید.\n"
        "🔹 **پروفایل من:** اطلاعات خود را مشاهده و ویرایش کنید.\n"
        "⚠️ **قوانین:** ارسال اطلاعات تماس (شماره، آیدی، لینک) ممنوع است."
    )
    await query.message.edit_text(help_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]))

# --- IN-CHAT CALLBACK HANDLERS ---
async def like_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    _, partner_id_str = query.data.split('_')
    
    if str(user_partners.get(user_id)) != partner_id_str:
        await query.answer("شما دیگر با این کاربر در چت نیستید.", show_alert=True)
        return

    if partner_id_str not in user_data[user_id]['following']:
        user_data[user_id]['following'].append(partner_id_str)
        user_data[partner_id_str]['liked_by'].append(user_id)
        save_data(user_data, USERS_DB_FILE)
        await query.answer("شما این کاربر را لایک کردید! 👍", show_alert=True)
        try:
            await context.bot.send_message(partner_id_str, "🎉 خبر خوب! هم‌صحبت شما، شما را لایک کرد!")
        except TelegramError as e:
            logger.warning(f"Could not notify {partner_id_str} about like: {e}")
    else:
        await query.answer("شما قبلاً این کاربر را لایک کرده‌اید.", show_alert=True)

async def view_partner_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    _, partner_id_str = query.data.split('_')

    if str(user_partners.get(user_id)) != partner_id_str:
        await query.answer("شما دیگر با این کاربر در چت نیستید.", show_alert=True)
        return
        
    text = get_user_profile_text(user_id, partner_id_str)
    photo_id = user_data.get(partner_id_str, {}).get('photo')

    await query.answer()
    if photo_id:
        await query.message.reply_photo(photo_id, caption=text)
    else:
        await query.message.reply_text(text)

async def report_partner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    user_id = str(query.from_user.id)
    _, partner_id_str = query.data.split('_')

    if str(user_partners.get(user_id)) != partner_id_str:
        await query.answer("شما دیگر با این کاربر در چت نیستید.", show_alert=True)
        return ConversationHandler.END
    
    context.user_data['reportee_id'] = partner_id_str
    await query.message.reply_text("لطفاً دلیل گزارش خود را بنویسید. پیام شما برای مدیریت ارسال خواهد شد.")
    return REPORT_REASON

async def received_report_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    reporter_id = str(update.effective_user.id)
    reportee_id = context.user_data.pop('reportee_id')
    reason = update.message.text
    
    report = {"reporter": reporter_id, "reportee": reportee_id, "reason": reason, "timestamp": datetime.now().isoformat()}
    reports_data.append(report)
    save_data(reports_data, REPORTS_DB_FILE)
    
    reporter_name = user_data.get(reporter_id, {}).get('name', 'N/A')
    reportee_name = user_data.get(reportee_id, {}).get('name', 'N/A')
    report_text = f"🚨 **گزارش جدید** 🚨\n\n**گزارش دهنده:** `{reporter_id}` ({reporter_name})\n**گزارش شده:** `{reportee_id}` ({reportee_name})\n**دلیل:** {reason}"
    await context.bot.send_message(ADMIN_ID, report_text, parse_mode=ParseMode.MARKDOWN)
    
    await update.message.reply_text("گزارش شما ثبت و برای مدیریت ارسال شد. سپاسگزاریم.")
    return ConversationHandler.END

# --- PROFILE EDITING CONVERSATION ---
async def start_edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data
    
    ACTION_MAP = {
        "edit_name": ("لطفاً نام جدید خود را وارد کنید:", EDIT_NAME),
        "edit_gender": ("جنسیت جدید خود را انتخاب کنید:", EDIT_GENDER),
        "edit_age": ("لطفاً سن جدید خود را به عدد وارد کنید:", EDIT_AGE),
        "edit_bio": ("بیوگرافی جدید خود را وارد کنید (حداکثر ۲۰۰ کاراکتر):", EDIT_BIO),
        "edit_photo": ("عکس پروفایل جدید خود را ارسال کنید یا /remove_photo را برای حذف عکس فعلی بزنید:", EDIT_PHOTO),
    }

    if action not in ACTION_MAP: return ConversationHandler.END
    prompt, state = ACTION_MAP[action]
    
    reply_markup = get_gender_keyboard("update_gender") if action == "edit_gender" else None
    await query.message.edit_text(prompt, reply_markup=reply_markup)
    return state

async def save_profile_change(update: Update, context: ContextTypes.DEFAULT_TYPE, field: str, value, message: str):
    """یک تابع کمکی برای ذخیره تغییرات پروفایل و ارسال پیام تایید"""
    user_id = str(update.effective_user.id)
    user_data[user_id][field] = value
    save_data(user_data, USERS_DB_FILE)
    await update.effective_message.reply_text(f"✅ {message} شما با موفقیت تغییر کرد.", reply_markup=get_main_menu(user_id))
    return ConversationHandler.END

async def received_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await save_profile_change(update, context, 'name', update.message.text, "نام")

async def received_new_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.delete()
    return await save_profile_change(query, context, 'gender', query.data.split('_')[-1], "جنسیت")

async def received_new_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        age = int(update.message.text)
        if not 13 <= age <= 80:
            await update.message.reply_text("سن معتبر نیست. عددی بین 13 تا 80 وارد کنید.")
            return EDIT_AGE
        return await save_profile_change(update, context, 'age', age, "سن")
    except ValueError:
        await update.message.reply_text("لطفاً سن را فقط به صورت عدد وارد کنید.")
        return EDIT_AGE

async def received_new_bio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if len(update.message.text) > 200:
        await update.message.reply_text("بیوگرافی طولانی است (حداکثر ۲۰۰ کاراکتر).")
        return EDIT_BIO
    return await save_profile_change(update, context, 'bio', update.message.text, "بیوگرافی")

async def received_new_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == '/remove_photo':
        return await save_profile_change(update, context, 'photo', None, "عکس پروفایل")
    if update.message.photo:
        return await save_profile_change(update, context, 'photo', update.message.photo[-1].file_id, "عکس پروفایل")
    
    await update.message.reply_text("لطفاً یک عکس ارسال کنید.")
    return EDIT_PHOTO

# --- ADMIN COMMANDS ---
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    keyboard = [[InlineKeyboardButton("📊 آمار ربات", callback_data="admin_stats")], [InlineKeyboardButton("📢 ارسال پیام همگانی", callback_data="admin_broadcast")]]
    await update.message.reply_text("به پنل مدیریت خوش آمدید.", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.split('_')[1]
    if action == "stats": await show_stats(update, context)
    elif action == "broadcast": await query.message.edit_text("لطفاً پیام خود را برای ارسال به همه کاربران وارد کنید:")

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = len(user_data)
    males = sum(1 for u in user_data.values() if u.get('gender') == 'male')
    females = sum(1 for u in user_data.values() if u.get('gender') == 'female')
    banned = sum(1 for u in user_data.values() if u.get('banned'))
    stats = f"📊 **آمار ربات**\n\n- کل کاربران: {total}\n- پسر: {males}\n- دختر: {females}\n- مسدود: {banned}\n- گزارش‌ها: {len(reports_data)}"
    await update.callback_query.message.edit_text(stats, parse_mode=ParseMode.MARKDOWN)

async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    message = update.message.text.replace("/broadcast ", "")
    users = [uid for uid, data in user_data.items() if not data.get('banned')]
    await update.message.reply_text(f"در حال ارسال پیام به {len(users)} کاربر...")
    sent, failed = 0, 0
    for uid in users:
        try:
            await context.bot.send_message(uid, message)
            sent += 1
        except TelegramError: failed += 1
    await update.message.reply_text(f"✅ ارسال به {sent} کاربر موفق بود.\n❌ ارسال به {failed} کاربر ناموفق بود.")

# --- GENERAL HANDLERS ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('عملیات لغو شد.', reply_markup=get_main_menu(update.effective_user.id))
    context.user_data.clear()
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(context.error, TelegramError) and "Conflict" in str(context.error):
        logger.critical("Conflict error: Make sure only one bot instance is running.")
        return
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("متاسفانه خطایی رخ داد. لطفاً دوباره تلاش کنید.")
        except TelegramError:
            logger.error("Failed to send error message to user.")

# --- MAIN APPLICATION SETUP ---
def main() -> None:
    """شروع به کار ربات و تنظیم کنترل‌کننده‌ها"""
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    application = Application.builder().token(TOKEN).build()
    
    # مکالمه‌ها (Conversations)
    profile_creation_handler = ConversationHandler(
        entry_points=[CommandHandler("profile", profile_command)],
        states={
            PROFILE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_profile_name)],
            PROFILE_GENDER: [CallbackQueryHandler(received_profile_gender, pattern="^profile_gender_")],
            PROFILE_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_profile_age)],
        },
        fallbacks=[CommandHandler("cancel", cancel)], per_message=False
    )
    
    profile_edit_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_edit_profile, pattern="^edit_")],
        states={
            EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_new_name)],
            EDIT_GENDER: [CallbackQueryHandler(received_new_gender, pattern="^update_gender_")],
            EDIT_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_new_age)],
            EDIT_BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_new_bio)],
            EDIT_PHOTO: [MessageHandler(filters.PHOTO | (filters.TEXT & filters.Regex('^/remove_photo$')), received_new_photo)],
        },
        fallbacks=[CommandHandler("cancel", cancel)], per_message=False
    )

    report_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(report_partner, pattern="^report_")],
        states={REPORT_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_report_reason)]},
        fallbacks=[CommandHandler("cancel", cancel)], per_message=False
    )
    
    # افزودن کنترل‌کننده‌ها (Handlers)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("broadcast", broadcast_message, filters=filters.User(ADMIN_ID)))
    application.add_handler(CommandHandler("cancel", cancel))
    
    application.add_handler(profile_creation_handler)
    application.add_handler(profile_edit_handler)
    application.add_handler(report_handler)
    
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    # ✅ FIX: The filter for stickers is `filters.Sticker` (capital S), not `STICKER`.
    application.add_handler(MessageHandler(filters.VOICE | filters.PHOTO | filters.VIDEO | filters.Sticker.ALL | filters.ANIMATION, handle_media_message))

    application.add_error_handler(error_handler)
    
    logger.info("Bot is starting to poll...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
