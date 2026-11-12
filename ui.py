"""
🎨 Umumiy yordamchilar: klaviaturalar, kontent yuborish, formatlash.
"""

import html
import re
from datetime import datetime, timedelta, timezone

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
    LinkPreviewOptions, ReplyKeyboardMarkup, ReplyKeyboardRemove,
)
from telegram.error import BadRequest

import config
import db

HTML = "HTML"
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
CAPTION_LIMIT = 1024

STATUS_LABELS = {
    "new": "🆕 Yangi",
    "contacted": "📞 Bog'lanilgan",
    "sold": "💰 Sotilgan",
    "rejected": "❌ Rad etilgan",
}
MEDIA_LABELS = {"photo": "rasm", "video": "video", "document": "fayl", "animation": "GIF"}

esc = html.escape


def is_admin(user_id) -> bool:
    return user_id in config.ADMIN_IDS


# ═══════════════════════════════════════════════════════
# ⌨️ KLAVIATURALAR
# ═══════════════════════════════════════════════════════

def btn(text, data):
    return InlineKeyboardButton(text, callback_data=data)


def url_btn(text, url):
    return InlineKeyboardButton(text, url=url)


def kb(rows):
    return InlineKeyboardMarkup(rows)


def main_keyboard():
    """Bosh menyu: "keng" tugmalar alohida qatorda, qolganlari ikkitadan."""
    rows, pair = [], []
    for node in db.children(None):
        if node["wide"]:
            if pair:
                rows.append(pair)
                pair = []
            rows.append([KeyboardButton(node["title"])])
        else:
            pair.append(KeyboardButton(node["title"]))
            if len(pair) == 2:
                rows.append(pair)
                pair = []
    if pair:
        rows.append(pair)
    if not rows:
        return ReplyKeyboardRemove()
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)


# ═══════════════════════════════════════════════════════
# 🕐 VAQT
# ═══════════════════════════════════════════════════════

