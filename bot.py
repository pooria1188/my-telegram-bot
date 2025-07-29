# bot.py (نسخه اصلاح شده برای Webhook)
import logging
import os
import asyncio
from flask import Flask, request

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import database as db

# --- توکن و شناسه‌ها ---
BOT_TOKEN = "7689216297:AAGLrWiCbItQvgDYZhKnn19Z04nEEg0kr-s"
ADMIN_ID = 6929024145

# --- تنظیمات لاگ‌گیری ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- تعریف مراحل مکالمه ---
(GET_USERNAME, GET_AGE, GET_GENDER) = range(3)

# --- (جدید) ساخت اپلیکیشن وب Flask ---
app = Flask(__name__)

# --- (جدید) تعریف متغیر گلوبال برای اپلیکیشن تلگرام ---
telegram_app = None

# === توابع اصلی ربات (بدون تغییر از بخش قبل) ===
# ... تمام توابع start, get_username, get_age, get_gender, show_main_menu,
# ... cancel_conversation, unknown_command, handle_button_press, back_to_main_menu
# ... دقیقا مثل قبل اینجا قرار می‌گیرند. من برای خلاصه‌شدن، آنها را دوباره اینجا کپی نمی‌کنم
# ... اما شما باید آنها را از کد قبلی کپی کرده و در این قسمت قرار دهید.
# ... در زیر فقط یک نمونه از توابع را برای یادآوری می‌آورم:

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_id = user.id
    if not db.user_exists(user_id):
        db.add_user(user_id)
        await update.message.reply_text(
            "👋 سلام! به ربات چت ناشناس خوش اومدی.\n"
            "برای شروع، باید پروفایلت رو کامل کنی. لطفا یک نام کاربری برای خودت انتخاب کن:"
        )
        return GET_USERNAME
    else:
        await show_main_menu(update, context)
        return ConversationHandler.END

# ... (ادامه توابع دیگر را اینجا کپی کنید)
async def get_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    username = update.message.text
    if len(username) < 3 or len(username) > 20:
        await update.message.reply_text("نام کاربری باید بین ۳ تا ۲۰ حرف باشه. لطفا یک نام دیگه انتخاب کن:")
        return GET_USERNAME
    db.update_profile_field(user_id, "username", username)
    await update.message.reply_text(f"عالیه! نام کاربری '{username}' ثبت شد.\nحالا سنت رو وارد کن (باید بین ۱۳ تا ۶۰ سال باشی):")
    return GET_AGE

async def get_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    try:
        age = int(update.message.text)
        if 13 <= age <= 60:
            db.update_profile_field(user_id, "age", age)
            keyboard = [[InlineKeyboardButton("دختر 👧", callback_data="gender_female"), InlineKeyboardButton("پسر 👦", callback_data="gender_male")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("خیلی هم خوب! حالا جنسیتت رو مشخص کن:", reply_markup=reply_markup)
            return GET_GENDER
        else:
            await update.message.reply_text("لطفا سنت رو به درستی و بین ۱۳ تا ۶۰ سال وارد کن:")
            return GET_AGE
    except ValueError:
        await update.message.reply_text("لطفا سن خود را فقط به صورت عدد وارد کن:")
        return GET_AGE

async def get_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    gender = "پسر" if query.data == "gender_male" else "دختر"
    db.update_profile_field(user_id, "gender", gender)
    user_info = db.get_user(user_id)
    await query.edit_message_text(
        text=f"✅ پروفایل اولیه شما با موفقیت ساخته شد!\n\n"
             f"👤 نام کاربری: {user_info['username']}\n"
             f"🎂 سن: {user_info['age']}\n"
             f"🚻 جنسیت: {gender}"
    )
    await show_main_menu(update, context)
    return ConversationHandler.END

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💬 جستجوی شانسی (رایگان)", callback_data="random_chat")],
        [InlineKeyboardButton("🎯 جستجوی پیشرفته", callback_data="advanced_search"), InlineKeyboardButton("👤 پروفایل من", callback_data="my_profile")],
        [InlineKeyboardButton("💰 سکه‌ها", callback_data="coins_menu"), InlineKeyboardButton("🏆 کاربران برتر", callback_data="top_users")],
        [InlineKeyboardButton("ℹ️ درباره ربات", callback_data="about_bot")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "به منوی اصلی خوش آمدید. چه کاری می‌خواهید انجام دهید؟"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        user = db.get_user(update.effective_user.id)
        await update.message.reply_text(f"سلام {user['username']}، خوش برگشتی!\n💰 شما {user['coins']} سکه دارید.", reply_markup=reply_markup)

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("ساخت پروفایل لغو شد. هر زمان خواستی با دستور /start دوباره شروع کن.")
    return ConversationHandler.END
    
async def handle_button_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # ... (منطق دکمه‌ها)
    if query.data == 'about_bot':
         await query.edit_message_text(text="سلام! این ربات صرفا جهت سرگرمی ساخته شده...")
    else:
        await query.edit_message_text(text=f"بخش '{query.data}' در حال ساخت است.")
        
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_reply_markup(reply_markup=reply_markup)
    
async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_main_menu(update, context)

# === (جدید) بخش مربوط به وب‌هوک و Flask ===

@app.route('/webhook', methods=['POST'])
async def webhook() -> str:
    """این تابع درخواست‌های تلگرام را دریافت و پردازش می‌کند"""
    try:
        update_data = request.get_json()
        update = Update.de_json(update_data, telegram_app.bot)
        await telegram_app.process_update(update)
        return "ok"
    except Exception as e:
        logger.error(f"Error in webhook: {e}")
        return "error", 500

async def setup_bot():
    """ربات را برای کار با وب‌هوک تنظیم می‌کند"""
    global telegram_app
    
    # برای اولین بار دیتابیس را ایجاد کن
    db.init_db()

    # ساخت اپلیکیشن تلگرام
    telegram_app = Application.builder().token(BOT_TOKEN).build()
    
    # --- ثبت ConversationHandler برای پروفایل ---
    profile_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            GET_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_username)],
            GET_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_age)],
            GET_GENDER: [CallbackQueryHandler(pattern="^gender_", callback=get_gender)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )
    telegram_app.add_handler(profile_conv_handler)
    
    # --- ثبت هندلرهای دیگر ---
    telegram_app.add_handler(CallbackQueryHandler(back_to_main_menu, pattern="^main_menu$"))
    telegram_app.add_handler(CallbackQueryHandler(handle_button_press, pattern="^(?!gender_).+$"))
    telegram_app.add_handler(CommandHandler("start", start)) # برای کاربرانی که از قبل ثبت‌نام کرده‌اند

    # --- تنظیم وب‌هوک ---
    # رندر به طور خودکار یک URL در متغیر محیطی RENDER_EXTERNAL_URL می‌دهد
    webhook_url = os.environ.get("RENDER_EXTERNAL_URL")
    if webhook_url:
        full_webhook_url = f"{webhook_url}/webhook"
        logger.info(f"Setting webhook to: {full_webhook_url}")
        await telegram_app.bot.set_webhook(url=full_webhook_url, allowed_updates=Update.ALL_TYPES)
    else:
        logger.warning("RENDER_EXTERNAL_URL not set, cannot set webhook automatically.")
        
# --- (جدید) اجرای تابع تنظیمات قبل از شروع وب سرور ---
# این کد تنها یک بار در زمان شروع به کار سرور اجرا می‌شود
if __name__ != "__main__":
    asyncio.run(setup_bot())
