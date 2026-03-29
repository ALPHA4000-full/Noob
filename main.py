#!/usr/bin/env python3
"""
💱 Professional Obmen Bot
- Avtomatik kurs (exchangerate-api.com)
- USD, EUR, RUB, GBP, JPY, CNY, UZS va boshqalar
- Ariza qoldirish + karta raqami
- To'liq admin panel
- SQLite bazasi
"""

import logging
import sqlite3
import aiohttp
import asyncio
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler,
)

# ══════════════════════════════════════════════
#  SOZLAMALAR
# ══════════════════════════════════════════════
BOT_TOKEN        = "8627453491:AAFgKPUgHdhhtNK3bX5SkhRUirQFUwa2kdI"
ADMIN_IDS        = [7399101034]           # Admin Telegram ID(lar)
CHANNEL_USERNAME = "@your_channel"       # Majburiy obuna kanali (bo'lmasa "" qo'ying)

# Kurs API (bepul plan yetarli)
RATES_API_URL = "https://api.exchangerate-api.com/v4/latest/USD"

# Obmen foizi (%)
EXCHANGE_FEE_PERCENT = 1.5

# Karta raqamlari (admin o'zgartiradi)
DEFAULT_CARDS = {
    "UZS": "8600 1234 5678 9012  (Uzcard)",
    "USD": "4111 1111 1111 1111  (Visa USD)",
    "RUB": "2200 9999 8888 7777  (MIR)",
}

# Valyutalar
CURRENCIES = ["USD", "EUR", "RUB", "GBP", "CNY", "JPY", "UZS", "KZT", "TRY", "AED"]
FLAG = {
    "USD": "🇺🇸", "EUR": "🇪🇺", "RUB": "🇷🇺", "GBP": "🇬🇧",
    "CNY": "🇨🇳", "JPY": "🇯🇵", "UZS": "🇺🇿", "KZT": "🇰🇿",
    "TRY": "🇹🇷", "AED": "🇦🇪",
}

# ConversationHandler holatlari
(
    MAIN_MENU,
    SEL_FROM, SEL_TO, ENTER_AMOUNT,
    ENTER_CARD, ENTER_RECEIPT, CONFIRM_APP,
    ADMIN_BROADCAST, ADMIN_SET_CARD, ADMIN_SET_FEE,
) = range(10)

# ══════════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════════
DB_PATH = "obmen.db"

def db_connect():
    return sqlite3.connect(DB_PATH)

def init_db():
    con = db_connect()
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id    INTEGER PRIMARY KEY,
            username   TEXT,
            full_name  TEXT,
            phone      TEXT,
            joined_at  TEXT
        );
        CREATE TABLE IF NOT EXISTS applications (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            username    TEXT,
            from_cur    TEXT,
            to_cur      TEXT,
            amount      REAL,
            rate        REAL,
            you_get     REAL,
            card_from   TEXT,
            receipt     TEXT,
            status      TEXT DEFAULT 'pending',
            created_at  TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    # Default sozlamalar
    for k, v in {
        "fee_percent": str(EXCHANGE_FEE_PERCENT),
        **{f"card_{c}": DEFAULT_CARDS.get(c, "Kiritilmagan") for c in CURRENCIES},
    }.items():
        cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    con.commit()
    con.close()

def get_setting(key: str) -> str:
    con = db_connect()
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    con.close()
    return row[0] if row else ""

def set_setting(key: str, value: str):
    con = db_connect()
    con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))
    con.commit()
    con.close()

def save_user(user_id, username, full_name):
    con = db_connect()
    con.execute(
        "INSERT OR IGNORE INTO users(user_id,username,full_name,joined_at) VALUES(?,?,?,?)",
        (user_id, username, full_name, datetime.now().isoformat())
    )
    con.commit()
    con.close()

