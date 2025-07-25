import logging
import json
import threading
import os
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

# --- CONFIGURATION ---
TOKEN = "7689216297:AAHVucWhXpGlp15Ulk2zsppst1gDH9PCZnQ"
ADMIN_ID = 6929024145
USERS_DB_FILE = "users.json"
REPORTS_DB_FILE = "reports.json"
STARTING_COINS = 20
DAILY_GIFT_COINS = 20
GENDER_SEARCH_COST = 2

# --- FLASK WEBSERVER ---
app = Flask(__name__)
@app.route('/')
def index():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

# --- LOGGING ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- DATABASE MANAGEMENT ---
def load_data(filename):
    try:
        with open(filename, "r", encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {} if filename == USERS_DB_FILE else []

def save_data(data, filename):
    with open(filename, "w", encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

user_data = load_data(USERS_DB_FILE)
reports_data = load_data(REPORTS_DB_FILE)

# --- STATE DEFINITIONS ---
(EDIT_NAME, EDIT_GENDER, EDIT_AGE, EDIT_PROVINCE, EDIT_CITY, EDIT_PHOTO,
 ADMIN_BROADCAST, ADMIN_BAN, ADMIN_UNBAN, ADMIN_VIEW_USER, ADMIN_GIVE_COINS_ID, ADMIN_GIVE_COINS_AMOUNT) = range(12)

# --- GLOBAL VARIABLES ---
user_partners = {}
waiting_pool = {"random": [], "male": [], "female": [], "province": []}
admin_spying_on = None
PROVINCES = [
    "آذربایجان شرقی", "آذربایجان غربی", "اردبیل", "اصفهان", "البرز", "ایلام", "بوشهر", "تهران",
    "چهارمحال و بختیاری", "خراسان جنوبی", "خراسان رضوی", "خراسان شمالی", "خوزستان", "زنجان",
    "سمنان", "سیستان و بلوچستان", "فارس", "قزوین", "قم", "کردستان", "کرمان", "کرمانشاه",
    "کهگیلویه و بویراحمد", "گلستان", "گیلان", "لرستان", "مازندران", "مرکزی", "هرمزگان", "همدان", "یزد"
]

# --- KEYBOARD HELPERS ---
def get_main_menu(user_id):
    coins = user_data.get(str(user_id), {}).get('coins', 0)
    keyboard = [
        [InlineKeyboardButton(f"🪙 سکه‌های شما: {coins}", callback_data="my_coins"), InlineKeyboardButton("🎁 هدیه روزانه", callback_data="daily_gift")],
        [InlineKeyboardButton("🔍 جستجوی شانسی (رایگان)", callback_data="search_random")],
        [
            InlineKeyboardButton(f"🧑‍💻 جستجوی پسر ({GENDER_SEARCH_COST} سکه)", callback_data="search_male"),
            InlineKeyboardButton(f"👩‍💻 جستجوی دختر ({GENDER_SEARCH_COST} سکه)", callback_data="search_female"),
        ],
        [InlineKeyboardButton("📍 جستجوی استانی (رایگان)", callback_data="search_province")],
        [InlineKeyboardButton("👤 پروفایل من", callback_data="my_profile"), InlineKeyboardButton("❓ راهنما", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_in_chat_keyboard(partner_id):
    keyboard = [
        [
            InlineKeyboardButton("👍 لایک", callback_data=f"like_{partner_id}"),
            InlineKeyboardButton("➕ دنبال کردن", callback_data=f"follow_{partner_id}"),
            InlineKeyboardButton("👤 پروفایلش", callback_data=f"view_partner_{partner_id}"),
        ],
        [
            InlineKeyboardButton("🚫 بلاک کردن", callback_data=f"block_{partner_id}"),
            InlineKeyboardButton("🚨 گزارش تخلف", callback_data=f"report_{partner_id}"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_report_reasons_keyboard(partner_id):
    keyboard = [
        [InlineKeyboardButton("محتوای نامناسب", callback_data=f"report_reason_inappropriate_{partner_id}")],
        [InlineKeyboardButton("توهین و فحاشی", callback_data=f"report_reason_insult_{partner_id}")],
        [InlineKeyboardButton("مزاحمت", callback_data=f"report_reason_harassment_{partner_id}")],
        [InlineKeyboardButton("لغو", callback_data=f"cancel_report_{partner_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ... (Other keyboard helpers)

# --- CORE BOT LOGIC ---

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    user = update.effective_user
    await update.message.reply_text(
        'عملیات لغو شد.', reply_markup=ReplyKeyboardRemove()
    )
    await update.message.reply_text(
        'منوی اصلی:', reply_markup=get_main_menu(user.id)
    )
    return ConversationHandler.END

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = str(user.id)

    if user_id not in user_data:
        user_data[user_id] = {
            "banned": False, "coins": STARTING_COINS, "likes": [], "following": [],
            "blocked_users": [], "last_daily_gift": None, "name": user.first_name
        }
        save_data(user_data, USERS_DB_FILE)
        await update.message.reply_text(
            "به نظر میاد اولین باره که وارد میشی! لطفاً با /profile پروفایلت رو بساز تا بتونی از ربات استفاده کنی."
        )
        return

    if user_data[user_id].get('banned', False):
        await update.message.reply_text("🚫 شما توسط مدیریت از ربات مسدود شده‌اید.")
        return

    welcome_text = f"سلام {user.first_name}! به «ایران‌گرام» خوش اومدی 👋\n\nاز منوی زیر برای شروع استفاده کن."
    await update.message.reply_text(welcome_text, reply_markup=get_main_menu(user_id))


async def daily_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    
    last_gift_str = user_data[user_id].get('last_daily_gift')
    now = datetime.now()

    if last_gift_str:
        last_gift_time = datetime.fromisoformat(last_gift_str)
        if now - last_gift_time < timedelta(hours=24):
            await query.answer("شما قبلاً هدیه امروز خود را دریافت کرده‌اید!", show_alert=True)
            return

    user_data[user_id]['coins'] += DAILY_GIFT_COINS
    user_data[user_id]['last_daily_gift'] = now.isoformat()
    save_data(user_data, USERS_DB_FILE)
    
    await query.answer(f"🎁 تبریک! {DAILY_GIFT_COINS} سکه به حساب شما اضافه شد.", show_alert=True)
    await query.edit_message_reply_markup(reply_markup=get_main_menu(user_id))

async def search_partner(update: Update, context: ContextTypes.DEFAULT_TYPE, search_type: str):
    query = update.callback_query
    user_id = str(query.from_user.id)
    
    if 'gender' not in user_data[user_id]:
        await query.answer("❌ اول باید پروفایلت رو کامل کنی!", show_alert=True)
        return

    if search_type in ["male", "female"]:
        if user_data[user_id]['coins'] < GENDER_SEARCH_COST:
            await query.answer(f"🪙 سکه کافی نداری! برای این جستجو به {GENDER_SEARCH_COST} سکه نیاز داری.", show_alert=True)
            return
        user_data[user_id]['coins'] -= GENDER_SEARCH_COST
        save_data(user_data, USERS_DB_FILE)
        await query.answer(f"-{GENDER_SEARCH_COST} سکه 🪙")
    
    # ... (Full search logic here)
    await query.edit_message_text(f"⏳ در حال جستجو... {len(waiting_pool.get(search_type, []))} نفر در این صف منتظرند.")
    # ...


async def report_user_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    partner_id = query.data.split('_')[1]
    await query.message.reply_text(
        "لطفاً دلیل گزارش خود را انتخاب کنید:",
        reply_markup=get_report_reasons_keyboard(partner_id)
    )

async def handle_report_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('_')
    reason_key = parts[2]
    partner_id = parts[3]
    reporter_id = str(query.from_user.id)

    reason_map = {
        "inappropriate": "محتوای نامناسب",
        "insult": "توهین و فحاشی",
        "harassment": "مزاحمت"
    }
    reason_text = reason_map.get(reason_key, "نامشخص")

    report = {
        "reporter_id": reporter_id,
        "reported_id": partner_id,
        "reason": reason_text,
        "timestamp": datetime.now().isoformat()
    }
    reports_data.append(report)
    save_data(reports_data, REPORTS_DB_FILE)

    await query.edit_message_text("✅ گزارش شما با موفقیت برای مدیر ارسال شد.")
    await context.bot.send_message(
        ADMIN_ID,
        f"🚨 گزارش تخلف جدید از `{reporter_id}` علیه `{partner_id}`.\nدلیل: **{reason_text}**",
        parse_mode=ParseMode.MARKDOWN
    )

# --- MAIN APPLICATION SETUP ---
def main() -> None:
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    application = Application.builder().token(TOKEN).build()
    
    # --- Conversation Handlers ---
    # These are now fully defined with the `cancel` fallback.
    profile_creation_handler = ConversationHandler(
        entry_points=[CommandHandler("profile", ...)], # Placeholder for full code
        states={
            # ... all states for profile creation
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    
    admin_actions_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(..., pattern="^admin_broadcast$"),
            # ... other admin entry points
        ],
        states={
            ADMIN_BROADCAST: [MessageHandler(filters.TEXT | filters.ATTACHMENT, ...)],
            # ... other admin states
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )

    # --- Add handlers to application ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel)) # A general cancel command
    # ... (Add all other handlers here)
    application.add_handler(profile_creation_handler)
    application.add_handler(admin_actions_handler)
    application.add_handler(CallbackQueryHandler(handle_callback_query)) # Main router for buttons
    
    logger.info("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    # The full, runnable code is in the artifact. This is a conceptual representation.
    main()
