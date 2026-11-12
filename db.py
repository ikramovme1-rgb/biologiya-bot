"""
🗄️ Ma'lumotlar bazasi (SQLite).

Baza bitta faylda (data/bot.db) turadi — Railway Volume'da saqlangani uchun
qayta deploy qilinganda o'chmaydi. Barcha vaqtlar UTC'da, "YYYY-MM-DD HH:MM:SS"
ko'rinishida saqlanadi.
"""

import html
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,      -- Telegram ID
    username    TEXT,
    full_name   TEXT,
    phone       TEXT,
    reg_name    TEXT,                     -- eski ro'yxatdan o'tishda yozilgan F.I.Sh
    region      TEXT,
    source      TEXT,                     -- qaysi reklama havolasidan kelgan
    joined_at   TEXT,                     -- eski foydalanuvchilarda bo'sh bo'lishi mumkin
    last_seen   TEXT,
    blocked     INTEGER NOT NULL DEFAULT 0
);

-- Menyu daraxti: bosh menyu tugmalari (parent_id NULL) va ularning ichidagilar
CREATE TABLE IF NOT EXISTS nodes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id      INTEGER REFERENCES nodes(id) ON DELETE CASCADE,
    title          TEXT NOT NULL,
    kind           TEXT NOT NULL,         -- 'section' (bo'lim) | 'page' (sahifa)
    text           TEXT,                  -- HTML
    media_type     TEXT,                  -- photo | video | document | animation
    media_id       TEXT,                  -- Telegram file_id
    url            TEXT,
    url_label      TEXT,
    lead           INTEGER NOT NULL DEFAULT 0,   -- "Kursga yozilish" tugmasi
    access_chat_id INTEGER,               -- sotilganda havola beriladigan yopiq kanal
    wide           INTEGER NOT NULL DEFAULT 0,   -- bosh menyuda alohida qatorda turadi
    hidden         INTEGER NOT NULL DEFAULT 0,
    position       INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id, position);

CREATE TABLE IF NOT EXISTS leads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    node_id     INTEGER,
    node_title  TEXT,
    phone       TEXT,
    status      TEXT NOT NULL DEFAULT 'new',     -- new | contacted | sold | rejected
    created_at  TEXT,
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status, id);
CREATE INDEX IF NOT EXISTS idx_leads_user ON leads(user_id);

-- Voronka va segmentlar uchun hodisalar: start | view | offer_view
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    type        TEXT NOT NULL,
    node_id     INTEGER,
    created_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type, created_at);
CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id, type);
CREATE INDEX IF NOT EXISTS idx_events_node ON events(node_id);

CREATE TABLE IF NOT EXISTS sources (
    code        TEXT PRIMARY KEY,
    node_id     INTEGER,                  -- havola ochilganda ko'rsatiladigan sahifa
    created_at  TEXT
);

-- Avto-seriya: /start'dan keyin belgilangan vaqt o'tgach yuboriladigan xabarlar
CREATE TABLE IF NOT EXISTS drip_steps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    delay_minutes INTEGER NOT NULL,
    text          TEXT,
    media_type    TEXT,
    media_id      TEXT,
    node_id       INTEGER,                -- xabar ostidagi tugma ochadigan sahifa
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT
);
CREATE TABLE IF NOT EXISTS drip_log (
    user_id  INTEGER NOT NULL,
    step_id  INTEGER NOT NULL,
    status   TEXT,
    sent_at  TEXT,
    PRIMARY KEY (user_id, step_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT
);
"""

LEAD_STATUSES = ("new", "contacted", "sold", "rejected")


# ═══════════════════════════════════════════════════════
# 🔌 ULANISH
# ═══════════════════════════════════════════════════════

def init(db_path: str):
    global _conn
    folder = os.path.dirname(db_path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    _conn = sqlite3.connect(db_path)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA foreign_keys=ON")
    _conn.executescript(SCHEMA)
    _conn.commit()


def close():
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def backup_to(path: str):
    """Bazaning to'liq, izchil nusxasini boshqa faylga yozadi (zaxira uchun)."""
    target = sqlite3.connect(path)
    try:
        _conn.backup(target)
    finally:
        target.close()


def _q(sql, params=()):
    return _conn.execute(sql, params).fetchall()


def _one(sql, params=()):
    return _conn.execute(sql, params).fetchone()


def _x(sql, params=()):
    cur = _conn.execute(sql, params)
    _conn.commit()
    return cur


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def ago(**kwargs) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kwargs)).strftime("%Y-%m-%d %H:%M:%S")


