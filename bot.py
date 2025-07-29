# bot.py
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
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

# --- توکن و شناسه ادمین ---
BOT_TOKEN = "7689216297:AAGLrWiCbItQvgDYZhKnn19Z04nEEg0kr-s"
ADMIN_ID = 6929024145

# --- تنظیمات لاگ‌گیری برای دیباگ ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- تعریف مراحل مکالمه برای ساخت پروفایل ---
(
    GET_USERNAME,
    GET_AGE,
    GET_GENDER,
    # مراحل بعدی در بخش‌های آینده اضافه خواهند شد
) = range(3)


# === توابع اصلی ربات ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دستور /start را مدیریت می‌کند."""
    user = update.effective_user
    user_id = user.id
    
    # برای اولین بار دیتابیس را ایجاد کن
    db.init_db()

    if not db.user_exists(user_id):
        db.add_user(user_id)
        await update.message.reply_text(
            "👋 سلام! به ربات چت ناشناس خوش اومدی.\n"
            "برای شروع، باید پروفایلت رو کامل کنی. لطفا یک نام کاربری برای خودت انتخاب کن (این نام در چت‌ها نمایش داده می‌شه):"
        )
        return GET_USERNAME
    else:
        # اگر کاربر قبلا ثبت نام کرده، منوی اصلی را نشان بده
        await show_main_menu(update, context)
        return ConversationHandler.END

async def get_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """نام کاربری را از کاربر دریافت و ذخیره می‌کند."""
    user_id = update.effective_user.id
    username = update.message.text
    
    # اینجا می‌توانید فیلتر کلمات نامناسب را اضافه کنید
    if len(username) < 3 or len(username) > 20:
        await update.message.reply_text("نام کاربری باید بین ۳ تا ۲۰ حرف باشه. لطفا یک نام دیگه انتخاب کن:")
        return GET_USERNAME

    db.update_profile_field(user_id, "username", username)
    context.user_data['profile_username'] = username
    
    await update.message.reply_text(f"عالیه! نام کاربری '{username}' ثبت شد.\nحالا سنت رو وارد کن (باید بین ۱۳ تا ۶۰ سال باشی):")
    return GET_AGE

async def get_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """سن را دریافت و اعتبارسنجی می‌کند."""
    user_id = update.effective_user.id
    try:
        age = int(update.message.text)
        if 13 <= age <= 60:
            db.update_profile_field(user_id, "age", age)
            keyboard = [
                [
                    InlineKeyboardButton("دختر 👧", callback_data="gender_female"),
                    InlineKeyboardButton("پسر 👦", callback_data="gender_male"),
                ]
            ]
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
    """جنسیت را از طریق دکمه شیشه‌ای دریافت می‌کند."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    gender_choice = query.data
    
    gender = "پسر" if gender_choice == "gender_male" else "دختر"
    db.update_profile_field(user_id, "gender", gender)

    await query.edit_message_text(
        text=f"✅ پروفایل اولیه شما با موفقیت ساخته شد!\n\n"
             f"👤 نام کاربری: {db.get_user(user_id)['username']}\n"
             f"🎂 سن: {db.get_user(user_id)['age']}\n"
             f"🚻 جنسیت: {gender}\n\n"
             "به زودی امکانات بیشتری برای تکمیل پروفایل (عکس، بیو، علایق) اضافه خواهد شد."
    )
    # نمایش منوی اصلی پس از ثبت نام
    await show_main_menu(update, context)
    return ConversationHandler.END


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی اصلی ربات را با دکمه‌های شیشه‌ای نمایش می‌دهد."""
    keyboard = [
        [InlineKeyboardButton("💬 جستجوی شانسی (رایگان)", callback_data="random_chat")],
        [
            InlineKeyboardButton("🎯 جستجوی پیشرفته", callback_data="advanced_search"),
            InlineKeyboardButton(" प्रोफाइल من", callback_data="my_profile")
        ],
        [
            InlineKeyboardButton("💰 سکه‌ها", callback_data="coins_menu"),
            InlineKeyboardButton("🏆 کاربران برتر", callback_data="top_users")
        ],
        [InlineKeyboardButton("ℹ️ درباره ربات", callback_data="about_bot")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # اگر از دستور استارت میاد، پیام جدیده. اگر از جای دیگه، پیام قبلی رو ویرایش کن
    if update.callback_query:
        await update.callback_query.edit_message_text("به منوی اصلی خوش آمدید. چه کاری می‌خواهید انجام دهید؟", reply_markup=reply_markup)
    else:
        # این حالت برای زمانی است که کاربر از قبل ثبت نام کرده
        user = db.get_user(update.effective_user.id)
        await update.message.reply_text(
            f"سلام {user['username']}، خوش برگشتی!\n"
            f"💰 شما {user['coins']} سکه دارید.",
            reply_markup=reply_markup
        )
        
async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """مکالمه ساخت پروفایل را لغو می‌کند."""
    await update.message.reply_text(
        "ساخت پروفایل لغو شد. هر زمان خواستی با دستور /start دوباره شروع کن."
    )
    return ConversationHandler.END

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاسخ به دستورات ناشناس"""
    await update.message.reply_text("ببخشید، این دستور رو متوجه نمی‌شم.")
    
async def handle_button_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دکمه‌های شیشه‌ای منوی اصلی"""
    query = update.callback_query
    await query.answer() # برای اینکه دکمه از حالت لودینگ خارج بشه
    
    # اینجا برای هر دکمه یک منطق تعریف می‌کنیم
    # در بخش‌های بعدی اینها را کامل خواهیم کرد
    if query.data == 'random_chat':
        await query.edit_message_text(text="درحال جستجو برای یک هم‌صحبت شانسی... (این بخش در حال ساخته)")
    elif query.data == 'my_profile':
        await query.edit_message_text(text="بخش پروفایل من در حال ساخته. به زودی میتونی پروفایلت رو کامل کنی!")
    elif query.data == 'about_bot':
        # TODO: متن "درباره ما" را کامل کن
        await query.edit_message_text(text="سلام! این ربات صرفا جهت سرگرمی ساخته شده... (توضیحات در بخش بعدی کامل میشه)")
    else:
        await query.edit_message_text(text=f"دکمه {query.data} فشرده شد. این بخش در حال ساخته.")

    # بعد از نمایش پیام، دکمه بازگشت به منو رو نشون بده
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_reply_markup(reply_markup=reply_markup)

async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """کاربر را به منوی اصلی برمی‌گرداند."""
    query = update.callback_query
    await query.answer()
    await show_main_menu(update, context)

def main() -> None:
    """ربات را اجرا می‌کند."""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # --- مکالمه برای ساخت پروفایل ---
    profile_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            GET_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_username)],
            GET_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_age)],
            GET_GENDER: [CallbackQueryHandler(pattern="^gender_", callback=get_gender)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
        # اگر کاربر در حین ثبت نام دستور دیگری بفرستد
        map_to_parent={
             ConversationHandler.END: ConversationHandler.END
        }
    )
    
    application.add_handler(profile_conv_handler)
    
    # --- مدیریت دکمه‌های منوی اصلی ---
    application.add_handler(CallbackQueryHandler(handle_button_press, pattern="^(?!gender_).+$"))
    application.add_handler(CallbackQueryHandler(back_to_main_menu, pattern="^main_menu$"))

    # --- مدیریت دستورات دیگر ---
    # این هندلر باید بعد از ConversationHandler اضافه شود تا تداخل نکند
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    print("Bot is running...")
    # ربات را در حالت polling اجرا می‌کند
    application.run_polling()


if __name__ == "__main__":
    main()
