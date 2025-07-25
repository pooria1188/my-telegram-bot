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
(EDIT_NAME, EDIT_GENDER, EDIT_AGE,
 ADMIN_BROADCAST, ADMIN_BAN, ADMIN_UNBAN, ADMIN_VIEW_USER) = range(7)

# --- GLOBAL VARIABLES ---
user_partners = {}
waiting_pool = {"random": [], "male": [], "female": []}
monitoring_enabled = True

# --- KEYBOARD HELPERS ---
def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("🔍 جستجوی شانسی", callback_data="search_random")],
        [
            InlineKeyboardButton("🧑‍💻 جستجوی پسر", callback_data="search_male"),
            InlineKeyboardButton("👩‍💻 جستجوی دختر", callback_data="search_female"),
        ],
        [InlineKeyboardButton("👤 پروفایل من", callback_data="my_profile")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_in_chat_keyboard():
    return ReplyKeyboardMarkup([["❌ قطع چت و بعدی"]], resize_keyboard=True)

def get_profile_edit_keyboard(user_id):
    keyboard = [
        [
            InlineKeyboardButton("✏️ ویرایش نام", callback_data=f"edit_name_{user_id}"),
            InlineKeyboardButton("✏️ ویرایش جنسیت", callback_data=f"edit_gender_{user_id}"),
        ],
        [InlineKeyboardButton("✏️ ویرایش سن", callback_data=f"edit_age_{user_id}")],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_gender_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("پسر", callback_data="set_gender_پسر"),
            InlineKeyboardButton("دختر", callback_data="set_gender_دختر"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_age_keyboard():
    buttons = [InlineKeyboardButton(str(age), callback_data=f"set_age_{age}") for age in range(13, 80)]
    # Group buttons into rows of 6
    keyboard = [buttons[i:i + 6] for i in range(0, len(buttons), 6)]
    return InlineKeyboardMarkup(keyboard)

def get_admin_panel_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 آمار ربات", callback_data="admin_stats")],
        [InlineKeyboardButton("🗣️ ارسال پیام همگانی", callback_data="admin_broadcast")],
        [
            InlineKeyboardButton("🚫 مسدود کردن", callback_data="admin_ban"),
            InlineKeyboardButton("✅ رفع مسدودیت", callback_data="admin_unban"),
        ],
        [InlineKeyboardButton("👤 مشاهده پروفایل کاربر", callback_data="admin_view_user")],
        [InlineKeyboardButton(f"👁️ مانیتورینگ ({'فعال' if monitoring_enabled else 'غیرفعال'})", callback_data="admin_monitor_toggle")],
    ]
    return InlineKeyboardMarkup(keyboard)

# --- USER-FACING COMMANDS & HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = str(user.id)

    if user_data.get(user_id, {}).get('banned', False):
        await update.message.reply_text("🚫 شما توسط مدیریت از ربات مسدود شده‌اید.")
        return

    await update.message.reply_text(
        f"سلام {user.first_name}! 🔥\nبه ربات چت ناشناس خوش اومدی!\n\nاز منوی زیر برای شروع استفاده کن:",
        reply_markup=get_main_menu(),
    )
    if user_id not in user_data:
        await update.message.reply_text(
            "اول باید پروفایلت رو بسازی! لطفاً روی /profile کلیک کن یا دستورش رو تایپ کن."
        )

# --- PROFILE MANAGEMENT ---
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "برای ساخت پروفایل، لطفاً نام خود را وارد کنید:",
        reply_markup=ReplyKeyboardRemove(),
    )
    return EDIT_NAME

async def received_name_for_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['profile_name'] = update.message.text
    await update.message.reply_text("عالی! حالا جنسیت خود را انتخاب کنید:", reply_markup=get_gender_keyboard())
    return EDIT_GENDER

async def received_gender_for_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['profile_gender'] = query.data.split('_')[-1]
    await query.edit_message_text("بسیار خب! حالا سن خود را از لیست زیر انتخاب کنید:", reply_markup=get_age_keyboard())
    return EDIT_AGE

async def received_age_for_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    
    user_data[user_id] = {
        "name": context.user_data['profile_name'],
        "gender": context.user_data['profile_gender'],
        "age": int(query.data.split('_')[-1]),
        "banned": False
    }
    save_user_data(user_data)
    
    await query.edit_message_text("✅ پروفایل شما با موفقیت ساخته شد!")
    await context.bot.send_message(chat_id=user_id, text="حالا می‌تونی چت رو شروع کنی:", reply_markup=get_main_menu())
    return ConversationHandler.END

# --- INLINE PROFILE EDITING ---
async def show_my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    if user_id in user_data:
        profile = user_data[user_id]
        text = (
            f"👤 **پروفایل شما**\n\n"
            f"🔹 **نام:** {profile['name']}\n"
            f"🔹 **جنسیت:** {profile['gender']}\n"
            f"🔹 **سن:** {profile['age']}\n\n"
            "می‌توانید هر بخش را به صورت جداگانه ویرایش کنید:"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_profile_edit_keyboard(user_id))
    else:
        await query.edit_message_text("شما هنوز پروفایلی نساخته‌اید! لطفاً از /profile استفاده کنید.")

async def edit_name_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("لطفاً نام جدید خود را وارد کنید:")
    return EDIT_NAME

async def received_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = str(update.effective_user.id)
    user_data[user_id]['name'] = update.message.text
    save_user_data(user_data)
    await update.message.reply_text("✅ نام شما با موفقیت تغییر کرد.")
    # Reshow profile
    profile = user_data[user_id]
    text = (
        f"👤 **پروفایل شما**\n\n"
        f"🔹 **نام:** {profile['name']}\n"
        f"🔹 **جنسیت:** {profile['gender']}\n"
        f"🔹 **سن:** {profile['age']}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_profile_edit_keyboard(user_id))
    return ConversationHandler.END

# ... Similar handlers for edit_gender and edit_age ...
async def edit_gender_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("لطفاً جنسیت جدید خود را انتخاب کنید:", reply_markup=get_gender_keyboard())
    return EDIT_GENDER

async def received_new_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    user_data[user_id]['gender'] = query.data.split('_')[-1]
    save_user_data(user_data)
    await query.edit_message_text("✅ جنسیت شما با موفقیت تغییر کرد.", reply_markup=get_profile_edit_keyboard(user_id))
    return ConversationHandler.END

async def edit_age_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("لطفاً سن جدید خود را از لیست زیر انتخاب کنید:", reply_markup=get_age_keyboard())
    return EDIT_AGE

async def received_new_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    user_data[user_id]['age'] = int(query.data.split('_')[-1])
    save_user_data(user_data)
    await query.edit_message_text("✅ سن شما با موفقیت تغییر کرد.", reply_markup=get_profile_edit_keyboard(user_id))
    return ConversationHandler.END

# --- CHAT LOGIC ---
# ... (search_partner, handle_text_message, handle_media, next_chat) ...
# This part is largely the same but adapted for the new callback structure
async def search_partner(update: Update, context: ContextTypes.DEFAULT_TYPE, search_type: str, target_gender: str = None):
    query = update.callback_query
    user_id = query.from_user.id

    if user_data.get(str(user_id), {}).get('banned', False):
        await query.edit_message_text("🚫 شما توسط مدیریت از ربات مسدود شده‌اید.")
        return

    if user_id in user_partners:
        await query.answer("شما در حال حاضر در یک چت هستید!", show_alert=True)
        return
    
    for queue in waiting_pool.values():
        if user_id in queue:
            await query.answer("شما از قبل در صف انتظار هستید!", show_alert=True)
            return

    await query.edit_message_text("⏳ در حال جستجو برای یک هم‌صحبت... لطفاً صبر کن.\nبرای لغو از /cancel استفاده کن.")
    
    partner_id = None
    my_gender = user_data[str(user_id)]['gender']

    if search_type == "random":
        # Prioritize opposite gender, then same gender, then random queue
        opposite_gender = "دختر" if my_gender == "پسر" else "پسر"
        opposite_queue_key = "female" if opposite_gender == "دختر" else "male"
        
        if waiting_pool[opposite_queue_key]:
            partner_id = waiting_pool[opposite_queue_key].pop(0)
        elif waiting_pool['random']:
            partner_id = waiting_pool['random'].pop(0)
    else: # Gender specific search
        if waiting_pool[search_type]:
            partner_id = waiting_pool[search_type].pop(0)

    if partner_id:
        user_partners[user_id] = partner_id
        user_partners[partner_id] = user_id
        
        profile1 = user_data[str(user_id)]
        profile2 = user_data[str(partner_id)]
        
        await context.bot.send_message(user_id, f"✅ یک هم‌صحبت پیدا شد!\n\n"
                                                 f"👤 پروفایل طرف مقابل: {profile2['name']}، {profile2['gender']}، {profile2['age']} ساله",
                                                 reply_markup=get_in_chat_keyboard())
        await context.bot.send_message(partner_id, f"✅ یک هم‌صحبت پیدا شد!\n\n"
                                                 f"👤 پروفایل طرف مقابل: {profile1['name']}، {profile1['gender']}، {profile1['age']} ساله",
                                                 reply_markup=get_in_chat_keyboard())
        await context.bot.send_message(ADMIN_ID, f"🔗 اتصال جدید: `{user_id}` به `{partner_id}`", parse_mode=ParseMode.MARKDOWN)
    else:
        # Add user to the correct waiting queue
        if target_gender: # User is looking for a specific gender
            if my_gender == "پسر": waiting_pool['male'].append(user_id)
            else: waiting_pool['female'].append(user_id)
        else: # Random search
            waiting_pool['random'].append(user_id)

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text

    if user_data.get(str(user_id), {}).get('banned', False): return

    if text == "❌ قطع چت و بعدی":
        await next_chat(update, context)
        return

    if user_id in user_partners:
        partner_id = user_partners[user_id]
        await context.bot.send_message(partner_id, text)
        if monitoring_enabled:
            sender_profile = user_data.get(str(user_id), {"name": "ناشناس"})
            await context.bot.send_message(ADMIN_ID, f"💬 پیام از `{user_id}` ({sender_profile['name']}):\n`{text}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("شما به کسی وصل نیستی. از منوی زیر استفاده کن:", reply_markup=get_main_menu())

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_data.get(str(user_id), {}).get('banned', False): return

    if user_id in user_partners:
        partner_id = user_partners[user_id]
        if monitoring_enabled:
            sender_profile = user_data.get(str(user_id), {"name": "ناشناس"})
            await context.bot.send_message(ADMIN_ID, f"🖼️ مدیا از `{user_id}` ({sender_profile['name']})", parse_mode=ParseMode.MARKDOWN)

        if update.message.photo: await context.bot.send_photo(partner_id, update.message.photo[-1].file_id, caption=update.message.caption)
        elif update.message.voice: await context.bot.send_voice(partner_id, update.message.voice.file_id, caption=update.message.caption)
        elif update.message.sticker: await context.bot.send_sticker(partner_id, update.message.sticker.file_id)
        elif update.message.video: await context.bot.send_video(partner_id, update.message.video.file_id, caption=update.message.caption)
        elif update.message.document: await context.bot.send_document(partner_id, update.message.document.file_id, caption=update.message.caption)

async def next_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id in user_partners:
        partner_id = user_partners.pop(user_id)
        if partner_id in user_partners: user_partners.pop(partner_id)
        
        await context.bot.send_message(partner_id, "❌ طرف مقابل چت را ترک کرد.", reply_markup=ReplyKeyboardRemove())
        await context.bot.send_message(partner_id, "از منوی زیر برای شروع یک چت جدید استفاده کن:", reply_markup=get_main_menu())
        
        await update.message.reply_text("شما چت را ترک کردید.", reply_markup=ReplyKeyboardRemove())
        await update.message.reply_text("از منوی زیر برای شروع یک چت جدید استفاده کن:", reply_markup=get_main_menu())

        await context.bot.send_message(ADMIN_ID, f"🔌 اتصال قطع شد: `{user_id}` و `{partner_id}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("شما در حال حاضر در چت نیستی.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    for queue in waiting_pool.values():
        if user_id in queue: queue.remove(user_id)
    
    await update.message.reply_text("عملیات لغو شد.", reply_markup=get_main_menu())
    return ConversationHandler.END

# --- ADMIN PANEL ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("شما اجازه دسترسی به این بخش را ندارید.")
        return
    await update.message.reply_text("پنل مدیریت ربات:", reply_markup=get_admin_panel_keyboard())

async def admin_broadcast_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("لطفاً پیام همگانی خود را ارسال کنید. برای لغو /cancel را بزنید.")
    return ADMIN_BROADCAST

async def admin_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message_to_send = update.message
    sent_count = 0
    failed_count = 0
    for user_id in user_data:
        try:
            await context.bot.copy_message(chat_id=user_id, from_chat_id=update.effective_chat.id, message_id=message_to_send.message_id)
            sent_count += 1
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user_id}: {e}")
            failed_count += 1
    await update.message.reply_text(f"✅ پیام همگانی با موفقیت به {sent_count} کاربر ارسال شد.\n"
                                  f"❌ ارسال به {failed_count} کاربر ناموفق بود.")
    return ConversationHandler.END

async def admin_ban_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("لطفاً آیدی عددی کاربری که می‌خواهید مسدود کنید را وارد نمایید:")
    return ADMIN_BAN

async def admin_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user_id_to_ban = update.message.text.strip()
        if user_id_to_ban in user_data:
            user_data[user_id_to_ban]['banned'] = True
            save_user_data(user_data)
            await update.message.reply_text(f"✅ کاربر با آیدی `{user_id_to_ban}` با موفقیت مسدود شد.", parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("کاربری با این آیدی یافت نشد.")
    except Exception as e:
        await update.message.reply_text(f"خطا: {e}")
    return ConversationHandler.END

# ... Similar handlers for unban and view_user ...

# --- MAIN CALLBACK QUERY ROUTER ---
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data

    if data == "main_menu":
        await query.answer()
        await query.edit_message_text("از منوی زیر برای شروع استفاده کن:", reply_markup=get_main_menu())
        return

    if data == "my_profile":
        await query.answer()
        await show_my_profile(update, context)
        return

    if data.startswith("search_"):
        await query.answer()
        user_id = query.from_user.id
        if str(user_id) not in user_data:
            await query.edit_message_text("❌ اول باید با دستور /profile پروفایلت رو بسازی!")
            return
        
        search_type = data.split('_')[1]
        target_gender = "پسر" if search_type == "male" else ("دختر" if search_type == "female" else None)
        await search_partner(update, context, search_type, target_gender)
        return
    
    # Admin callbacks
    if data.startswith("admin_"):
        if query.from_user.id != ADMIN_ID:
            await query.answer("شما اجازه دسترسی ندارید.", show_alert=True)
            return
        
        if data == "admin_stats":
            # ... (code for stats) ...
            await query.answer()
        elif data == "admin_monitor_toggle":
            global monitoring_enabled
            monitoring_enabled = not monitoring_enabled
            await query.answer(f"مانیتورینگ {'فعال' if monitoring_enabled else 'غیرفعال'} شد")
            await query.edit_message_reply_markup(reply_markup=get_admin_panel_keyboard())


def main() -> None:
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    application = Application.builder().token(TOKEN).build()

    # --- Conversation Handlers ---
    profile_creation_handler = ConversationHandler(
        entry_points=[CommandHandler("profile", profile_command)],
        states={
            EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_name_for_profile)],
            EDIT_GENDER: [CallbackQueryHandler(received_gender_for_profile, pattern="^set_gender_")],
            EDIT_AGE: [CallbackQueryHandler(received_age_for_profile, pattern="^set_age_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    profile_editing_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(edit_name_prompt, pattern="^edit_name_"),
            CallbackQueryHandler(edit_gender_prompt, pattern="^edit_gender_"),
            CallbackQueryHandler(edit_age_prompt, pattern="^edit_age_"),
        ],
        states={
            EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_new_name)],
            EDIT_GENDER: [CallbackQueryHandler(received_new_gender, pattern="^set_gender_")],
            EDIT_AGE: [CallbackQueryHandler(received_new_age, pattern="^set_age_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    admin_actions_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_broadcast_prompt, pattern="^admin_broadcast$"),
            CallbackQueryHandler(admin_ban_prompt, pattern="^admin_ban$"),
            # ... other admin entry points
        ],
        states={
            ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_send)],
            ADMIN_BAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_ban_user)],
            # ... other admin states
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # --- Add handlers to application ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(profile_creation_handler)
    application.add_handler(profile_editing_handler)
    application.add_handler(admin_actions_handler)
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    application.add_handler(MessageHandler(filters.PHOTO | filters.VOICE | filters.STICKER | filters.VIDEO | filters.DOCUMENT, handle_media))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    logger.info("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
