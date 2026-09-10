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


def load_lessons():
    return load_json(LESSONS_FILE, [])


def load_courses():
    return load_json(COURSES_FILE, [])


def find_item(items, item_id):
    return next((i for i in items if i.get("id") == item_id), None)


def new_id():
    return uuid.uuid4().hex[:8]


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

async def send_lesson(context: ContextTypes.DEFAULT_TYPE, chat_id: int, lesson: dict):
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"📚 <b>{lesson['title']}</b>\n\n"
            f"▶️ Darsni tomosha qiling:\n{lesson['url']}"
        ),
        parse_mode="HTML"
    )


async def send_free_lessons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lessons = load_lessons()

    if not lessons:
        await update.message.reply_text(
            "📚 <b>Bepul kurslar</b>\n\n"
            "Hozircha darslar qo'shilmagan. Tez orada qo'shiladi! 🔜",
            parse_mode="HTML"
        )
        return

    if len(lessons) == 1:
        await send_lesson(context, update.effective_chat.id, lessons[0])
        return

    keyboard = [[InlineKeyboardButton(f"📖 {l['title']}", callback_data=f"lesson:{l['id']}")]
                for l in lessons]
    await update.message.reply_text(
        f"📚 <b>Bepul kurslar</b>\n\nJami {len(lessons)} ta dars. Mavzuni tanlang:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def lesson_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    lesson = find_item(load_lessons(), query.data.split(":", 1)[1])
    if not lesson:
        await query.answer("❌ Bu dars o'chirilgan", show_alert=True)
        return

    await send_lesson(context, query.from_user.id, lesson)


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
        "/dars_qoshish — yangi mavzu + YouTube link qo'shish\n\n"
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


async def add_lesson_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/dars_qoshish — bepul dars qo'shishni boshlaydi"""
    if update.effective_user.id != ADMIN_ID:
        return
    context.user_data.clear()
    context.user_data["action"] = "lesson_title"
    await update.message.reply_text(
        "📚 <b>Yangi bepul dars</b>\n\nMavzu nomini yozing:\n"
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

    lessons = load_lessons()
    lessons.append({
        "id": new_id(),
        "title": context.user_data["lesson_title"],
        "url": url,
        "added_at": datetime.now().isoformat(timespec="seconds"),
    })
    save_json(LESSONS_FILE, lessons)
    context.user_data.clear()

    await update.message.reply_text(
        f"✅ <b>Dars qo'shildi!</b>\n\n"
        f"📖 {lessons[-1]['title']}\n"
        f"Jami bepul darslar: {len(lessons)} ta",
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


async def admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/royxat — qo'shilgan darslar va kurslarni o'chirish tugmalari bilan ko'rsatadi"""
    if update.effective_user.id != ADMIN_ID:
        return

    lessons = load_lessons()
    courses = load_courses()

    if lessons:
        keyboard = [[InlineKeyboardButton(f"❌ {l['title']}", callback_data=f"dellesson:{l['id']}")]
                    for l in lessons]
        await update.message.reply_text(
            f"📚 <b>Bepul darslar ({len(lessons)} ta)</b>\n\n"
            "O'chirish uchun ustiga bosing:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text("📚 Bepul darslar hali qo'shilmagan.")

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


async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dars yoki kursni o'chirish (faqat admin)"""
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ Sizda ruxsat yo'q", show_alert=True)
        return

    kind, item_id = query.data.split(":", 1)
    filepath = LESSONS_FILE if kind == "dellesson" else COURSES_FILE
    items = load_json(filepath, [])

    item = find_item(items, item_id)
    if not item:
        await query.answer("Allaqachon o'chirilgan", show_alert=True)
        return

    items = [i for i in items if i.get("id") != item_id]
    save_json(filepath, items)

    await query.answer(f"O'chirildi: {item['title']}")

    # O'chirilgan qatorni tugmalar orasidan olib tashlaymiz
    remaining = [row for row in query.message.reply_markup.inline_keyboard
                 if not row[0].callback_data.endswith(item_id)]
    if remaining:
        await query.message.edit_reply_markup(InlineKeyboardMarkup(remaining))
    else:
        await query.message.edit_text("✅ Hammasi o'chirildi.")


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
    await update.message.reply_text(
        f"👥 Botdagi jami obunachilar: <b>{total}</b> ta\n"
        f"📚 Bepul darslar: <b>{len(load_lessons())}</b> ta\n"
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
        if action == "lesson_title":
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
    app.add_handler(CommandHandler("dars_qoshish", add_lesson_start))
    app.add_handler(CommandHandler("kurs_qoshish", add_course_start))
    app.add_handler(CommandHandler("royxat", admin_list))
    app.add_handler(CommandHandler("export", export_registrations))
    app.add_handler(CommandHandler("import", import_start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("xabar", broadcast_start))

    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
    app.add_handler(CallbackQueryHandler(lesson_callback, pattern="^lesson:"))
    app.add_handler(CallbackQueryHandler(course_callback, pattern="^course:"))
    app.add_handler(CallbackQueryHandler(delete_callback, pattern="^(dellesson|delcourse):"))

    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL) & ~filters.COMMAND,
        handle_message
    ))

    logger.info("🎓 Bot ishga tushdi!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
