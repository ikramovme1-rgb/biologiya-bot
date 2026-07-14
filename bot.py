"""
🎓 Milliy Sertifikat / Marafon Bot
Muallif: Makhmudjon Ikramov
"""

import os
import csv
import io
import json
import asyncio
import logging
from datetime import datetime

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
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

# Admin Telegram ID — xatoliklar shu odamga yuboriladi (ixtiyoriy)
ADMIN_ID = int(os.getenv("ADMIN_ID", "1227596738"))

# Milliy Sertifikat uchun YouTube link
YOUTUBE_LINK = os.getenv("YOUTUBE_LINK", "https://youtu.be/wLA_0xU8g3U")

# Botdan foydalanishdan oldin obuna bo'lishi shart bo'lgan asosiy kanal
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@ikramov_biologiya")

# Marafon kanaliga qo'shilish uchun doimiy (permanent) taklif havolasi
MARATHON_CHANNEL_LINK = os.getenv("MARATHON_CHANNEL_LINK", "https://t.me/+8exWHbwDxSNjZjcy")

# Google Sheets sozlamalari
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "1uw8r56rBpmf_kxSPtKVu5UcRefuuuWS96Rx8dAIew2U")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_SHEET_WORKSHEET = os.getenv("GOOGLE_SHEET_WORKSHEET", "Marafon")

# ═══════════════════════════════════════════════════════
# 📂 MA'LUMOTLAR FAYLLARI
# ═══════════════════════════════════════════════════════

DATA_DIR = "data"
REGISTRATIONS_FILE = os.path.join(DATA_DIR, "marathon_registrations.json")

REGIONS = [
    "Toshkent shahri", "Toshkent viloyati",
    "Andijon", "Farg'ona",
    "Namangan", "Sirdaryo",
    "Jizzax", "Samarqand",
    "Buxoro", "Navoiy",
    "Qashqadaryo", "Surxondaryo",
    "Xorazm", "Qoraqalpog'iston",
]

BTN_CERTIFICATE = "🎓 Milliy Sertifikat"
BTN_MARATHON = "🏆 1-2 Avgust Marafon"

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
    if not os.path.exists(REGISTRATIONS_FILE):
        with open(REGISTRATIONS_FILE, "w", encoding="utf-8") as f:
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


# ═══════════════════════════════════════════════════════
# 📊 GOOGLE SHEETS
# ═══════════════════════════════════════════════════════

def _append_to_sheet_sync(row):
    """Google Sheet'ga bitta qator yozish (blocking, thread'da chaqiriladi)"""
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(GOOGLE_SHEET_ID)

    try:
        worksheet = sheet.worksheet(GOOGLE_SHEET_WORKSHEET)
    except gspread.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title=GOOGLE_SHEET_WORKSHEET, rows=1000, cols=10)
        worksheet.append_row(
            ["Sana", "Telegram ID", "Username", "F.I.Sh", "Telefon", "Viloyat/tuman"]
        )

    worksheet.append_row(row)


async def append_registration_to_sheet(row):
    """append_row bloklovchi bo'lgani uchun alohida thread'da ishga tushiramiz"""
    if not GOOGLE_SHEET_ID:
        logger.warning("GOOGLE_SHEET_ID sozlanmagan — Sheet'ga yozilmadi.")
        return False
    try:
        await asyncio.to_thread(_append_to_sheet_sync, row)
        return True
    except Exception:
        logger.exception("Google Sheet'ga yozishda xatolik")
        return False


# ═══════════════════════════════════════════════════════
# 🎨 KLAVIATURALAR
# ═══════════════════════════════════════════════════════

def get_main_menu_keyboard():
    keyboard = [[KeyboardButton(BTN_CERTIFICATE), KeyboardButton(BTN_MARATHON)]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_region_keyboard():
    keyboard = []
    for i in range(0, len(REGIONS), 2):
        row = [InlineKeyboardButton(REGIONS[i], callback_data=f"region_{i}")]
        if i + 1 < len(REGIONS):
            row.append(InlineKeyboardButton(REGIONS[i + 1], callback_data=f"region_{i + 1}"))
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)


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
    text = (
        "🎓 <b>Xush kelibsiz!</b>\n\n"
        "Kerakli bo'limni tanlang:\n\n"
        f"{BTN_CERTIFICATE} — Milliy Sertifikat bo'yicha video dars\n"
        f"{BTN_MARATHON} — Marafon kanaliga qo'shilish"
    )
    await context.bot.send_message(
        chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=get_main_menu_keyboard()
    )


