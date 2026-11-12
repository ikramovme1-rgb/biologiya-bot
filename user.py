"""
👤 Foydalanuvchi tomoni: /start, obuna tekshiruvi, menyu bo'ylab yurish, ariza qoldirish.
"""

import logging
import re
import time

from telegram import Update
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes

import config
import db
import ui
from ui import btn, esc, kb, url_btn

logger = logging.getLogger(__name__)

SUB_CACHE_SECONDS = 600           # obuna tasdiqlangach, 10 daqiqa qayta so'ralmaydi
GATE_ALERT_INTERVAL = 3600        # kanal sozlamasi xatosi haqida adminga soatiga 1 marta
SOURCE_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")


# ═══════════════════════════════════════════════════════
# ✅ KANALGA OBUNA
# ═══════════════════════════════════════════════════════

def gate_channel() -> str:
    return db.get_setting("gate_channel", config.CHANNEL_USERNAME) or ""


def gate_enabled() -> bool:
    return db.get_setting("gate_enabled", "1") == "1" and bool(gate_channel())


async def is_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    if not gate_enabled():
        return True
    if context.user_data.get("sub_until", 0) > time.time():
        return True

    channel = gate_channel()
    try:
        member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
    except (BadRequest, Forbidden) as e:
        # Bot kanalda admin emas yoki kanal nomi noto'g'ri. Bunday holatda hammani
        # to'sib qo'ymaymiz — o'tkazib yuboramiz va adminni ogohlantiramiz.
        await _alert_gate_problem(context, channel, e)
        return True
    except TelegramError:
        return True       # vaqtinchalik tarmoq xatosi — foydalanuvchini kuttirmaymiz

    ok = member.status in ("member", "administrator", "creator") or (
        member.status == "restricted" and getattr(member, "is_member", False))
    if ok:
        context.user_data["sub_until"] = time.time() + SUB_CACHE_SECONDS
    return ok


async def _alert_gate_problem(context, channel, error):
    last = context.bot_data.get("gate_alert_at", 0)
    if time.time() - last < GATE_ALERT_INTERVAL:
        return
    context.bot_data["gate_alert_at"] = time.time()
    logger.warning("Obuna tekshiruvi ishlamayapti (%s): %s", channel, error)
    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"⚠️ <b>Obuna tekshiruvi ishlamayapti</b>\n\n"
                f"Kanal: {esc(channel)}\nXato: <code>{esc(str(error))}</code>\n\n"
                f"Botni shu kanalga <b>admin</b> qilib qo'shing yoki /admin → Sozlamalar "
                f"orqali kanalni to'g'rilang. Hozircha foydalanuvchilar tekshiruvsiz "
                f"o'tkazilmoqda.", parse_mode=ui.HTML)
        except TelegramError:
            pass


async def send_gate(context, chat_id):
    channel = gate_channel()
    rows = [
        [url_btn("📢 Kanalga obuna bo'lish", f"https://t.me/{channel.lstrip('@')}")],
        [btn("✅ Obunani tekshirish", "check_sub")],
    ]
    await context.bot.send_message(
        chat_id,
        "📢 <b>Botdan foydalanish uchun avval kanalimizga obuna bo'ling:</b>\n\n"
        f"{esc(channel)}\n\n"
        "Obuna bo'lgach, «✅ Obunani tekshirish» tugmasini bosing.",
        parse_mode=ui.HTML, reply_markup=kb(rows))


# ═══════════════════════════════════════════════════════
# 🚀 /start
# ═══════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    payload = context.args[0] if context.args else None
    source = payload if payload and SOURCE_RE.fullmatch(payload) else None

    db.upsert_user(user.id, user.username, user.full_name, source)
    db.add_event(user.id, "start")
    context.user_data.pop("state", None)
    context.user_data.pop("astate", None)

    # Reklama havolasi aniq bir sahifaga olib borishi mumkin
    src = db.get_source(source) if source else None
    context.user_data["pending_node"] = src["node_id"] if src and src["node_id"] else None

    if not await is_subscribed(context, user.id):
        await send_gate(context, user.id)
        return
    await welcome(context, user)


async def welcome(context, user):
    text = db.get_setting("welcome", config.DEFAULT_WELCOME)
    text = text.replace("{name}", esc(user.first_name or user.full_name or ""))
    await context.bot.send_message(user.id, text, parse_mode=ui.HTML,
                                   reply_markup=ui.main_keyboard(),
                                   link_preview_options=ui.NO_PREVIEW)

    pending = context.user_data.pop("pending_node", None)
    node = db.get_node(pending) if pending else None
    if node and not node["hidden"]:
        await open_node(context, user.id, node)