def local_dt(utc_str, fmt="%d.%m.%Y %H:%M") -> str:
    """Bazadagi UTC vaqtni Toshkent vaqtida ko'rsatadi."""
    if not utc_str:
        return "—"
    try:
        dt = datetime.strptime(utc_str[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return utc_str
    return (dt + timedelta(hours=config.TZ_OFFSET_HOURS)).strftime(fmt)


def local_day_start(days_back=0) -> str:
    """Toshkent vaqti bilan (bugun - days_back) kun boshining UTC ko'rinishi."""
    local_now = datetime.now(timezone.utc) + timedelta(hours=config.TZ_OFFSET_HOURS)
    midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_back)
    return (midnight - timedelta(hours=config.TZ_OFFSET_HOURS)).strftime("%Y-%m-%d %H:%M:%S")


def parse_delay(text):
    """"30 daqiqa", "2 soat", "1 kun" → daqiqalar soni. Tushunilmasa None."""
    m = re.fullmatch(r"\s*(\d{1,4})\s*([a-zA-Z]+)\s*", text or "")
    if not m:
        return None
    amount, unit = int(m.group(1)), m.group(2).lower()
    if unit.startswith(("daq", "min")) or unit == "m":
        minutes = amount
    elif unit.startswith("soat") or unit in ("s", "h"):
        minutes = amount * 60
    elif unit.startswith("kun") or unit in ("k", "d"):
        minutes = amount * 1440
    else:
        return None
    return minutes if minutes <= 90 * 1440 else None


def fmt_delay(minutes) -> str:
    if minutes == 0:
        return "darhol"
    if minutes % 1440 == 0:
        return f"{minutes // 1440} kun"
    if minutes % 60 == 0:
        return f"{minutes // 60} soat"
    return f"{minutes} daqiqa"


# ═══════════════════════════════════════════════════════
# ☎️ TELEFON
# ═══════════════════════════════════════════════════════

def normalize_phone(raw):
    """Qo'lda yozilgan raqamni +998XXXXXXXXX ko'rinishiga keltiradi. Noto'g'ri bo'lsa None."""
    s = (raw or "").strip()
    if not s or re.search(r"[^\d\s+\-()]", s):
        return None
    digits = re.sub(r"\D", "", s)
    if len(digits) == 9:
        return "+998" + digits
    if len(digits) == 12 and digits.startswith("998"):
        return "+" + digits
    if s.startswith("+") and 10 <= len(digits) <= 15:
        return "+" + digits
    return None


# ═══════════════════════════════════════════════════════
# 📨 KONTENT
# ═══════════════════════════════════════════════════════

def extract_content(message):
    """Xabardan saqlanadigan kontentni ajratadi: matn (HTML) va/yoki bitta media."""
    if message.photo:
        return {"text": message.caption_html, "media_type": "photo",
                "media_id": message.photo[-1].file_id}
    if message.video:
        return {"text": message.caption_html, "media_type": "video",
                "media_id": message.video.file_id}
    if message.animation:
        return {"text": message.caption_html, "media_type": "animation",
                "media_id": message.animation.file_id}
    if message.document:
        return {"text": message.caption_html, "media_type": "document",
                "media_id": message.document.file_id}
    if message.text:
        return {"text": message.text_html, "media_type": None, "media_id": None}
    return None


def visible_len(text) -> int:
    """HTML teglarsiz uzunlik — Telegram cheklovlari shu bo'yicha hisoblanadi."""
    return len(html.unescape(re.sub(r"<[^>]+>", "", text or "")))


def describe_content(text, media_type) -> str:
    parts = []
    if media_type:
        parts.append(MEDIA_LABELS.get(media_type, media_type))
    if text:
        parts.append(f"matn ({visible_len(text)} belgi)")
    return " + ".join(parts) if parts else "yo'q"


def snippet(text, limit=30) -> str:
    plain = " ".join(html.unescape(re.sub(r"<[^>]+>", "", text or "")).split())
    return plain if len(plain) <= limit else plain[:limit - 1] + "…"


async def send_content(bot, chat_id, text=None, media_type=None, media_id=None,
                       reply_markup=None, preview=False):
    """Matn va/yoki mediani yuboradi. Izoh sig'masa, media va matn alohida ketadi."""
    if media_type and media_id:
        sender = {"photo": bot.send_photo, "video": bot.send_video,
                  "document": bot.send_document, "animation": bot.send_animation}[media_type]
        media = {media_type: media_id}
        if text and visible_len(text) > CAPTION_LIMIT:
            await sender(chat_id=chat_id, **media)
            return await bot.send_message(chat_id=chat_id, text=text, parse_mode=HTML,
                                          reply_markup=reply_markup, link_preview_options=NO_PREVIEW)
        return await sender(chat_id=chat_id, caption=text or None, parse_mode=HTML,
                            reply_markup=reply_markup, **media)
    return await bot.send_message(
        chat_id=chat_id, text=text or "…", parse_mode=HTML, reply_markup=reply_markup,
        link_preview_options=None if preview else NO_PREVIEW)


async def answer(query, text=None, alert=False):
    """Tugma bosilishiga javob. Juda eski tugma bo'lsa (bot o'chiq turgan payt) xato bermaydi."""
    try:
        await query.answer(text, show_alert=alert)
    except BadRequest:
        pass


async def safe_edit(query, text, markup=None):
    """Xabarni joyida tahrirlaydi; bo'lmasa (masalan u rasm bo'lsa) yangisini yuboradi."""
    try:
        await query.edit_message_text(text, parse_mode=HTML, reply_markup=markup,
                                      link_preview_options=NO_PREVIEW)
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return
        await query.get_bot().send_message(
            chat_id=query.from_user.id, text=text, parse_mode=HTML,
            reply_markup=markup, link_preview_options=NO_PREVIEW)


# ═══════════════════════════════════════════════════════
# 📥 ARIZA KARTASI (adminlar uchun)
# ═══════════════════════════════════════════════════════

def lead_card(lead):
    """Ariza haqidagi to'liq ma'lumot va holatni o'zgartirish tugmalari."""
    name = lead["full_name"] or lead["reg_name"] or "Foydalanuvchi"
    lines = [
        f"📥 <b>Ariza #{lead['id']}</b> — {STATUS_LABELS.get(lead['status'], lead['status'])}",
        "",
        f"👤 <a href=\"tg://user?id={lead['user_id']}\">{esc(name)}</a>"
        + (f" (@{esc(lead['username'])})" if lead["username"] else ""),
        f"📞 <code>{esc(lead['phone'] or '—')}</code>",
        f"💎 {esc(lead['node_title'] or '—')}",
    ]
    if lead["reg_name"] and lead["reg_name"] != name:
        lines.append(f"📝 F.I.Sh: {esc(lead['reg_name'])}")
    if lead["region"]:
        lines.append(f"📍 {esc(lead['region'])}")
    if lead["source"]:
        lines.append(f"🔗 Manba: {esc(lead['source'])}")
    lines.append(f"🕐 {local_dt(lead['created_at'])}")

    status_buttons = [btn(STATUS_LABELS[s], f"a:ls:{lead['id']}:{s}")
                      for s in db.LEAD_STATUSES if s != lead["status"]]
    rows = [status_buttons[:2], status_buttons[2:]]
    if lead["username"]:
        rows.append([url_btn("💬 Telegramda yozish", f"https://t.me/{lead['username']}")])
    rows.append([btn("⬅️ Arizalar ro'yxati", f"a:leads:{lead['status']}:0")])
    return "\n".join(lines), kb([r for r in rows if r])