async def proceed_after_subscription(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    if get_registration(user_id):
        await show_main_menu(context, user_id)
        return

    context.user_data["action"] = "reg_name"
    await context.bot.send_message(
        chat_id=user_id,
        text=(
            "🎓 <b>Rahmat, obuna tasdiqlandi!</b>\n\n"
            "Botdan foydalanishdan oldin ma'lumotlaringizni to'ldiring.\n\n"
            "Ism va familiyangizni to'liq kiriting:"
        ),
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove()
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id

    if not await check_subscription(user_id, context):
        await update.message.reply_text(
            "📢 <b>Botdan foydalanish uchun avval kanalimizga obuna bo'ling:</b>\n\n"
            f"{CHANNEL_USERNAME}\n\n"
            "✅ Obuna bo'lgach, pastdagi tugmani bosing:",
            parse_mode="HTML",
            reply_markup=get_subscribe_keyboard()
        )
        return

    await proceed_after_subscription(context, user_id)


async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if not await check_subscription(user_id, context):
        await query.answer("❌ Siz hali obuna bo'lmagansiz!", show_alert=True)
        return

    await query.answer()
    await query.message.delete()
    await proceed_after_subscription(context, user_id)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Bekor qilindi.", reply_markup=get_main_menu_keyboard()
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


# ═══════════════════════════════════════════════════════
# 🎓 MILLIY SERTIFIKAT
# ═══════════════════════════════════════════════════════

async def send_certificate_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🎓 <b>Milliy Sertifikat</b>\n\n"
        "Video darsni quyidagi havoladan tomosha qiling:\n"
        f"▶️ {YOUTUBE_LINK}"
    )
    await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=False)


# ═══════════════════════════════════════════════════════
# 📝 RO'YXATDAN O'TISH (start bosilganda, tugmalardan oldin)
# ═══════════════════════════════════════════════════════

async def handle_reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["full_name"] = update.message.text.strip()
    context.user_data["action"] = "reg_phone"
    await update.message.reply_text(
        "📱 Hozir foydalanadigan telefon raqamingizni qo'lda kiriting "
        "(masalan: +998901234567):"
    )


async def handle_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE, phone: str):
    context.user_data["phone"] = phone.strip()
    context.user_data["action"] = "reg_region"
    await update.message.reply_text(
        "📍 Viloyat/tumaningizni tanlang:",
        reply_markup=get_region_keyboard()
    )


async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if context.user_data.get("action") != "reg_region":
        return

    index = int(query.data.split("_")[1])
    region = REGIONS[index]
    context.user_data["region"] = region

    await query.message.edit_text(f"📍 Tanlandi: <b>{region}</b>\n\n⏳ Saqlanmoqda...", parse_mode="HTML")

    await finish_registration(update, context)


async def finish_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    full_name = context.user_data.get("full_name", "-")
    phone = context.user_data.get("phone", "-")
    region = context.user_data.get("region", "-")
    now = datetime.now().isoformat()

    row = [now[:19], str(user.id), user.username or "-", full_name, phone, region]
    sheet_ok = await append_registration_to_sheet(row)

    save_registration(user.id, {
        "full_name": full_name,
        "phone": phone,
        "region": region,
        "registered_at": now,
        "sheet_synced": sheet_ok,
    })

    context.user_data.clear()

    await context.bot.send_message(
        chat_id=user.id,
        text="✅ <b>Ma'lumotlaringiz saqlandi!</b>",
        parse_mode="HTML"
    )
    await show_main_menu(context, user.id)


# ═══════════════════════════════════════════════════════
# 🏆 MARAFON
# ═══════════════════════════════════════════════════════

async def send_marathon_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🏆 <b>1-2 Avgust Marafon</b>\n\n"
        "Quyidagi havola orqali marafon kanaliga qo'shiling:\n\n"
        f"🔗 {MARATHON_CHANNEL_LINK}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ═══════════════════════════════════════════════════════
# 💬 XABARLARNI QAYTA ISHLASH
# ═══════════════════════════════════════════════════════

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == BTN_CERTIFICATE:
        context.user_data.clear()
        await send_certificate_link(update, context)
        return
    elif text == BTN_MARATHON:
        context.user_data.clear()
        await send_marathon_link(update, context)
        return

    action = context.user_data.get("action")

    if action == "reg_name":
        await handle_reg_name(update, context)
        return
    elif action == "reg_phone":
        await handle_reg_phone(update, context, text)
        return


# ═══════════════════════════════════════════════════════
# 🏁 BOTNI ISHGA TUSHIRISH
# ═══════════════════════════════════════════════════════

def main():
    ensure_data_dir()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("export", export_registrations))
    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
    app.add_handler(CallbackQueryHandler(region_callback, pattern="^region_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🎓 Bot ishga tushdi!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
