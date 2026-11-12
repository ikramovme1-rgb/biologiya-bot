"""
🧬 Ikramov Biologiya — kontent va sotuv boti
Muallif: Makhmudjon Ikramov

Fayllar:
    bot.py     — ishga tushirish va tugmalarni ulash (shu fayl)
    config.py  — sozlamalar (Railway Variables'dan o'qiladi)
    db.py      — ma'lumotlar bazasi
    ui.py      — klaviatura va xabar yuborish yordamchilari
    user.py    — foydalanuvchi ko'radigan qism
    admin.py   — /admin paneli
"""

import asyncio
import logging
import sys
import time

from telegram import BotCommand, BotCommandScopeChat, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application, CallbackQueryHandler, ChatMemberHandler, CommandHandler,
    ContextTypes, MessageHandler, filters,
)

import admin
import config
import db
import ui
import user

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                    level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)     # har bir so'rovni yozib o'tirmasin
logger = logging.getLogger(__name__)

DRIP_INTERVAL = 60              # avto-seriya har daqiqada tekshiriladi
ERROR_ALERT_INTERVAL = 300      # xato haqida adminga 5 daqiqada ko'pi bilan 1 marta


# ═══════════════════════════════════════════════════════
# 💬 XABARLAR
# ═══════════════════════════════════════════════════════

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shaxsiy chatdagi har qanday (buyruq bo'lmagan) xabar shu yerdan o'tadi."""
    tg_user = update.effective_user
    db.upsert_user(tg_user.id, tg_user.username, tg_user.full_name)

    if await user.try_menu_button(update, context):
        return
    if ui.is_admin(tg_user.id) and await admin.handle_state_message(update, context):
        return
    if await user.handle_state_message(update, context):
        return
    await user.fallback(update, context)


async def on_unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ui.is_admin(update.effective_user.id):
        await update.message.reply_text(
            "Bu buyruq endi yo'q — hamma narsa bitta joyda: /admin",
            reply_markup=ui.main_keyboard())
    else:
        await user.fallback(update, context)


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    """Kutilmagan xato: logga yoziladi va adminga qisqa xabar boradi."""
    logger.error("Kutilmagan xato", exc_info=context.error)

    last = context.bot_data.get("error_alert_at", 0)
    if time.time() - last < ERROR_ALERT_INTERVAL:
        return
    context.bot_data["error_alert_at"] = time.time()
    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                "⚠️ <b>Botda xatolik yuz berdi</b>\n\n"
                f"<code>{ui.esc(type(context.error).__name__)}: "
                f"{ui.esc(str(context.error))[:500]}</code>\n\n"
                "Bot ishlashda davom etmoqda. Takrorlansa, shu xabarni dasturchiga yuboring.",
                parse_mode=ui.HTML)
        except TelegramError:
            pass


# ═══════════════════════════════════════════════════════
# ⏱ ORQA FON ISHLARI
# ═══════════════════════════════════════════════════════

async def drip_loop(app: Application):
    while True:
        await asyncio.sleep(DRIP_INTERVAL)
        try:
            await admin.drip_tick(app.bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Avto-seriyada xatolik")


async def post_init(app: Application):
    try:
        await app.bot.set_my_commands([BotCommand("start", "Bosh menyu")])
        for admin_id in config.ADMIN_IDS:
            await app.bot.set_my_commands(
                [BotCommand("start", "Bosh menyu"), BotCommand("admin", "Boshqaruv paneli")],
                scope=BotCommandScopeChat(admin_id))
    except TelegramError as e:
        logger.warning("Buyruqlar ro'yxatini o'rnatib bo'lmadi: %s", e)

    app.bot_data["drip_task"] = asyncio.create_task(drip_loop(app))
    logger.info("🧬 Bot ishga tushdi: @%s", app.bot.username)


async def post_shutdown(app: Application):
    task = app.bot_data.pop("drip_task", None)
    if task:
        task.cancel()
    db.close()


# ═══════════════════════════════════════════════════════
# 🏁 ISHGA TUSHIRISH
# ═══════════════════════════════════════════════════════

def build_application(token=None, request=None) -> Application:
    builder = (Application.builder().token(token or config.BOT_TOKEN)
               .post_init(post_init).post_shutdown(post_shutdown))
    if request is not None:
        builder = builder.request(request).get_updates_request(request)
    app = builder.build()

    private = filters.ChatType.PRIVATE

    app.add_handler(CommandHandler("start", user.cmd_start, filters=private))
    app.add_handler(CommandHandler("admin", admin.cmd_admin, filters=private))
    app.add_handler(CommandHandler("cancel", admin.cmd_cancel, filters=private))
    app.add_handler(CommandHandler("stats", admin.shortcut(admin.v_stats), filters=private))
    app.add_handler(CommandHandler("xabar", admin.shortcut(admin.v_bc), filters=private))
    app.add_handler(CommandHandler("export", admin.shortcut(admin.v_exp), filters=private))

    app.add_handler(CallbackQueryHandler(user.cb_check_sub, pattern=r"^check_sub$"))
    app.add_handler(CallbackQueryHandler(user.cb_node, pattern=r"^n:\d+$"))
    app.add_handler(CallbackQueryHandler(user.cb_open, pattern=r"^o:\d+$"))
    app.add_handler(CallbackQueryHandler(user.cb_lead, pattern=r"^lead:\d+$"))
    app.add_handler(CallbackQueryHandler(user.cb_lead_saved_phone, pattern=r"^leadok:\d+$"))
    app.add_handler(CallbackQueryHandler(user.cb_lead_new_phone, pattern=r"^leadnew:\d+$"))
    app.add_handler(CallbackQueryHandler(admin.cb_admin, pattern=r"^a:"))

    app.add_handler(ChatMemberHandler(user.on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(private & filters.COMMAND, on_unknown_command))
    app.add_handler(MessageHandler(private & ~filters.COMMAND, on_message))
    app.add_error_handler(on_error)
    return app


def main():
    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN o'rnatilmagan! Railway → Variables bo'limiga BOT_TOKEN qo'shing.")
        sys.exit(1)

    db.init(config.DB_FILE)
    db.migrate_legacy(config.DATA_DIR, config.ADMIN_USERNAME)

    build_application().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
