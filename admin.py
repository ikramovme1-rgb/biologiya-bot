"""
🔧 Admin paneli (/admin).

Bo'limlar:
    🧩 Menyu konstruktori   — tugma qo'shish, o'chirish, nomini/tartibini o'zgartirish
    📥 Arizalar             — kursga yozilganlar, holatlari, yopiq kanalga avtomatik kirish
    📊 Statistika           — o'sish, voronka, manbalar
    📢 Xabar yuborish       — segment bo'yicha, tugma bilan
    🤖 Avto-seriya          — /start'dan keyin o'zi ketadigan xabarlar
    🔗 Reklama havolalari   — qaysi reklama mijoz olib kelayotganini o'lchash
    ⚙️ Sozlamalar, 📤 eksport va zaxira

Barcha tugmalar "a:<amal>:<parametrlar>" ko'rinishidagi callback bilan ishlaydi.
Matn kiritish kerak bo'lgan qadamlar user_data["astate"] da saqlanadi.
"""

import asyncio
import csv
import io
import logging
import os
import re
import tempfile

from telegram import Update
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import ContextTypes

import config
import db
import ui
import user as user_side
from ui import btn, esc, kb, url_btn

logger = logging.getLogger(__name__)

TITLE_LIMIT = 60
LEADS_PER_PAGE = 8
CODE_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")
CHANNEL_RE = re.compile(r"@[A-Za-z][A-Za-z0-9_]{3,31}")
URL_RE = re.compile(r"(https?://)?[\w.-]+\.[a-zA-Z]{2,}(/\S*)?")

SEGMENTS = [
    ("all", "👥 Hammaga"),
    ("new7", "🆕 Oxirgi 7 kunda qo'shilganlar"),
    ("offer_no_lead", "👀 Kursni ko'rgan, ariza qoldirmagan"),
    ("leads", "📥 Ariza qoldirgan, hali sotib olmagan"),
    ("buyers", "💰 Sotib olganlar"),
    ("cold", "🧊 Hali hech narsa ko'rmaganlar"),
]


def segment_label(segment) -> str:
    if segment.startswith("src_"):
        return f"🔗 «{segment[4:]}» havolasidan kelganlar"
    return dict(SEGMENTS).get(segment, segment)


# ═══════════════════════════════════════════════════════
# 🧰 YORDAMCHILAR
# ═══════════════════════════════════════════════════════

async def reply(update, text, rows=None):
    await update.message.reply_text(text, parse_mode=ui.HTML,
                                    reply_markup=kb(rows) if rows else None,
                                    link_preview_options=ui.NO_PREVIEW)


def set_state(context, name, **params):
    context.user_data["astate"] = {"name": name, **params}


def clean_url(raw):
    """Havolani tekshiradi; "youtu.be/..." kabi sxemasiz yozilsa https:// qo'shadi."""
    raw = (raw or "").strip()
    if not raw or " " in raw or not URL_RE.fullmatch(raw):
        return None
    return raw if raw.lower().startswith(("http://", "https://")) else "https://" + raw


def check_title(text, parent_id, except_id=None):
    """Tugma nomini tekshiradi. (nom, xato) juftligini qaytaradi."""
    title = " ".join((text or "").split())
    if not title:
        return None, "❌ Tugma nomini matn ko'rinishida yozing."
    if len(title) > TITLE_LIMIT:
        return None, f"❌ Nom juda uzun ({len(title)} belgi). {TITLE_LIMIT} belgidan oshmasin."
    if parent_id is None and db.root_title_taken(title, except_id):
        return None, "❌ Bosh menyuda shu nomli tugma bor. Boshqa nom yozing."
    return title, None


def node_label(node) -> str:
    prefix = "📂 " if node["kind"] == "section" else "▫️ "
    suffix = (" 📝" if node["lead"] else "") + (" 🙈" if node["hidden"] else "")
    return prefix + node["title"] + suffix


def picker_rows(prefix, with_home=None):
    """Sahifa tanlash ro'yxati: avval kurs takliflari, keyin bosh menyu tugmalari."""
    rows, seen = [], set()
    if with_home:
        rows.append([btn(with_home, f"{prefix}:0")])
    for node in list(db.offer_nodes()) + list(db.children(None)):
        if node["id"] in seen or node["hidden"]:
            continue
        seen.add(node["id"])
        rows.append([btn(("💎 " if node["lead"] else "") + node["title"], f"{prefix}:{node['id']}")])
    return rows[:40]


# ═══════════════════════════════════════════════════════
# 🏠 BOSH PANEL
# ═══════════════════════════════════════════════════════

def v_home():
    new = db.lead_counts()["new"]
    rows = [
        [btn("🧩 Menyu tugmalari", "a:menu:0")],
        [btn(f"📥 Arizalar ({new} yangi)" if new else "📥 Arizalar", "a:leads:new:0"),
         btn("📊 Statistika", "a:stats:all")],
        [btn("📢 Xabar yuborish", "a:bc"), btn("🤖 Avto-seriya", "a:drip")],
        [btn("🔗 Reklama havolalari", "a:src"), btn("⚙️ Sozlamalar", "a:set")],
        [btn("📤 Eksport va zaxira", "a:exp")],
    ]
    return "🔧 <b>Boshqaruv paneli</b>\n\nBo'limni tanlang:", rows


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ui.is_admin(update.effective_user.id):
        return
    context.user_data.pop("astate", None)
    await reply(update, *v_home())


def shortcut(view):
    """/stats, /xabar, /export kabi eski buyruqlar panelning tegishli bo'limini ochadi."""
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not ui.is_admin(update.effective_user.id):
            return
        context.user_data.pop("astate", None)
        await reply(update, *view())
    return handler


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("astate", None)
    context.user_data.pop("state", None)
    context.user_data.pop("bc", None)
    await update.message.reply_text("❌ Bekor qilindi.", reply_markup=ui.main_keyboard())


async def a_home(query, context, args):
    await ui.safe_edit(query, *_kb(v_home()))


def _kb(view):
    text, rows = view
    return text, kb(rows)


# ═══════════════════════════════════════════════════════
# 🧩 MENYU KONSTRUKTORI
# ═══════════════════════════════════════════════════════

def v_menu(node_id):
    """Bosh menyu (node_id=0) yoki bo'lim ichidagi tugmalar ro'yxati."""
    if node_id:
        node = db.get_node(node_id)
        if not node:
            return v_menu(0)
        if node["kind"] != "section":
            return v_node(node_id)
        kids = db.children(node_id, include_hidden=True)
        text = (f"📂 <b>{esc(' › '.join(db.node_path(node_id)))}</b>\n\n"
                f"Ichida {len(kids)} ta tugma. Tahrirlash uchun tugmani tanlang.")
        back = f"a:menu:{node['parent_id'] or 0}"
    else:
        kids = db.children(None, include_hidden=True)
        text = ("🧩 <b>Bosh menyu tugmalari</b>\n\n"
                "Tahrirlash uchun tugmani tanlang yoki yangisini qo'shing.\n"
                "<i>📂 bo'lim · ▫️ sahifa · 📝 ariza tugmasi bor · 🙈 yashirilgan</i>")
        back = "a:home"

    rows = [[btn(node_label(k),
                 f"a:menu:{k['id']}" if k["kind"] == "section" else f"a:node:{k['id']}")]
            for k in kids]
    rows.append([btn("➕ Tugma qo'shish", f"a:add:{node_id}")])
    if node_id:
        rows.append([btn("⚙️ Shu bo'limni sozlash", f"a:node:{node_id}")])
    rows.append([btn("⬅️ Orqaga", back)])
    return text, rows