def save_application(data: dict) -> int:
    con = db_connect()
    cur = con.execute(
        """INSERT INTO applications
           (user_id,username,from_cur,to_cur,amount,rate,you_get,card_from,receipt,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            data["user_id"], data["username"],
            data["from_cur"], data["to_cur"],
            data["amount"], data["rate"], data["you_get"],
            data["card_from"], data.get("receipt", ""),
            datetime.now().strftime("%d.%m.%Y %H:%M"),
        )
    )
    app_id = cur.lastrowid
    con.commit()
    con.close()
    return app_id

def update_app_status(app_id: int, status: str):
    con = db_connect()
    con.execute("UPDATE applications SET status=? WHERE id=?", (status, app_id))
    con.commit()
    con.close()

def get_app(app_id: int):
    con = db_connect()
    row = con.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
    con.close()
    return row

def get_stats():
    con = db_connect()
    total_users   = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_apps    = con.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    done_apps     = con.execute("SELECT COUNT(*) FROM applications WHERE status='done'").fetchone()[0]
    pending_apps  = con.execute("SELECT COUNT(*) FROM applications WHERE status='pending'").fetchone()[0]
    con.close()
    return total_users, total_apps, done_apps, pending_apps

# ══════════════════════════════════════════════
#  KURS OLISH
# ══════════════════════════════════════════════
_rates_cache = {}
_rates_time  = 0

async def fetch_rates() -> dict:
    global _rates_cache, _rates_time
    now = asyncio.get_event_loop().time()
    if _rates_cache and now - _rates_time < 300:   # 5 daqiqa cache
        return _rates_cache
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(RATES_API_URL, timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
                _rates_cache = data.get("rates", {})
                _rates_time  = now
                return _rates_cache
    except Exception:
        return _rates_cache or {}

async def convert(from_cur: str, to_cur: str, amount: float) -> tuple[float, float]:
    """(you_get, rate) qaytaradi, fee hisobga olingan"""
    rates = await fetch_rates()
    if not rates:
        return 0, 0
    usd_amount = amount / rates.get(from_cur, 1)
    raw        = usd_amount * rates.get(to_cur, 1)
    fee        = float(get_setting("fee_percent"))
    you_get    = raw * (1 - fee / 100)
    rate       = you_get / amount
    return round(you_get, 4), round(rate, 6)

# ══════════════════════════════════════════════
#  YORDAMCHI
# ══════════════════════════════════════════════
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

def flag(c): return FLAG.get(c, "💱")

def cur_kbd(exclude: str = "") -> InlineKeyboardMarkup:
    btns, row = [], []
    for c in CURRENCIES:
        if c == exclude: continue
        row.append(InlineKeyboardButton(f"{flag(c)} {c}", callback_data=f"cur_{c}"))
        if len(row) == 3:
            btns.append(row); row = []
    if row: btns.append(row)
    btns.append([InlineKeyboardButton("❌ Bekor", callback_data="cancel")])
    return InlineKeyboardMarkup(btns)

def main_kbd(is_admin=False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("💱 Kurslar", callback_data="rates"),
         InlineKeyboardButton("📝 Ariza", callback_data="new_app")],
        [InlineKeyboardButton("📋 Arizalarim", callback_data="my_apps"),
         InlineKeyboardButton("ℹ️ Haqida", callback_data="about")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton("⚙️ Admin panel", callback_data="admin")])
    return InlineKeyboardMarkup(rows)

async def check_subscription(bot, user_id: int) -> bool:
    if not CHANNEL_USERNAME:
        return True
    try:
        m = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return m.status not in ("left", "kicked")
    except Exception:
        return True

# ══════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    save_user(u.id, u.username or "", u.full_name)

    if not await check_subscription(ctx.bot, u.id):
        kbd = InlineKeyboardMarkup([[
            InlineKeyboardButton("📢 Kanalga obuna bo'lish", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"),
            InlineKeyboardButton("✅ Tekshirish", callback_data="check_sub"),
        ]])
        await update.message.reply_text(
            "⚠️ Botdan foydalanish uchun kanalimizga obuna bo'ling!",
            reply_markup=kbd,
        )
        return MAIN_MENU

    await update.message.reply_text(
        f"👋 Xush kelibsiz, *{u.first_name}*!\n\n"
        "💱 *Professional Obmen Bot*\n"
        "Tez, ishonchli va foydali kurs almashinuvi.\n\n"
        "Quyidagi tugmalardan foydalaning 👇",
        parse_mode="Markdown",
        reply_markup=main_kbd(u.id in ADMIN_IDS),
    )
    return MAIN_MENU

async def check_sub_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = update.effective_user
    if await check_subscription(ctx.bot, u.id):
        await query.edit_message_text(
            "✅ Obuna tasdiqlandi!\n/start bosing.",
        )
    else:
        await query.answer("Hali obuna bo'lmadingiz!", show_alert=True)

# ══════════════════════════════════════════════
#  KURSLAR
# ══════════════════════════════════════════════
async def show_rates(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rates = await fetch_rates()
    if not rates:
        await query.edit_message_text("⚠️ Kurslarni olishda xatolik. Qayta urinib ko'ring.")
        return MAIN_MENU

    fee  = float(get_setting("fee_percent"))
    base = ["USD", "EUR", "RUB", "GBP", "CNY"]
    text = f"📊 *Joriy kurslar* (UZS)\n_Xizmat haqqi: {fee}%_\n\n"
    uzs_rate = rates.get("UZS", 1)
    for c in base:
        if c == "UZS": continue
        raw = uzs_rate / rates.get(c, 1)
        net = raw * (1 - fee / 100)
        text += f"{flag(c)} *{c}* → UZS\n"
        text += f"  Bozor: `{raw:,.2f}`\n"
        text += f"  Bizda: `{net:,.2f}`\n\n"

    text += f"🕐 _{datetime.now().strftime('%d.%m.%Y %H:%M')}_"
    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Yangilash", callback_data="rates"),
         InlineKeyboardButton("📝 Ariza berish", callback_data="new_app")],
        [InlineKeyboardButton("🏠 Bosh sahifa", callback_data="home")],
    ])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kbd)
    return MAIN_MENU

# ══════════════════════════════════════════════
#  ARIZA JARAYONI
# ══════════════════════════════════════════════
async def new_app_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    await query.edit_message_text(
        "📝 *Yangi ariza*\n\nQaysi valyutadan o'tkazasiz?",
        parse_mode="Markdown",
        reply_markup=cur_kbd(),
    )
    return SEL_FROM

async def sel_from(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["from_cur"] = query.data.replace("cur_", "")
    await query.edit_message_text(
        f"✅ *{flag(ctx.user_data['from_cur'])} {ctx.user_data['from_cur']}* tanlandi.\n\n"
        "Qaysi valyutaga o'tkazasiz?",
        parse_mode="Markdown",
        reply_markup=cur_kbd(exclude=ctx.user_data["from_cur"]),
    )
    return SEL_TO

async def sel_to(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["to_cur"] = query.data.replace("cur_", "")
    fc, tc = ctx.user_data["from_cur"], ctx.user_data["to_cur"]
    await query.edit_message_text(
        f"💱 *{flag(fc)} {fc}* → *{flag(tc)} {tc}*\n\n"
        f"Qancha *{fc}* almashtirasiz? (raqam yozing)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor", callback_data="cancel")]]),
    )
    return ENTER_AMOUNT

async def enter_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.replace(",", ".").replace(" ", ""))
        if amount <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Iltimos, to'g'ri raqam kiriting.")
        return ENTER_AMOUNT

    fc, tc = ctx.user_data["from_cur"], ctx.user_data["to_cur"]
    you_get, rate = await convert(fc, tc, amount)
    if you_get == 0:
        await update.message.reply_text("⚠️ Kurslarni olishda xatolik. Qayta urinib ko'ring.")
        return ENTER_AMOUNT

    ctx.user_data.update({"amount": amount, "you_get": you_get, "rate": rate})
    fee = float(get_setting("fee_percent"))
    card_to = get_setting(f"card_{tc}")

    text = (
        f"📋 *Ariza tafsilotlari:*\n\n"
        f"  {flag(fc)} Yuborasiz: *{amount:,.4f} {fc}*\n"
        f"  {flag(tc)} Olasiz:    *{you_get:,.4f} {tc}*\n"
        f"  📈 Kurs: `1 {fc} = {rate} {tc}`\n"
        f"  💼 Xizmat haqqi: {fee}%\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💳 *To'lov kartasi ({fc}):*\n`{get_setting(f'card_{fc}')}`\n\n"
        f"⬇️ Ushbu kartaga *{amount:,.4f} {fc}* o'tkazing,\n"
        f"so'ng o'tkazma karta raqamingizni yozing 👇"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
    return ENTER_CARD

async def enter_card(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["card_from"] = update.message.text.strip()
    await update.message.reply_text(
        "📸 Endi to'lov chekini (screenshot) yuboring yoki «O'tkazib yuborish» bosing:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⏭ O'tkazib yuborish", callback_data="skip_receipt")
        ]]),
    )
    return ENTER_RECEIPT

async def enter_receipt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        ctx.user_data["receipt"] = update.message.photo[-1].file_id
    elif update.message.document:
        ctx.user_data["receipt"] = update.message.document.file_id
    else:
        ctx.user_data["receipt"] = update.message.text or ""
    return await finalize_app(update, ctx)

async def skip_receipt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["receipt"] = ""
    return await finalize_app(update, ctx, via_query=True)

async def finalize_app(update: Update, ctx: ContextTypes.DEFAULT_TYPE, via_query=False):
    u = update.effective_user
    d = ctx.user_data
    app_id = save_application({
        "user_id":   u.id,
        "username":  u.username or u.full_name,
        "from_cur":  d["from_cur"],
        "to_cur":    d["to_cur"],
        "amount":    d["amount"],
        "rate":      d["rate"],
        "you_get":   d["you_get"],
        "card_from": d["card_from"],
        "receipt":   d.get("receipt", ""),
    })

    confirm_text = (
        f"✅ *Arizangiz qabul qilindi!*\n\n"
        f"🔢 Ariza raqami: *#{app_id}*\n"
        f"{flag(d['from_cur'])} {d['amount']:,.4f} {d['from_cur']} → "
        f"{flag(d['to_cur'])} {d['you_get']:,.4f} {d['to_cur']}\n\n"
        f"⏳ Ko'rib chiqish vaqti: *10–30 daqiqa*\n"
        f"Natija haqida sizga xabar beramiz."
    )
    send = update.callback_query.message.reply_text if via_query else update.message.reply_text
    await send(confirm_text, parse_mode="Markdown",
               reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Bosh sahifa", callback_data="home")]]))

    # Adminlarga yuborish
    admin_text = (
        f"🔔 *Yangi ariza #{app_id}*\n\n"
        f"👤 @{u.username or u.first_name} (ID: {u.id})\n"
        f"{flag(d['from_cur'])} {d['amount']:,.4f} {d['from_cur']} → "
        f"{flag(d['to_cur'])} {d['you_get']:,.4f} {d['to_cur']}\n"
        f"💳 Karta: `{d['card_from']}`\n"
        f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    admin_kbd = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"adm_ok_{app_id}"),
        InlineKeyboardButton("❌ Rad etish",  callback_data=f"adm_rej_{app_id}"),
    ]])
    for adm in ADMIN_IDS:
        try:
            msg = await ctx.bot.send_message(adm, admin_text, parse_mode="Markdown", reply_markup=admin_kbd)
            if d.get("receipt") and len(d["receipt"]) > 10:
                await ctx.bot.send_photo(adm, d["receipt"], caption=f"📸 Chek — ariza #{app_id}")
        except Exception as e:
            logger.error(f"Admin xabari: {e}")

    ctx.user_data.clear()
    return MAIN_MENU

# ══════════════════════════════════════════════
#  MENING ARIZALARIM
# ══════════════════════════════════════════════
async def my_apps(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = update.effective_user
    con = db_connect()
    rows = con.execute(
        "SELECT id,from_cur,to_cur,amount,you_get,status,created_at FROM applications WHERE user_id=? ORDER BY id DESC LIMIT 10",
        (u.id,)
    ).fetchall()
    con.close()

    if not rows:
        await query.edit_message_text(
            "📋 Sizda hali ariza yo'q.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 Ariza berish", callback_data="new_app"),
                                                InlineKeyboardButton("🏠 Bosh sahifa", callback_data="home")]]),
        )
        return MAIN_MENU

    STATUS_EMOJI = {"pending": "🟡", "done": "✅", "rejected": "❌", "processing": "🔄"}
    text = "📋 *So'nggi arizalaringiz:*\n\n"
    for r in rows:
        sid, fc, tc, amt, yg, st, dt = r
        emoji = STATUS_EMOJI.get(st, "❓")
        text += f"{emoji} *#{sid}* — {flag(fc)}{fc}→{flag(tc)}{tc}\n"
        text += f"   {amt:,.2f} → {yg:,.2f} | _{dt}_\n\n"

    await query.edit_message_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Bosh sahifa", callback_data="home")]]),
    )
    return MAIN_MENU

# ══════════════════════════════════════════════
#  ADMIN PANEL
# ══════════════════════════════════════════════
async def admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in ADMIN_IDS:
        await query.answer("❌ Ruxsat yo'q!", show_alert=True)
        return MAIN_MENU

    tu, ta, td, tp = get_stats()
    text = (
        f"⚙️ *Admin Panel*\n\n"
        f"👥 Foydalanuvchilar: *{tu}*\n"
        f"📦 Jami arizalar:    *{ta}*\n"
        f"✅ Bajarilgan:        *{td}*\n"
        f"🟡 Kutilayotgan:     *{tp}*\n"
    )
    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Kutayotgan arizalar", callback_data="adm_pending")],
        [InlineKeyboardButton("💳 Kartalarni sozlash",  callback_data="adm_cards")],
        [InlineKeyboardButton("💼 Foizni sozlash",       callback_data="adm_fee")],
        [InlineKeyboardButton("📢 Xabar yuborish",       callback_data="adm_broadcast")],
        [InlineKeyboardButton("🏠 Bosh sahifa",          callback_data="home")],
    ])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kbd)
    return MAIN_MENU

async def adm_pending(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    con = db_connect()
    rows = con.execute(
        "SELECT id,username,from_cur,to_cur,amount,you_get,card_from,created_at FROM applications WHERE status='pending' ORDER BY id DESC LIMIT 20"
    ).fetchall()
    con.close()
    if not rows:
        await query.edit_message_text(
            "✅ Kutayotgan arizalar yo'q.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="admin")]]),
        )
        return MAIN_MENU

    for r in rows:
        sid, uname, fc, tc, amt, yg, card, dt = r
        text = (
            f"📋 *Ariza #{sid}*\n"
            f"👤 @{uname}\n"
            f"{flag(fc)} {amt:,.4f} {fc} → {flag(tc)} {yg:,.4f} {tc}\n"
            f"💳 Karta: `{card}`\n"
            f"🕐 {dt}"
        )
        kbd = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ OK",  callback_data=f"adm_ok_{sid}"),
            InlineKeyboardButton("❌ Rad", callback_data=f"adm_rej_{sid}"),
        ]])
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kbd)

    await query.edit_message_text(
        f"📦 *{len(rows)} ta kutayotgan ariza:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="admin")]]),
    )
    return MAIN_MENU

async def adm_ok(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in ADMIN_IDS:
        return MAIN_MENU
    app_id = int(query.data.replace("adm_ok_", ""))
    update_app_status(app_id, "done")
    row = get_app(app_id)
    if row:
        try:
            await ctx.bot.send_message(
                row[1],
                f"🎉 *Ariza #{app_id} tasdiqlandi!*\n\n"
                f"✅ *{row[6]:,.4f} {row[4]}* hisobingizga o'tkazildi.\n"
                f"Xizmatimizdan foydalanganingiz uchun rahmat! 🙏",
                parse_mode="Markdown",
            )
        except Exception: pass
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton(f"✅ #{app_id} tasdiqlandi", callback_data="noop")
    ]]))

async def adm_rej(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in ADMIN_IDS:
        return MAIN_MENU
    app_id = int(query.data.replace("adm_rej_", ""))
    update_app_status(app_id, "rejected")
    row = get_app(app_id)
    if row:
        try:
            await ctx.bot.send_message(
                row[1],
                f"❌ *Ariza #{app_id} rad etildi.*\n\n"
                f"Muammo bo'lsa admin bilan bog'laning.",
                parse_mode="Markdown",
            )
        except Exception: pass
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton(f"❌ #{app_id} rad etildi", callback_data="noop")
    ]]))

# ──── Kartalarni sozlash ────
async def adm_cards(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    btns = []
    for c in CURRENCIES:
        btns.append([InlineKeyboardButton(f"{flag(c)} {c} kartasini o'zgartirish", callback_data=f"setcard_{c}")])
    btns.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin")])
    await query.edit_message_text("💳 *Kartalarni sozlash:*", parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(btns))
    return MAIN_MENU

async def setcard_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cur = query.data.replace("setcard_", "")
    ctx.user_data["setcard_cur"] = cur
    current = get_setting(f"card_{cur}")
    await query.edit_message_text(
        f"💳 *{flag(cur)} {cur}* uchun karta:\nHozirgi: `{current}`\n\nYangi karta raqamini yozing:",
        parse_mode="Markdown",
    )
    return ADMIN_SET_CARD

async def setcard_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cur = ctx.user_data.get("setcard_cur", "")
    set_setting(f"card_{cur}", update.message.text.strip())
    await update.message.reply_text(
        f"✅ *{flag(cur)} {cur}* kartasi yangilandi!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Admin", callback_data="admin")]]),
    )
    return MAIN_MENU

# ──── Foizni sozlash ────
async def adm_fee(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current = get_setting("fee_percent")
    await query.edit_message_text(
        f"💼 *Xizmat haqqi foizi*\nHozirgi: *{current}%*\n\nYangi foizni yozing (masalan: 1.5):",
        parse_mode="Markdown",
    )
    return ADMIN_SET_FEE

async def adm_fee_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text.replace(",", "."))
        if not (0 <= val <= 20): raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ 0–20 oralig'ida raqam kiriting.")
        return ADMIN_SET_FEE
    set_setting("fee_percent", str(val))
    await update.message.reply_text(
        f"✅ Foiz *{val}%* ga o'zgartirildi!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Admin", callback_data="admin")]]),
    )
    return MAIN_MENU

# ──── Broadcast ────
async def adm_broadcast_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📢 Barcha foydalanuvchilarga yubormoqchi bo'lgan xabarni yozing:")
    return ADMIN_BROADCAST

async def adm_broadcast_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    con = db_connect()
    users = [r[0] for r in con.execute("SELECT user_id FROM users").fetchall()]
    con.close()
    text = update.message.text
    ok, fail = 0, 0
    for uid in users:
        try:
            await ctx.bot.send_message(uid, f"📢 {text}")
            ok += 1
        except Exception:
            fail += 1
    await update.message.reply_text(
        f"📢 Xabar yuborildi!\n✅ Muvaffaqiyatli: {ok}\n❌ Muvaffaqiyatsiz: {fail}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Admin", callback_data="admin")]]),
    )
    return MAIN_MENU

# ──── Umumiy ────
async def home(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = update.effective_user
    await query.edit_message_text(
        "🏠 *Bosh sahifa*\nNima qilmoqchisiz?",
        parse_mode="Markdown",
        reply_markup=main_kbd(u.id in ADMIN_IDS),
    )
    return MAIN_MENU

async def about(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "ℹ️ *Obmen Bot haqida*\n\n"
        "• Avtomatik kurs yangilanadi\n"
        "• Tez va ishonchli almashinuv\n"
        "• 10–30 daqiqada bajariladi\n\n"
        "Savollar uchun: @admin_username",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Bosh sahifa", callback_data="home")]]),
    )
    return MAIN_MENU

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    u = update.effective_user
    await query.edit_message_text(
        "❌ Bekor qilindi.",
        reply_markup=main_kbd(u.id in ADMIN_IDS),
    )
    return MAIN_MENU

async def noop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

# ══════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(show_rates,         pattern="^rates$"),
                CallbackQueryHandler(new_app_start,      pattern="^new_app$"),
                CallbackQueryHandler(my_apps,            pattern="^my_apps$"),
                CallbackQueryHandler(about,              pattern="^about$"),
                CallbackQueryHandler(home,               pattern="^home$"),
                CallbackQueryHandler(admin_panel,        pattern="^admin$"),
                CallbackQueryHandler(adm_pending,        pattern="^adm_pending$"),
                CallbackQueryHandler(adm_cards,          pattern="^adm_cards$"),
                CallbackQueryHandler(setcard_start,      pattern="^setcard_"),
                CallbackQueryHandler(adm_fee,            pattern="^adm_fee$"),
                CallbackQueryHandler(adm_broadcast_start,pattern="^adm_broadcast$"),
                CallbackQueryHandler(adm_ok,             pattern="^adm_ok_"),
                CallbackQueryHandler(adm_rej,            pattern="^adm_rej_"),
                CallbackQueryHandler(cancel,             pattern="^cancel$"),
                CallbackQueryHandler(noop,               pattern="^noop$"),
                CallbackQueryHandler(check_sub_cb,       pattern="^check_sub$"),
            ],
            SEL_FROM:  [CallbackQueryHandler(sel_from,   pattern="^cur_"),
                        CallbackQueryHandler(cancel,      pattern="^cancel$")],
            SEL_TO:    [CallbackQueryHandler(sel_to,     pattern="^cur_"),
                        CallbackQueryHandler(cancel,      pattern="^cancel$")],
            ENTER_AMOUNT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_amount)],
            ENTER_CARD:    [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_card)],
            ENTER_RECEIPT: [
                MessageHandler(filters.PHOTO | filters.Document.ALL | filters.TEXT & ~filters.COMMAND, enter_receipt),
                CallbackQueryHandler(skip_receipt, pattern="^skip_receipt$"),
            ],
            ADMIN_SET_CARD:  [MessageHandler(filters.TEXT & ~filters.COMMAND, setcard_save)],
            ADMIN_SET_FEE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_fee_save)],
            ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_broadcast_send)],
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
    )

    app.add_handler(conv)
    print("✅ Obmen bot ishga tushdi!")
    app.run_polling()

if __name__ == "__main__":
    main()
