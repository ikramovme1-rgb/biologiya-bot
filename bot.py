"""
🧬 Biologiya Bot — @ikramov_biologiya
Instagram → Telegram konvertatsiya boti
Muallif: Makhmudjon Ikramov
"""

import os
import json
import logging
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.error import TelegramError

# ═══════════════════════════════════════════════════════
# ⚙️ SOZLAMALAR — BU YERGA O'Z MA'LUMOTLARINGIZNI YOZING
# ═══════════════════════════════════════════════════════

BOT_TOKEN = os.getenv("BOT_TOKEN", "BOT_TOKENINGIZNI_SHU_YERGA_YOZING")

# Telegram kanal username (@ belgisi bilan)
CHANNEL_USERNAME = "@ikramov_biologiya"

# Admin Telegram ID (o'zingizning ID raqamingiz)
# @userinfobot ga yozib bilib olishingiz mumkin
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# ═══════════════════════════════════════════════════════
# 📂 MA'LUMOTLAR FAYLLARI
# ═══════════════════════════════════════════════════════

DATA_DIR = "data"
FREE_LESSONS_FILE = os.path.join(DATA_DIR, "free_lessons.json")
PAID_COURSES_FILE = os.path.join(DATA_DIR, "paid_courses.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# 🗄️ MA'LUMOTLAR BILAN ISHLASH
# ═══════════════════════════════════════════════════════

def ensure_data_dir():
    """Data papkasini yaratish"""
    os.makedirs(DATA_DIR, exist_ok=True)
    for filepath, default in [
        (FREE_LESSONS_FILE, []),
        (PAID_COURSES_FILE, []),
        (USERS_FILE, {})
    ]:
        if not os.path.exists(filepath):
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(default, f, ensure_ascii=False, indent=2)


def load_json(filepath):
    """JSON faylni o'qish"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return [] if "lessons" in filepath or "courses" in filepath else {}


def save_json(filepath, data):
    """JSON faylga yozish"""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_user(user_id, username, full_name):
    """Foydalanuvchini saqlash"""
    users = load_json(USERS_FILE)
    users[str(user_id)] = {
        "username": username,
        "full_name": full_name,
        "joined": datetime.now().isoformat(),
        "is_paid": False
    }
    save_json(USERS_FILE, users)


# ═══════════════════════════════════════════════════════
# ✅ KANAL OBUNA TEKSHIRISH
# ═══════════════════════════════════════════════════════

async def check_subscription(user_id, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Foydalanuvchi kanalga obuna bo'lganini tekshirish"""
    try:
        member = await context.bot.get_chat_member(
            chat_id=CHANNEL_USERNAME,
            user_id=user_id
        )
        return member.status in ["member", "administrator", "creator"]
    except TelegramError:
        return False


# ═══════════════════════════════════════════════════════
# 🎨 KLAVIATURALAR
# ═══════════════════════════════════════════════════════

def get_main_menu_keyboard():
    """Asosiy menyu tugmalari"""
    keyboard = [
        [KeyboardButton("📚 Bepul darslar"), KeyboardButton("💎 Pullik kurslar")],
        [KeyboardButton("📊 Mening statistikam"), KeyboardButton("📞 Bog'lanish")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_subscribe_keyboard():
    """Obuna bo'lish tugmasi"""
    keyboard = [
        [InlineKeyboardButton("📢 Kanalga obuna bo'lish", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
        [InlineKeyboardButton("✅ Obunani tekshirish", callback_data="check_sub")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_keyboard():
    """Admin panel tugmalari"""
    keyboard = [
        [KeyboardButton("➕ Bepul dars qo'shish"), KeyboardButton("➕ Pullik kurs qo'shish")],
        [KeyboardButton("📊 Statistika"), KeyboardButton("📢 Xabar yuborish")],
        [KeyboardButton("🔙 Asosiy menyu")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ═══════════════════════════════════════════════════════
# 🚀 ASOSIY KOMANDALAR
# ═══════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start komandasi — botga kirish"""
    user = update.effective_user
    save_user(user.id, user.username, user.full_name)

    # Obuna tekshirish
    is_subscribed = await check_subscription(user.id, context)

    if not is_subscribed:
        welcome_text = (
            f"🧬 <b>Assalomu alaykum, {user.first_name}!</b>\n\n"
            f"<b>Biologiya — hayot haqidagi fan!</b> 🌿\n\n"
            f"Botdan foydalanish uchun avval kanalimizga obuna bo'ling:\n\n"
            f"📢 <b>{CHANNEL_USERNAME}</b>\n\n"
            f"✅ Obuna bo'lgach, quyidagi tugmani bosing:"
        )
        await update.message.reply_text(
            welcome_text,
            parse_mode="HTML",
            reply_markup=get_subscribe_keyboard()
        )
    else:
        await show_main_menu(update, context)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Asosiy menyuni ko'rsatish"""
    user = update.effective_user
    menu_text = (
        f"🧬 <b>Biologiya Bot</b>\n\n"
        f"Xush kelibsiz, <b>{user.first_name}</b>! 🎉\n\n"
        f"📚 <b>Bepul darslar</b> — asosiy mavzular bo'yicha darsliklar\n"
        f"💎 <b>Pullik kurslar</b> — chuqurlashtirilgan maxsus kurslar\n"
        f"📊 <b>Statistika</b> — sizning faolligingiz\n"
        f"📞 <b>Bog'lanish</b> — savol va takliflar uchun\n\n"
        f"⬇️ Quyidagi tugmalardan birini tanlang:"
    )
    await update.message.reply_text(
        menu_text,
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard()
    )


# ═══════════════════════════════════════════════════════
# ✅ OBUNA TEKSHIRISH CALLBACK
# ═══════════════════════════════════════════════════════

async def check_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obuna tekshirish tugmasi bosilganda"""
    query = update.callback_query
    await query.answer()

    is_subscribed = await check_subscription(query.from_user.id, context)

    if is_subscribed:
        await query.message.delete()
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=(
                "✅ <b>Obuna tasdiqlandi!</b>\n\n"
                "Endi botdan to'liq foydalanishingiz mumkin 🎉"
            ),
            parse_mode="HTML",
            reply_markup=get_main_menu_keyboard()
        )
    else:
        await query.message.edit_text(
            text=(
                "❌ <b>Siz hali kanalga obuna bo'lmagansiz!</b>\n\n"
                f"Iltimos, avval {CHANNEL_USERNAME} kanaliga obuna bo'ling,\n"
                "so'ng «✅ Obunani tekshirish» tugmasini bosing."
            ),
            parse_mode="HTML",
            reply_markup=get_subscribe_keyboard()
        )


# ═══════════════════════════════════════════════════════
# 📚 BEPUL DARSLAR
# ═══════════════════════════════════════════════════════

async def free_lessons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bepul darslar ro'yxati"""
    # Avval obuna tekshirish
    is_subscribed = await check_subscription(update.effective_user.id, context)
    if not is_subscribed:
        await update.message.reply_text(
            "⚠️ Avval kanalga obuna bo'ling!",
            reply_markup=get_subscribe_keyboard()
        )
        return

    lessons = load_json(FREE_LESSONS_FILE)

    if not lessons:
        await update.message.reply_text(
            "📚 <b>Bepul darslar</b>\n\n"
            "Hozircha darslar yuklanmagan.\n"
            "Tez orada yangi darslar qo'shiladi! 🔜",
            parse_mode="HTML"
        )
        return

    # Darslar ro'yxatini ko'rsatish
    keyboard = []
    for i, lesson in enumerate(lessons):
        keyboard.append([
            InlineKeyboardButton(
                f"📖 {lesson['title']}",
                callback_data=f"free_{i}"
            )
        ])

    await update.message.reply_text(
        "📚 <b>Bepul darslar</b>\n\n"
        "Quyidagi darslardan birini tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def free_lesson_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bepul dars tafsilotlari"""
    query = update.callback_query
    await query.answer()

    lesson_index = int(query.data.split("_")[1])
    lessons = load_json(FREE_LESSONS_FILE)

    if lesson_index >= len(lessons):
        await query.answer("❌ Dars topilmadi!", show_alert=True)
        return

    lesson = lessons[lesson_index]

    # Dars haqida ma'lumot
    text = (
        f"📖 <b>{lesson['title']}</b>\n\n"
        f"📝 {lesson.get('description', 'Tavsif mavjud emas')}\n\n"
        f"📅 Qo'shilgan: {lesson.get('date', 'Noma\'lum')}"
    )

    await query.message.edit_text(text, parse_mode="HTML")

    # Agar fayl bo'lsa — yuborish
    if "file_id" in lesson:
        await context.bot.send_document(
            chat_id=query.from_user.id,
            document=lesson["file_id"],
            caption=f"📚 {lesson['title']}"
        )
    elif "video_id" in lesson:
        await context.bot.send_video(
            chat_id=query.from_user.id,
            video=lesson["video_id"],
            caption=f"🎬 {lesson['title']}"
        )


# ═══════════════════════════════════════════════════════
# 💎 PULLIK KURSLAR
# ═══════════════════════════════════════════════════════

async def paid_courses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pullik kurslar ro'yxati"""
    is_subscribed = await check_subscription(update.effective_user.id, context)
    if not is_subscribed:
        await update.message.reply_text(
            "⚠️ Avval kanalga obuna bo'ling!",
            reply_markup=get_subscribe_keyboard()
        )
        return

    courses = load_json(PAID_COURSES_FILE)

    if not courses:
        await update.message.reply_text(
            "💎 <b>Pullik kurslar</b>\n\n"
            "Hozircha kurslar yuklanmagan.\n"
            "Tez orada maxsus kurslar qo'shiladi! 🔜",
            parse_mode="HTML"
        )
        return

    keyboard = []
    for i, course in enumerate(courses):
        price = course.get("price", "Narxi ko'rsatilmagan")
        keyboard.append([
            InlineKeyboardButton(
                f"💎 {course['title']} — {price}",
                callback_data=f"paid_{i}"
            )
        ])

    await update.message.reply_text(
        "💎 <b>Pullik kurslar</b>\n\n"
        "📌 Kursni tanlang va to'lov qiling.\n"
        "To'lovdan so'ng darsliklar avtomatik ochiladi!\n\n"
        "Quyidagi kurslardan birini tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def paid_course_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pullik kurs tafsilotlari"""
    query = update.callback_query
    await query.answer()

    course_index = int(query.data.split("_")[1])
    courses = load_json(PAID_COURSES_FILE)

    if course_index >= len(courses):
        await query.answer("❌ Kurs topilmadi!", show_alert=True)
        return

    course = courses[course_index]

    text = (
        f"💎 <b>{course['title']}</b>\n\n"
        f"📝 {course.get('description', 'Tavsif mavjud emas')}\n\n"
        f"💰 <b>Narxi:</b> {course.get('price', 'Kelishiladi')}\n"
        f"📚 <b>Darslar soni:</b> {course.get('lessons_count', 'Noma\'lum')}\n\n"
        f"💳 <b>To'lov usuli:</b>\n"
        f"Karta: {course.get('card_number', 'Admin bilan bog\'laning')}\n\n"
        f"✅ To'lovdan so'ng chekni adminga yuboring:"
    )

    keyboard = [
        [InlineKeyboardButton("💬 Admin bilan bog'lanish", url=f"https://t.me/{course.get('admin_username', 'ikramov_biologiya')}")],
        [InlineKeyboardButton("🔙 Ortga", callback_data="back_to_courses")]
    ]

    await query.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def back_to_courses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kurslar ro'yxatiga qaytish"""
    query = update.callback_query
    await query.answer()

    courses = load_json(PAID_COURSES_FILE)
    keyboard = []
    for i, course in enumerate(courses):
        price = course.get("price", "")
        keyboard.append([
            InlineKeyboardButton(
                f"💎 {course['title']} — {price}",
                callback_data=f"paid_{i}"
            )
        ])

    await query.message.edit_text(
        "💎 <b>Pullik kurslar</b>\n\nKursni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ═══════════════════════════════════════════════════════
# 📊 STATISTIKA & BOG'LANISH
# ═══════════════════════════════════════════════════════

async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi statistikasi"""
    user = update.effective_user
    users = load_json(USERS_FILE)
    user_data = users.get(str(user.id), {})

    free_count = len(load_json(FREE_LESSONS_FILE))
    paid_count = len(load_json(PAID_COURSES_FILE))

    text = (
        f"📊 <b>Sizning statistikangiz</b>\n\n"
        f"👤 Ism: <b>{user.full_name}</b>\n"
        f"📅 Qo'shilgan: <b>{user_data.get('joined', 'Noma\'lum')[:10]}</b>\n"
        f"💎 Status: <b>{'Premium ✨' if user_data.get('is_paid') else 'Bepul'}</b>\n\n"
        f"📚 Bepul darslar: <b>{free_count} ta</b>\n"
        f"💎 Pullik kurslar: <b>{paid_count} ta</b>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bog'lanish"""
    text = (
        "📞 <b>Bog'lanish</b>\n\n"
        "📢 Kanal: @ikramov_biologiya\n"
        "💬 Savol va takliflar uchun:\n\n"
        "Quyidagi tugmani bosing:"
    )
    keyboard = [[InlineKeyboardButton("💬 Yozish", url="https://t.me/ikramov_biologiya")]]
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ═══════════════════════════════════════════════════════
# 🔧 ADMIN PANEL
# ═══════════════════════════════════════════════════════

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/admin komandasi"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Sizda ruxsat yo'q!")
        return

    await update.message.reply_text(
        "🔧 <b>Admin panel</b>\n\n"
        "Quyidagi amallardan birini tanlang:",
        parse_mode="HTML",
        reply_markup=get_admin_keyboard()
    )


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin statistikasi"""
    if update.effective_user.id != ADMIN_ID:
        return

    users = load_json(USERS_FILE)
    free_count = len(load_json(FREE_LESSONS_FILE))
    paid_count = len(load_json(PAID_COURSES_FILE))
    paid_users = sum(1 for u in users.values() if u.get("is_paid"))

    text = (
        f"📊 <b>Bot statistikasi</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{len(users)}</b>\n"
        f"💎 Pullik a'zolar: <b>{paid_users}</b>\n"
        f"📚 Bepul darslar: <b>{free_count} ta</b>\n"
        f"💎 Pullik kurslar: <b>{paid_count} ta</b>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ═══════════════════════════════════════════════════════
# ➕ DARS/KURS QO'SHISH (ADMIN)
# ═══════════════════════════════════════════════════════

async def add_free_lesson_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bepul dars qo'shishni boshlash"""
    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data["action"] = "add_free_title"
    await update.message.reply_text(
        "📚 <b>Yangi bepul dars qo'shish</b>\n\n"
        "Dars nomini yozing:",
        parse_mode="HTML"
    )


async def add_paid_course_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pullik kurs qo'shishni boshlash"""
    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data["action"] = "add_paid_title"
    await update.message.reply_text(
        "💎 <b>Yangi pullik kurs qo'shish</b>\n\n"
        "Kurs nomini yozing:",
        parse_mode="HTML"
    )


async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Barcha foydalanuvchilarga xabar yuborish"""
    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data["action"] = "broadcast"
    await update.message.reply_text(
        "📢 <b>Xabar yuborish</b>\n\n"
        "Barcha foydalanuvchilarga yuboriladigan xabarni yozing:",
        parse_mode="HTML"
    )


async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Asosiy menyuga qaytish"""
    context.user_data.clear()
    await show_main_menu(update, context)


# ═══════════════════════════════════════════════════════
# 💬 XABARLARNI QAYTA ISHLASH
# ═══════════════════════════════════════════════════════

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Barcha matnli xabarlarni qayta ishlash"""
    text = update.message.text
    user_id = update.effective_user.id

    # Menyu tugmalari
    if text == "📚 Bepul darslar":
        await free_lessons(update, context)
        return
    elif text == "💎 Pullik kurslar":
        await paid_courses(update, context)
        return
    elif text == "📊 Mening statistikam":
        await my_stats(update, context)
        return
    elif text == "📞 Bog'lanish":
        await contact(update, context)
        return

    # Admin tugmalari
    if user_id == ADMIN_ID:
        if text == "➕ Bepul dars qo'shish":
            await add_free_lesson_start(update, context)
            return
        elif text == "➕ Pullik kurs qo'shish":
            await add_paid_course_start(update, context)
            return
        elif text == "📊 Statistika":
            await admin_stats(update, context)
            return
        elif text == "📢 Xabar yuborish":
            await broadcast_start(update, context)
            return
        elif text == "🔙 Asosiy menyu":
            await back_to_main(update, context)
            return

    # Admin qo'shish jarayonlari
    action = context.user_data.get("action")

    if action == "add_free_title" and user_id == ADMIN_ID:
        context.user_data["lesson_title"] = text
        context.user_data["action"] = "add_free_desc"
        await update.message.reply_text("📝 Dars tavsifini yozing:")
        return

    elif action == "add_free_desc" and user_id == ADMIN_ID:
        context.user_data["lesson_desc"] = text
        context.user_data["action"] = "add_free_file"
        await update.message.reply_text(
            "📎 Dars faylini yuboring (PDF, video, rasm yoki matn).\n"
            "Yoki /skip bosib faylsiz saqlang."
        )
        return

    elif action == "add_paid_title" and user_id == ADMIN_ID:
        context.user_data["course_title"] = text
        context.user_data["action"] = "add_paid_desc"
        await update.message.reply_text("📝 Kurs tavsifini yozing:")
        return

    elif action == "add_paid_desc" and user_id == ADMIN_ID:
        context.user_data["course_desc"] = text
        context.user_data["action"] = "add_paid_price"
        await update.message.reply_text("💰 Kurs narxini yozing (masalan: 50,000 so'm):")
        return

    elif action == "add_paid_price" and user_id == ADMIN_ID:
        context.user_data["course_price"] = text
        context.user_data["action"] = "add_paid_card"
        await update.message.reply_text("💳 To'lov karta raqamini yozing:")
        return

    elif action == "add_paid_card" and user_id == ADMIN_ID:
        # Kursni saqlash
        courses = load_json(PAID_COURSES_FILE)
        courses.append({
            "title": context.user_data["course_title"],
            "description": context.user_data["course_desc"],
            "price": context.user_data["course_price"],
            "card_number": text,
            "lessons_count": 0,
            "admin_username": "ikramov_biologiya",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "lessons": []
        })
        save_json(PAID_COURSES_FILE, courses)
        context.user_data.clear()
        await update.message.reply_text(
            "✅ <b>Pullik kurs muvaffaqiyatli qo'shildi!</b>",
            parse_mode="HTML",
            reply_markup=get_admin_keyboard()
        )
        return

    elif action == "broadcast" and user_id == ADMIN_ID:
        # Xabar yuborish
        users = load_json(USERS_FILE)
        success = 0
        fail = 0
        for uid in users:
            try:
                await context.bot.send_message(chat_id=int(uid), text=text)
                success += 1
            except Exception:
                fail += 1

        await update.message.reply_text(
            f"📢 <b>Xabar yuborildi!</b>\n\n"
            f"✅ Yuborildi: {success}\n"
            f"❌ Xatolik: {fail}",
            parse_mode="HTML",
            reply_markup=get_admin_keyboard()
        )
        context.user_data.clear()
        return


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fayl qabul qilish (admin dars qo'shganda)"""
    if update.effective_user.id != ADMIN_ID:
        return

    action = context.user_data.get("action")

    if action == "add_free_file":
        doc = update.message.document or update.message.video or update.message.photo
        if update.message.document:
            file_id = update.message.document.file_id
            file_type = "file_id"
        elif update.message.video:
            file_id = update.message.video.file_id
            file_type = "video_id"
        elif update.message.photo:
            file_id = update.message.photo[-1].file_id
            file_type = "file_id"
        else:
            await update.message.reply_text("❌ Fayl turini aniqlab bo'lmadi. Qaytadan yuboring.")
            return

        lessons = load_json(FREE_LESSONS_FILE)
        lessons.append({
            "title": context.user_data["lesson_title"],
            "description": context.user_data["lesson_desc"],
            file_type: file_id,
            "date": datetime.now().strftime("%Y-%m-%d")
        })
        save_json(FREE_LESSONS_FILE, lessons)
        context.user_data.clear()

        await update.message.reply_text(
            "✅ <b>Bepul dars muvaffaqiyatli qo'shildi!</b>",
            parse_mode="HTML",
            reply_markup=get_admin_keyboard()
        )


async def skip_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/skip — faylsiz saqlash"""
    if update.effective_user.id != ADMIN_ID:
        return

    action = context.user_data.get("action")
    if action == "add_free_file":
        lessons = load_json(FREE_LESSONS_FILE)
        lessons.append({
            "title": context.user_data["lesson_title"],
            "description": context.user_data["lesson_desc"],
            "date": datetime.now().strftime("%Y-%m-%d")
        })
        save_json(FREE_LESSONS_FILE, lessons)
        context.user_data.clear()

        await update.message.reply_text(
            "✅ <b>Bepul dars (faylsiz) saqlandi!</b>",
            parse_mode="HTML",
            reply_markup=get_admin_keyboard()
        )


# ═══════════════════════════════════════════════════════
# 🔗 CALLBACK HANDLER
# ═══════════════════════════════════════════════════════

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Barcha callback query'larni yo'naltirish"""
    query = update.callback_query
    data = query.data

    if data == "check_sub":
        await check_subscription_callback(update, context)
    elif data.startswith("free_"):
        await free_lesson_detail(update, context)
    elif data.startswith("paid_"):
        await paid_course_detail(update, context)
    elif data == "back_to_courses":
        await back_to_courses(update, context)


# ═══════════════════════════════════════════════════════
# 🏁 BOTNI ISHGA TUSHIRISH
# ═══════════════════════════════════════════════════════

def main():
    """Botni ishga tushirish"""
    ensure_data_dir()

    app = Application.builder().token(BOT_TOKEN).build()

    # Komandalar
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("skip", skip_file))

    # Callback query
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Xabarlar
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.VIDEO | filters.PHOTO,
        handle_document
    ))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🧬 Biologiya Bot ishga tushdi!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