def v_node(node_id):
    """Bitta tugmaning sozlamalari."""
    node = db.get_node(node_id)
    if not node:
        return v_menu(0)

    is_page = node["kind"] == "page"
    lines = [f"🧩 <b>{esc(node['title'])}</b>", "",
             f"Joyi: {esc(' › '.join(db.node_path(node_id)))}",
             "Turi: " + ("sahifa" if is_page else "bo'lim (ichida tugmalar)"),
             f"Kontent: {ui.describe_content(node['text'], node['media_type'])}"]
    if is_page:
        if node["url"]:
            lines.append(f"Havola: {esc(node['url'])}")
        lines.append("Ariza tugmasi: " + ("✅ bor" if node["lead"] else "— yo'q"))
        if node["lead"]:
            lines.append("Yopiq kanal: " + (f"✅ <code>{node['access_chat_id']}</code>"
                                            if node["access_chat_id"] else "— ulanmagan"))
        total, uniq = db.node_views(node_id)
        lines.append(f"Ko'rishlar: {total} marta ({uniq} kishi)")
    lines.append("Holat: " + ("🙈 yashirilgan" if node["hidden"] else "👁 ko'rinadi"))

    rows = [[btn("✏️ Nomi", f"a:ren:{node_id}"), btn("📝 Kontent", f"a:cont:{node_id}")]]
    if is_page:
        rows.append([btn("🔗 Havola", f"a:url:{node_id}"),
                     btn("📝 Ariza tugmasi: " + ("o'chirish" if node["lead"] else "yoqish"),
                         f"a:lead:{node_id}")])
        if node["lead"]:
            rows.append([btn("🔐 Yopiq kanal (sotuvdan keyin kirish)", f"a:acc:{node_id}")])
    rows.append([btn("⬆️ Yuqoriga", f"a:up:{node_id}"), btn("⬇️ Pastga", f"a:down:{node_id}")])
    if node["parent_id"] is None:
        rows.append([btn(f"↔️ Alohida qatorda: {'✅' if node['wide'] else '—'}",
                         f"a:wide:{node_id}")])
    rows.append([btn("👁 Ko'rsatish" if node["hidden"] else "🙈 Yashirish", f"a:hide:{node_id}"),
                 btn("👀 Ko'rib chiqish", f"a:prev:{node_id}")])
    rows.append([btn("🗑 O'chirish", f"a:del:{node_id}")])
    if is_page:
        rows.append([btn("⬅️ Orqaga", f"a:menu:{node['parent_id'] or 0}")])
    else:
        rows.append([btn("⬅️ Bo'lim ichiga", f"a:menu:{node_id}")])
    return "\n".join(lines), rows


async def a_menu(query, context, args):
    await ui.safe_edit(query, *_kb(v_menu(int(args[0]))))


async def a_node(query, context, args):
    await ui.safe_edit(query, *_kb(v_node(int(args[0]))))


async def a_add(query, context, args):
    parent = int(args[0])
    rows = [
        [btn("📂 Bo'lim — ichida boshqa tugmalar bo'ladi", f"a:new:{parent}:s")],
        [btn("🔗 Havola — video dars, kanal, sayt", f"a:new:{parent}:u")],
        [btn("📄 Sahifa — matn, rasm yoki video", f"a:new:{parent}:p")],
        [btn("💎 Kurs taklifi — «Kursga yozilish» tugmasi bilan", f"a:new:{parent}:o")],
        [btn("⬅️ Orqaga", f"a:menu:{parent}")],
    ]
    await ui.safe_edit(query, "➕ <b>Yangi tugma</b>\n\nQanday tugma qo'shamiz?", kb(rows))


async def a_new(query, context, args):
    parent, kind = int(args[0]), args[1]
    set_state(context, "new_title", parent=parent, t=kind)
    await ui.safe_edit(
        query, f"✏️ Tugma nomini yozing (ko'pi bilan {TITLE_LIMIT} belgi).\n\n"
               "<i>Emoji qo'shsangiz chiroyliroq ko'rinadi, masalan: 📕 10-sinf darsligi</i>",
        kb([[btn("❌ Bekor qilish", f"a:menu:{parent}")]]))


async def a_ren(query, context, args):
    node_id = int(args[0])
    set_state(context, "rename", id=node_id)
    await ui.safe_edit(query, "✏️ Tugmaning yangi nomini yozing:",
                       kb([[btn("❌ Bekor qilish", f"a:node:{node_id}")]]))


async def a_cont(query, context, args):
    node_id = int(args[0])
    node = db.get_node(node_id)
    if not node:
        return "Topilmadi"
    set_state(context, "content", id=node_id)
    if node["kind"] == "section":
        hint = "Bo'lim ochilganda tugmalar ustida ko'rinadigan matnni yuboring."
    else:
        hint = ("Sahifa kontentini bitta xabar qilib yuboring: matn, yoki rasm/video/fayl "
                "(izohi bilan). Matndagi qalin, kursiv, havolalar saqlanadi.")
    await ui.safe_edit(query, f"📝 {hint}\n\n<i>Kontentni o'chirish uchun «-» yuboring.</i>",
                       kb([[btn("❌ Bekor qilish", f"a:node:{node_id}")]]))


async def a_url(query, context, args):
    node_id = int(args[0])
    set_state(context, "url", id=node_id)
    await ui.safe_edit(
        query,
        "🔗 Havolani yuboring.\n\n"
        "Tugma matnini ham bermoqchi bo'lsangiz:\n<code>Tugma matni | https://havola</code>\n\n"
        "<i>Havolani olib tashlash uchun «-» yuboring.</i>",
        kb([[btn("❌ Bekor qilish", f"a:node:{node_id}")]]))


async def a_lead(query, context, args):
    node_id = int(args[0])
    node = db.get_node(node_id)
    if not node or node["kind"] != "page":
        return "Faqat sahifalar uchun"
    db.update_node(node_id, lead=0 if node["lead"] else 1)
    await ui.safe_edit(query, *_kb(v_node(node_id)))
    return "Ariza tugmasi o'chirildi" if node["lead"] else "Ariza tugmasi yoqildi"


async def a_acc(query, context, args):
    node_id = int(args[0])
    set_state(context, "access", id=node_id)
    await ui.safe_edit(
        query,
        "🔐 <b>Yopiq kanalni ulash</b>\n\n"
        "Arizani «💰 Sotilgan» deb belgilaganingizda, bot xaridorga shu kanalga "
        "bir martalik havolani o'zi yuboradi.\n\n"
        "1. Botni o'sha kanalga <b>admin</b> qiling («Foydalanuvchilarni taklif qilish» "
        "huquqi bilan).\n"
        "2. Kanaldagi istalgan postni shu yerga <b>forward</b> qiling "
        "(yoki kanal ID'sini yozing, masalan <code>-1001234567890</code>).\n\n"
        "<i>Uzish uchun «-» yuboring.</i>",
        kb([[btn("❌ Bekor qilish", f"a:node:{node_id}")]]))


