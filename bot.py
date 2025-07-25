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
# توکن ربات خود را در اینجا قرار دهید
TOKEN = os.environ.get("TELEGRAM_TOKEN", "7689216297:AAHVucWhXpGlp15Ulk2zsppst1gDH9PCZnQ") 
# آیدی عددی ادمین ربات
ADMIN_ID = int(os.environ.get("ADMIN_ID", 6929024145))
# یوزرنیم ربات بدون @
BOT_USERNAME = os.environ.get("BOT_USERNAME", "irangram_chatbot")

# --- DATABASE & CONSTANTS (پایگاه داده و مقادیر ثابت) ---
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
# وضعیت‌ها برای ویرایش پروفایل
EDIT_CONVO, EDIT_NAME, EDIT_GENDER, EDIT_AGE, EDIT_BIO, EDIT_PHOTO, REPORT_REASON = range(3, 10)


# --- DATABASE & CONFIG MANAGEMENT (مدیریت فایل‌های JSON) ---
def load_data(filename, default_type=dict):
    try:
        with open(filename, "r", encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # اگر فایل وجود نداشت یا خالی بود، یک دیکشنری یا لیست خالی برمی‌گرداند
        return default_type()

def save_data(data, filename):
    with open(filename, "w", encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# بارگذاری داده‌ها در هنگام شروع به کار ربات
user_data = load_data(USERS_DB_FILE)
reports_data = load_data(REPORTS_DB_FILE, default_type=list)
config_data = load_data(CONFIG_FILE)

# --- GLOBAL VARIABLES (متغیرهای سراسری) ---
# این دیکشنری‌ها وضعیت‌های لحظه‌ای ربات را نگه می‌دارند
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
    """بررسی می‌کند که آیا پیام حاوی شماره تلفن یا آیدی تلگرام است یا خیر"""
    # این عبارات باقاعده شماره تلفن‌ها و آیدی‌های تلگرامی را پیدا می‌کنند
    phone_regex = r'\+?\d[\d\s-]{8,12}\d'
    id_regex = r'@[a-zA-Z0-9_]{5,}'
    link_regex = r't\.me/|https?://'
    return bool(re.search(phone_regex, text) or re.search(id_regex, text, re.IGNORECASE) or re.search(link_regex, text, re.IGNORECASE))

def get_user_profile_text(user_id, target_user_id):
    """متن پروفایل یک کاربر را برای نمایش به کاربر دیگر ایجاد می‌کند"""
    profile = user_data.get(str(target_user_id), {})
    if not profile:
        return "پروفایل این کاربر یافت نشد."
    
    # بررسی اینکه آیا کاربر فعلی توسط کاربر هدف لایک شده است
    is_liked_by = str(user_id) in profile.get('following', [])

    text = (
        f"👤 پروفایل کاربر:\n\n"
        f"🔹 نام: {profile.get('name', 'ثبت نشده')}\n"
        f"🔹 جنسیت: {'پسر' if profile.get('gender') == 'male' else 'دختر' if profile.get('gender') == 'female' else 'ثبت نشده'}\n"
        f"🔹 سن: {profile.get('age', 'ثبت نشده')}\n"
        f"📝 بیو: {profile.get('bio', 'ثبت نشده') or 'بیوگرافی ثبت نشده است.'}\n"
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
    
    # بررسی لینک دعوت
    if context.args and user_id not in user_data:
        try:
            payload = context.args[0]
            if payload.startswith('ref_'):
                referrer_id = payload.split('_')[1]
                # کاربر نمی‌تواند خودش را دعوت کند
                if str(referrer_id) != user_id:
                    # این مقدار به صورت موقت ذخیره می‌شود تا پس از تکمیل پروفایل استفاده شود
                    context.user_data['referred_by'] = referrer_id
        except Exception as e:
            logger.error(f"Error processing referral link for user {user_id}: {e}")

    # اگر کاربر جدید است
    if user_id not in user_data:
        user_data[user_id] = {
            "name": user.first_name,
            "banned": False,
            "coins": STARTING_COINS,
            "likes": 0, # دیگر استفاده نمی‌شود، می‌توان حذف کرد
            "following": [], # کسانی که این کاربر لایک کرده
            "liked_by": [], # کسانی که این کاربر را لایک کرده‌اند
            "blocked_users": [],
            "last_daily_gift": None,
            "bio": "",
            "age": None,
            "gender": None,
            "photo": None,
            "referrals": 0
        }
        if 'referred_by' in context.user_data:
            user_data[user_id]['referred_by'] = context.user_data['referred_by']
        
        save_data(user_data, USERS_DB_FILE)
        
        await update.message.reply_text(
            "🎉 سلام! به «ایران‌گرام» خوش اومدی!\n\n"
            "اینجا می‌تونی به صورت ناشناس با بقیه صحبت کنی.\n\n"
            "برای شروع، لطفاً پروفایلت رو کامل کن. روی /profile کلیک کن یا این دستور رو تایپ کن."
        )
        # به طور خودکار کاربر را به مرحله اول ساخت پروفایل هدایت می‌کنیم
        await profile_command(update, context)
        return

    # اگر کاربر مسدود شده است
    if user_data[user_id].get('banned', False):
        await update.message.reply_text("🚫 شما توسط مدیریت از ربات مسدود شده‌اید و نمی‌توانید از امکانات آن استفاده کنید.")
        return

    # خوش‌آمدگویی به کاربر قدیمی
    welcome_text = (
        f"سلام {user.first_name}! دوباره به «ایران‌گرام» خوش اومدی 👋\n\n"
        "از منوی زیر برای شروع استفاده کن."
    )
    await update.message.reply_text(welcome_text, reply_markup=get_main_menu(user_id))

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """شروع مکالمه برای ساخت پروفایل"""
    await update.message.reply_text("لطفاً نام خود را وارد کنید (این نام به دیگران نمایش داده می‌شود):", reply_markup=ReplyKeyboardRemove())
    return PROFILE_NAME

async def received_profile_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """نام کاربر را دریافت و درخواست جنسیت می‌کند"""
    context.user_data['profile_name'] = update.message.text
    await update.message.reply_text("جنسیت خود را انتخاب کنید:", reply_markup=get_gender_keyboard("profile_gender"))
    return PROFILE_GENDER

async def received_profile_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """جنسیت کاربر را دریافت و درخواست سن می‌کند"""
    query = update.callback_query
    await query.answer()
    context.user_data['profile_gender'] = query.data.split('_')[-1]
    await query.edit_message_text("عالی! حالا لطفاً سن خود را به عدد وارد کنید (مثلا: 25):")
    return PROFILE_AGE

async def received_profile_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """سن کاربر را دریافت، پروفایل را ذخیره و مکالمه را تمام می‌کند"""
    user_id = str(update.effective_user.id)
    try:
        age = int(update.message.text)
        if not 13 <= age <= 80:
            await update.message.reply_text("سن وارد شده معتبر نیست. لطفاً یک عدد بین 13 تا 80 وارد کنید.")
            return PROFILE_AGE
        
        # ذخیره اطلاعات پروفایل
        user_data[user_id].update({
            "name": context.user_data['profile_name'],
            "gender": context.user_data['profile_gender'],
            "age": age
        })

        # اعمال پاداش دعوت اگر وجود داشته باشد
        if 'referred_by' in user_data[user_id]:
            referrer_id = user_data[user_id]['referred_by']
            if referrer_id in user_data:
                user_data[referrer_id]['coins'] = user_data[referrer_id].get('coins', 0) + REFERRAL_BONUS_COINS
                user_data[referrer_id]['referrals'] = user_data[referrer_id].get('referrals', 0) + 1
                try:
                    await context.bot.send_message(
                        referrer_id,
                        f"🎉 تبریک! یک نفر با لینک شما عضو شد و پروفایلش را تکمیل کرد. {REFERRAL_BONUS_COINS} سکه هدیه گرفتی!"
                    )
                except TelegramError as e:
                    logger.warning(f"Could not send referral bonus message to {referrer_id}: {e}")
            # حذف کلید موقت
            del user_data[user_id]['referred_by']

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
    """کاربر را در صف انتظار قرار می‌دهد یا به یک هم‌صحبت وصل می‌کند"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    # بررسی کامل بودن پروفایل
    profile = user_data.get(str(user_id), {})
    if not all(profile.get(key) for key in ['name', 'gender', 'age']):
        await query.message.reply_text("❌ برای شروع چت، اول باید پروفایل خود را با دستور /profile کامل کنی!")
        return

    if user_id in user_partners:
        await query.message.reply_text("شما در حال حاضر در یک چت هستید! ابتدا چت فعلی را تمام کنید.")
        return
        
    for queue in waiting_pool.values():
        if user_id in queue:
            await query.message.reply_text("شما از قبل در صف انتظار هستید!", reply_markup=get_cancel_search_keyboard())
            return

    # کسر هزینه برای جستجوی جنسیت خاص
    if search_type in ["male", "female"]:
        if user_data[str(user_id)]['coins'] < GENDER_SEARCH_COST:
            await query.message.reply_text(f"🪙 سکه کافی نداری! برای این جستجو به {GENDER_SEARCH_COST} سکه نیاز داری.")
            return
        user_data[str(user_id)]['coins'] -= GENDER_SEARCH_COST
        save_data(user_data, USERS_DB_FILE)
        await query.message.reply_text(f"💰 {GENDER_SEARCH_COST} سکه از حساب شما کسر شد.", reply_markup=get_main_menu(user_id))


    # پیدا کردن هم‌صحبت
    partner_id = None
    # تعیین صف جستجوی طرف مقابل
    my_gender = user_data[str(user_id)]['gender']
    
    # اگر کاربر به دنبال جنسیت خاصی است
    if search_type in ["male", "female"]:
        target_queue = waiting_pool[search_type]
        if target_queue:
            partner_id = target_queue.pop(0)
    # اگر جستجوی شانسی است
    else: # search_type == "random"
        # اول در صف جنس مخالف جستجو کن
        opposite_gender = "female" if my_gender == "male" else "male"
        if waiting_pool[opposite_gender]:
            partner_id = waiting_pool[opposite_gender].pop(0)
        # اگر کسی نبود، در صف جستجوی شانسی بگرد
        elif waiting_pool["random"]:
            partner_id = waiting_pool["random"].pop(0)
        # اگر باز هم کسی نبود، در صف همجنس‌ها بگرد
        elif waiting_pool[my_gender]:
             partner_id = waiting_pool[my_gender].pop(0)

    if partner_id:
        user_partners[user_id] = partner_id
        user_partners[partner_id] = user_id
        
        # اطلاع‌رسانی به هر دو کاربر
        for uid, pid in [(user_id, partner_id), (partner_id, user_id)]:
            try:
                await context.bot.send_message(
                    uid, 
                    "✅ یک هم‌صحبت برای شما پیدا شد! می‌تونید صحبت رو شروع کنید.", 
                    reply_markup=get_in_chat_keyboard(pid)
                )
            except TelegramError as e:
                logger.error(f"Failed to send message to {uid}: {e}")
                # اگر ارسال پیام به یکی از طرفین ممکن نباشد، چت را لغو کن
                await end_chat_for_both(uid, pid, context, "⚠️ به دلیل مشکل فنی، چت لغو شد.")
                return
    else:
        # اضافه کردن کاربر به صف انتظار مناسب
        if search_type == "random":
            # کاربرانی که جستجوی شانسی می‌زنند در صف جنسیت خودشان می‌روند تا منطق پیدا کردن ساده‌تر شود
             waiting_pool[my_gender].append(user_id)
        else:
            waiting_pool[search_type].append(user_id)
        await query.message.reply_text("⏳ شما در صف انتظار قرار گرفتید... لطفاً صبور باشید.", reply_markup=get_cancel_search_keyboard())

async def end_chat_for_both(user_id, partner_id, context, message_for_partner):
    """چت را برای هر دو کاربر پایان می‌دهد"""
    if user_id in user_partners:
        del user_partners[user_id]
    if partner_id in user_partners:
        del user_partners[partner_id]
    
    try:
        await context.bot.send_message(partner_id, message_for_partner, reply_markup=get_main_menu(partner_id))
    except TelegramError as e:
        logger.warning(f"Could not notify partner {partner_id} about chat end: {e}")

async def next_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """چت فعلی را قطع و کاربر را به منوی اصلی برمی‌گرداند"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id in user_partners:
        partner_id = user_partners[user_id]
        
        await end_chat_for_both(user_id, partner_id, context, "❌ طرف مقابل چت را ترک کرد.")
        
        await query.message.edit_text("شما چت را ترک کردید. برای شروع چت جدید از منو استفاده کنید.", reply_markup=get_main_menu(user_id))
    else:
        await query.answer("شما در حال حاضر در چت نیستید.", show_alert=True)

async def cancel_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """کاربر را از صف انتظار خارج می‌کند"""
    query = update.callback_query
    user_id = query.from_user.id
    
    removed = False
    for queue in waiting_pool.values():
        if user_id in queue:
            queue.remove(user_id)
            removed = True
            break
            
    if removed:
        await query.message.edit_text("جستجوی شما لغو شد.", reply_markup=get_main_menu(user_id))
    else:
        await query.answer("شما در صف انتظار نیستید.", show_alert=True)

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پیام‌های متنی را مدیریت می‌کند (ارسال به هم‌صحبت یا پاسخ مناسب)"""
    user_id = update.effective_user.id
    text = update.message.text

    # فیلتر کردن محتوای ممنوعه
    if is_message_forbidden(text):
        try:
            await update.message.delete()
            await update.message.reply_text("🚫 ارسال شماره تلفن، آیدی یا لینک در ربات ممنوع است و پیام شما حذف شد.", quote=False)
        except TelegramError as e:
            logger.warning(f"Could not delete forbidden message from {user_id}: {e}")
        return
    
    # اگر کاربر در چت است، پیام را به طرف مقابل ارسال کن
    if user_id in user_partners:
        partner_id = user_partners[user_id]
        try:
            await context.bot.send_message(partner_id, text)
        except TelegramError as e:
            logger.warning(f"Failed to forward message from {user_id} to {partner_id}: {e}")
            await update.message.reply_text("⚠️ به نظر می‌رسد هم‌صحبت شما ربات را مسدود کرده است. چت به صورت خودکار پایان یافت.")
            await end_chat_for_both(user_id, partner_id, context, "⚠️ کاربر مقابل دیگر در دسترس نیست. چت پایان یافت.")
    else:
        await update.message.reply_text("شما به کسی وصل نیستی. از منوی زیر استفاده کن:", reply_markup=get_main_menu(user_id))

async def handle_media_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پیام‌های رسانه‌ای (عکس، ویدیو، استیکر و...) را مدیریت می‌کند"""
    user_id = update.effective_user.id
    if user_id in user_partners:
        partner_id = user_partners[user_id]
        try:
            if update.message.photo:
                await context.bot.send_photo(partner_id, update.message.photo[-1].file_id, caption=update.message.caption)
            elif update.message.voice:
                await context.bot.send_voice(partner_id, update.message.voice.file_id)
            elif update.message.video:
                await context.bot.send_video(partner_id, update.message.video.file_id, caption=update.message.caption)
            elif update.message.sticker:
                await context.bot.send_sticker(partner_id, update.message.sticker.file_id)
            elif update.message.animation:
                await context.bot.send_animation(partner_id, update.message.animation.file_id)
        except TelegramError as e:
            logger.warning(f"Failed to forward media from {user_id} to {partner_id}: {e}")
            await update.message.reply_text("⚠️ ارسال پیام به هم‌صحبت شما با مشکل مواجه شد. ممکن است او ربات را بلاک کرده باشد.")
            await end_chat_for_both(user_id, partner_id, context, "⚠️ کاربر مقابل دیگر در دسترس نیست. چت پایان یافت.")
    else:
        await update.message.reply_text("شما به کسی وصل نیستی. برای ارسال رسانه ابتدا یک چت را شروع کنید.", reply_markup=get_main_menu(user_id))

# --- CALLBACK QUERY HANDLERS (مدیریت دکمه‌های شیشه‌ای) ---
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تمام callback query ها را به تابع مناسب هدایت می‌کند"""
    query = update.callback_query
    data = query.data
    user_id = str(query.from_user.id)

    # جدا کردن دستور و پارامتر
    command, _, param = data.partition('_')
    
    # نقشه برای مرتبط کردن دستورات با توابع
    COMMAND_MAP = {
        "search": search_partner,
        "my": handle_my_commands,
        "daily": daily_gift,
        "invite": invite_friends,
        "hall": hall_of_fame,
        "help": help_command,
        "main": main_menu_from_callback,
        "like": like_partner,
        "view": view_partner_profile,
        "report": report_partner,
        "next": next_chat,
        "cancel": cancel_search,
        "edit": start_edit_profile,
        "admin": admin_panel,
        "broadcast": broadcast_message,
        "stats": show_stats,
    }
    
    handler = COMMAND_MAP.get(command)
    
    if handler:
        # برای search_partner، پارامتر نوع جستجو است
        if command == "search":
            await handler(update, context, param)
        else:
            await handler(update, context)
    else:
        await query.answer("دستور ناشناخته.", show_alert=True)

async def main_menu_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی اصلی از طریق یک دکمه بازگشت"""
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("منوی اصلی:", reply_markup=get_main_menu(query.from_user.id))

async def handle_my_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستورات مربوط به 'my' مانند my_profile و my_coins را مدیریت می‌کند"""
    query = update.callback_query
    command = query.data
    user_id = str(query.from_user.id)
    
    if command == "my_profile":
        profile = user_data.get(user_id, {})
        text = get_user_profile_text(user_id, user_id)
        # نمایش عکس پروفایل اگر وجود داشته باشد
        photo_id = profile.get('photo')
        if photo_id:
             await query.message.reply_photo(photo_id, caption=text, reply_markup=get_profile_edit_menu())
             await query.message.delete() # حذف پیام متنی قبلی
        else:
            await query.message.edit_text(text, reply_markup=get_profile_edit_menu())

    elif command == "my_coins":
        coins = user_data.get(user_id, {}).get('coins', 0)
        await query.answer(f"🪙 شما در حال حاضر {coins} سکه دارید.", show_alert=True)

async def daily_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش هدیه روزانه"""
    query = update.callback_query
    user_id = str(query.from_user.id)
    
    last_gift_str = user_data[user_id].get('last_daily_gift')
    now = datetime.now()
    
    if last_gift_str:
        last_gift_time = datetime.fromisoformat(last_gift_str)
        if now - last_gift_time < timedelta(hours=24):
            remaining = timedelta(hours=24) - (now - last_gift_time)
            hours, remainder = divmod(remaining.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            await query.answer(f"شما قبلاً هدیه امروز را گرفته‌اید! {hours} ساعت و {minutes} دقیقه دیگر دوباره تلاش کنید.", show_alert=True)
            return
            
    user_data[user_id]['coins'] = user_data[user_id].get('coins', 0) + DAILY_GIFT_COINS
    user_data[user_id]['last_daily_gift'] = now.isoformat()
    save_data(user_data, USERS_DB_FILE)
    
    await query.answer(f"🎁 تبریک! {DAILY_GIFT_COINS} سکه به حساب شما اضافه شد.", show_alert=True)
    # آپدیت کردن منو برای نمایش سکه جدید
    await query.message.edit_reply_markup(reply_markup=get_main_menu(user_id))

async def invite_friends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال لینک دعوت برای کاربر"""
    query = update.callback_query
    user_id = query.from_user.id
    invite_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    
    invite_text = config_data.get("invite_text", 
        f"🔥 با این لینک دوستات رو به بهترین ربات چت ناشناس دعوت کن و با هر عضویت جدید که پروفایلش رو کامل کنه، {REFERRAL_BONUS_COINS} سکه هدیه بگیر! 🔥"
    )
    
    final_text = f"{invite_text}\n\nلینک دعوت شما:\n`{invite_link}`" # Use markdown for easy copy
    await query.message.reply_text(final_text, parse_mode=ParseMode.MARKDOWN)
    await query.answer()

async def hall_of_fame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش تالار مشاهیر (کاربران با بیشترین لایک)"""
    query = update.callback_query
    # فیلتر کردن کاربرانی که پروفایل کامل دارند
    valid_users = {uid: data for uid, data in user_data.items() if 'liked_by' in data and 'name' in data}
    sorted_users = sorted(valid_users.items(), key=lambda item: len(item[1].get('liked_by', [])), reverse=True)
    
    text = "🏆 **تالار مشاهیر - ۱۰ کاربر برتر** 🏆\n\n"
    if not sorted_users:
        text += "هنوز کسی در تالار مشاهیر ثبت نشده است."
    else:
        for i, (user_id, data) in enumerate(sorted_users[:10]):
            likes = len(data.get('liked_by', []))
            name = data.get('name', 'ناشناس')
            text += f"{i+1}. **{name}** - {likes} لایک 👍\n"
            
    await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش پیام راهنما"""
    query = update.callback_query
    help_text = (
        "**❓ راهنمای ربات ایران‌گرام**\n\n"
        "🔹 **جستجوی شانسی:** شما را به یک کاربر آنلاین (پسر یا دختر) وصل می‌کند.\n"
        "🔹 **جستجوی پسر/دختر:** با پرداخت سکه، فقط با جنسیت مورد نظر شما چت می‌کنید.\n"
        "🔹 **هدیه روزانه:** هر ۲۴ ساعت یک بار می‌توانید مقداری سکه رایگان دریافت کنید.\n"
        "🔹 **دعوت دوستان:** با دعوت از دوستانتان، پس از تکمیل پروفایل توسط آن‌ها، سکه هدیه بگیرید.\n"
        "🔹 **پروفایل من:** اطلاعات خود را مشاهده و ویرایش کنید.\n"
        "🔹 **تالار مشاهیر:** لیست محبوب‌ترین کاربران ربات را ببینید.\n\n"
        "⚠️ **قوانین:** ارسال هرگونه اطلاعات تماس (شماره، آیدی، لینک) ممنوع است و منجر به حذف پیام و در صورت تکرار، مسدود شدن شما می‌شود."
    )
    await query.message.edit_text(help_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]))

# --- IN-CHAT CALLBACK HANDLERS ---
async def like_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش لایک کردن هم‌صحبت"""
    query = update.callback_query
    user_id = str(query.from_user.id)
    _, partner_id_str = query.data.split('_')
    
    # اطمینان از اینکه کاربر هنوز در چت با همان فرد است
    if user_id not in user_partners or str(user_partners[user_id]) != partner_id_str:
        await query.answer("شما دیگر با این کاربر در چت نیستید.", show_alert=True)
        return

    partner_id = str(partner_id_str)
    
    if partner_id not in user_data[user_id]['following']:
        user_data[user_id]['following'].append(partner_id)
        user_data[partner_id]['liked_by'].append(user_id)
        save_data(user_data, USERS_DB_FILE)
        await query.answer("شما این کاربر را لایک کردید! 👍", show_alert=True)
        try:
            await context.bot.send_message(partner_id, "🎉 خبر خوب! هم‌صحبت شما، شما را لایک کرد!")
        except TelegramError as e:
            logger.warning(f"Could not notify {partner_id} about like: {e}")
    else:
        await query.answer("شما قبلاً این کاربر را لایک کرده‌اید.", show_alert=True)

async def view_partner_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش پروفایل هم‌صحبت"""
    query = update.callback_query
    user_id = str(query.from_user.id)
    _, partner_id_str = query.data.split('_')

    if user_id not in user_partners or str(user_partners[user_id]) != partner_id_str:
        await query.answer("شما دیگر با این کاربر در چت نیستید.", show_alert=True)
        return
        
    text = get_user_profile_text(user_id, partner_id_str)
    profile = user_data.get(partner_id_str, {})
    photo_id = profile.get('photo')

    await query.answer()
    if photo_id:
        await query.message.reply_photo(photo_id, caption=text)
    else:
        await query.message.reply_text(text)

async def report_partner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """شروع روند گزارش کاربر"""
    query = update.callback_query
    user_id = str(query.from_user.id)
    _, partner_id_str = query.data.split('_')

    if user_id not in user_partners or str(user_partners[user_id]) != partner_id_str:
        await query.answer("شما دیگر با این کاربر در چت نیستید.", show_alert=True)
        return ConversationHandler.END
    
    context.user_data['reportee_id'] = partner_id_str
    await query.message.reply_text("لطفاً دلیل گزارش خود را بنویسید. پیام شما برای مدیریت ارسال خواهد شد.")
    return REPORT_REASON

async def received_report_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت دلیل گزارش و ارسال آن به ادمین"""
    reporter_id = str(update.effective_user.id)
    reportee_id = context.user_data['reportee_id']
    reason = update.message.text
    
    report = {
        "reporter": reporter_id,
        "reportee": reportee_id,
        "reason": reason,
        "timestamp": datetime.now().isoformat()
    }
    reports_data.append(report)
    save_data(reports_data, REPORTS_DB_FILE)
    
    report_text = (
        f"🚨 **گزارش جدید** 🚨\n\n"
        f"🔹 **گزارش دهنده:** `{reporter_id}` (نام: {user_data.get(reporter_id, {}).get('name', 'N/A')})\n"
        f"🔹 **گزارش شده:** `{reportee_id}` (نام: {user_data.get(reportee_id, {}).get('name', 'N/A')})\n"
        f"🔹 **دلیل:** {reason}"
    )
    await context.bot.send_message(ADMIN_ID, report_text, parse_mode=ParseMode.MARKDOWN)
    
    await update.message.reply_text("گزارش شما ثبت شد و برای مدیریت ارسال گردید. از همکاری شما سپاسگزاریم.")
    
    context.user_data.clear()
    return ConversationHandler.END

# --- PROFILE EDITING CONVERSATION ---
async def start_edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """شروع مکالمه برای ویرایش یکی از فیلدهای پروفایل"""
    query = update.callback_query
    await query.answer()
    action = query.data

    ACTION_MAP = {
        "edit_name": ("لطفاً نام جدید خود را وارد کنید:", EDIT_NAME),
        "edit_gender": ("جنسیت جدید خود را انتخاب کنید:", EDIT_GENDER),
        "edit_age": ("لطفاً سن جدید خود را به عدد وارد کنید:", EDIT_AGE),
        "edit_bio": ("بیوگرافی جدید خود را وارد کنید (حداکثر ۲۰۰ کاراکتر):", EDIT_BIO),
        "edit_photo": ("عکس پروفایل جدید خود را ارسال کنید:", EDIT_PHOTO),
    }

    if action not in ACTION_MAP:
        return ConversationHandler.END

    prompt, state = ACTION_MAP[action]
    
    if action == "edit_gender":
        await query.message.edit_text(prompt, reply_markup=get_gender_keyboard("update_gender"))
    else:
        await query.message.edit_text(prompt)
        
    return state

async def received_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = str(update.effective_user.id)
    user_data[user_id]['name'] = update.message.text
    save_data(user_data, USERS_DB_FILE)
    await update.message.reply_text("✅ نام شما با موفقیت تغییر کرد.", reply_markup=get_main_menu(user_id))
    return ConversationHandler.END

async def received_new_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    user_data[user_id]['gender'] = query.data.split('_')[-1]
    save_data(user_data, USERS_DB_FILE)
    await query.message.edit_text("✅ جنسیت شما با موفقیت تغییر کرد.", reply_markup=get_main_menu(user_id))
    return ConversationHandler.END

async def received_new_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = str(update.effective_user.id)
    try:
        age = int(update.message.text)
        if not 13 <= age <= 80:
            await update.message.reply_text("سن وارد شده معتبر نیست. لطفاً یک عدد بین 13 تا 80 وارد کنید.")
            return EDIT_AGE
        user_data[user_id]['age'] = age
        save_data(user_data, USERS_DB_FILE)
        await update.message.reply_text("✅ سن شما با موفقیت تغییر کرد.", reply_markup=get_main_menu(user_id))
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("ورودی نامعتبر است. لطفاً سن را فقط به صورت عدد وارد کنید.")
        return EDIT_AGE

async def received_new_bio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = str(update.effective_user.id)
    bio = update.message.text
    if len(bio) > 200:
        await update.message.reply_text("بیوگرافی شما طولانی است. لطفاً متنی کوتاه‌تر (حداکثر ۲۰۰ کاراکتر) وارد کنید.")
        return EDIT_BIO
    user_data[user_id]['bio'] = bio
    save_data(user_data, USERS_DB_FILE)
    await update.message.reply_text("✅ بیوگرافی شما با موفقیت تغییر کرد.", reply_markup=get_main_menu(user_id))
    return ConversationHandler.END

async def received_new_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = str(update.effective_user.id)
    if update.message.photo:
        user_data[user_id]['photo'] = update.message.photo[-1].file_id
        save_data(user_data, USERS_DB_FILE)
        await update.message.reply_text("✅ عکس پروفایل شما با موفقیت تغییر کرد.", reply_markup=get_main_menu(user_id))
        return ConversationHandler.END
    else:
        await update.message.reply_text("لطفاً یک عکس ارسال کنید.")
        return EDIT_PHOTO

# --- ADMIN COMMANDS ---
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("شما اجازه دسترسی به این بخش را ندارید.")
        return
    keyboard = [
        [InlineKeyboardButton("📊 آمار ربات", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 ارسال پیام همگانی", callback_data="admin_broadcast")],
        # More admin features can be added here
    ]
    await update.message.reply_text("به پنل مدیریت خوش آمدید.", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles admin panel button clicks."""
    query = update.callback_query
    await query.answer()
    
    action = query.data.split('_')[1]
    
    if action == "stats":
        await show_stats(update, context)
    elif action == "broadcast":
        await query.message.edit_text("لطفاً پیام خود را برای ارسال به همه کاربران وارد کنید:")
        # Here you would typically enter a conversation handler state for broadcasting
        # For simplicity, this part is left as an exercise.
        pass

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays bot statistics for the admin."""
    query = update.callback_query
    total_users = len(user_data)
    male_users = sum(1 for u in user_data.values() if u.get('gender') == 'male')
    female_users = sum(1 for u in user_data.values() if u.get('gender') == 'female')
    banned_users = sum(1 for u in user_data.values() if u.get('banned'))
    
    stats_text = (
        f"📊 **آمار ربات**\n\n"
        f"- کل کاربران: {total_users}\n"
        f"- کاربران پسر: {male_users}\n"
        f"- کاربران دختر: {female_users}\n"
        f"- کاربران مسدود شده: {banned_users}\n"
        f"- گزارش‌های ثبت شده: {len(reports_data)}"
    )
    await query.message.edit_text(stats_text, parse_mode=ParseMode.MARKDOWN)

async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This is a simplified broadcast function. A real one should handle rate limits and errors.
    if update.effective_user.id != ADMIN_ID:
        return
    
    message_to_send = update.message.text.replace("/broadcast ", "")
    active_users = [uid for uid, data in user_data.items() if not data.get('banned')]
    sent_count = 0
    failed_count = 0
    
    await update.message.reply_text(f"در حال ارسال پیام به {len(active_users)} کاربر...")
    
    for user_id in active_users:
        try:
            await context.bot.send_message(user_id, message_to_send)
            sent_count += 1
        except TelegramError:
            failed_count += 1
            
    await update.message.reply_text(f"✅ پیام با موفقیت به {sent_count} کاربر ارسال شد.\n❌ ارسال به {failed_count} کاربر ناموفق بود.")

# --- GENERAL HANDLERS ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دستور /cancel برای لغو هرگونه مکالمه"""
    user = update.effective_user
    await update.message.reply_text('عملیات لغو شد و به منوی اصلی بازگشتی.', reply_markup=get_main_menu(user.id))
    context.user_data.clear()
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """لاگ کردن خطاها و ارسال پیام خطا به کاربر در صورت امکان"""
    logger.error("Exception while handling an update:", exc_info=context.error)

    # خطای Conflict به دلیل اجرای همزمان چند نمونه از ربات است.
    # بهترین راه حل، توقف تمام نمونه‌های دیگر و اجرای مجدد است.
    if isinstance(context.error, TelegramError) and "Conflict" in str(context.error):
        logger.critical(
            "Conflict error detected. Make sure only one instance of the bot is running."
        )
        # در این حالت، بهتر است پروسه را متوقف کنیم تا پلتفرم آن را ری‌استارت کند
        # os._exit(1) # Use with caution
        return

    # تلاش برای اطلاع‌رسانی به کاربر در صورت بروز خطا
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("متاسفانه خطایی رخ داد. لطفاً دوباره تلاش کنید.")
        except TelegramError:
            logger.error("Failed to send error message to user.")


# --- MAIN APPLICATION SETUP ---
def main() -> None:
    """شروع به کار ربات"""
    # اجرای وب‌سرور در یک ترد جداگانه
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    application = Application.builder().token(TOKEN).build()
    
    # مکالمه برای ساخت پروفایل اولیه
    profile_creation_handler = ConversationHandler(
        entry_points=[CommandHandler("profile", profile_command)],
        states={
            PROFILE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_profile_name)],
            PROFILE_GENDER: [CallbackQueryHandler(received_profile_gender, pattern="^profile_gender_")],
            PROFILE_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_profile_age)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    
    # مکالمه برای ویرایش پروفایل
    profile_edit_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_edit_profile, pattern="^edit_")],
        states={
            EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_new_name)],
            EDIT_GENDER: [CallbackQueryHandler(received_new_gender, pattern="^update_gender_")],
            EDIT_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_new_age)],
            EDIT_BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_new_bio)],
            EDIT_PHOTO: [MessageHandler(filters.PHOTO, received_new_photo)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )

    # مکالمه برای گزارش کاربر
    report_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(report_partner, pattern="^report_")],
        states={
            REPORT_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_report_reason)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    
    # افزودن کنترل‌کننده‌ها به اپلیکیشن
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("cancel", cancel)) # A general cancel command
    
    # Add conversation handlers
    application.add_handler(profile_creation_handler)
    application.add_handler(profile_edit_handler)
    application.add_handler(report_handler)
    
    # Handler for all inline button clicks
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    
    # Handlers for messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(MessageHandler(filters.VOICE | filters.PHOTO | filters.VIDEO | filters.STICKER | filters.ANIMATION, handle_media_message))

    # Error handler
    application.add_handler(CommandHandler("broadcast", broadcast_message, filters=filters.User(ADMIN_ID)))
    application.add_error_handler(error_handler)
    
    logger.info("Bot is starting to poll...")
    # drop_pending_updates=True به پاکسازی آپدیت‌های قدیمی در هنگام ری‌استارت کمک می‌کند
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