# ═══════════════════════════════════════════════════════
# ⚙️ SOZLAMALAR
# ═══════════════════════════════════════════════════════

def get_setting(key, default=None):
    row = _one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


def set_setting(key, value):
    _x("INSERT INTO settings(key, value) VALUES(?, ?) "
       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


# ═══════════════════════════════════════════════════════
# 👥 FOYDALANUVCHILAR
# ═══════════════════════════════════════════════════════

def upsert_user(user_id, username, full_name, source=None) -> bool:
    """Foydalanuvchini yozadi yoki yangilaydi. Yangi bo'lsa True qaytaradi."""
    ts = now()
    if _one("SELECT 1 FROM users WHERE id=?", (user_id,)):
        _x("UPDATE users SET username=?, full_name=?, last_seen=?, blocked=0 WHERE id=?",
           (username, full_name, ts, user_id))
        return False
    _x("INSERT INTO users(id, username, full_name, source, joined_at, last_seen) "
       "VALUES(?, ?, ?, ?, ?, ?)", (user_id, username, full_name, source, ts, ts))
    return True


def get_user(user_id):
    return _one("SELECT * FROM users WHERE id=?", (user_id,))


def set_user_phone(user_id, phone):
    _x("UPDATE users SET phone=? WHERE id=?", (phone, user_id))


def set_blocked(user_id, blocked: bool):
    _x("UPDATE users SET blocked=? WHERE id=?", (1 if blocked else 0, user_id))


def all_users():
    return _q("SELECT * FROM users ORDER BY joined_at IS NULL, joined_at, id")


def import_user(user_id, full_name=None, phone=None, region=None, joined_at=None):
    """CSV yoki eski fayllardan foydalanuvchini qo'shadi; bor ma'lumotni buzmaydi."""
    if _one("SELECT 1 FROM users WHERE id=?", (user_id,)):
        _x("UPDATE users SET reg_name=COALESCE(NULLIF(?, ''), reg_name), "
           "phone=COALESCE(NULLIF(?, ''), phone), region=COALESCE(NULLIF(?, ''), region) "
           "WHERE id=?", (full_name, phone, region, user_id))
        return False
    _x("INSERT INTO users(id, full_name, reg_name, phone, region, joined_at) "
       "VALUES(?, ?, ?, ?, ?, ?)",
       (user_id, full_name, full_name, phone or None, region or None, joined_at or None))
    return True


# ═══════════════════════════════════════════════════════
# 🧩 MENYU DARAXTI
# ═══════════════════════════════════════════════════════

NODE_FIELDS = {"title", "kind", "text", "media_type", "media_id", "url", "url_label",
               "lead", "access_chat_id", "wide", "hidden", "position", "parent_id"}


def get_node(node_id):
    return _one("SELECT * FROM nodes WHERE id=?", (node_id,))


def children(parent_id, include_hidden=False):
    sql = "SELECT * FROM nodes WHERE parent_id IS ?"
    if not include_hidden:
        sql += " AND hidden=0"
    return _q(sql + " ORDER BY position, id", (parent_id,))


def find_root_by_title(title):
    return _one("SELECT * FROM nodes WHERE parent_id IS NULL AND hidden=0 AND title=?", (title,))


def root_title_taken(title, except_id=None):
    row = _one("SELECT id FROM nodes WHERE parent_id IS NULL AND title=?", (title,))
    return bool(row) and row["id"] != except_id


def create_node(parent_id, title, kind, **fields):
    pos = _one("SELECT COALESCE(MAX(position), 0) + 1 AS p FROM nodes WHERE parent_id IS ?",
               (parent_id,))["p"]
    data = {"parent_id": parent_id, "title": title, "kind": kind,
            "position": pos, "created_at": now()}
    data.update({k: v for k, v in fields.items() if k in NODE_FIELDS})
    cols = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    return _x(f"INSERT INTO nodes({cols}) VALUES({marks})", tuple(data.values())).lastrowid


def update_node(node_id, **fields):
    fields = {k: v for k, v in fields.items() if k in NODE_FIELDS}
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    _x(f"UPDATE nodes SET {sets} WHERE id=?", (*fields.values(), node_id))


def delete_node(node_id):
    _x("DELETE FROM nodes WHERE id=?", (node_id,))


def count_descendants(node_id) -> int:
    return _one(
        "WITH RECURSIVE sub(id) AS (SELECT id FROM nodes WHERE parent_id=? "
        "UNION ALL SELECT n.id FROM nodes n JOIN sub ON n.parent_id=sub.id) "
        "SELECT COUNT(*) AS c FROM sub", (node_id,))["c"]


def move_node(node_id, direction: int) -> bool:
    """Tugmani qo'shnisi bilan almashtiradi (direction: -1 yuqoriga, +1 pastga)."""
    node = get_node(node_id)
    if not node:
        return False
    siblings = children(node["parent_id"], include_hidden=True)
    ids = [s["id"] for s in siblings]
    i = ids.index(node_id)
    j = i + direction
    if j < 0 or j >= len(ids):
        return False
    ids[i], ids[j] = ids[j], ids[i]
    for pos, nid in enumerate(ids, start=1):
        _conn.execute("UPDATE nodes SET position=? WHERE id=?", (pos, nid))
    _conn.commit()
    return True


def node_path(node_id):
    """Bosh menyudan shu tugmagacha bo'lgan nomlar ro'yxati."""
    titles = []
    node = get_node(node_id)
    while node:
        titles.append(node["title"])
        node = get_node(node["parent_id"]) if node["parent_id"] else None
    return list(reversed(titles))


def offer_nodes():
    return _q("SELECT * FROM nodes WHERE lead=1 ORDER BY position, id")


def count_nodes() -> int:
    return _one("SELECT COUNT(*) AS c FROM nodes")["c"]


# ═══════════════════════════════════════════════════════
# 📊 HODISALAR VA STATISTIKA
# ═══════════════════════════════════════════════════════

def add_event(user_id, event_type, node_id=None):
    _x("INSERT INTO events(user_id, type, node_id, created_at) VALUES(?, ?, ?, ?)",
       (user_id, event_type, node_id, now()))


def node_views(node_id):
    row = _one("SELECT COUNT(*) AS total, COUNT(DISTINCT user_id) AS uniq FROM events "
               "WHERE node_id=? AND type IN ('view', 'offer_view')", (node_id,))
    return row["total"], row["uniq"]


def user_counts(today_start, week_start, month_start):
    row = _one(
        "SELECT COUNT(*) AS total, SUM(blocked) AS blocked, "
        "SUM(joined_at >= ?) AS today, SUM(joined_at >= ?) AS week, SUM(joined_at >= ?) AS month "
        "FROM users", (today_start, week_start, month_start))
    return {k: (row[k] or 0) for k in ("total", "blocked", "today", "week", "month")}


def funnel(since=None):
    """Voronka bosqichlari: kirgan → kontent ko'rgan → taklif ko'rgan → ariza → sotuv."""
    if since:
        return {
            "users": _one("SELECT COUNT(*) AS c FROM users WHERE joined_at >= ?", (since,))["c"],
            "viewers": _one("SELECT COUNT(DISTINCT user_id) AS c FROM events "
                            "WHERE type IN ('view','offer_view') AND created_at >= ?", (since,))["c"],
            "offer": _one("SELECT COUNT(DISTINCT user_id) AS c FROM events "
                          "WHERE type='offer_view' AND created_at >= ?", (since,))["c"],
            "leads": _one("SELECT COUNT(DISTINCT user_id) AS c FROM leads "
                          "WHERE created_at >= ?", (since,))["c"],
            "sold": _one("SELECT COUNT(DISTINCT user_id) AS c FROM leads "
                         "WHERE status='sold' AND updated_at >= ?", (since,))["c"],
        }
    return {
        "users": _one("SELECT COUNT(*) AS c FROM users")["c"],
        "viewers": _one("SELECT COUNT(DISTINCT user_id) AS c FROM events "
                        "WHERE type IN ('view','offer_view')")["c"],
        "offer": _one("SELECT COUNT(DISTINCT user_id) AS c FROM events "
                      "WHERE type='offer_view'")["c"],
        "leads": _one("SELECT COUNT(DISTINCT user_id) AS c FROM leads")["c"],
        "sold": _one("SELECT COUNT(DISTINCT user_id) AS c FROM leads WHERE status='sold'")["c"],
    }


def top_nodes(limit=5, since=None):
    sql = ("SELECT n.id, n.title, COUNT(DISTINCT e.user_id) AS uniq FROM events e "
           "JOIN nodes n ON n.id = e.node_id WHERE e.type IN ('view','offer_view')")
    params = []
    if since:
        sql += " AND e.created_at >= ?"
        params.append(since)
    sql += " GROUP BY n.id ORDER BY uniq DESC, n.id LIMIT ?"
    params.append(limit)
    return _q(sql, params)


def source_stats():
    """Har bir manba bo'yicha: kelganlar, arizalar, sotuvlar."""
    return _q(
        "SELECT COALESCE(u.source, '') AS code, COUNT(*) AS users, "
        "COUNT(DISTINCT l.user_id) AS leads, "
        "COUNT(DISTINCT CASE WHEN l.status='sold' THEN l.user_id END) AS sold "
        "FROM users u LEFT JOIN leads l ON l.user_id = u.id "
        "GROUP BY COALESCE(u.source, '') ORDER BY users DESC")


# ═══════════════════════════════════════════════════════
# 🔗 REKLAMA HAVOLALARI
# ═══════════════════════════════════════════════════════

def add_source(code, node_id=None):
    _x("INSERT INTO sources(code, node_id, created_at) VALUES(?, ?, ?) "
       "ON CONFLICT(code) DO UPDATE SET node_id=excluded.node_id", (code, node_id, now()))


def get_source(code):
    return _one("SELECT * FROM sources WHERE code=?", (code,))


def list_sources():
    return _q("SELECT * FROM sources ORDER BY created_at")


def delete_source(code):
    _x("DELETE FROM sources WHERE code=?", (code,))


# ═══════════════════════════════════════════════════════
# 📥 ARIZALAR
# ═══════════════════════════════════════════════════════

def create_lead(user_id, node_id, node_title, phone):
    ts = now()
    return _x("INSERT INTO leads(user_id, node_id, node_title, phone, created_at, updated_at) "
              "VALUES(?, ?, ?, ?, ?, ?)", (user_id, node_id, node_title, phone, ts, ts)).lastrowid


def open_lead(user_id, node_id):
    """Shu foydalanuvchining shu kurs bo'yicha hali yopilmagan arizasi."""
    return _one("SELECT * FROM leads WHERE user_id=? AND node_id IS ? "
                "AND status IN ('new', 'contacted') ORDER BY id DESC", (user_id, node_id))


def get_lead(lead_id):
    return _one(
        "SELECT l.*, u.username, u.full_name, u.reg_name, u.region, u.source "
        "FROM leads l LEFT JOIN users u ON u.id = l.user_id WHERE l.id=?", (lead_id,))


def set_lead_status(lead_id, status):
    _x("UPDATE leads SET status=?, updated_at=? WHERE id=?", (status, now(), lead_id))


def list_leads(status, limit, offset):
    return _q(
        "SELECT l.*, u.full_name, u.username FROM leads l LEFT JOIN users u ON u.id = l.user_id "
        "WHERE l.status=? ORDER BY l.id DESC LIMIT ? OFFSET ?", (status, limit, offset))


def lead_counts():
    counts = {s: 0 for s in LEAD_STATUSES}
    for row in _q("SELECT status, COUNT(*) AS c FROM leads GROUP BY status"):
        counts[row["status"]] = row["c"]
    return counts


def all_leads():
    return _q(
        "SELECT l.*, u.full_name, u.username, u.source FROM leads l "
        "LEFT JOIN users u ON u.id = l.user_id ORDER BY l.id")


# ═══════════════════════════════════════════════════════
# 🎯 SEGMENTLAR (xabar yuborish uchun)
# ═══════════════════════════════════════════════════════

def _segment_sql(segment):
    base = "SELECT id FROM users WHERE blocked=0"
    if segment == "all":
        return base, ()
    if segment == "new7":
        return base + " AND joined_at >= ?", (ago(days=7),)
    if segment == "offer_no_lead":
        return (base + " AND id IN (SELECT user_id FROM events WHERE type='offer_view') "
                       "AND id NOT IN (SELECT user_id FROM leads)"), ()
    if segment == "leads":
        return base + " AND id IN (SELECT user_id FROM leads WHERE status IN ('new','contacted'))", ()
    if segment == "buyers":
        return base + " AND id IN (SELECT user_id FROM leads WHERE status='sold')", ()
    if segment == "cold":
        return (base + " AND id NOT IN (SELECT user_id FROM events "
                       "WHERE type IN ('view','offer_view')) "
                       "AND id NOT IN (SELECT user_id FROM leads)"), ()
    if segment.startswith("src_"):
        return base + " AND source=?", (segment[4:],)
    raise ValueError(f"Noma'lum segment: {segment}")


def segment_user_ids(segment):
    sql, params = _segment_sql(segment)
    return [r["id"] for r in _q(sql, params)]


def segment_count(segment) -> int:
    sql, params = _segment_sql(segment)
    return _one(f"SELECT COUNT(*) AS c FROM ({sql})", params)["c"]


# ═══════════════════════════════════════════════════════
# 🤖 AVTO-SERIYA
# ═══════════════════════════════════════════════════════

def add_drip(delay_minutes, text, media_type, media_id):
    return _x("INSERT INTO drip_steps(delay_minutes, text, media_type, media_id, created_at) "
              "VALUES(?, ?, ?, ?, ?)", (delay_minutes, text, media_type, media_id, now())).lastrowid


def get_drip(step_id):
    return _one("SELECT * FROM drip_steps WHERE id=?", (step_id,))


def list_drip():
    return _q("SELECT * FROM drip_steps ORDER BY delay_minutes, id")


def update_drip(step_id, **fields):
    allowed = {k: v for k, v in fields.items() if k in ("active", "node_id")}
    if allowed:
        sets = ", ".join(f"{k}=?" for k in allowed)
        _x(f"UPDATE drip_steps SET {sets} WHERE id=?", (*allowed.values(), step_id))


def delete_drip(step_id):
    _x("DELETE FROM drip_steps WHERE id=?", (step_id,))
    _x("DELETE FROM drip_log WHERE step_id=?", (step_id,))


def drip_sent_count(step_id) -> int:
    return _one("SELECT COUNT(*) AS c FROM drip_log WHERE step_id=? AND status='ok'",
                (step_id,))["c"]


def drip_due(step, limit=25):
    """
    Shu qadam xabarini olish vaqti kelgan foydalanuvchilar.

    Faqat qadam yaratilgandan KEYIN kelganlar oladi (eski obunachilarga birdan
    yog'ilmasligi uchun), va vaqti 48 soatdan ko'p o'tib ketganlar tashlab
    ketiladi (bot uzoq o'chiq turib yonganda eskirgan xabarlar ketmasligi uchun).
    """
    cutoff = ago(minutes=step["delay_minutes"])
    stale = ago(minutes=step["delay_minutes"], hours=48)
    lower = max(step["created_at"] or "", stale)
    return [r["id"] for r in _q(
        "SELECT u.id FROM users u WHERE u.blocked=0 AND u.joined_at IS NOT NULL "
        "AND u.joined_at >= ? AND u.joined_at <= ? "
        "AND NOT EXISTS (SELECT 1 FROM drip_log l WHERE l.user_id=u.id AND l.step_id=?) "
        "ORDER BY u.joined_at LIMIT ?", (lower, cutoff, step["id"], limit))]


def log_drip(user_id, step_id, status):
    _x("INSERT OR IGNORE INTO drip_log(user_id, step_id, status, sent_at) VALUES(?, ?, ?, ?)",
       (user_id, step_id, status, now()))


# ═══════════════════════════════════════════════════════
# 🚚 ESKI VERSIYADAN KO'CHIRISH
# ═══════════════════════════════════════════════════════

def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def migrate_legacy(data_dir: str, admin_username: str):
    """
    Eski versiyaning JSON fayllaridagi ma'lumotlarni bazaga ko'chiradi va
    boshlang'ich menyuni yaratadi. Faqat bir marta ishlaydi.
    """
    if get_setting("migrated") == "1":
        return
    summary = {"users": 0, "books": 0, "lessons": 0, "courses": 0}

    # 1) Foydalanuvchilar
    for uid, info in _load_json(os.path.join(data_dir, "users.json"), {}).items():
        if not str(uid).lstrip("-").isdigit():
            continue
        if not _one("SELECT 1 FROM users WHERE id=?", (int(uid),)):
            _conn.execute("INSERT INTO users(id, username, full_name) VALUES(?, ?, ?)",
                          (int(uid), info.get("username"), info.get("full_name")))
            summary["users"] += 1

    for uid, reg in _load_json(os.path.join(data_dir, "marathon_registrations.json"), {}).items():
        if not str(uid).lstrip("-").isdigit():
            continue
        joined = (reg.get("registered_at") or "")[:19].replace("T", " ") or None
        if _one("SELECT 1 FROM users WHERE id=?", (int(uid),)):
            _conn.execute(
                "UPDATE users SET reg_name=?, phone=?, region=?, "
                "joined_at=COALESCE(joined_at, ?) WHERE id=?",
                (reg.get("full_name"), reg.get("phone"), reg.get("region"), joined, int(uid)))
        else:
            _conn.execute(
                "INSERT INTO users(id, full_name, reg_name, phone, region, joined_at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (int(uid), reg.get("full_name"), reg.get("full_name"),
                 reg.get("phone"), reg.get("region"), joined))
            summary["users"] += 1
    _conn.commit()

    # 2) Menyu — faqat baza hali bo'sh bo'lsa
    if count_nodes() == 0:
        free_id = create_node(None, "📚 Bepul kurslar", "section",
                              text="📚 <b>Bepul kurslar</b>\n\nKerakli bo'limni tanlang:")
        books = _load_json(os.path.join(data_dir, "free_lessons.json"), [])
        if books and "lessons" not in books[0]:        # eng eski, tekis format
            books = [{"title": "Darslar", "lessons": books}]
        for book in books:
            book_id = create_node(free_id, f"📕 {book.get('title', 'Darslik')}", "section")
            summary["books"] += 1
            for lesson in book.get("lessons", []):
                create_node(book_id, f"📖 {lesson.get('title', 'Dars')}", "page",
                            url=lesson.get("url"))
                summary["lessons"] += 1

        paid_id = create_node(None, "💎 Pullik kurslar", "section",
                              text="💎 <b>Pullik kurslar</b>\n\nKursni tanlang:")
        for course in _load_json(os.path.join(data_dir, "paid_courses.json"), []):
            create_node(
                paid_id, f"💎 {course.get('title', 'Kurs')}", "page",
                text=html.escape(course.get("text") or "") or None,
                media_type="photo" if course.get("photo") else None,
                media_id=course.get("photo"), lead=1)
            summary["courses"] += 1

        create_node(
            None, "💬 Admin bilan aloqa", "page", wide=1,
            text="💬 <b>Admin bilan aloqa</b>\n\nSavol va takliflar uchun yozing:",
            url=f"https://t.me/{admin_username}", url_label="✍️ Adminga yozish")

    set_setting("migrated", "1")
    logger.info("Eski ma'lumotlar ko'chirildi: %s", summary)