async def _toggle(query, node_id, field):
    node = db.get_node(node_id)
    if not node:
        return "Topilmadi"
    db.update_node(node_id, **{field: 0 if node[field] else 1})
    await ui.safe_edit(query, *_kb(v_node(node_id)))


async def a_wide(query, context, args):
    return await _toggle(query, int(args[0]), "wide")


async def a_hide(query, context, args):
    return await _toggle(query, int(args[0]), "hidden")


async def _move(query, node_id, direction):
    if not db.move_node(node_id, direction):
        return "Bundan nariga surib bo'lmaydi"
    await ui.safe_edit(query, *_kb(v_node(node_id)))
    return "Ko'chirildi ✅"


async def a_up(query, context, args):
    return await _move(query, int(args[0]), -1)


async def a_down(query, context, args):
    return await _move(query, int(args[0]), +1)


async def a_prev(query, context, args):
    node = db.get_node(int(args[0]))
    if not node:
        return "Topilmadi"
    await user_side.open_node(context, query.from_user.id, node, track=False)
    return "Foydalanuvchi ko'radigan ko'rinish pastga yuborildi 👇"


async def a_del(query, context, args):
    node_id = int(args[0])
    node = db.get_node(node_id)
    if not node:
        return "Topilmadi"
    nested = db.count_descendants(node_id)
    warn = f"\n\n⚠️ Ichidagi <b>{nested} ta</b> tugma ham o'chadi." if nested else ""
    await ui.safe_edit(
        query, f"🗑 <b>{esc(node['title'])}</b> o'chirilsinmi?{warn}\n\nBu amalni qaytarib bo'lmaydi.",
        kb([[btn("✅ Ha, o'chirish", f"a:delok:{node_id}")],
            [btn("❌ Yo'q", f"a:node:{node_id}")]]))


async def a_delok(query, context, args):
    node = db.get_node(int(args[0]))
    if not node:
        return "Allaqachon o'chirilgan"
    db.delete_node(node["id"])
    await ui.safe_edit(query, *_kb(v_menu(node["parent_id"] or 0)))
    return "O'chirildi"


# --- matn kiritiladigan qadamlar ---------------------------------------------

async def s_new_title(update, context, st):
    parent = st["parent"] or None
    title, error = check_title(update.message.text, parent)
    if error:
        return await reply(update, error)

    if st["t"] == "s":
        node_id = db.create_node(parent, title, "section")
        context.user_data.pop("astate", None)
        return await reply(update, "✅ Bo'lim yaratildi. Endi ichiga tugmalar qo'shing.\n\n"
                                   + v_menu(node_id)[0], v_menu(node_id)[1])
    if st["t"] == "u":
        set_state(context, "new_url", parent=st["parent"], title=title)
        return await reply(update, "🔗 Endi havolani yuboring (masalan YouTube video havolasi):")

    set_state(context, "new_content", parent=st["parent"], title=title, lead=st["t"] == "o")
    await reply(update, "📝 Endi kontentni bitta xabar qilib yuboring: matn, yoki "
                        "rasm/video (izohi bilan).")


async def s_new_url(update, context, st):
    url = clean_url(update.message.text)
    if not url:
        return await reply(update, "❌ Bu havolaga o'xshamaydi. To'liq havolani yuboring, "
                                   "masalan: https://youtu.be/xxxxx")
    node_id = db.create_node(st["parent"] or None, st["title"], "page", url=url)
    context.user_data.pop("astate", None)
    await reply(update, "✅ Tugma qo'shildi.\n\n" + v_node(node_id)[0], v_node(node_id)[1])


async def s_new_content(update, context, st):
    content = ui.extract_content(update.message)
    if not content:
        return await reply(update, "❌ Matn, rasm, video yoki fayl yuboring.")
    node_id = db.create_node(st["parent"] or None, st["title"], "page",
                             lead=1 if st["lead"] else 0, **content)
    context.user_data.pop("astate", None)
    await reply(update, "✅ Tugma qo'shildi.\n\n" + v_node(node_id)[0], v_node(node_id)[1])


async def s_rename(update, context, st):
    node = db.get_node(st["id"])
    if not node:
        context.user_data.pop("astate", None)
        return await reply(update, "❌ Tugma topilmadi.")
    title, error = check_title(update.message.text, node["parent_id"], except_id=node["id"])
    if error:
        return await reply(update, error)
    db.update_node(node["id"], title=title)
    context.user_data.pop("astate", None)
    await reply(update, "✅ Nomi o'zgartirildi.\n\n" + v_node(node["id"])[0], v_node(node["id"])[1])


async def s_content(update, context, st):
    node = db.get_node(st["id"])
    if not node:
        context.user_data.pop("astate", None)
        return await reply(update, "❌ Tugma topilmadi.")

    if (update.message.text or "").strip() == "-":
        db.update_node(node["id"], text=None, media_type=None, media_id=None)
    else:
        content = ui.extract_content(update.message)
        if not content:
            return await reply(update, "❌ Matn, rasm, video yoki fayl yuboring.")
        if node["kind"] == "section" and content["media_type"]:
            return await reply(update, "❌ Bo'lim uchun faqat matn yuborish mumkin.")
        db.update_node(node["id"], **content)
    context.user_data.pop("astate", None)
    await reply(update, "✅ Kontent saqlandi.\n\n" + v_node(node["id"])[0], v_node(node["id"])[1])


async def s_url(update, context, st):
    raw = (update.message.text or "").strip()
    if raw == "-":
        db.update_node(st["id"], url=None, url_label=None)
    else:
        label, _, link = raw.rpartition("|")
        url = clean_url(link)
        if not url:
            return await reply(update, "❌ Bu havolaga o'xshamaydi. Masalan: https://t.me/kanal")
        db.update_node(st["id"], url=url, url_label=label.strip()[:40] or None)
    context.user_data.pop("astate", None)
    await reply(update, "✅ Havola saqlandi.\n\n" + v_node(st["id"])[0], v_node(st["id"])[1])


async def s_access(update, context, st):
    message = update.message
    raw = (message.text or "").strip()

    if raw == "-":
        db.update_node(st["id"], access_chat_id=None)
        context.user_data.pop("astate", None)
        return await reply(update, "✅ Yopiq kanal uzildi.\n\n" + v_node(st["id"])[0],
                           v_node(st["id"])[1])

    origin = getattr(message, "forward_origin", None)
    if origin is not None and getattr(origin, "chat", None) is not None:
        chat_id = origin.chat.id
    elif re.fullmatch(r"-?\d{5,20}", raw):
        chat_id = int(raw)
    else:
        return await reply(update, "❌ Kanaldagi postni forward qiling yoki kanal ID'sini yozing "
                                   "(masalan -1001234567890).")

    # Bot haqiqatan ham havola yarata olishini hoziroq tekshiramiz
    try:
        chat = await context.bot.get_chat(chat_id)
        link = await context.bot.create_chat_invite_link(chat_id, member_limit=1, name="tekshiruv")
        await context.bot.revoke_chat_invite_link(chat_id, link.invite_link)
    except TelegramError as e:
        return await reply(
            update, "❌ Bot bu kanalda havola yarata olmadi.\n\n"
                    f"Xato: <code>{esc(str(e))}</code>\n\n"
                    "Botni kanalga admin qilib, «Foydalanuvchilarni taklif qilish» huquqini "
                    "bering, so'ng qayta urinib ko'ring.")

    db.update_node(st["id"], access_chat_id=chat_id)
    context.user_data.pop("astate", None)
    await reply(update, f"✅ Yopiq kanal ulandi: <b>{esc(chat.title or str(chat_id))}</b>\n\n"
                        + v_node(st["id"])[0], v_node(st["id"])[1])


