"""
🏆 Marafon Bot
Muallif: Makhmudjon Ikramov
"""

import os
import csv
import io
import json
import asyncio
import logging

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

# Admin Telegram ID — xatoliklar shu odamga yuboriladi (ixtiyoriy)
ADMIN_ID = int(os.getenv("ADMIN_ID", "1227596738"))

# Admin bilan aloqa uchun Telegram username (@ belgisisiz)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "qabul30")

# Botdan foydalanishdan oldin obuna bo'lishi shart bo'lgan asosiy kanal
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@ikramov_biologiya")

# Marafon kanaliga qo'shilish uchun doimiy (permanent) taklif havolasi
MARATHON_CHANNEL_LINK = os.getenv("MARATHON_CHANNEL_LINK", "https://t.me/+9dU3dAgOrB9hZTky")

# ═══════════════════════════════════════════════════════
# 📂 MA'LUMOTLAR FAYLLARI
# ═══════════════════════════════════════════════════════

DATA_DIR = "data"
REGISTRATIONS_FILE = os.path.join(DATA_DIR, "marathon_registrations.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")

BTN_MARATHON = "🏆 Marafon kanaliga qo'shilish!"
BTN_MOCK_TEST = "📝 Mock test | Rash tekshiruv"
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
    for filepath in (REGISTRATIONS_FILE, USERS_FILE):
        if not os.path.exists(filepath):
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=2)


def load_json(filepath, default):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_registration(user_id):
    registrations = load_json(REGISTRATIONS_FILE, {})
    return registrations.get(str(user_id))


def save_registration(user_id, record):
    registrations = load_json(REGISTRATIONS_FILE, {})
    registrations[str(user_id)] = record
    save_json(REGISTRATIONS_FILE, registrations)


def save_user(user_id, username, full_name):
    users = load_json(USERS_FILE, {})
    users[str(user_id)] = {"username": username, "full_name": full_name}
    save_json(USERS_FILE, users)


# ═══════════════════════════════════════════════════════
# 🎨 KLAVIATURALAR
# ═══════════════════════════════════════════════════════

def get_main_menu_keyboard():
    keyboard = [
        [KeyboardButton(BTN_MARATHON)],
        [KeyboardButton(BTN_MOCK_TEST), KeyboardButton(BTN_ADMIN)],
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
    """/export — marafon ro'yxatini CSV fayl qilib yuborish (faqat admin)"""
    if update.effective_user.id != ADMIN_ID:
        return

    registrations = load_json(REGISTRATIONS_FILE, {})
    if not registrations:
        await update.message.reply_text("Hozircha marafonga ro'yxatdan o'tganlar yo'q.")
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
                "sheet_synced": False,
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
    await update.message.reply_text(f"👥 Botdagi jami obunachilar: <b>{total}</b> ta", parse_mode="HTML")


# ═══════════════════════════════════════════════════════
# 🏆 MENYU TUGMALARI
# ═══════════════════════════════════════════════════════

async def send_marathon_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🏆 <b>Marafon kanaliga qo'shilish!</b>\n\n"
        "Quyidagi havola orqali marafon kanaliga qo'shiling:\n\n"
        f"🔗 {MARATHON_CHANNEL_LINK}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def send_mock_test_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔜 <b>Tez kunda ishga tushadi!</b>", parse_mode="HTML")


async def send_admin_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "💬 <b>Admin bilan aloqa</b>\n\nSavol va takliflar uchun murojaat qiling:"
    keyboard = [[InlineKeyboardButton("✍️ Yozish", url=f"https://t.me/{ADMIN_USERNAME}")]]
    await update.message.reply_text(
        text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ═══════════════════════════════════════════════════════
# 💬 XABARLARNI QAYTA ISHLASH
# ═══════════════════════════════════════════════════════

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = context.user_data.get("action")
    if action == "broadcast" and update.effective_user.id == ADMIN_ID:
        await handle_broadcast_message(update, context)
        return
    if action == "import" and update.effective_user.id == ADMIN_ID and update.message.document:
        await handle_import_document(update, context)
        return

    text = update.message.text
    if text is None:
        return

    if text == BTN_MARATHON:
        await send_marathon_link(update, context)
    elif text == BTN_MOCK_TEST:
        await send_mock_test_info(update, context)
    elif text == BTN_ADMIN:
        await send_admin_contact(update, context)


# ═══════════════════════════════════════════════════════
# 🏁 BOTNI ISHGA TUSHIRISH
# ═══════════════════════════════════════════════════════

def main():
    ensure_data_dir()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("export", export_registrations))
    app.add_handler(CommandHandler("import", import_start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("xabar", broadcast_start))
    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL) & ~filters.COMMAND,
        handle_message
    ))

    logger.info("🎓 Bot ishga tushdi!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
