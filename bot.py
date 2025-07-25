import logging
import json
import threading
import os
import random
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
import asyncio

# --- CONFIGURATION ---
TOKEN = "7689216297:AAHVucWhXpGlp15Ulk2zsppst1gDH9PCZnQ"
ADMIN_ID = 6929024145
BOT_USERNAME = "irangram_chatbot"
USERS_DB_FILE = "users.json"
REPORTS_DB_FILE = "reports.json"
CONFIG_FILE = "config.json"
STARTING_COINS = 20
DAILY_GIFT_COINS = 20
REFERRAL_BONUS_COINS = 50
GENDER_SEARCH_COST = 2
CHAT_HISTORY_TTL_MINUTES = 20

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

# --- DATABASE & CONFIG MANAGEMENT ---
def load_data(filename, default_type=dict):
    try:
        with open(filename, "r", encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_type()

def save_data(data, filename):
    with open(filename, "w", encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

user_data = load_data(USERS_DB_FILE)
reports_data = load_data(REPORTS_DB_FILE, default_type=list)
config_data = load_data(CONFIG_FILE)

# --- STATE DEFINITIONS ---
(EDIT_NAME, EDIT_GENDER, EDIT_AGE, EDIT_BIO, EDIT_PHOTO, ADMIN_SET_INVITE_TEXT, ADMIN_SET_INVITE_BANNER) = range(7)

# --- GLOBAL VARIABLES ---
user_partners = {}
chat_history = {}
waiting_pool = {"random": [], "male": [], "female": []}

# --- KEYBOARD & UI HELPERS ---
def get_main_menu(user_id):
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

def get_in_chat_keyboard():
    return ReplyKeyboardMarkup([["❌ قطع مکالمه"]], resize_keyboard=True)

def get_in_chat_inline_keyboard(partner_id):
    keyboard = [
        [
            InlineKeyboardButton("👍 لایک", callback_data=f"like_{partner_id}"),
            InlineKeyboardButton("👤 پروفایلش", callback_data=f"view_partner_{partner_id}"),
            InlineKeyboardButton("🚨 گزارش", callback_data=f"report_{partner_id}"),
        ],
        [InlineKeyboardButton("🎲 بازی و سرگرمی", callback_data=f"game_menu_{partner_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_profile_edit_menu():
    keyboard = [
        [InlineKeyboardButton("✏️ نام", callback_data="edit_name"), InlineKeyboardButton("✏️ جنسیت", callback_data="edit_gender")],
        [InlineKeyboardButton("✏️ سن", callback_data="edit_age"), InlineKeyboardButton("📝 بیوگرافی", callback_data="edit_bio")],
        [InlineKeyboardButton("🖼️ عکس پروفایل", callback_data="edit_photo")],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_gender_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("پسر", callback_data="set_gender_پسر"), InlineKeyboardButton("دختر", callback_data="set_gender_دختر")]])

def get_game_menu(partner_id):
    keyboard = [
        [InlineKeyboardButton("🎲 جرأت یا حقیقت", callback_data=f"game_truthordare_{partner_id}")],
        [InlineKeyboardButton("🔢 حدس عدد", callback_data=f"game_guessnumber_{partner_id}")],
        [InlineKeyboardButton("✂️ سنگ، کاغذ، قیچی", callback_data=f"game_rps_{partner_id}")],
        [InlineKeyboardButton("🔙 بازگشت به چت", callback_data=f"game_back_{partner_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- UTILITY & FILTERING ---
def is_message_forbidden(text: str) -> bool:
    phone_regex = r'\+?\d[\d -]{8,12}\d'
    id_regex = r'@[\w_]{5,}'
    return bool(re.search(phone_regex, text, re.IGNORECASE) or re.search(id_regex, text, re.IGNORECASE))

# --- CORE BOT LOGIC ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = str(user.id)
    
    if context.args:
        try:
            payload = context.args[0]
            if payload.startswith('ref_'):
                referrer_id = payload.split('_')[1]
                if str(referrer_id) != user_id and 'referred_by' not in user_data.get(user_id, {}):
                    context.user_data['referred_by'] = referrer_id
        except Exception as e:
            logger.error(f"Error processing referral link: {e}")

    if user_id not in user_data:
        user_data[user_id] = {
            "name": user.first_name, "banned": False, "coins": STARTING_COINS, "likes": [], "liked_by": [], "last_daily_gift": None, "bio": ""
        }
        if 'referred_by' in context.user_data:
            user_data[user_id]['referred_by'] = context.user_data['referred_by']
        save_data(user_data, USERS_DB_FILE)
        await update.message.reply_text(
            "سلام! به نظر میاد اولین باره که وارد میشی! لطفاً با دستور /profile پروفایلت رو کامل کن تا بتونی از همه امکانات استفاده کنی."
        )
        return

    if user_data[user_id].get('banned', False):
        await update.message.reply_text("🚫 شما توسط مدیریت از ربات مسدود شده‌اید.")
        return

    welcome_text = (
        f"سلام {user.first_name}! به «ایران‌گرام» خوش اومدی 👋\n\n"
        "فعالیت این ربات هزینه‌بر است، از حمایت شما سپاسگزاریم.\n\n"
        "از منوی زیر برای شروع استفاده کن."
    )
    await update.message.reply_text(welcome_text, reply_markup=get_main_menu(user_id))

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("لطفاً نام خود را وارد کنید:", reply_markup=ReplyKeyboardRemove())
    return EDIT_NAME

async def received_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['profile_name'] = update.message.text
    await update.message.reply_text("جنسیت خود را انتخاب کنید:", reply_markup=get_gender_keyboard())
    return EDIT_GENDER
    
async def received_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['profile_gender'] = query.data.split('_')[-1]
    await query.edit_message_text("لطفاً سن خود را وارد کنید (فقط عدد):")
    return EDIT_AGE

async def received_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = str(update.effective_user.id)
    try:
        age = int(update.message.text)
        if not 13 <= age <= 80:
            await update.message.reply_text("لطفاً یک سن بین ۱۳ تا ۸۰ سال وارد کن.")
            return EDIT_AGE
        
        user_data[user_id].update({
            "name": context.user_data['profile_name'],
            "gender": context.user_data['profile_gender'],
            "age": age
        })

        if 'referred_by' in user_data[user_id]:
            referrer_id = user_data[user_id]['referred_by']
            if referrer_id in user_data:
                user_data[referrer_id]['coins'] = user_data[referrer_id].get('coins', 0) + REFERRAL_BONUS_COINS
                try:
                    await context.bot.send_message(referrer_id, f"🎉 تبریک! یک نفر با لینک شما عضو شد و پروفایلش را تکمیل کرد. {REFERRAL_BONUS_COINS} سکه هدیه گرفتی!")
                except TelegramError as e:
                    logger.warning(f"Could not send referral bonus message to {referrer_id}: {e}")
            del user_data[user_id]['referred_by']

        save_data(user_data, USERS_DB_FILE)
        await update.message.reply_text("✅ پروفایل شما با موفقیت تکمیل شد!", reply_markup=ReplyKeyboardRemove())
        await update.message.reply_text("از منوی اصلی استفاده کن:", reply_markup=get_main_menu(user_id))
        return ConversationHandler.END
    except (ValueError, KeyError):
        await update.message.reply_text("لطفاً سن را به صورت عدد صحیح وارد کن.")
        return EDIT_AGE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    for queue in waiting_pool.values():
        if user.id in queue:
            queue.remove(user.id)
            await update.message.reply_text("جستجو لغو شد.")
            break

    await update.message.reply_text('عملیات لغو شد.', reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text('منوی اصلی:', reply_markup=get_main_menu(user.id))
    context.user_data.clear()
    return ConversationHandler.END

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text

    if is_message_forbidden(text):
        try:
            await update.message.delete()
            await update.message.reply_text("🚫 ارسال شماره تلفن یا آیدی در ربات ممنوع است.", quote=False)
        except TelegramError as e:
            logger.warning(f"Could not delete forbidden message: {e}")
        return
    
    if text == "❌ قطع مکالمه":
        await next_chat(update, context)
        return

    if user_id in user_partners:
        partner_id = user_partners[user_id]
        await context.bot.send_message(partner_id, text)
    else:
        await update.message.reply_text("شما به کسی وصل نیستی. از منوی زیر استفاده کن:", reply_markup=get_main_menu(user_id))

async def next_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_partners:
        partner_id = user_partners.pop(user_id)
        if partner_id in user_partners:
            user_partners.pop(partner_id)
        
        await context.bot.send_message(partner_id, "❌ طرف مقابل چت را ترک کرد.", reply_markup=ReplyKeyboardRemove())
        await context.bot.send_message(partner_id, "از منوی زیر برای شروع یک چت جدید استفاده کن:", reply_markup=get_main_menu(partner_id))
        
        await update.message.reply_text("شما چت را ترک کردید.", reply_markup=ReplyKeyboardRemove())
        await update.message.reply_text("از منوی زیر برای شروع یک چت جدید استفاده کن:", reply_markup=get_main_menu(user_id))
    else:
        await update.message.reply_text("شما در حال حاضر در چت نیستی.")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text("به پنل مدیریت خوش آمدید.")
    else:
        await update.message.reply_text("شما اجازه دسترسی به این بخش را ندارید.")

async def search_partner(update: Update, context: ContextTypes.DEFAULT_TYPE, search_type: str):
    query = update.callback_query
    user_id = query.from_user.id

    if 'gender' not in user_data[str(user_id)]:
        await query.message.reply_text("❌ اول باید پروفایل خود را با دستور /profile کامل کنی!")
        return

    if user_id in user_partners:
        await query.message.reply_text("شما در حال حاضر در یک چت هستید!")
        return
        
    for queue in waiting_pool.values():
        if user_id in queue:
            await query.message.reply_text("شما از قبل در صف انتظار هستید! برای لغو /cancel را بزنید.")
            return

    if search_type in ["male", "female"]:
        if user_data[str(user_id)]['coins'] < GENDER_SEARCH_COST:
            await query.message.reply_text(f"🪙 سکه کافی نداری! برای این جستجو به {GENDER_SEARCH_COST} سکه نیاز داری.")
            return
        user_data[str(user_id)]['coins'] -= GENDER_SEARCH_COST
        save_data(user_data, USERS_DB_FILE)
        await query.answer(f"-{GENDER_SEARCH_COST} سکه 🪙")

    partner_id = None
    if search_type == "random":
        if waiting_pool["random"]:
            partner_id = waiting_pool["random"].pop(0)
    elif search_type == "male":
        if waiting_pool["male"]:
            partner_id = waiting_pool["male"].pop(0)
    elif search_type == "female":
        if waiting_pool["female"]:
            partner_id = waiting_pool["female"].pop(0)

    if partner_id:
        user_partners[user_id] = partner_id
        user_partners[partner_id] = user_id
        
        await context.bot.send_message(user_id, "✅ یک هم‌صحبت پیدا شد!", reply_markup=get_in_chat_keyboard())
        await context.bot.send_message(user_id, "می‌توانید از دکمه‌های زیر استفاده کنید:", reply_markup=get_in_chat_inline_keyboard(partner_id))
        
        await context.bot.send_message(partner_id, "✅ یک هم‌صحبت پیدا شد!", reply_markup=get_in_chat_keyboard())
        await context.bot.send_message(partner_id, "می‌توانید از دکمه‌های زیر استفاده کنید:", reply_markup=get_in_chat_inline_keyboard(user_id))
    else:
        waiting_pool[search_type].append(user_id)
        await query.message.reply_text("⏳ شما در صف انتظار قرار گرفتید... برای لغو /cancel را بزنید.")

async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    profile = user_data.get(user_id, {})
    
    caption = (
        f"👤 **پروفایل شما**\n\n"
        f"🔹 **نام:** {profile.get('name', 'ثبت نشده')}\n"
        f"🔹 **جنسیت:** {profile.get('gender', 'ثبت نشده')}\n"
        f"🔹 **سن:** {profile.get('age', 'ثبت نشده')}\n"
        f"📝 **بیو:** {profile.get('bio', 'ثبت نشده')}"
    )
    
    photo_id = profile.get('profile_photo_id')
    
    try:
        await query.delete_message()
    except TelegramError:
        pass

    if photo_id:
        await context.bot.send_photo(chat_id=user_id, photo=photo_id, caption=caption, parse_mode=ParseMode.MARKDOWN, reply_markup=get_profile_edit_menu())
    else:
        await context.bot.send_message(chat_id=user_id, text=caption, parse_mode=ParseMode.MARKDOWN, reply_markup=get_profile_edit_menu())


async def hall_of_fame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sorted_users = sorted(user_data.items(), key=lambda item: len(item[1].get('liked_by', [])), reverse=True)
    text = "🏆 **تالار مشاهیر - ۱۰ کاربر برتر** 🏆\n\n"
    for i, (user_id, data) in enumerate(sorted_users[:10]):
        likes = len(data.get('liked_by', []))
        name = data.get('name', 'ناشناس')
        text += f"{i+1}. **{name}** - {likes} لایک 👍\n"
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_menu(query.from_user.id))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text("این راهنمای ربات است.")

async def invite_friends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    invite_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    
    invite_text = config_data.get("invite_text", 
        "🔥 با این لینک دوستات رو به بهترین ربات چت ناشناس دعوت کن و با هر عضویت جدید، ۵۰ سکه هدیه بگیر! 🔥"
    )
    invite_banner_id = config_data.get("invite_banner_id")

    final_text = f"{invite_text}\n\nلینک دعوت شما:\n{invite_link}"

    try:
        if invite_banner_id:
            await query.message.reply_photo(photo=invite_banner_id, caption=final_text)
        else:
            await query.message.reply_text(final_text)
    except Exception as e:
        logger.error(f"Error sending invite: {e}")
        await query.message.reply_text(final_text)

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    user_id = str(query.from_user.id)
    data = query.data

    if data == "my_coins":
        coins = user_data.get(user_id, {}).get('coins', 0)
        await query.message.reply_text(f"🪙 شما در حال حاضر {coins} سکه دارید.")
    elif data == "daily_gift":
        last_gift_str = user_data[user_id].get('last_daily_gift')
        now = datetime.now()
        if last_gift_str and now - datetime.fromisoformat(last_gift_str) < timedelta(hours=24):
            await query.message.reply_text("شما قبلاً هدیه امروز خود را دریافت کرده‌اید!")
        else:
            user_data[user_id]['coins'] = user_data[user_id].get('coins', 0) + DAILY_GIFT_COINS
            user_data[user_id]['last_daily_gift'] = now.isoformat()
            save_data(user_data, USERS_DB_FILE)
            await query.message.reply_text(f"🎁 تبریک! {DAILY_GIFT_COINS} سکه به حساب شما اضافه شد.")
            await query.edit_message_reply_markup(reply_markup=get_main_menu(user_id))
    elif data.startswith("search_"):
        await search_partner(update, context, data.split('_')[1])
    elif data == "invite_friends":
        await invite_friends(update, context)
    elif data == "my_profile":
        await my_profile(update, context)
    elif data == "hall_of_fame":
        await hall_of_fame(update, context)
    elif data == "help":
        await help_command(update, context)
    elif data == "main_menu":
        await query.edit_message_text("منوی اصلی:", reply_markup=get_main_menu(user_id))
    else:
        await query.edit_message_text(text=f"دکمه {query.data} به زودی فعال می‌شود.")
        
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="سیستم دچار اختلال شده است. لطفاً دوباره تلاش کنید."
            )
        except Exception as e:
            logger.error(f"Error in error_handler itself: {e}")

# --- MAIN APPLICATION SETUP ---
def main() -> None:
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    application = Application.builder().token(TOKEN).build()
    
    profile_handler = ConversationHandler(
        entry_points=[CommandHandler("profile", profile_command)],
        states={
            EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_name)],
            EDIT_GENDER: [CallbackQueryHandler(received_gender, pattern="^set_gender_")],
            EDIT_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_age)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    
    application.add_error_handler(error_handler)
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(profile_handler)
    
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    
    logger.info("Bot is running...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
