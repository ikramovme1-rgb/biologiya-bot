"""
⚙️ Sozlamalar — hammasi Railway "Variables" bo'limidan o'qiladi.

Majburiy:
    BOT_TOKEN        — @BotFather bergan token

Ixtiyoriy:
    ADMIN_IDS        — adminlar Telegram ID'lari, vergul bilan (masalan: 111,222)
    ADMIN_USERNAME   — "Admin bilan aloqa" uchun username (@ belgisisiz)
    CHANNEL_USERNAME — majburiy obuna kanali (keyin panel orqali ham o'zgartirsa bo'ladi)
    DATA_DIR         — baza turadigan papka (Railway Volume shu yerga ulanadi)
"""

import os


def _parse_admin_ids():
    raw = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID") or "1227596738"
    ids = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            ids.append(int(part))
    return ids or [1227596738]


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = _parse_admin_ids()
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "qabul30").lstrip("@")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@ikramov_biologiya")

DATA_DIR = os.getenv("DATA_DIR", "data")
DB_FILE = os.path.join(DATA_DIR, "bot.db")

# Vaqtni ko'rsatishda ishlatiladi (Toshkent, UTC+5). Bazada hammasi UTC'da saqlanadi.
TZ_OFFSET_HOURS = 5

# Xabar tarqatish tezligi: Telegram cheklovi ~30 xabar/soniya, biz ehtiyot bilan 20.
BROADCAST_DELAY = 0.05

DEFAULT_WELCOME = (
    "🧬 <b>Assalomu alaykum, {name}!</b>\n\n"
    "Ikramov Biologiya botiga xush kelibsiz.\n"
    "Kerakli bo'limni quyidagi menyudan tanlang 👇"
)
DEFAULT_LEAD_TEXT = (
    "✅ <b>Arizangiz qabul qilindi!</b>\n\n"
    "Tez orada siz bilan bog'lanamiz."
)