# ═══════════════════════════════════════════════════════
# 📥 ARIZALAR
# ═══════════════════════════════════════════════════════

def v_leads(status="new", page=0):
    counts = db.lead_counts()
    leads = db.list_leads(status, LEADS_PER_PAGE + 1, page * LEADS_PER_PAGE)
    has_next = len(leads) > LEADS_PER_PAGE
    leads = leads[:LEADS_PER_PAGE]

    text = (f"📥 <b>Arizalar</b> — {ui.STATUS_LABELS[status]}: {counts[status]} ta\n\n"
            + ("Ko'rish uchun arizani tanlang:" if leads else "<i>Bu ro'yxat hozircha bo'sh.</i>"))

    tabs = [btn(("• " if s == status else "") + f"{ui.STATUS_LABELS[s]} ({counts[s]})",
                f"a:leads:{s}:0") for s in db.LEAD_STATUSES]
    rows = [tabs[:2], tabs[2:]]
    for lead in leads:
        name = (lead["full_name"] or "Foydalanuvchi")[:20]
        rows.append([btn(f"{name} · {ui.snippet(lead['node_title'], 22)} · "
                         f"{ui.local_dt(lead['created_at'], '%d.%m')}", f"a:lv:{lead['id']}")])
    nav = []
    if page > 0:
        nav.append(btn("◀️ Oldingi", f"a:leads:{status}:{page - 1}"))
    if has_next:
        nav.append(btn("Keyingi ▶️", f"a:leads:{status}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([btn("⬅️ Panel", "a:home")])
    return text, rows


async def a_leads(query, context, args):
    await ui.safe_edit(query, *_kb(v_leads(args[0], int(args[1]))))


async def a_lv(query, context, args):
    lead = db.get_lead(int(args[0]))
    if not lead:
        return "Ariza topilmadi"
    await ui.safe_edit(query, *ui.lead_card(lead))


async def a_ls(query, context, args):
    """Ariza holatini o'zgartirish. «Sotilgan» bo'lsa — yopiq kanal havolasi yuboriladi."""
    lead_id, status = int(args[0]), args[1]
    lead = db.get_lead(lead_id)
    if not lead or status not in db.LEAD_STATUSES:
        return "Ariza topilmadi"

    db.set_lead_status(lead_id, status)
    note, alert = f"Holat: {ui.STATUS_LABELS[status]}", False
    if status == "sold" and lead["status"] != "sold":
        delivery = await deliver_access(context, lead)
        if delivery:
            note, alert = delivery, True

    text, markup = ui.lead_card(db.get_lead(lead_id))
    await ui.safe_edit(query, text, markup)
    return note, alert


async def deliver_access(context, lead):
    """Xaridorga yopiq kanalga bir martalik havola yuboradi (kurs kanalga ulangan bo'lsa)."""
    node = db.get_node(lead["node_id"]) if lead["node_id"] else None
    if not node or not node["access_chat_id"]:
        return None
    try:
        link = await context.bot.create_chat_invite_link(
            node["access_chat_id"], member_limit=1, name=f"ariza-{lead['id']}"[:32])
        await context.bot.send_message(
            lead["user_id"],
            "🎉 <b>To'lovingiz tasdiqlandi!</b>\n\n"
            f"«{esc(node['title'])}» kursining yopiq kanaliga qo'shilish havolasi "
            "(faqat siz uchun, bir martalik):\n\n"
            f"{link.invite_link}", parse_mode=ui.HTML)
        return "✅ Sotildi. Xaridorga yopiq kanal havolasi yuborildi."
    except TelegramError as e:
        logger.warning("Yopiq kanal havolasi yuborilmadi: %s", e)
        return f"⚠️ Sotildi, lekin havola yuborilmadi: {e}"


# ═══════════════════════════════════════════════════════
# 📊 STATISTIKA
# ═══════════════════════════════════════════════════════

def _pct(part, whole) -> str:
    return f" ({part * 100 / whole:.1f}%)" if whole and part else ""


def v_stats(period="all"):
    days = {"7": 7, "30": 30}.get(period)
    since = db.ago(days=days) if days else None

    c = db.user_counts(ui.local_day_start(0), db.ago(days=7), db.ago(days=30))
    f = db.funnel(since)
    title = {"7": "oxirgi 7 kun", "30": "oxirgi 30 kun"}.get(period, "butun davr")

    lines = [
        "📊 <b>Statistika</b>", "",
        f"👥 Jami foydalanuvchilar: <b>{c['total']}</b>",
        f"   faol: {c['total'] - c['blocked']} · botni bloklagan: {c['blocked']}",
        f"🆕 Bugun: +{c['today']} · 7 kun: +{c['week']} · 30 kun: +{c['month']}", "",
        f"<b>Sotuv voronkasi — {title}</b>",
        f"1. Botga kirgan — <b>{f['users']}</b>",
        f"2. Dars/sahifa ochgan — <b>{f['viewers']}</b>{_pct(f['viewers'], f['users'])}",
        f"3. Kurs taklifini ko'rgan — <b>{f['offer']}</b>{_pct(f['offer'], f['users'])}",
        f"4. Ariza qoldirgan — <b>{f['leads']}</b>{_pct(f['leads'], f['offer'])}",
        f"5. Sotib olgan — <b>{f['sold']}</b>{_pct(f['sold'], f['leads'])}",
    ]

    top = db.top_nodes(5, since)
    if top:
        lines += ["", "<b>Eng ko'p ochilganlar</b>"]
        lines += [f"• {esc(n['title'])} — {n['uniq']} kishi" for n in top]

    sources = [s for s in db.source_stats() if s["code"]][:5]
    if sources:
        lines += ["", "<b>Manbalar</b> (kelgan · ariza · sotuv)"]
        lines += [f"• {esc(s['code'])} — {s['users']} · {s['leads']} · {s['sold']}" for s in sources]

    lines += ["", "<i>Ochishlar va voronka yangi versiya o'rnatilgandan beri hisoblanadi.</i>"]

    periods = [("all", "Butun davr"), ("30", "30 kun"), ("7", "7 kun")]
    rows = [[btn(("• " if p == period else "") + label, f"a:stats:{p}") for p, label in periods],
            [btn("⬅️ Panel", "a:home")]]
    return "\n".join(lines), rows


async def a_stats(query, context, args):
    await ui.safe_edit(query, *_kb(v_stats(args[0] if args else "all")))


# ═══════════════════════════════════════════════════════
# 📢 XABAR YUBORISH
# ═══════════════════════════════════════════════════════

def v_bc():
    rows = [[btn(f"{label} — {db.segment_count(seg)}", f"a:bcs:{seg}")] for seg, label in SEGMENTS]
    for src in db.list_sources():
        seg = "src_" + src["code"]
        rows.append([btn(f"🔗 {src['code']} — {db.segment_count(seg)}", f"a:bcs:{seg}")])
    rows.append([btn("⬅️ Panel", "a:home")])
    return ("📢 <b>Xabar yuborish</b>\n\nKimlarga yuboramiz? "
            "(raqam — botni bloklamagan qabul qiluvchilar soni)"), rows


async def a_bc(query, context, args):
    context.user_data.pop("bc", None)
    await ui.safe_edit(query, *_kb(v_bc()))


async def a_bcs(query, context, args):
    if context.bot_data.get("broadcasting"):
        return "⏳ Oldingi xabar hali yuborilmoqda. U tugashini kuting.", True
    segment = args[0]
    set_state(context, "bc_msg", segment=segment)
    await ui.safe_edit(
        query, f"📢 <b>{esc(segment_label(segment))}</b>\n\n"
               "Yuboriladigan xabarni shu yerga yuboring — matn, rasm, video, istalgan ko'rinishda.",
        kb([[btn("❌ Bekor qilish", "a:bc")]]))


async def s_bc_msg(update, context, st):
    context.user_data["bc"] = {"segment": st["segment"], "chat_id": update.effective_chat.id,
                               "message_id": update.message.message_id, "button": None}
    context.user_data.pop("astate", None)
    await reply(update, "🔘 Xabar ostiga tugma qo'shamizmi?", [
        [btn("➡️ Tugmasiz davom etish", "a:bcb:none")],
        [btn("📄 Bot ichidagi sahifani ochadigan tugma", "a:bcb:node")],
        [btn("🔗 Havola tugmasi", "a:bcb:url")],
        [btn("❌ Bekor qilish", "a:bcx")],
    ])


def draft_markup(draft):
    button = draft.get("button")
    if not button:
        return None
    if button["type"] == "url":
        return kb([[url_btn(button["label"], button["url"])]])
    node = db.get_node(button["id"])
    return kb([[btn(node["title"], f"o:{node['id']}")]]) if node else None


async def confirm_broadcast(context, chat_id):
    """Adminga xabarning aynan qanday ko'rinishini ko'rsatib, tasdiq so'raydi."""
    draft = context.user_data.get("bc")
    if not draft:
        return
    await context.bot.copy_message(chat_id, draft["chat_id"], draft["message_id"],
                                   reply_markup=draft_markup(draft))
    count = db.segment_count(draft["segment"])
    await context.bot.send_message(
        chat_id,
        "👆 Xabar shunday ko'rinadi.\n\n"
        f"Kimga: <b>{esc(segment_label(draft['segment']))}</b>\n"
        f"Qabul qiluvchilar: <b>{count} ta</b>\n\nYuboraymi?",
        parse_mode=ui.HTML,
        reply_markup=kb([[btn(f"✅ Ha, {count} kishiga yuborish", "a:bcgo")],
                         [btn("❌ Bekor qilish", "a:bcx")]]))


async def a_bcb(query, context, args):
    if "bc" not in context.user_data:
        return "Xabar topilmadi, qaytadan boshlang"
    choice = args[0]
    if choice == "none":
        await ui.safe_edit(query, "➡️ Tugmasiz yuboriladi.")
        await confirm_broadcast(context, query.from_user.id)
    elif choice == "url":
        set_state(context, "bc_url")
        await ui.safe_edit(query, "🔗 Tugma matni va havolani shu ko'rinishda yuboring:\n\n"
                                  "<code>Kanalga o'tish | https://t.me/kanal</code>",
                           kb([[btn("❌ Bekor qilish", "a:bcx")]]))
    else:
        rows = picker_rows("a:bcn") + [[btn("❌ Bekor qilish", "a:bcx")]]
        await ui.safe_edit(query, "📄 Tugma qaysi sahifani ochsin?", kb(rows))


async def a_bcn(query, context, args):
    draft = context.user_data.get("bc")
    node = db.get_node(int(args[0]))
    if not draft or not node:
        return "Topilmadi, qaytadan boshlang"
    draft["button"] = {"type": "node", "id": node["id"]}
    await ui.safe_edit(query, f"🔘 Tugma: {esc(node['title'])}")
    await confirm_broadcast(context, query.from_user.id)


async def s_bc_url(update, context, st):
    draft = context.user_data.get("bc")
    label, _, link = (update.message.text or "").rpartition("|")
    url = clean_url(link)
    if not draft or not url or not label.strip():
        return await reply(update, "❌ Shu ko'rinishda yuboring:\n"
                                   "<code>Tugma matni | https://havola</code>")
    draft["button"] = {"type": "url", "label": label.strip()[:40], "url": url}
    context.user_data.pop("astate", None)
    await confirm_broadcast(context, update.effective_chat.id)


async def a_bcx(query, context, args):
    context.user_data.pop("bc", None)
    await ui.safe_edit(query, "❌ Xabar yuborish bekor qilindi.")


async def a_bcgo(query, context, args):
    draft = context.user_data.pop("bc", None)
    if not draft:
        return "Xabar topilmadi, qaytadan boshlang"
    if context.bot_data.get("broadcasting"):
        context.user_data["bc"] = draft
        return "⏳ Oldingi xabar hali yuborilmoqda. U tugashini kuting.", True

    user_ids = db.segment_user_ids(draft["segment"])
    context.bot_data["broadcasting"] = True
    await ui.safe_edit(query, f"⏳ Yuborish boshlandi: {len(user_ids)} kishi...")
    context.application.create_task(
        run_broadcast(context.application, query.from_user.id, draft, user_ids))


async def run_broadcast(app, admin_id, draft, user_ids):
    """Xabarni orqa fonda tarqatadi — bu vaqtda bot boshqalarga javob beraveradi."""
    bot = app.bot
    markup = draft_markup(draft)
    sent = blocked = failed = 0
    status = None
    try:
        status = await bot.send_message(admin_id, f"⏳ 0 / {len(user_ids)}")
        for i, uid in enumerate(user_ids, start=1):
            for attempt in (1, 2):
                try:
                    await bot.copy_message(uid, draft["chat_id"], draft["message_id"],
                                           reply_markup=markup)
                    sent += 1
                except RetryAfter as e:
                    if attempt == 1:
                        await asyncio.sleep(e.retry_after + 1)
                        continue
                    failed += 1
                except Forbidden:
                    db.set_blocked(uid, True)      # botni bloklagan — keyingi safar yuborilmaydi
                    blocked += 1
                except TelegramError:
                    failed += 1
                break
            if i % 200 == 0:
                try:
                    await status.edit_text(f"⏳ {i} / {len(user_ids)}")
                except TelegramError:
                    pass
            await asyncio.sleep(config.BROADCAST_DELAY)
    finally:
        app.bot_data["broadcasting"] = False

    report = (f"📢 <b>Xabar yuborildi!</b>\n\n✅ Yetkazildi: {sent}\n"
              f"🚫 Botni bloklagan: {blocked}\n❌ Xatolik: {failed}")
    try:
        await bot.send_message(admin_id, report, parse_mode=ui.HTML)
    except TelegramError:
        pass


# ═══════════════════════════════════════════════════════
# 🔗 REKLAMA HAVOLALARI
# ═══════════════════════════════════════════════════════

def v_src(bot_username):
    stats = {s["code"]: s for s in db.source_stats()}
    registered = db.list_sources()
    known = {s["code"] for s in registered}

    def numbers(code):
        s = stats.get(code)
        return f"👥 {s['users']} · 📥 {s['leads']} · 💰 {s['sold']}" if s else "👥 0 · 📥 0 · 💰 0"

    lines = ["🔗 <b>Reklama havolalari</b>", "",
             "Har bir reklama uchun alohida havola yarating — qaysi biri mijoz olib "
             "kelayotgani ko'rinadi.", "<i>👥 kelganlar · 📥 arizalar · 💰 sotuvlar</i>"]
    for src in registered:
        target = db.get_node(src["node_id"]) if src["node_id"] else None
        lines += ["", f"<b>{esc(src['code'])}</b> → {esc(target['title']) if target else 'bosh menyu'}",
                  f"<code>https://t.me/{bot_username}?start={src['code']}</code>",
                  numbers(src["code"])]

    others = [c for c in stats if c and c not in known]
    if others:
        lines += ["", "<b>Boshqa kodlar</b>"]
        lines += [f"• {esc(c)} — {numbers(c)}" for c in others[:10]]
    lines += ["", f"Havolasiz kelganlar: {numbers('')}"]

    rows = [[btn("➕ Yangi havola", "a:srcadd")]]
    rows += [[btn(f"🗑 {src['code']}", f"a:srcdel:{src['code']}")] for src in registered]
    rows.append([btn("⬅️ Panel", "a:home")])
    return "\n".join(lines), rows


async def a_src(query, context, args):
    await ui.safe_edit(query, *_kb(v_src(context.bot.username)))


async def a_srcadd(query, context, args):
    set_state(context, "src_code")
    await ui.safe_edit(
        query, "🔗 Havola uchun qisqa kod yozing — faqat lotin harflari, raqamlar, «_» va «-».\n\n"
               "Masalan: <code>instagram</code>, <code>reklama1</code>, <code>kanal_post</code>",
        kb([[btn("❌ Bekor qilish", "a:src")]]))


async def s_src_code(update, context, st):
    code = (update.message.text or "").strip()
    if not CODE_RE.fullmatch(code):
        return await reply(update, "❌ Kod faqat lotin harflari, raqamlar, «_» va «-» dan iborat "
                                   "bo'lsin (32 belgigacha). Masalan: instagram")
    context.user_data.pop("astate", None)
    rows = picker_rows(f"a:srct:{code}", with_home="🏠 Bosh menyu (oddiy /start)")
    await reply(update, f"📄 <b>{esc(code)}</b> havolasi orqali kelgan odamga darhol "
                        "qaysi sahifa ko'rsatilsin?", rows)


async def a_srct(query, context, args):
    code, node_id = args[0], int(args[1])
    db.add_source(code, node_id or None)
    await ui.safe_edit(query, *_kb(v_src(context.bot.username)))
    return "Havola yaratildi ✅"


async def a_srcdel(query, context, args):
    db.delete_source(args[0])
    await ui.safe_edit(query, *_kb(v_src(context.bot.username)))
    return "Havola o'chirildi (statistikasi saqlanadi)"


# ═══════════════════════════════════════════════════════
# 🤖 AVTO-SERIYA
# ═══════════════════════════════════════════════════════

def v_drip():
    steps = db.list_drip()
    text = ("🤖 <b>Avto-seriya</b>\n\n"
            "Yangi foydalanuvchi /start bosgandan keyin belgilangan vaqt o'tgach, bot unga "
            "shu xabarlarni o'zi yuboradi. Masalan: 1 soatdan keyin bepul dars, ertasiga "
            "kurs taklifi.\n\n"
            "<i>Faqat xabar qo'shilgandan keyin kelgan odamlarga ketadi — eski "
            "obunachilarga birdan yog'ilmaydi.</i>")
    rows = [[btn(f"{'✅' if s['active'] else '⏸'} {ui.fmt_delay(s['delay_minutes'])} — "
                 f"{ui.snippet(s['text'], 24) or ui.MEDIA_LABELS.get(s['media_type'], 'xabar')}",
                 f"a:dripv:{s['id']}")] for s in steps]
    rows.append([btn("➕ Xabar qo'shish", "a:dripadd")])
    rows.append([btn("⬅️ Panel", "a:home")])
    return text, rows


def v_dripv(step_id):
    step = db.get_drip(step_id)
    if not step:
        return v_drip()
    node = db.get_node(step["node_id"]) if step["node_id"] else None
    text = "\n".join([
        "🤖 <b>Avto-seriya xabari</b>", "",
        f"⏱ /start'dan keyin: <b>{ui.fmt_delay(step['delay_minutes'])}</b>",
        f"📝 Kontent: {ui.describe_content(step['text'], step['media_type'])}",
        "🔘 Tugma: " + (esc(node["title"]) if node else "— yo'q"),
        f"📨 Yuborilgan: {db.drip_sent_count(step_id)} kishiga",
        "Holat: " + ("✅ ishlayapti" if step["active"] else "⏸ to'xtatilgan"),
    ])
    rows = [
        [btn("👀 Ko'rib chiqish", f"a:dripp:{step_id}"), btn("🔘 Tugma biriktirish", f"a:dripb:{step_id}")],
        [btn("⏸ To'xtatish" if step["active"] else "▶️ Yoqish", f"a:dript:{step_id}"),
         btn("🗑 O'chirish", f"a:dripdel:{step_id}")],
        [btn("⬅️ Orqaga", "a:drip")],
    ]
    return text, rows


async def send_drip_step(bot, chat_id, step):
    node = db.get_node(step["node_id"]) if step["node_id"] else None
    markup = kb([[btn(node["title"], f"o:{node['id']}")]]) if node and not node["hidden"] else None
    await ui.send_content(bot, chat_id, step["text"], step["media_type"], step["media_id"],
                          reply_markup=markup)


async def drip_tick(bot):
    """Vaqti kelgan avto-seriya xabarlarini yuboradi (har daqiqada chaqiriladi)."""
    for step in db.list_drip():
        if not step["active"]:
            continue
        for uid in db.drip_due(step):
            status = "ok"
            try:
                await send_drip_step(bot, uid, step)
            except Forbidden:
                db.set_blocked(uid, True)
                status = "blocked"
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                continue                    # yozib qo'ymaymiz — keyingi safar qayta urinadi
            except TelegramError as e:
                logger.warning("Avto-seriya xabari yuborilmadi (%s): %s", uid, e)
                status = "error"
            db.log_drip(uid, step["id"], status)
            await asyncio.sleep(config.BROADCAST_DELAY)


async def a_drip(query, context, args):
    await ui.safe_edit(query, *_kb(v_drip()))


async def a_dripv(query, context, args):
    await ui.safe_edit(query, *_kb(v_dripv(int(args[0]))))


async def a_dripadd(query, context, args):
    set_state(context, "drip_delay")
    await ui.safe_edit(
        query, "⏱ /start'dan qancha vaqt o'tgach yuborilsin?\n\n"
               "Masalan: <code>30 daqiqa</code>, <code>2 soat</code>, <code>1 kun</code>",
        kb([[btn("❌ Bekor qilish", "a:drip")]]))


async def s_drip_delay(update, context, st):
    minutes = ui.parse_delay(update.message.text)
    if minutes is None:
        return await reply(update, "❌ Tushunmadim. Shu ko'rinishda yozing: "
                                   "<code>30 daqiqa</code>, <code>2 soat</code> yoki <code>1 kun</code>")
    set_state(context, "drip_content", delay=minutes)
    await reply(update, f"📝 Endi <b>{ui.fmt_delay(minutes)}</b>dan keyin yuboriladigan xabarni "
                        "yuboring: matn, yoki rasm/video (izohi bilan).")


async def s_drip_content(update, context, st):
    content = ui.extract_content(update.message)
    if not content:
        return await reply(update, "❌ Matn, rasm, video yoki fayl yuboring.")
    step_id = db.add_drip(st["delay"], content["text"], content["media_type"], content["media_id"])
    context.user_data.pop("astate", None)
    await reply(update, "✅ Xabar avto-seriyaga qo'shildi.\n\n" + v_dripv(step_id)[0],
                v_dripv(step_id)[1])


async def a_dripp(query, context, args):
    step = db.get_drip(int(args[0]))
    if not step:
        return "Topilmadi"
    await send_drip_step(context.bot, query.from_user.id, step)
    return "Ko'rinishi pastga yuborildi 👇"


async def a_dripb(query, context, args):
    step_id = int(args[0])
    rows = picker_rows(f"a:dripn:{step_id}", with_home="🚫 Tugmasiz")
    rows.append([btn("⬅️ Orqaga", f"a:dripv:{step_id}")])
    await ui.safe_edit(query, "🔘 Xabar ostidagi tugma qaysi sahifani ochsin?", kb(rows))


async def a_dripn(query, context, args):
    step_id, node_id = int(args[0]), int(args[1])
    db.update_drip(step_id, node_id=node_id or None)
    await ui.safe_edit(query, *_kb(v_dripv(step_id)))
    return "Saqlandi ✅"


async def a_dript(query, context, args):
    step = db.get_drip(int(args[0]))
    if not step:
        return "Topilmadi"
    db.update_drip(step["id"], active=0 if step["active"] else 1)
    await ui.safe_edit(query, *_kb(v_dripv(step["id"])))


async def a_dripdel(query, context, args):
    db.delete_drip(int(args[0]))
    await ui.safe_edit(query, *_kb(v_drip()))
    return "O'chirildi"


# ═══════════════════════════════════════════════════════
# ⚙️ SOZLAMALAR
# ═══════════════════════════════════════════════════════

def v_set():
    gate_on = db.get_setting("gate_enabled", "1") == "1"
    channel = user_side.gate_channel() or "—"
    text = "\n".join([
        "⚙️ <b>Sozlamalar</b>", "",
        "📢 Majburiy obuna: " + ("✅ yoqilgan" if gate_on else "— o'chirilgan"),
        f"   Kanal: {esc(channel)}", "",
        f"👋 Salomlashuv: <i>{esc(ui.snippet(db.get_setting('welcome', config.DEFAULT_WELCOME), 70))}</i>",
        f"✅ Ariza javobi: <i>{esc(ui.snippet(db.get_setting('lead_text', config.DEFAULT_LEAD_TEXT), 70))}</i>",
        "", f"👮 Adminlar: <code>{', '.join(map(str, config.ADMIN_IDS))}</code>",
        "<i>(adminlar ro'yxati Railway'dagi ADMIN_IDS o'zgaruvchisi orqali o'zgaradi)</i>",
    ])
    rows = [
        [btn("📢 Majburiy obunani " + ("o'chirish" if gate_on else "yoqish"), "a:setgate")],
        [btn("✏️ Kanalni o'zgartirish", "a:setch")],
        [btn("👋 Salomlashuv matni", "a:setwel"), btn("✅ Ariza javobi matni", "a:setlead")],
        [btn("⬅️ Panel", "a:home")],
    ]
    return text, rows


async def a_set(query, context, args):
    await ui.safe_edit(query, *_kb(v_set()))


async def a_setgate(query, context, args):
    on = db.get_setting("gate_enabled", "1") == "1"
    db.set_setting("gate_enabled", "0" if on else "1")
    await ui.safe_edit(query, *_kb(v_set()))


async def a_setch(query, context, args):
    set_state(context, "set_channel")
    await ui.safe_edit(query, "📢 Kanal username'ini yuboring, masalan: <code>@ikramov_biologiya</code>\n\n"
                              "<i>Bot shu kanalda admin bo'lishi kerak, aks holda obunani "
                              "tekshira olmaydi.</i>", kb([[btn("❌ Bekor qilish", "a:set")]]))


async def a_setwel(query, context, args):
    set_state(context, "set_text", key="welcome")
    await ui.safe_edit(query, "👋 Yangi salomlashuv matnini yuboring.\n\n"
                              "<i>{name} yozsangiz, o'rniga foydalanuvchining ismi qo'yiladi.</i>",
                       kb([[btn("❌ Bekor qilish", "a:set")]]))


async def a_setlead(query, context, args):
    set_state(context, "set_text", key="lead_text")
    await ui.safe_edit(query, "✅ Ariza qoldirgan odamga ko'rsatiladigan matnni yuboring:",
                       kb([[btn("❌ Bekor qilish", "a:set")]]))


async def s_set_channel(update, context, st):
    channel = (update.message.text or "").strip()
    if not CHANNEL_RE.fullmatch(channel):
        return await reply(update, "❌ Username @ bilan boshlansin, masalan: @ikramov_biologiya")

    warning = ""
    try:
        await context.bot.get_chat_member(channel, context.bot.id)
    except TelegramError as e:
        warning = (f"\n\n⚠️ Diqqat: bot bu kanalni tekshira olmadi (<code>{esc(str(e))}</code>). "
                   "Botni kanalga admin qilib qo'shing.")
    db.set_setting("gate_channel", channel)
    context.user_data.pop("astate", None)
    await reply(update, f"✅ Kanal saqlandi: {esc(channel)}{warning}\n\n" + v_set()[0], v_set()[1])


async def s_set_text(update, context, st):
    if not update.message.text:
        return await reply(update, "❌ Matn yuboring.")
    db.set_setting(st["key"], update.message.text_html)
    context.user_data.pop("astate", None)
    await reply(update, "✅ Matn saqlandi.\n\n" + v_set()[0], v_set()[1])


# ═══════════════════════════════════════════════════════
# 📤 EKSPORT, ZAXIRA, IMPORT
# ═══════════════════════════════════════════════════════

def v_exp():
    rows = [
        [btn("👥 Foydalanuvchilar (CSV)", "a:expu"), btn("📥 Arizalar (CSV)", "a:expl")],
        [btn("💾 Bazaning to'liq zaxirasi", "a:bak")],
        [btn("📥 CSV'dan foydalanuvchilarni tiklash", "a:imp")],
        [btn("⬅️ Panel", "a:home")],
    ]
    return ("📤 <b>Eksport va zaxira</b>\n\n"
            "CSV fayllar Excel yoki Google Sheets'da ochiladi.\n"
            "Zaxira — botdagi hamma narsa (menyu, foydalanuvchilar, arizalar) bitta faylda. "
            "Oyda bir marta olib qo'yishni tavsiya qilaman."), rows


async def a_exp(query, context, args):
    await ui.safe_edit(query, *_kb(v_exp()))


def _csv_bytes(header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")      # Excel o'zbekcha harflarni to'g'ri o'qishi uchun


async def a_expu(query, context, args):
    users = db.all_users()
    data = _csv_bytes(
        ["Telegram ID", "Username", "Ism", "F.I.Sh", "Telefon", "Viloyat/tuman", "Manba",
         "Qo'shilgan sana", "Botni bloklagan"],
        [[u["id"], u["username"] or "", u["full_name"] or "", u["reg_name"] or "",
          u["phone"] or "", u["region"] or "", u["source"] or "",
          ui.local_dt(u["joined_at"], "%Y-%m-%d %H:%M") if u["joined_at"] else "",
          "ha" if u["blocked"] else ""] for u in users])
    await context.bot.send_document(query.from_user.id, document=data,
                                    filename="foydalanuvchilar.csv",
                                    caption=f"👥 Jami: {len(users)} ta")


async def a_expl(query, context, args):
    leads = db.all_leads()
    if not leads:
        return "Hali arizalar yo'q", True
    data = _csv_bytes(
        ["№", "Sana", "Ism", "Username", "Telefon", "Kurs", "Holat", "Manba", "Telegram ID"],
        [[l["id"], ui.local_dt(l["created_at"], "%Y-%m-%d %H:%M"), l["full_name"] or "",
          l["username"] or "", l["phone"] or "", l["node_title"] or "",
          ui.STATUS_LABELS.get(l["status"], l["status"]), l["source"] or "", l["user_id"]]
         for l in leads])
    await context.bot.send_document(query.from_user.id, document=data, filename="arizalar.csv",
                                    caption=f"📥 Jami: {len(leads)} ta ariza")


async def a_bak(query, context, args):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db.backup_to(path)
        with open(path, "rb") as f:
            await context.bot.send_document(
                query.from_user.id, document=f, filename="bot_zaxira.db",
                caption="💾 Bazaning to'liq zaxirasi. Shu faylni saqlab qo'ying.")
    finally:
        os.remove(path)


async def a_imp(query, context, args):
    set_state(context, "import")
    await ui.safe_edit(query, "📥 Foydalanuvchilar CSV faylini yuboring "
                              "(avval shu botdan eksport qilingan fayl).",
                       kb([[btn("❌ Bekor qilish", "a:exp")]]))


async def s_import(update, context, st):
    document = update.message.document
    if not document:
        return await reply(update, "❌ CSV faylni fayl (document) ko'rinishida yuboring.")
    try:
        tg_file = await context.bot.get_file(document.file_id)
        raw = bytes(await tg_file.download_as_bytearray())
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        added = updated = 0
        for row in reader:
            uid = (row.get("Telegram ID") or row.get("id") or "").strip()
            if not uid.isdigit():
                continue
            joined = (row.get("Ro'yxatdan o'tgan sana") or "").strip()[:19].replace("T", " ")
            is_new = db.import_user(
                int(uid),
                full_name=(row.get("F.I.Sh") or row.get("Ism") or "").strip(),
                phone=(row.get("Telefon") or "").strip(),
                region=(row.get("Viloyat/tuman") or "").strip(),
                joined_at=joined or None)
            added += is_new
            updated += not is_new
    except Exception:
        logger.exception("CSV import xatoligi")
        return await reply(update, "❌ Faylni o'qib bo'lmadi. To'g'ri CSV ekanini tekshiring.")

    context.user_data.pop("astate", None)
    await reply(update, f"✅ <b>Import tugadi</b>\n\nYangi qo'shildi: {added}\n"
                        f"Yangilandi: {updated}")


# ═══════════════════════════════════════════════════════
# 🔀 MARSHRUTLASH
# ═══════════════════════════════════════════════════════

ROUTES = {
    "home": a_home,
    "menu": a_menu, "node": a_node, "add": a_add, "new": a_new, "ren": a_ren, "cont": a_cont,
    "url": a_url, "lead": a_lead, "acc": a_acc, "wide": a_wide, "hide": a_hide,
    "up": a_up, "down": a_down, "prev": a_prev, "del": a_del, "delok": a_delok,
    "leads": a_leads, "lv": a_lv, "ls": a_ls,
    "stats": a_stats,
    "bc": a_bc, "bcs": a_bcs, "bcb": a_bcb, "bcn": a_bcn, "bcx": a_bcx, "bcgo": a_bcgo,
    "src": a_src, "srcadd": a_srcadd, "srct": a_srct, "srcdel": a_srcdel,
    "drip": a_drip, "dripv": a_dripv, "dripadd": a_dripadd, "dripp": a_dripp,
    "dripb": a_dripb, "dripn": a_dripn, "dript": a_dript, "dripdel": a_dripdel,
    "set": a_set, "setgate": a_setgate, "setch": a_setch, "setwel": a_setwel, "setlead": a_setlead,
    "exp": a_exp, "expu": a_expu, "expl": a_expl, "bak": a_bak, "imp": a_imp,
}

STATE_HANDLERS = {
    "new_title": s_new_title, "new_url": s_new_url, "new_content": s_new_content,
    "rename": s_rename, "content": s_content, "url": s_url, "access": s_access,
    "bc_msg": s_bc_msg, "bc_url": s_bc_url,
    "src_code": s_src_code,
    "drip_delay": s_drip_delay, "drip_content": s_drip_content,
    "set_channel": s_set_channel, "set_text": s_set_text,
    "import": s_import,
}


async def cb_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Paneldagi barcha tugmalar shu yerdan o'tadi.
    Amal funksiyasi hech narsa qaytarmasa — jimgina javob beriladi; matn qaytarsa —
    tepada qisqa bildirishnoma; (matn, True) qaytarsa — oynacha (alert) chiqadi.
    """
    query = update.callback_query
    if not ui.is_admin(query.from_user.id):
        await query.answer("⛔ Bu tugma faqat admin uchun.", show_alert=True)
        return

    parts = query.data.split(":")
    handler = ROUTES.get(parts[1]) if len(parts) > 1 else None
    context.user_data.pop("astate", None)     # yangi tugma — oldingi kiritish qadami bekor

    result = None
    if handler:
        try:
            result = await handler(query, context, parts[2:])
        except (ValueError, IndexError):
            logger.exception("Admin tugmasini bajarib bo'lmadi: %s", query.data)
            result = ("Tugma eskirgan. /admin ni qayta oching.", True)

    text, alert = (result if isinstance(result, tuple) else (result, False))
    try:
        await query.answer(text, show_alert=alert)
    except BadRequest:
        pass


async def handle_state_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Admin biror qadamda matn/fayl kiritayotgan bo'lsa — qabul qiladi va True qaytaradi."""
    st = context.user_data.get("astate")
    handler = STATE_HANDLERS.get(st["name"]) if st else None
    if not handler:
        return False
    await handler(update, context, st)
    return True
