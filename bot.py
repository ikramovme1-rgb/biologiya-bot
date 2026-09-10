"""
🎓 Biologiya Bot — Bepul va Pullik kurslar
Muallif: Makhmudjon Ikramov
"""

import os
import csv
import io
import json
import uuid
import asyncio
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
from telegram.error import TelegramError, RetryAfter

# ═══════════════════════════════════════════════════════
# ⚙️ SOZLAMALAR — BU YERGA O'Z MA'LUMOTLARINGIZNI YOZING
# ═══════════════════════════════════════════════════════

BOT_TOKEN = os.getenv("BOT_TOKEN", "BOT_TOKENINGIZNI_SHU_YERGA_YOZING")

# Admin Telegram ID — faqat shu odam kurs qo'sha oladi
ADMIN_ID = int(os.getenv("ADMIN_ID", "1227596738"))

# Admin bilan aloqa uchun Telegram username (@ belgisisiz)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "qabul30")

# Botdan foydalanishdan oldin obuna bo'lishi shart bo'lgan asosiy kanal
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@ikramov_biologiya")

# ═══════════════════════════════════════════════════════
# 📂 MA'LUMOTLAR FAYLLARI
# ═══════════════════════════════════════════════════════

DATA_DIR = "data"
REGISTRATIONS_FILE = os.path.join(DATA_DIR, "marathon_registrations.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
LESSONS_FILE = os.path.join(DATA_DIR, "free_lessons.json")     # bepul kurslar (mavzu + YouTube)
COURSES_FILE = os.path.join(DATA_DIR, "paid_courses.json")     # pullik kurslar (matn/rasm)

BTN_FREE = "📚 Bepul kurslar"
BTN_PAID = "💎 Pullik kurslar"
BTN_ADMIN = "💬 Admin bilan aloqa"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# 🗄️ MA'LUMOTLAR BILAN ISHLASH
# ═══════════════════════════════════════════════════════

def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    for filepath, default in (
        (REGISTRATIONS_FILE, {}), (USERS_FILE, {}),
        (LESSONS_FILE, []), (COURSES_FILE, []),
    ):
        if not os.path.exists(filepath):
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(default, f, ensure_ascii=False, indent=2)


def load_json(filepath, default):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_user(user_id, username, full_name):
    users = load_json(USERS_FILE, {})
    users[str(user_id)] = {"username": username, "full_name": full_name}
    save_json(USERS_FILE, users)


def new_id():
    return uuid.uuid4().hex[:8]


def find_item(items, item_id):
    return next((i for i in items if i.get("id") == item_id), None)


def load_books():
    """
    Bepul darsliklar: [{id, title, lessons: [{id, title, url}]}]

    Eski versiyada darslar tekis ro'yxatda saqlangan edi — agar shunday
    ma'lumot uchrasa, uni bitta darslik ichiga o'rab, yangi formatga
    o'tkazamiz (shunda avval qo'shilgan darslar yo'qolmaydi).
    """
    raw = load_json(LESSONS_FILE, [])
    if raw and "lessons" not in raw[0]:
        raw = [{
            "id": new_id(),
            "title": "Darslar",
            "added_at": datetime.now().isoformat(timespec="seconds"),
            "lessons": raw,
        }]
        save_json(LESSONS_FILE, raw)
        logger.info("Eski formatdagi %s ta dars yangi darslikka ko'chirildi", len(raw[0]["lessons"]))
    return raw


def count_lessons(books):
    return sum(len(b.get("lessons", [])) for b in books)


def load_courses():
    return load_json(COURSES_FILE, [])


# ═══════════════════════════════════════════════════════
# 🎨 KLAVIATURALAR
# ═══════════════════════════════════════════════════════

def get_main_menu_keyboard():
    keyboard = [
        [KeyboardButton(BTN_FREE), KeyboardButton(BTN_PAID)],
        [KeyboardButton(BTN_ADMIN)],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_subscribe_keyboard():
    keyboard = [
        [InlineKeyboardButton(
            "📢 Kanalga obuna bo'lish",
            url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"
        )],
        [InlineKeyboardButton("✅ Obunani tekshirish", callback_data="check_sub")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ═══════════════════════════════════════════════════════
# ✅ KANAL OBUNA TEKSHIRISH
# ═══════════════════════════════════════════════════════

async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except TelegramError:
        return False


# ═══════════════════════════════════════════════════════
# 🚀 ASOSIY KOMANDALAR
# ═══════════════════════════════════════════════════════

async def show_main_menu(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    text = "🎓 <b>Xush kelibsiz!</b>\n\nKerakli bo'limni tanlang:"
    await context.bot.send_message(
        chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=get_main_menu_keyboard()
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user = update.effective_user
    user_id = user.id
    save_user(user_id, user.username, user.full_name)

    if not await check_subscription(user_id, context):
        await update.message.reply_text(
            "📢 <b>Botdan foydalanish uchun avval kanalimizga obuna bo'ling:</b>\n\n"
            f"{CHANNEL_USERNAME}\n\n"
            "✅ Obuna bo'lgach, pastdagi tugmani bosing:",
            parse_mode="HTML",
            reply_markup=get_subscribe_keyboard()
        )
        return

    await show_main_menu(context, user_id)


async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if not await check_subscription(user_id, context):
        await query.answer("❌ Siz hali obuna bo'lmagansiz!", show_alert=True)
        return

    await query.answer()
    await query.message.delete()
    await show_main_menu(context, user_id)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Bekor qilindi.", reply_markup=get_main_menu_keyboard()
    )


# ═══════════════════════════════════════════════════════
# 📚 BEPUL KURSLAR (o'quvchi uchun)
# ═══════════════════════════════════════════════════════

def books_keyboard(books):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📕 {b['title']}", callback_data=f"book:{b['id']}")]
        for b in books
    ])


def topics_keyboard(book, show_back: bool):
    rows = [[InlineKeyboardButton(f"📖 {l['title']}", callback_data=f"lesson:{book['id']}:{l['id']}")]
            for l in book.get("lessons", [])]
    if show_back:
        rows.append([InlineKeyboardButton("⬅️ Darsliklarga qaytish", callback_data="books")])
    return InlineKeyboardMarkup(rows)


def topics_text(book):
    lessons = book.get("lessons", [])
    if not lessons:
        return f"📕 <b>{book['title']}</b>\n\nBu darslikka hali mavzu qo'shilmagan."
    return (f"📕 <b>{book['title']}</b>\n\n"
            f"Jami {len(lessons)} ta mavzu. Kerakligini tanlang:")


async def send_free_lessons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    books = load_books()

    if not books:
        await update.message.reply_text(
            "📚 <b>Bepul kurslar</b>\n\n"
            "Hozircha darslar qo'shilmagan. Tez orada qo'shiladi! 🔜",
            parse_mode="HTML"
        )
        return

    # Darslik bitta bo'lsa — to'g'ridan-to'g'ri uning mavzularini ko'rsatamiz
    if len(books) == 1:
        await update.message.reply_text(
            topics_text(books[0]), parse_mode="HTML",
            reply_markup=topics_keyboard(books[0], show_back=False)
        )
        return

    await update.message.reply_text(
        f"📚 <b>Bepul kurslar</b>\n\nJami {len(books)} ta darslik. Birini tanlang:",
        parse_mode="HTML",
        reply_markup=books_keyboard(books)
    )


async def book_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Darslik tanlanganda — uning mavzular ro'yxatini shu xabarning o'zida ochamiz."""
    query = update.callback_query
    await query.answer()

    books = load_books()
    book = find_item(books, query.data.split(":", 1)[1])
    if not book:
        await query.answer("❌ Bu darslik o'chirilgan", show_alert=True)
        return

    await query.message.edit_text(
        topics_text(book), parse_mode="HTML",
        reply_markup=topics_keyboard(book, show_back=len(books) > 1)
    )


async def books_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """⬅️ Darsliklar ro'yxatiga qaytish."""
    query = update.callback_query
    await query.answer()

    books = load_books()
    await query.message.edit_text(
        f"📚 <b>Bepul kurslar</b>\n\nJami {len(books)} ta darslik. Birini tanlang:",
        parse_mode="HTML",
        reply_markup=books_keyboard(books)
    )


async def lesson_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mavzu tanlanganda — YouTube havolasini alohida xabar qilib yuboramiz."""
    query = update.callback_query
    await query.answer()

    _, book_id, lesson_id = query.data.split(":", 2)
    book = find_item(load_books(), book_id)
    lesson = find_item(book.get("lessons", []), lesson_id) if book else None

    if not lesson:
        await query.answer("❌ Bu dars o'chirilgan", show_alert=True)
        return

    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=(f"📖 <b>{lesson['title']}</b>\n\n"
              f"▶️ Darsni tomosha qiling:\n{lesson['url']}"),
        parse_mode="HTML"
    )


# ═══════════════════════════════════════════════════════
# 💎 PULLIK KURSLAR (o'quvchi uchun)
# ═══════════════════════════════════════════════════════

async def send_course(context: ContextTypes.DEFAULT_TYPE, chat_id: int, course: dict):
    caption = f"💎 <b>{course['title']}</b>"
    if course.get("text"):
        caption += f"\n\n{course['text']}"

    if course.get("photo"):
        # Telegram rasm izohi 1024 belgidan oshmasligi kerak — uzun bo'lsa ajratamiz
        if len(caption) <= 1024:
            await context.bot.send_photo(chat_id=chat_id, photo=course["photo"],
                                         caption=caption, parse_mode="HTML")
        else:
            await context.bot.send_photo(chat_id=chat_id, photo=course["photo"],
                                         caption=f"💎 <b>{course['title']}</b>", parse_mode="HTML")
            await context.bot.send_message(chat_id=chat_id, text=course["text"], parse_mode="HTML")
    else:
        await context.bot.send_message(chat_id=chat_id, text=caption, parse_mode="HTML")

    keyboard = [[InlineKeyboardButton("✍️ Admin bilan bog'lanish",
                                      url=f"https://t.me/{ADMIN_USERNAME}")]]
    await context.bot.send_message(
        chat_id=chat_id,
        text="Kursga yozilish yoki savollar uchun:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def send_paid_courses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    courses = load_courses()

    if not courses:
        await update.message.reply_text(
            "💎 <b>Pullik kurslar</b>\n\n"
            "Hozircha kurslar qo'shilmagan. Tez orada qo'shiladi! 🔜",
            parse_mode="HTML"
        )
        return

    if len(courses) == 1:
        await send_course(context, update.effective_chat.id, courses[0])
        return

    keyboard = [[InlineKeyboardButton(f"💎 {c['title']}", callback_data=f"course:{c['id']}")]
                for c in courses]
    await update.message.reply_text(
        f"💎 <b>Pullik kurslar</b>\n\nJami {len(courses)} ta kurs. Birini tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def course_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    course = find_item(load_courses(), query.data.split(":", 1)[1])
    if not course:
        await query.answer("❌ Bu kurs o'chirilgan", show_alert=True)
        return

    await send_course(context, query.from_user.id, course)


async def send_admin_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "💬 <b>Admin bilan aloqa</b>\n\nSavol va takliflar uchun murojaat qiling:"
    keyboard = [[InlineKeyboardButton("✍️ Yozish", url=f"https://t.me/{ADMIN_USERNAME}")]]
    await update.message.reply_text(
        text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ═══════════════════════════════════════════════════════
# 🔧 ADMIN — KURS QO'SHISH VA O'CHIRISH
# ═══════════════════════════════════════════════════════

async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/admin — admin uchun mavjud buyruqlar ro'yxati"""
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text(
        "🔧 <b>Admin buyruqlari</b>\n\n"
        "📚 <b>Bepul kurslar</b>\n"
        "/darslik_qoshish — yangi darslik (bo'lim) yaratish\n"
        "/dars_qoshish — darslik ichiga mavzu + YouTube link qo'shish\n\n"
        "💎 <b>Pullik kurslar</b>\n"
        "/kurs_qoshish — yangi kurs (matn yoki rasm) qo'shish\n\n"
        "📋 <b>Boshqarish</b>\n"
        "/royxat — qo'shilganlarni ko'rish va o'chirish\n\n"
        "👥 <b>Foydalanuvchilar</b>\n"
        "/stats — obunachilar soni\n"
        "/xabar — hammaga xabar yuborish\n"
        "/export — ro'yxatni CSV qilib olish\n"
        "/import — CSV'dan ro'yxatni tiklash\n\n"
        "/cancel — boshlangan amalni bekor qilish",
        parse_mode="HTML"
    )


async def add_book_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/darslik_qoshish — yangi darslik (bo'lim) yaratadi"""
    if update.effective_user.id != ADMIN_ID:
        return
    context.user_data.clear()
    context.user_data["action"] = "book_title"
    await update.message.reply_text(
        "📕 <b>Yangi darslik</b>\n\nDarslik nomini yozing "
        "(masalan: 10-sinf darsligi):\n<i>(bekor qilish uchun /cancel)</i>",
        parse_mode="HTML"
    )


async def handle_book_title(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    books = load_books()
    books.append({
        "id": new_id(),
        "title": text.strip()[:200],
        "added_at": datetime.now().isoformat(timespec="seconds"),
        "lessons": [],
    })
    save_json(LESSONS_FILE, books)
    context.user_data.clear()

    await update.message.reply_text(
        f"✅ <b>Darslik yaratildi!</b>\n\n"
        f"📕 {books[-1]['title']}\n\n"
        f"Endi unga mavzu qo'shish uchun /dars_qoshish buyrug'ini yuboring.",
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard()
    )


async def add_lesson_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/dars_qoshish — mavzu qo'shishni boshlaydi (avval darslik tanlanadi)"""
    if update.effective_user.id != ADMIN_ID:
        return

    books = load_books()
    if not books:
        await update.message.reply_text(
            "📕 Avval darslik yarating: /darslik_qoshish\n\n"
            "Mavzular darsliklar ichida saqlanadi."
        )
        return

    context.user_data.clear()
    keyboard = [[InlineKeyboardButton(f"📕 {b['title']}", callback_data=f"pickbook:{b['id']}")]
                for b in books]
    await update.message.reply_text(
        "📚 <b>Yangi mavzu</b>\n\nQaysi darslikka qo'shilsin?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def pick_book_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin mavzu qo'shish uchun darslikni tanladi."""
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ Sizda ruxsat yo'q", show_alert=True)
        return
    await query.answer()

    book_id = query.data.split(":", 1)[1]
    book = find_item(load_books(), book_id)
    if not book:
        await query.message.edit_text("❌ Bu darslik o'chirilgan.")
        return

    context.user_data.clear()
    context.user_data["book_id"] = book_id
    context.user_data["action"] = "lesson_title"

    await query.message.edit_text(
        f"📕 <b>{book['title']}</b>\n\nMavzu nomini yozing:\n"
        "<i>(bekor qilish uchun /cancel)</i>",
        parse_mode="HTML"
    )


async def handle_lesson_title(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    context.user_data["lesson_title"] = text.strip()[:200]
    context.user_data["action"] = "lesson_url"
    await update.message.reply_text("▶️ Endi shu mavzuning YouTube havolasini yuboring:")


async def handle_lesson_url(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    url = text.strip()
    if not url.startswith(("http://", "https://")):
        await update.message.reply_text(
            "❌ Bu havolaga o'xshamaydi. To'liq havolani yuboring "
            "(masalan: https://youtu.be/xxxxx):"
        )
        return

    books = load_books()
    book = find_item(books, context.user_data.get("book_id"))
    if not book:
        context.user_data.clear()
        await update.message.reply_text("❌ Darslik topilmadi (o'chirilgan bo'lishi mumkin).")
        return

    book.setdefault("lessons", []).append({
        "id": new_id(),
        "title": context.user_data["lesson_title"],
        "url": url,
        "added_at": datetime.now().isoformat(timespec="seconds"),
    })
    save_json(LESSONS_FILE, books)
    context.user_data.clear()

    await update.message.reply_text(
        f"✅ <b>Mavzu qo'shildi!</b>\n\n"
        f"📕 {book['title']}\n"
        f"📖 {book['lessons'][-1]['title']}\n\n"
        f"Shu darslikda jami {len(book['lessons'])} ta mavzu.",
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard()
    )


async def add_course_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/kurs_qoshish — pullik kurs qo'shishni boshlaydi"""
    if update.effective_user.id != ADMIN_ID:
        return
    context.user_data.clear()
    context.user_data["action"] = "course_title"
    await update.message.reply_text(
        "💎 <b>Yangi pullik kurs</b>\n\nKurs nomini yozing:\n"
        "<i>(bekor qilish uchun /cancel)</i>",
        parse_mode="HTML"
    )


async def handle_course_title(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    context.user_data["course_title"] = text.strip()[:200]
    context.user_data["action"] = "course_info"
    await update.message.reply_text(
        "📝 Endi kurs haqidagi ma'lumotni yuboring:\n\n"
        "• Oddiy matn yozing, <b>yoki</b>\n"
        "• Rasm yuboring (izoh bilan birga bo'lsa ham bo'ladi)",
        parse_mode="HTML"
    )


async def handle_course_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pullik kurs ma'lumoti — matn yoki rasm (izohi bilan)."""
    message = update.message
    photo_id = message.photo[-1].file_id if message.photo else None
    text = (message.caption or message.text or "").strip()

    if not photo_id and not text:
        await message.reply_text("❌ Matn yoki rasm yuboring:")
        return

    courses = load_courses()
    courses.append({
        "id": new_id(),
        "title": context.user_data["course_title"],
        "text": text,
        "photo": photo_id,
        "added_at": datetime.now().isoformat(timespec="seconds"),
    })
    save_json(COURSES_FILE, courses)
    context.user_data.clear()

    await message.reply_text(
        f"✅ <b>Kurs qo'shildi!</b>\n\n"
        f"💎 {courses[-1]['title']}\n"
        f"Jami pullik kurslar: {len(courses)} ta",
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard()
    )


def manage_book_markup(book):
    """Bitta darslik ichidagi mavzular + darslikni butunlay o'chirish tugmasi."""
    rows = [[InlineKeyboardButton(f"❌ {l['title']}",
                                  callback_data=f"dellesson:{book['id']}:{l['id']}")]
            for l in book.get("lessons", [])]
    rows.append([InlineKeyboardButton("🗑 Darslikni butunlay o'chirish",
                                      callback_data=f"delbook:{book['id']}")])
    return InlineKeyboardMarkup(rows)


def manage_book_text(book):
    lessons = book.get("lessons", [])
    if not lessons:
        return f"📕 <b>{book['title']}</b>\n\nMavzu yo'q."
    return (f"📕 <b>{book['title']}</b> — {len(lessons)} ta mavzu\n\n"
            "Mavzuni o'chirish uchun ustiga bosing:")


async def admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/royxat — darsliklar va kurslarni boshqarish"""
    if update.effective_user.id != ADMIN_ID:
        return

    books = load_books()
    courses = load_courses()

    if books:
        keyboard = [[InlineKeyboardButton(
            f"📕 {b['title']} ({len(b.get('lessons', []))} ta mavzu)",
            callback_data=f"mgbook:{b['id']}")] for b in books]
        await update.message.reply_text(
            f"📚 <b>Darsliklar ({len(books)} ta)</b>\n\n"
            "Ichidagi mavzularni ko'rish yoki o'chirish uchun darslikni tanlang:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text("📚 Darsliklar hali yaratilmagan. /darslik_qoshish")

    if courses:
        keyboard = [[InlineKeyboardButton(f"❌ {c['title']}", callback_data=f"delcourse:{c['id']}")]
                    for c in courses]
        await update.message.reply_text(
            f"💎 <b>Pullik kurslar ({len(courses)} ta)</b>\n\n"
            "O'chirish uchun ustiga bosing:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text("💎 Pullik kurslar hali qo'shilmagan.")


async def manage_book_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin darslikni boshqarish uchun tanladi."""
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ Sizda ruxsat yo'q", show_alert=True)
        return
    await query.answer()

    book = find_item(load_books(), query.data.split(":", 1)[1])
    if not book:
        await query.message.edit_text("❌ Bu darslik allaqachon o'chirilgan.")
        return

    await query.message.edit_text(manage_book_text(book), parse_mode="HTML",
                                  reply_markup=manage_book_markup(book))


async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mavzu, darslik yoki pullik kursni o'chirish (faqat admin)"""
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ Sizda ruxsat yo'q", show_alert=True)
        return

    parts = query.data.split(":")
    kind = parts[0]

    if kind == "delcourse":
        courses = load_courses()
        course = find_item(courses, parts[1])
        if not course:
            await query.answer("Allaqachon o'chirilgan", show_alert=True)
            return
        save_json(COURSES_FILE, [c for c in courses if c["id"] != parts[1]])
        await query.answer(f"O'chirildi: {course['title']}")

        remaining = [row for row in query.message.reply_markup.inline_keyboard
                     if not row[0].callback_data.endswith(parts[1])]
        if remaining:
            await query.message.edit_reply_markup(InlineKeyboardMarkup(remaining))
        else:
            await query.message.edit_text("✅ Barcha pullik kurslar o'chirildi.")
        return

    books = load_books()
    book = find_item(books, parts[1])
    if not book:
        await query.answer("Bu darslik allaqachon o'chirilgan", show_alert=True)
        return

    if kind == "delbook":
        save_json(LESSONS_FILE, [b for b in books if b["id"] != parts[1]])
        await query.answer(f"O'chirildi: {book['title']}")
        await query.message.edit_text(
            f"🗑 <b>{book['title']}</b> darsligi va uning "
            f"{len(book.get('lessons', []))} ta mavzusi o'chirildi.",
            parse_mode="HTML"
        )
        return

    # kind == "dellesson"
    lesson = find_item(book.get("lessons", []), parts[2])
    if not lesson:
        await query.answer("Allaqachon o'chirilgan", show_alert=True)
        return

    book["lessons"] = [l for l in book["lessons"] if l["id"] != parts[2]]
    save_json(LESSONS_FILE, books)

    await query.answer(f"O'chirildi: {lesson['title']}")
    await query.message.edit_text(manage_book_text(book), parse_mode="HTML",
                                  reply_markup=manage_book_markup(book))


# ═══════════════════════════════════════════════════════
# 👥 FOYDALANUVCHILAR BILAN ISHLASH (admin)
# ═══════════════════════════════════════════════════════

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/xabar — barcha foydalanuvchilarga xabar yuborishni boshlash (faqat admin)"""
    if update.effective_user.id != ADMIN_ID:
        return

    if context.bot_data.get("broadcasting"):
        await update.message.reply_text(
            "⏳ Oldingi xabar hali yuborilmoqda. Iltimos, u tugaguncha kuting "
            "(1000+ kishiga yuborish bir necha daqiqa vaqt oladi)."
        )
        return

    context.user_data.clear()
    context.user_data["action"] = "broadcast"
    await update.message.reply_text(
        "📢 Barcha foydalanuvchilarga yuboriladigan xabarni yozing "
        "(matn, rasm, video — istalgani bo'lishi mumkin):"
    )


async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.bot_data["broadcasting"] = True

    users = load_json(USERS_FILE, {})
    registrations = load_json(REGISTRATIONS_FILE, {})
    target_ids = set(users.keys()) | set(registrations.keys())

    await update.message.reply_text(
        f"⏳ {len(target_ids)} kishiga yuborilmoqda, biroz kuting..."
    )

    success = 0
    fail = 0
    try:
        for uid in target_ids:
            try:
                await context.bot.copy_message(
                    chat_id=int(uid),
                    from_chat_id=update.effective_chat.id,
                    message_id=update.message.message_id
                )
                success += 1
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after)
                try:
                    await context.bot.copy_message(
                        chat_id=int(uid),
                        from_chat_id=update.effective_chat.id,
                        message_id=update.message.message_id
                    )
                    success += 1
                except TelegramError:
                    fail += 1
            except TelegramError:
                fail += 1
            await asyncio.sleep(0.05)
    finally:
        context.bot_data["broadcasting"] = False

    await update.message.reply_text(
        f"📢 <b>Xabar yuborildi!</b>\n\n"
        f"✅ Yuborildi: {success}\n"
        f"❌ Yetkazilmadi: {fail}",
        parse_mode="HTML"
    )


async def export_registrations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/export — ro'yxatni CSV fayl qilib yuborish (faqat admin)"""
    if update.effective_user.id != ADMIN_ID:
        return

    registrations = load_json(REGISTRATIONS_FILE, {})
    if not registrations:
        await update.message.reply_text("Hozircha ro'yxatdan o'tganlar yo'q.")
        return

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Telegram ID", "F.I.Sh", "Telefon", "Viloyat/tuman", "Ro'yxatdan o'tgan sana"])
    for user_id, record in registrations.items():
        writer.writerow([
            user_id,
            record.get("full_name", ""),
            record.get("phone", ""),
            record.get("region", ""),
            record.get("registered_at", "")[:19],
        ])

    file_bytes = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    file_bytes.name = "marafon_royxati.csv"

    await update.message.reply_document(
        document=file_bytes,
        filename="marafon_royxati.csv",
        caption=f"📋 Jami ro'yxatdan o'tganlar: {len(registrations)} ta"
    )


async def import_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/import — avval eksport qilingan CSV faylni qayta yuklab, ro'yxatni tiklash (faqat admin)"""
    if update.effective_user.id != ADMIN_ID:
        return
    context.user_data.clear()
    context.user_data["action"] = "import"
    await update.message.reply_text(
        "📥 Avval /export orqali olingan marafon_royxati.csv faylni shu yerga yuboring:"
    )


async def handle_import_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    tg_file = await context.bot.get_file(document.file_id)
    raw = await tg_file.download_as_bytearray()

    try:
        text = bytes(raw).decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))

        registrations = load_json(REGISTRATIONS_FILE, {})
        users = load_json(USERS_FILE, {})
        count = 0
        for row in reader:
            uid = (row.get("Telegram ID") or "").strip()
            if not uid.isdigit():
                continue
            registrations[uid] = {
                "full_name": row.get("F.I.Sh", ""),
                "phone": row.get("Telefon", ""),
                "region": row.get("Viloyat/tuman", ""),
                "registered_at": row.get("Ro'yxatdan o'tgan sana", ""),
            }
            users.setdefault(uid, {"username": None, "full_name": row.get("F.I.Sh", "")})
            count += 1

        save_json(REGISTRATIONS_FILE, registrations)
        save_json(USERS_FILE, users)
    except Exception:
        logger.exception("CSV import xatoligi")
        context.user_data.clear()
        await update.message.reply_text("❌ Faylni o'qib bo'lmadi. To'g'ri CSV ekanligini tekshiring.")
        return

    context.user_data.clear()
    await update.message.reply_text(
        f"✅ <b>{count} ta yozuv import qilindi!</b>\n\n"
        f"Jami ro'yxatda: {len(registrations)} ta",
        parse_mode="HTML"
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stats — botdagi jami obunachilar sonini ko'rsatish (faqat admin)"""
    if update.effective_user.id != ADMIN_ID:
        return
    users = load_json(USERS_FILE, {})
    registrations = load_json(REGISTRATIONS_FILE, {})
    total = len(set(users.keys()) | set(registrations.keys()))
    books = load_books()
    await update.message.reply_text(
        f"👥 Botdagi jami obunachilar: <b>{total}</b> ta\n"
        f"📕 Darsliklar: <b>{len(books)}</b> ta\n"
        f"📖 Bepul mavzular: <b>{count_lessons(books)}</b> ta\n"
        f"💎 Pullik kurslar: <b>{len(load_courses())}</b> ta",
        parse_mode="HTML"
    )


# ═══════════════════════════════════════════════════════
# 💬 XABARLARNI QAYTA ISHLASH
# ═══════════════════════════════════════════════════════

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin = update.effective_user.id == ADMIN_ID
    action = context.user_data.get("action")
    text = update.message.text

    # Menyu tugmasi bosilsa — boshlangan amal bekor qilinadi (tiqilib qolmaslik uchun)
    if text in (BTN_FREE, BTN_PAID, BTN_ADMIN):
        context.user_data.clear()
        if text == BTN_FREE:
            await send_free_lessons(update, context)
        elif text == BTN_PAID:
            await send_paid_courses(update, context)
        else:
            await send_admin_contact(update, context)
        return

    # Admin boshlagan ko'p bosqichli amallar (matn, rasm yoki fayl bo'lishi mumkin)
    if is_admin:
        if action == "broadcast":
            await handle_broadcast_message(update, context)
            return
        if action == "import" and update.message.document:
            await handle_import_document(update, context)
            return
        if action == "course_info":
            await handle_course_info(update, context)
            return

    if text is None:
        return

    if is_admin:
        if action == "book_title":
            await handle_book_title(update, context, text)
        elif action == "lesson_title":
            await handle_lesson_title(update, context, text)
        elif action == "lesson_url":
            await handle_lesson_url(update, context, text)
        elif action == "course_title":
            await handle_course_title(update, context, text)


# ═══════════════════════════════════════════════════════
# 🏁 BOTNI ISHGA TUSHIRISH
# ═══════════════════════════════════════════════════════

def main():
    ensure_data_dir()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("admin", admin_help))
    app.add_handler(CommandHandler("darslik_qoshish", add_book_start))
    app.add_handler(CommandHandler("dars_qoshish", add_lesson_start))
    app.add_handler(CommandHandler("kurs_qoshish", add_course_start))
    app.add_handler(CommandHandler("royxat", admin_list))
    app.add_handler(CommandHandler("export", export_registrations))
    app.add_handler(CommandHandler("import", import_start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("xabar", broadcast_start))

    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
    app.add_handler(CallbackQueryHandler(book_callback, pattern="^book:"))
    app.add_handler(CallbackQueryHandler(books_back_callback, pattern="^books$"))
    app.add_handler(CallbackQueryHandler(lesson_callback, pattern="^lesson:"))
    app.add_handler(CallbackQueryHandler(course_callback, pattern="^course:"))
    app.add_handler(CallbackQueryHandler(pick_book_callback, pattern="^pickbook:"))
    app.add_handler(CallbackQueryHandler(manage_book_callback, pattern="^mgbook:"))
    app.add_handler(CallbackQueryHandler(delete_callback,
                                         pattern="^(dellesson|delbook|delcourse):"))

    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL) & ~filters.COMMAND,
        handle_message
    ))

    logger.info("🎓 Bot ishga tushdi!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