async def cb_check_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_subscribed(context, query.from_user.id):
        await ui.answer(query, "❌ Siz hali kanalga obuna bo'lmagansiz!", alert=True)
        return
    await ui.answer(query, "✅ Obuna tasdiqlandi!")
    try:
        await query.message.delete()
    except TelegramError:
        pass
    await welcome(context, query.from_user)


# ═══════════════════════════════════════════════════════
# 🧭 MENYU BO'YLAB YURISH
# ═══════════════════════════════════════════════════════

async def open_node(context, user_id, node, query=None, track=True):
    """
    Tugma ortidagi narsani ko'rsatadi.
    Bo'lim — ichidagi tugmalar ro'yxati (callback'dan kelsa, xabar joyida almashadi).
    Sahifa — har doim yangi xabar, shunda ro'yxat yuqorida qolaveradi.
    """
    bot = context.bot

    if node["kind"] == "section":
        kids = db.children(node["id"])
        text = node["text"] or f"📂 <b>{esc(node['title'])}</b>"
        if not kids:
            text += "\n\n<i>Bu bo'lim hozircha bo'sh. Tez orada to'ldiriladi! 🔜</i>"
        rows = [[btn(k["title"], f"n:{k['id']}")] for k in kids]
        if node["parent_id"]:
            rows.append([btn("⬅️ Orqaga", f"n:{node['parent_id']}")])
        if query:
            await ui.safe_edit(query, text, kb(rows))
        else:
            await bot.send_message(user_id, text, parse_mode=ui.HTML, reply_markup=kb(rows),
                                   link_preview_options=ui.NO_PREVIEW)
        return

    if track:
        db.add_event(user_id, "offer_view" if node["lead"] else "view", node["id"])

    has_body = bool(node["text"] or node["media_id"])
    rows = []
    if node["lead"]:
        rows.append([btn("📝 Kursga yozilish", f"lead:{node['id']}")])
    if node["url"] and has_body:
        rows.append([url_btn(node["url_label"] or "🔗 Ochish", node["url"])])
    markup = kb(rows) if rows else None

    if has_body:
        await ui.send_content(bot, user_id, node["text"], node["media_type"], node["media_id"],
                              reply_markup=markup)
    elif node["url"]:
        # Faqat havola (masalan YouTube dars) — havola ko'rinishi (preview) bilan
        await ui.send_content(bot, user_id, f"<b>{esc(node['title'])}</b>\n\n▶️ {esc(node['url'])}",
                              reply_markup=markup, preview=True)
    else:
        await ui.send_content(bot, user_id, f"<b>{esc(node['title'])}</b>", reply_markup=markup)


async def _node_from_callback(update, context):
    """Callback'dagi tugmani topadi va obunani tekshiradi. Muammo bo'lsa None."""
    query = update.callback_query
    user = query.from_user
    db.upsert_user(user.id, user.username, user.full_name)

    node = db.get_node(int(query.data.split(":")[1]))
    if not node or node["hidden"]:
        await ui.answer(query, "Bu bo'lim hozir mavjud emas.", alert=True)
        return None
    if not await is_subscribed(context, user.id):
        await ui.answer(query)
        await send_gate(context, user.id)
        return None
    await ui.answer(query)
    return node


async def cb_node(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menyu ichidagi tugma: bo'lim bo'lsa ro'yxat shu xabarning o'zida almashadi."""
    node = await _node_from_callback(update, context)
    if node:
        query = update.callback_query
        await open_node(context, query.from_user.id, node,
                        query=query if node["kind"] == "section" else None)


async def cb_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xabar/avto-seriya ostidagi tugma: asl xabarga tegmasdan, yangi xabar bilan ochadi."""
    node = await _node_from_callback(update, context)
    if node:
        await open_node(context, update.callback_query.from_user.id, node)


# ═══════════════════════════════════════════════════════
# 📝 ARIZA QOLDIRISH
# ═══════════════════════════════════════════════════════

PHONE_PROMPT = (
    "📞 <b>Telefon raqamingizni yozing</b>\n\n"
    "Siz bilan bog'lanishimiz uchun hozir ishlatayotgan raqamingizni kiriting.\n"
    "Masalan: <code>90 123 45 67</code>"
)


async def cb_lead(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    db.upsert_user(user.id, user.username, user.full_name)
    node = db.get_node(int(query.data.split(":")[1]))

    if not node or not node["lead"] or node["hidden"]:
        await ui.answer(query, "Bu kursga yozilish hozir yopiq.", alert=True)
        return
    if db.open_lead(user.id, node["id"]):
        await ui.answer(query, "✅ Arizangiz allaqachon qabul qilingan. Tez orada bog'lanamiz!",
                           alert=True)
        return
    await ui.answer(query)

    context.user_data["state"] = {"name": "lead_phone", "node_id": node["id"]}
    saved = db.get_user(user.id)["phone"]
    if saved:
        rows = [[btn(f"✅ Ha, {saved}", f"leadok:{node['id']}")],
                [btn("✏️ Boshqa raqam yozaman", f"leadnew:{node['id']}")]]
        await context.bot.send_message(
            user.id, f"📞 Siz bilan shu raqam orqali bog'lanaylikmi?\n\n<b>{esc(saved)}</b>",
            parse_mode=ui.HTML, reply_markup=kb(rows))
    else:
        await context.bot.send_message(user.id, PHONE_PROMPT, parse_mode=ui.HTML)


async def cb_lead_saved_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi avval saqlangan raqamini tasdiqladi."""
    query = update.callback_query
    user = query.from_user
    node_id = int(query.data.split(":")[1])
    row = db.get_user(user.id)
    saved = row["phone"] if row else None
    await ui.answer(query)
    if not saved:
        context.user_data["state"] = {"name": "lead_phone", "node_id": node_id}
        await context.bot.send_message(user.id, PHONE_PROMPT, parse_mode=ui.HTML)
        return
    try:
        await query.message.edit_reply_markup(None)
    except TelegramError:
        pass
    await finish_lead(context, user, node_id, saved)


async def cb_lead_new_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await ui.answer(query)
    context.user_data["state"] = {"name": "lead_phone",
                                  "node_id": int(query.data.split(":")[1])}
    await ui.safe_edit(query, PHONE_PROMPT)


async def finish_lead(context, user, node_id, phone):
    context.user_data.pop("state", None)
    node = db.get_node(node_id)
    title = node["title"] if node else "—"

    if db.open_lead(user.id, node_id):      # ikki marta bosilgan bo'lsa takrorlamaymiz
        lead_id = None
    else:
        db.set_user_phone(user.id, phone)
        lead_id = db.create_lead(user.id, node_id, title, phone)

    await context.bot.send_message(
        user.id, db.get_setting("lead_text", config.DEFAULT_LEAD_TEXT),
        parse_mode=ui.HTML, reply_markup=ui.main_keyboard())

    if lead_id:
        text, markup = ui.lead_card(db.get_lead(lead_id))
        for admin_id in config.ADMIN_IDS:
            try:
                await context.bot.send_message(admin_id, "🔔 <b>Yangi ariza!</b>\n\n" + text,
                                               parse_mode=ui.HTML, reply_markup=markup,
                                               link_preview_options=ui.NO_PREVIEW)
            except TelegramError as e:
                logger.warning("Adminga (%s) ariza xabari yetmadi: %s", admin_id, e)


# ═══════════════════════════════════════════════════════
# 💬 MATNLI XABARLAR
# ═══════════════════════════════════════════════════════

async def try_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Bosh menyu tugmasi bosilgan bo'lsa — ochadi va True qaytaradi."""
    text = update.message.text
    node = db.find_root_by_title(text) if text else None
    if not node:
        return False

    # Menyu tugmasi boshlangan har qanday amalni bekor qiladi (tiqilib qolmaslik uchun)
    context.user_data.pop("state", None)
    context.user_data.pop("astate", None)

    user = update.effective_user
    if not await is_subscribed(context, user.id):
        await send_gate(context, user.id)
        return True
    await open_node(context, user.id, node)
    return True


async def handle_state_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Foydalanuvchi ariza uchun telefon raqamini yozayotgan bo'lsa — qabul qiladi."""
    state = context.user_data.get("state")
    if not state or state.get("name") != "lead_phone":
        return False

    phone = ui.normalize_phone(update.message.text)
    if not phone:
        await update.message.reply_text(
            "❌ Raqam noto'g'ri ko'rinadi.\n\n"
            "To'liq raqamni yozing, masalan: <code>90 123 45 67</code> "
            "yoki <code>+998901234567</code>", parse_mode=ui.HTML)
        return True
    await finish_lead(context, update.effective_user, state["node_id"], phone)
    return True


async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tushunarsiz xabar: menyuni qayta ko'rsatamiz (klaviatura ham yangilanadi)."""
    user = update.effective_user
    if not await is_subscribed(context, user.id):
        await send_gate(context, user.id)
        return
    await update.message.reply_text("Kerakli bo'limni quyidagi menyudan tanlang 👇",
                                    reply_markup=ui.main_keyboard())


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi botni bloklasa yoki blokdan chiqarsa — bazada belgilab qo'yamiz."""
    change = update.my_chat_member
    if change.chat.type != "private":
        return
    db.set_blocked(change.chat.id, change.new_chat_member.status == "kicked")
