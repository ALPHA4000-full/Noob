#!/usr/bin/env python3
"""
💎 NOZex Style — Professional Kripto Obmen Bot
Kriptolar: USDT(TRC20), USDT(BEP20), BNB, TRX, SOL, TON, DOGE, LTC
Fiat: Humo, Uzcard
Referal tizimi, Admin panel, SQLite
"""

import logging
import sqlite3
import aiohttp
import asyncio
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler,
)

# ══════════════════════════════════════════════════════════
#  SOZLAMALAR
# ══════════════════════════════════════════════════════════
BOT_TOKEN         = "8627453491:AAFgKPUgHdhhtNK3bX5SkhRUirQFUwa2kdI"
ADMIN_IDS         = [7399101034]
CHANNEL_USERNAME  = "@your_channel"   # Majburiy obuna, bo'lmasa ""
REFERRAL_BONUS    = 5000              # So'm (har bir taklif uchun)
MIN_WITHDRAW      = 20000             # Minimal yechish summasi

# ══════════════════════════════════════════════════════════
#  KRIPTOLAR VA FIAT
# ══════════════════════════════════════════════════════════
CRYPTOS = {
    "USDT_TRC20": {"name": "USDT (TRC20)", "emoji": "💠", "coingecko": "tether"},
    "USDT_BEP20": {"name": "USDT (BEP20)", "emoji": "🔶", "coingecko": "tether"},
    "BNB":        {"name": "BNB",          "emoji": "🟡", "coingecko": "binancecoin"},
    "TRX":        {"name": "TRON (TRX)",   "emoji": "🔴", "coingecko": "tron"},
    "SOL":        {"name": "Solana (SOL)", "emoji": "🟣", "coingecko": "solana"},
    "TON":        {"name": "Toncoin",      "emoji": "🔷", "coingecko": "the-open-network"},
    "DOGE":       {"name": "Dogecoin",     "emoji": "🐕", "coingecko": "dogecoin"},
    "LTC":        {"name": "Litecoin",     "emoji": "⚪", "coingecko": "litecoin"},
}

FIATS = {
    "HUMO":   {"name": "Humo",   "emoji": "🏦", "currency": "UZS"},
    "UZCARD": {"name": "Uzcard", "emoji": "💳", "currency": "UZS"},
}

# ConversationHandler holatlari
(
    ST_MAIN, ST_BUY_SEL_CRYPTO, ST_BUY_ENTER_AMT, ST_BUY_ENTER_CARD,
    ST_SELL_SEL_CRYPTO, ST_SELL_ENTER_AMT, ST_SELL_ENTER_WALLET, ST_SELL_ENTER_RECEIPT,
    ST_FEEDBACK, ST_ADM_BROADCAST, ST_ADM_SET_WALLET, ST_ADM_SET_FEE,
    ST_ADM_SET_BONUS, ST_WITHDRAW,
) = range(14)

# ══════════════════════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════════════════════
DB = "nozex.db"

def db():
    return sqlite3.connect(DB)

def init_db():
    con = db()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id    INTEGER PRIMARY KEY,
            username   TEXT DEFAULT '',
            full_name  TEXT DEFAULT '',
            phone      TEXT DEFAULT '',
            ref_by     INTEGER DEFAULT 0,
            balance    REAL DEFAULT 0,
            total_refs INTEGER DEFAULT 0,
            joined_at  TEXT
        );
        CREATE TABLE IF NOT EXISTS orders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            username    TEXT,
            type        TEXT,   -- buy / sell
            crypto      TEXT,
            fiat        TEXT,
            amount      REAL,
            uzs_amount  REAL,
            rate        REAL,
            wallet      TEXT DEFAULT '',
            card        TEXT DEFAULT '',
            receipt     TEXT DEFAULT '',
            status      TEXT DEFAULT 'pending',
            created_at  TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS referrals (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_by    INTEGER,
            new_user  INTEGER,
            bonus     REAL,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS feedback (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   INTEGER,
            username  TEXT,
            message   TEXT,
            created_at TEXT
        );
    """)
    defaults = {
        "fee_buy": "1.5",
        "fee_sell": "2.0",
        "referral_bonus": str(REFERRAL_BONUS),
        "min_withdraw": str(MIN_WITHDRAW),
        **{f"wallet_{k}": "Kiritilmagan" for k in CRYPTOS},
        **{f"card_{k}": "Kiritilmagan" for k in FIATS},
    }
    for k, v in defaults.items():
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    con.commit()
    con.close()

def gs(key): # get setting
    con = db()
    r = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    con.close()
    return r[0] if r else ""

def ss(key, val): # set setting
    con = db()
    con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, val))
    con.commit()
    con.close()

def get_or_create_user(user_id, username, full_name, ref_by=0):
    con = db()
    existing = con.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not existing:
        con.execute(
            "INSERT INTO users(user_id,username,full_name,ref_by,joined_at) VALUES(?,?,?,?,?)",
            (user_id, username or "", full_name or "", ref_by, datetime.now().isoformat())
        )
        con.commit()
        # Referal bonus
        if ref_by and ref_by != user_id:
            bonus = float(gs("referral_bonus"))
            con.execute("UPDATE users SET balance=balance+?, total_refs=total_refs+1 WHERE user_id=?", (bonus, ref_by))
            con.execute(
                "INSERT INTO referrals(ref_by,new_user,bonus,created_at) VALUES(?,?,?,?)",
                (ref_by, user_id, bonus, datetime.now().isoformat())
            )
            con.commit()
    con.close()

def get_user(user_id):
    con = db()
    r = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    con.close()
    return r  # (user_id, username, full_name, phone, ref_by, balance, total_refs, joined_at)

def save_order(data: dict) -> int:
    con = db()
    cur = con.execute(
        """INSERT INTO orders(user_id,username,type,crypto,fiat,amount,uzs_amount,rate,
           wallet,card,receipt,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (data["user_id"], data["username"], data["type"], data["crypto"], data["fiat"],
         data["amount"], data["uzs_amount"], data["rate"],
         data.get("wallet",""), data.get("card",""), data.get("receipt",""),
         datetime.now().strftime("%d.%m.%Y %H:%M"))
    )
    oid = cur.lastrowid
    con.commit(); con.close()
    return oid

def update_order(oid, status):
    con = db()
    con.execute("UPDATE orders SET status=? WHERE id=?", (status, oid))
    con.commit(); con.close()

def get_order(oid):
    con = db()
    r = con.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    con.close()
    return r

def get_stats():
    con = db()
    tu = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    to_ = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    td = con.execute("SELECT COUNT(*) FROM orders WHERE status='done'").fetchone()[0]
    tp = con.execute("SELECT COUNT(*) FROM orders WHERE status='pending'").fetchone()[0]
    tr = con.execute("SELECT COUNT(*) FROM referrals").fetchone()[0]
    con.close()
    return tu, to_, td, tp, tr

# ══════════════════════════════════════════════════════════
#  KURS OLISH (CoinGecko)
# ══════════════════════════════════════════════════════════
_price_cache = {}
_price_time  = 0

async def get_prices() -> dict:
    global _price_cache, _price_time
    now = asyncio.get_event_loop().time()
    if _price_cache and now - _price_time < 180:
        return _price_cache
    ids = list({v["coingecko"] for v in CRYPTOS.values()})
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(ids)}&vs_currencies=usd,uzs"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
                _price_cache = data
                _price_time  = now
                return data
    except Exception:
        return _price_cache or {}

async def get_crypto_uzs(crypto_key: str) -> float:
    prices = await get_prices()
    cg_id = CRYPTOS[crypto_key]["coingecko"]
    return prices.get(cg_id, {}).get("uzs", 0)

# ══════════════════════════════════════════════════════════
#  KEYBOARD HELPERS
# ══════════════════════════════════════════════════════════
def main_reply_kbd():
    return ReplyKeyboardMarkup([
        ["💱 Valuta ayirboshlash", "📊 Kurs"],
        ["👥 Hamkorlar",           "👥 Referal"],
        ["⚙️ Sozlamalar",          "📞 Qayta aloqa"],
        ["🔄 Almashuv tarixi",     "📖 Qo'llanma"],
    ], resize_keyboard=True)

def crypto_inline_kbd(action: str) -> InlineKeyboardMarkup:
    rows = []
    keys = list(CRYPTOS.keys())
    for i in range(0, len(keys), 2):
        row = []
        for k in keys[i:i+2]:
            c = CRYPTOS[k]
            row.append(InlineKeyboardButton(f"{c['emoji']} {c['name']}", callback_data=f"{action}_{k}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("🏠 Bosh menyu", callback_data="home")])
    return InlineKeyboardMarkup(rows)

def fiat_inline_kbd(action: str) -> InlineKeyboardMarkup:
    rows = []
    for k, v in FIATS.items():
        rows.append([InlineKeyboardButton(f"{v['emoji']} {v['name']}", callback_data=f"{action}_{k}")])
    rows.append([InlineKeyboardButton("🏠 Bosh menyu", callback_data="home")])
    return InlineKeyboardMarkup(rows)

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════════════════
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    args = ctx.args
    ref_by = 0
    if args and args[0].startswith("ref_"):
        try: ref_by = int(args[0].replace("ref_", ""))
        except: pass

    get_or_create_user(u.id, u.username, u.full_name, ref_by)

    # Majburiy obuna tekshirish
    if CHANNEL_USERNAME:
        try:
            m = await ctx.bot.get_chat_member(CHANNEL_USERNAME, u.id)
            if m.status in ("left", "kicked"):
                kbd = InlineKeyboardMarkup([[
                    InlineKeyboardButton("📢 Kanalga obuna bo'lish",
                                        url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"),
                    InlineKeyboardButton("✅ Tekshirish", callback_data="check_sub"),
                ]])
                await update.message.reply_text(
                    "⚠️ Botdan foydalanish uchun kanalga obuna bo'ling!",
                    reply_markup=kbd
                )
                return ST_MAIN
        except: pass

    await update.message.reply_text(
        f"👋 Xush kelibsiz, *{u.first_name}*!\n\n"
        "💎 *NOZex CHange Bot*\n"
        "Kripto ↔ Fiat tez va ishonchli almashinuvi\n\n"
        "Quyidagi menyudan foydalaning 👇",
        parse_mode="Markdown",
        reply_markup=main_reply_kbd(),
    )
    return ST_MAIN

async def check_sub_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = update.effective_user
    try:
        m = await ctx.bot.get_chat_member(CHANNEL_USERNAME, u.id)
        if m.status not in ("left", "kicked"):
            await query.edit_message_text("✅ Obuna tasdiqlandi! /start bosing.")
            return
    except: pass
    await query.answer("Hali obuna bo'lmadingiz!", show_alert=True)

# ══════════════════════════════════════════════════════════
#  KURSLAR
# ══════════════════════════════════════════════════════════
async def show_rates(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    if update.callback_query: await update.callback_query.answer()

    prices = await get_prices()
    fee_buy  = float(gs("fee_buy"))
    fee_sell = float(gs("fee_sell"))

    text = "📊 *Joriy kurslar (UZS)*\n\n"
    for key, info in CRYPTOS.items():
        cg_id = info["coingecko"]
        uzs   = prices.get(cg_id, {}).get("uzs", 0)
        usd   = prices.get(cg_id, {}).get("usd", 0)
        if uzs:
            buy_rate  = uzs * (1 + fee_buy/100)
            sell_rate = uzs * (1 - fee_sell/100)
            text += (
                f"{info['emoji']} *{info['name']}*\n"
                f"  💵 USD: `${usd:,.4f}`\n"
                f"  🟢 Sotib olish: `{buy_rate:,.0f}` UZS\n"
                f"  🔴 Sotish:       `{sell_rate:,.0f}` UZS\n\n"
            )
    text += f"🕐 _{datetime.now().strftime('%d.%m.%Y %H:%M')}_"
    kbd = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Yangilash", callback_data="rates"),
        InlineKeyboardButton("💱 Almashtirish", callback_data="exchange"),
    ]])
    await msg.reply_text(text, parse_mode="Markdown", reply_markup=kbd)
    return ST_MAIN

# ══════════════════════════════════════════════════════════
#  ALMASHTIRISH TANLASH
# ══════════════════════════════════════════════════════════
async def exchange_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    if update.callback_query: await update.callback_query.answer()

    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Kripto SOTIB OLISH (UZS → Kripto)", callback_data="buy_start")],
        [InlineKeyboardButton("🔴 Kripto SOTISH (Kripto → UZS)",       callback_data="sell_start")],
        [InlineKeyboardButton("🏠 Bosh menyu", callback_data="home")],
    ])
    await msg.reply_text(
        "💱 *Almashtirish turi:*\n\n"
        "🟢 *Sotib olish* — UZS to'lab, kripto olasiz\n"
        "🔴 *Sotish* — Kripto yuborib, UZS olasiz",
        parse_mode="Markdown",
        reply_markup=kbd,
    )
    return ST_MAIN

# ══════════════════════════════════════════════════════════
#  SOTIB OLISH (UZS → Kripto)
# ══════════════════════════════════════════════════════════
async def buy_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    ctx.user_data["type"] = "buy"
    await query.message.reply_text(
        "🟢 *Kripto SOTIB OLISH*\nQaysi kriptoni sotib olmoqchisiz?",
        parse_mode="Markdown",
        reply_markup=crypto_inline_kbd("buy_crypto"),
    )
    return ST_BUY_SEL_CRYPTO

async def buy_sel_crypto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    crypto_key = query.data.replace("buy_crypto_", "")
    ctx.user_data["crypto"] = crypto_key
    ctx.user_data["fiat"] = "UZCARD"

    price = await get_crypto_uzs(crypto_key)
    fee   = float(gs("fee_buy"))
    rate  = price * (1 + fee/100)
    ctx.user_data["rate"] = rate

    info = CRYPTOS[crypto_key]
    await query.edit_message_text(
        f"🟢 *{info['emoji']} {info['name']} sotib olish*\n\n"
        f"📈 Kurs: `{rate:,.0f} UZS = 1 {crypto_key.replace('_TRC20','').replace('_BEP20','')}`\n"
        f"💼 Komissiya: {fee}%\n\n"
        f"Necha *UZS* to'laysiz? (raqam yozing)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor", callback_data="home")]]),
    )
    return ST_BUY_ENTER_AMT

async def buy_enter_amt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        uzs = float(update.message.text.replace(" ", "").replace(",", ""))
        if uzs < 10000: raise ValueError
    except:
        await update.message.reply_text("⚠️ Kamida 10,000 UZS kiriting.")
        return ST_BUY_ENTER_AMT

    rate       = ctx.user_data["rate"]
    crypto_key = ctx.user_data["crypto"]
    you_get    = uzs / rate
    ctx.user_data.update({"uzs_amount": uzs, "amount": you_get})

    info      = CRYPTOS[crypto_key]
    wallet    = gs(f"wallet_{crypto_key}")
    card_humo = gs("card_HUMO")
    card_uzc  = gs("card_UZCARD")

    await update.message.reply_text(
        f"📋 *Buyurtma tafsilotlari:*\n\n"
        f"💳 To'laysiz: *{uzs:,.0f} UZS*\n"
        f"{info['emoji']} Olasiz: *{you_get:.6f} {crypto_key.replace('_TRC20','').replace('_BEP20','')}*\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💳 *To'lov kartalari:*\n"
        f"🏦 Humo: `{card_humo}`\n"
        f"💳 Uzcard: `{card_uzc}`\n\n"
        f"⬇️ Ushbu kartalardan biriga *{uzs:,.0f} UZS* o'tkazing,\n"
        f"so'ng o'zingizning kripto *wallet adresingizni* yozing 👇",
        parse_mode="Markdown",
    )
    return ST_BUY_ENTER_CARD

async def buy_enter_card(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["wallet"] = update.message.text.strip()
    await finalize_order(update, ctx)
    return ST_MAIN

# ══════════════════════════════════════════════════════════
#  SOTISH (Kripto → UZS)
# ══════════════════════════════════════════════════════════
async def sell_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    ctx.user_data["type"] = "sell"
    await query.message.reply_text(
        "🔴 *Kripto SOTISH*\nQaysi kriptoni sotmoqchisiz?",
        parse_mode="Markdown",
        reply_markup=crypto_inline_kbd("sell_crypto"),
    )
    return ST_SELL_SEL_CRYPTO

async def sell_sel_crypto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    crypto_key = query.data.replace("sell_crypto_", "")
    ctx.user_data["crypto"] = crypto_key

    price = await get_crypto_uzs(crypto_key)
    fee   = float(gs("fee_sell"))
    rate  = price * (1 - fee/100)
    ctx.user_data["rate"] = rate

    info = CRYPTOS[crypto_key]
    await query.edit_message_text(
        f"🔴 *{info['emoji']} {info['name']} sotish*\n\n"
        f"📉 Kurs: `1 {crypto_key.replace('_TRC20','').replace('_BEP20','')} = {rate:,.0f} UZS`\n"
        f"💼 Komissiya: {fee}%\n\n"
        f"Qancha kripto sotasiz? (raqam yozing)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor", callback_data="home")]]),
    )
    return ST_SELL_ENTER_AMT

async def sell_enter_amt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.replace(" ", "").replace(",", ""))
        if amount <= 0: raise ValueError
    except:
        await update.message.reply_text("⚠️ To'g'ri raqam kiriting.")
        return ST_SELL_ENTER_AMT

    rate       = ctx.user_data["rate"]
    crypto_key = ctx.user_data["crypto"]
    uzs_get    = amount * rate
    ctx.user_data.update({"amount": amount, "uzs_amount": uzs_get})

    info       = CRYPTOS[crypto_key]
    our_wallet = gs(f"wallet_{crypto_key}")

    await update.message.reply_text(
        f"📋 *Buyurtma tafsilotlari:*\n\n"
        f"{info['emoji']} Yuborasiz: *{amount} {crypto_key.replace('_TRC20','').replace('_BEP20','')}*\n"
        f"💳 Olasiz: *{uzs_get:,.0f} UZS*\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📤 *Bizning wallet:*\n`{our_wallet}`\n\n"
        f"⬇️ Kriptoni yuborgan kartangiz raqamini yozing (UZS keladigan karta) 👇",
        parse_mode="Markdown",
    )
    return ST_SELL_ENTER_WALLET

async def sell_enter_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["card"] = update.message.text.strip()
    await update.message.reply_text(
        "📸 Endi kripto o'tkazma screenshotini yuboring yoki «O'tkazib yuborish» bosing:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⏭ O'tkazib yuborish", callback_data="skip_receipt")
        ]]),
    )
    return ST_SELL_ENTER_RECEIPT

async def sell_enter_receipt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        ctx.user_data["receipt"] = update.message.photo[-1].file_id
    elif update.message.document:
        ctx.user_data["receipt"] = update.message.document.file_id
    else:
        ctx.user_data["receipt"] = update.message.text or ""
    await finalize_order(update, ctx)
    return ST_MAIN

async def skip_receipt_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["receipt"] = ""
    await finalize_order(update, ctx, via_query=True)
    return ST_MAIN

# ══════════════════════════════════════════════════════════
#  BUYURTMANI YAKUNLASH
# ══════════════════════════════════════════════════════════
async def finalize_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE, via_query=False):
    u = update.effective_user
    d = ctx.user_data
    oid = save_order({
        "user_id":    u.id,
        "username":   u.username or u.full_name,
        "type":       d["type"],
        "crypto":     d["crypto"],
        "fiat":       d.get("fiat", "UZCARD"),
        "amount":     d["amount"],
        "uzs_amount": d["uzs_amount"],
        "rate":       d["rate"],
        "wallet":     d.get("wallet", ""),
        "card":       d.get("card", ""),
        "receipt":    d.get("receipt", ""),
    })

    type_emoji = "🟢" if d["type"] == "buy" else "🔴"
    type_text  = "Sotib olish" if d["type"] == "buy" else "Sotish"
    info = CRYPTOS[d["crypto"]]

    confirm = (
        f"✅ *Buyurtma #{oid} qabul qilindi!*\n\n"
        f"{type_emoji} *{type_text}*\n"
        f"{info['emoji']} {info['name']}\n"
        f"{'💳 To\'laysiz' if d['type']=='buy' else '📤 Yuborasiz'}: "
        f"*{d['uzs_amount'] if d['type']=='buy' else d['amount']}* "
        f"{'UZS' if d['type']=='buy' else d['crypto'].replace('_TRC20','').replace('_BEP20','')}\n"
        f"{'📤 Olasiz' if d['type']=='buy' else '💳 Olasiz'}: "
        f"*{d['amount'] if d['type']=='buy' else d['uzs_amount']:,.2f}* "
        f"{'kripto' if d['type']=='buy' else 'UZS'}\n\n"
        f"⏳ Ko'rib chiqish: *10–30 daqiqa*"
    )
    send = (update.callback_query.message.reply_text if via_query else update.message.reply_text)
    await send(confirm, parse_mode="Markdown",
               reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Bosh menyu", callback_data="home")]]))

    # Admin xabari
    adm_text = (
        f"🔔 *Yangi buyurtma #{oid}* {type_emoji}\n\n"
        f"👤 @{u.username or u.first_name} (ID: {u.id})\n"
        f"{info['emoji']} {info['name']} | {type_text}\n"
        f"💰 UZS: {d['uzs_amount']:,.0f} | Kripto: {d['amount']}\n"
        f"💳/👛 {d.get('wallet') or d.get('card','—')}\n"
        f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    adm_kbd = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"adm_ok_{oid}"),
        InlineKeyboardButton("❌ Rad etish",  callback_data=f"adm_rej_{oid}"),
    ]])
    for adm_id in ADMIN_IDS:
        try:
            await ctx.bot.send_message(adm_id, adm_text, parse_mode="Markdown", reply_markup=adm_kbd)
            if d.get("receipt") and len(d["receipt"]) > 15:
                await ctx.bot.send_photo(adm_id, d["receipt"], caption=f"📸 Chek — #{oid}")
        except Exception as e:
            logger.error(e)
    ctx.user_data.clear()

# ══════════════════════════════════════════════════════════
#  REFERAL
# ══════════════════════════════════════════════════════════
async def show_referral(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user = get_user(u.id)
    balance    = user[5] if user else 0
    total_refs = user[6] if user else 0
    bonus      = float(gs("referral_bonus"))
    min_w      = float(gs("min_withdraw"))
    link = f"https://t.me/{(await ctx.bot.get_me()).username}?start=ref_{u.id}"

    text = (
        f"👥 *Referal tizimi*\n\n"
        f"🔗 Sizning havolangiz:\n`{link}`\n\n"
        f"👥 Taklif qilganlaringiz: *{total_refs} ta*\n"
        f"💰 Har bir taklif uchun: *{bonus:,.0f} UZS*\n"
        f"💎 Balansingiz: *{balance:,.0f} UZS*\n"
        f"📤 Minimal yechish: *{min_w:,.0f} UZS*\n\n"
        f"Havolangizni do'stlaringizga yuboring va bonus oling! 🎁"
    )
    kbd = InlineKeyboardMarkup([[
        InlineKeyboardButton("💸 Bonusni yechish", callback_data="withdraw"),
    ]])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kbd)
    return ST_MAIN

async def withdraw_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = update.effective_user
    user = get_user(u.id)
    balance = user[5] if user else 0
    min_w   = float(gs("min_withdraw"))
    if balance < min_w:
        await query.answer(f"Balansingiz {balance:,.0f} UZS. Minimal: {min_w:,.0f} UZS", show_alert=True)
        return ST_MAIN
    ctx.user_data["withdraw_amount"] = balance
    await query.message.reply_text(
        f"💸 *Bonus yechish*\nMiqdor: *{balance:,.0f} UZS*\n\nKartangiz raqamini yozing:",
        parse_mode="Markdown",
    )
    return ST_WITHDRAW

async def withdraw_card(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    card = update.message.text.strip()
    amount = ctx.user_data.get("withdraw_amount", 0)
    con = db()
    con.execute("UPDATE users SET balance=0 WHERE user_id=?", (u.id,))
    con.commit(); con.close()

    await update.message.reply_text(
        f"✅ So'rov qabul qilindi!\n💸 *{amount:,.0f} UZS* → `{card}`\n\n"
        f"24 soat ichida o'tkaziladi.",
        parse_mode="Markdown",
    )
    for adm_id in ADMIN_IDS:
        try:
            await ctx.bot.send_message(
                adm_id,
                f"💸 *Bonus yechish so'rovi!*\n"
                f"👤 @{u.username or u.first_name} (ID: {u.id})\n"
                f"💰 {amount:,.0f} UZS → `{card}`",
                parse_mode="Markdown",
            )
        except: pass
    return ST_MAIN

# ══════════════════════════════════════════════════════════
#  HAMKORLAR (statistika)
# ══════════════════════════════════════════════════════════
async def show_partners(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    con = db()
    refs = con.execute(
        "SELECT u.username, u.full_name, r.bonus, r.created_at FROM referrals r "
        "JOIN users u ON r.new_user=u.user_id WHERE r.ref_by=? ORDER BY r.id DESC LIMIT 20",
        (u.id,)
    ).fetchall()
    con.close()

    if not refs:
        await update.message.reply_text("👥 Hali hamkorlaringiz yo'q.\nReferal havolangizni ulashing!")
        return ST_MAIN

    text = f"👥 *Hamkorlaringiz ({len(refs)} ta):*\n\n"
    for r in refs:
        uname, fname, bonus, dt = r
        text += f"• @{uname or fname} — +{bonus:,.0f} UZS | _{dt[:10]}_\n"
    await update.message.reply_text(text, parse_mode="Markdown")
    return ST_MAIN

# ══════════════════════════════════════════════════════════
#  TARIXI
# ══════════════════════════════════════════════════════════
async def show_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    con = db()
    rows = con.execute(
        "SELECT id,type,crypto,amount,uzs_amount,status,created_at FROM orders "
        "WHERE user_id=? ORDER BY id DESC LIMIT 10",
        (u.id,)
    ).fetchall()
    con.close()

    STATUS = {"pending": "🟡 Kutilmoqda", "done": "✅ Bajarildi", "rejected": "❌ Rad etildi"}
    if not rows:
        await update.message.reply_text("🔄 Hali almashinuvlaringiz yo'q.")
        return ST_MAIN

    text = "🔄 *So'nggi almashinuvlar:*\n\n"
    for r in rows:
        sid, tp, cr, amt, uzs, st, dt = r
        emoji = "🟢" if tp == "buy" else "🔴"
        info  = CRYPTOS.get(cr, {})
        text += (
            f"{emoji} *#{sid}* — {info.get('emoji','')} {cr}\n"
            f"   {STATUS.get(st,'❓')} | {dt}\n"
            f"   {amt:.4f} kripto ↔ {uzs:,.0f} UZS\n\n"
        )
    await update.message.reply_text(text, parse_mode="Markdown")
    return ST_MAIN

# ══════════════════════════════════════════════════════════
#  QO'LLANMA
# ══════════════════════════════════════════════════════════
async def show_guide(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Qo'llanma*\n\n"
        "🟢 *Kripto SOTIB OLISH:*\n"
        "1️⃣ «Valuta ayirboshlash» → «Sotib olish»\n"
        "2️⃣ Kriptoni tanlang\n"
        "3️⃣ Summani kiriting\n"
        "4️⃣ Ko'rsatilgan kartaga pul o'tkazing\n"
        "5️⃣ Wallet adresingizni yozing\n"
        "6️⃣ 10–30 daqiqada kripto kelib tushadi ✅\n\n"
        "🔴 *Kripto SOTISH:*\n"
        "1️⃣ «Valuta ayirboshlash» → «Sotish»\n"
        "2️⃣ Kriptoni tanlang\n"
        "3️⃣ Miqdorni kiriting\n"
        "4️⃣ Bizning walletga kriptoni yuboring\n"
        "5️⃣ Karta raqamingizni yozing\n"
        "6️⃣ Screenshot yuboring\n"
        "7️⃣ 10–30 daqiqada UZS kelib tushadi ✅\n\n"
        "❓ Savol bo'lsa: «Qayta aloqa» bo'limiga yozing",
        parse_mode="Markdown",
    )
    return ST_MAIN

# ══════════════════════════════════════════════════════════
#  QAYTA ALOQA
# ══════════════════════════════════════════════════════════
async def feedback_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📞 *Qayta aloqa*\nXabaringizni yozing, admin tez orada javob beradi:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor", callback_data="home")]]),
    )
    return ST_FEEDBACK

async def feedback_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    msg = update.message.text
    con = db()
    con.execute(
        "INSERT INTO feedback(user_id,username,message,created_at) VALUES(?,?,?,?)",
        (u.id, u.username or u.full_name, msg, datetime.now().strftime("%d.%m.%Y %H:%M"))
    )
    con.commit(); con.close()
    await update.message.reply_text("✅ Xabaringiz adminga yuborildi. Tez orada javob beramiz!")
    for adm_id in ADMIN_IDS:
        try:
            await ctx.bot.send_message(
                adm_id,
                f"📞 *Yangi xabar!*\n👤 @{u.username or u.first_name} (ID: {u.id})\n\n{msg}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💬 Javob berish", url=f"tg://user?id={u.id}")
                ]]),
            )
        except: pass
    return ST_MAIN

# ══════════════════════════════════════════════════════════
#  SOZLAMALAR (foydalanuvchi)
# ══════════════════════════════════════════════════════════
async def show_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user = get_user(u.id)
    bal  = user[5] if user else 0
    refs = user[6] if user else 0
    await update.message.reply_text(
        f"⚙️ *Sozlamalar*\n\n"
        f"👤 ID: `{u.id}`\n"
        f"📛 Ism: {u.full_name}\n"
        f"👤 Username: @{u.username or '—'}\n"
        f"💰 Balans: *{bal:,.0f} UZS*\n"
        f"👥 Taklif qilganlar: *{refs} ta*\n",
        parse_mode="Markdown",
    )
    return ST_MAIN

# ══════════════════════════════════════════════════════════
#  ADMIN PANEL
# ══════════════════════════════════════════════════════════
async def admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return ST_MAIN
    tu, to_, td, tp, tr = get_stats()
    fee_buy  = gs("fee_buy")
    fee_sell = gs("fee_sell")
    await update.message.reply_text(
        f"⚙️ *Admin Panel*\n\n"
        f"👥 Foydalanuvchilar: *{tu}*\n"
        f"📦 Jami buyurtmalar: *{to_}*\n"
        f"✅ Bajarilgan: *{td}*\n"
        f"🟡 Kutilayotgan: *{tp}*\n"
        f"👥 Referallar: *{tr}*\n"
        f"💼 Fee buy/sell: *{fee_buy}%/{fee_sell}%*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 Kutayotgan", callback_data="adm_pending"),
             InlineKeyboardButton("💳 Walletlar",  callback_data="adm_wallets")],
            [InlineKeyboardButton("💼 Foizlar",    callback_data="adm_fees"),
             InlineKeyboardButton("📢 Xabar",      callback_data="adm_broadcast")],
            [InlineKeyboardButton("📊 Statistika", callback_data="adm_stats")],
        ]),
    )
    return ST_MAIN

async def adm_pending_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in ADMIN_IDS: return ST_MAIN
    con = db()
    rows = con.execute(
        "SELECT id,username,type,crypto,amount,uzs_amount,wallet,card,created_at "
        "FROM orders WHERE status='pending' ORDER BY id DESC LIMIT 15"
    ).fetchall()
    con.close()
    if not rows:
        await query.edit_message_text("✅ Kutayotgan buyurtmalar yo'q.")
        return ST_MAIN
    for r in rows:
        sid, uname, tp, cr, amt, uzs, wallet, card, dt = r
        info = CRYPTOS.get(cr, {})
        emoji = "🟢" if tp == "buy" else "🔴"
        text = (
            f"{emoji} *Buyurtma #{sid}*\n"
            f"👤 @{uname} | {dt}\n"
            f"{info.get('emoji','')} {cr} | {amt:.4f} ↔ {uzs:,.0f} UZS\n"
            f"👛 {wallet or card or '—'}"
        )
        kbd = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ OK",  callback_data=f"adm_ok_{sid}"),
            InlineKeyboardButton("❌ Rad", callback_data=f"adm_rej_{sid}"),
        ]])
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kbd)
    await query.edit_message_text(f"📦 *{len(rows)} ta kutayotgan:*", parse_mode="Markdown")
    return ST_MAIN

async def adm_ok_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in ADMIN_IDS: return ST_MAIN
    oid = int(query.data.replace("adm_ok_", ""))
    update_order(oid, "done")
    order = get_order(oid)
    if order:
        try:
            await ctx.bot.send_message(
                order[1],
                f"🎉 *Buyurtma #{oid} bajarildi!*\n\n"
                f"✅ To'lov amalga oshirildi. Rahmat! 🙏",
                parse_mode="Markdown",
            )
        except: pass
    await query.edit_message_reply_markup(InlineKeyboardMarkup([[
        InlineKeyboardButton(f"✅ #{oid} tasdiqlandi", callback_data="noop")
    ]]))

async def adm_rej_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in ADMIN_IDS: return ST_MAIN
    oid = int(query.data.replace("adm_rej_", ""))
    update_order(oid, "rejected")
    order = get_order(oid)
    if order:
        try:
            await ctx.bot.send_message(
                order[1],
                f"❌ *Buyurtma #{oid} rad etildi.*\n\nAdmin bilan bog'laning.",
                parse_mode="Markdown",
            )
        except: pass
    await query.edit_message_reply_markup(InlineKeyboardMarkup([[
        InlineKeyboardButton(f"❌ #{oid} rad etildi", callback_data="noop")
    ]]))

async def adm_wallets_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in ADMIN_IDS: return ST_MAIN
    btns = []
    for k, v in CRYPTOS.items():
        current = gs(f"wallet_{k}")
        btns.append([InlineKeyboardButton(f"{v['emoji']} {v['name']}: {current[:20]}...",
                                           callback_data=f"setwallet_{k}")])
    for k, v in FIATS.items():
        current = gs(f"card_{k}")
        btns.append([InlineKeyboardButton(f"{v['emoji']} {v['name']} karta: {current[:20]}...",
                                           callback_data=f"setwallet_FIAT_{k}")])
    await query.edit_message_text(
        "💳 *Wallet/Karta sozlash:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(btns),
    )
    return ST_MAIN

async def setwallet_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace("setwallet_", "")
    ctx.user_data["setwallet_key"] = key
    if key.startswith("FIAT_"):
        fk = key.replace("FIAT_", "")
        name = FIATS.get(fk, {}).get("name", fk)
        cur  = gs(f"card_{fk}")
        label = f"{name} karta raqami"
    else:
        name = CRYPTOS.get(key, {}).get("name", key)
        cur  = gs(f"wallet_{key}")
        label = f"{name} wallet"
    await query.edit_message_text(
        f"✏️ *{label}*\nHozirgi: `{cur}`\n\nYangi manzilni yozing:",
        parse_mode="Markdown",
    )
    return ST_ADM_SET_WALLET

async def setwallet_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    key = ctx.user_data.get("setwallet_key", "")
    val = update.message.text.strip()
    if key.startswith("FIAT_"):
        ss(f"card_{key.replace('FIAT_','')}", val)
    else:
        ss(f"wallet_{key}", val)
    await update.message.reply_text(
        f"✅ Yangilandi!\n`{val}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Admin", callback_data="adm_wallets")]]),
    )
    return ST_MAIN

async def adm_fees_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        f"💼 *Komissiya sozlash*\n\nHozirgi:\n"
        f"🟢 Sotib olish: *{gs('fee_buy')}%*\n"
        f"🔴 Sotish: *{gs('fee_sell')}%*\n\n"
        f"Yangi qiymatni yozing:\nFormat: `buy:1.5 sell:2.0`",
        parse_mode="Markdown",
    )
    return ST_ADM_SET_FEE

async def adm_fees_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.strip().split()
        for p in parts:
            k, v = p.split(":")
            if k == "buy":  ss("fee_buy", str(float(v)))
            if k == "sell": ss("fee_sell", str(float(v)))
        await update.message.reply_text(
            f"✅ Komissiya yangilandi!\n🟢 Buy: {gs('fee_buy')}% | 🔴 Sell: {gs('fee_sell')}%"
        )
    except:
        await update.message.reply_text("⚠️ Format: `buy:1.5 sell:2.0`", parse_mode="Markdown")
    return ST_MAIN

async def adm_broadcast_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📢 Barcha foydalanuvchilarga xabar yozing:")
    return ST_ADM_BROADCAST

async def adm_broadcast_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    con = db()
    users = [r[0] for r in con.execute("SELECT user_id FROM users").fetchall()]
    con.close()
    ok = fail = 0
    for uid in users:
        try:
            await ctx.bot.send_message(uid, f"📢 {update.message.text}")
            ok += 1
        except: fail += 1
    await update.message.reply_text(f"📢 Yuborildi!\n✅ {ok} | ❌ {fail}")
    return ST_MAIN

async def adm_stats_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    con = db()
    volume = con.execute("SELECT SUM(uzs_amount) FROM orders WHERE status='done'").fetchone()[0] or 0
    con.close()
    tu, to_, td, tp, tr = get_stats()
    await query.edit_message_text(
        f"📊 *Batafsil statistika:*\n\n"
        f"👥 Foydalanuvchilar: *{tu}*\n"
        f"📦 Jami buyurtmalar: *{to_}*\n"
        f"✅ Bajarilgan: *{td}*\n"
        f"🟡 Kutilayotgan: *{tp}*\n"
        f"❌ Rad etilgan: *{to_-td-tp}*\n"
        f"👥 Referallar: *{tr}*\n"
        f"💰 Jami hajm: *{volume:,.0f} UZS*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="adm_back")]]),
    )

async def home_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    await query.message.reply_text(
        "🏠 *Bosh menyu*", parse_mode="Markdown", reply_markup=main_reply_kbd()
    )
    return ST_MAIN

async def noop_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

# ══════════════════════════════════════════════════════════
#  MESSAGE ROUTER
# ══════════════════════════════════════════════════════════
async def msg_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "💱 Valuta ayirboshlash": return await exchange_menu(update, ctx)
    if text == "📊 Kurs":                return await show_rates(update, ctx)
    if text == "👥 Referal":             return await show_referral(update, ctx)
    if text == "👥 Hamkorlar":           return await show_partners(update, ctx)
    if text == "⚙️ Sozlamalar":          return await show_settings(update, ctx)
    if text == "📞 Qayta aloqa":         return await feedback_start(update, ctx)
    if text == "🔄 Almashuv tarixi":     return await show_history(update, ctx)
    if text == "📖 Qo'llanma":           return await show_guide(update, ctx)
    return ST_MAIN

# ══════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ST_MAIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_router),
                CallbackQueryHandler(show_rates,          pattern="^rates$"),
                CallbackQueryHandler(exchange_menu,        pattern="^exchange$"),
                CallbackQueryHandler(buy_start,            pattern="^buy_start$"),
                CallbackQueryHandler(sell_start,           pattern="^sell_start$"),
                CallbackQueryHandler(home_cb,              pattern="^home$"),
                CallbackQueryHandler(withdraw_cb,          pattern="^withdraw$"),
                CallbackQueryHandler(adm_pending_cb,       pattern="^adm_pending$"),
                CallbackQueryHandler(adm_wallets_cb,       pattern="^adm_wallets$"),
                CallbackQueryHandler(adm_fees_cb,          pattern="^adm_fees$"),
                CallbackQueryHandler(adm_broadcast_start,  pattern="^adm_broadcast$"),
                CallbackQueryHandler(adm_stats_cb,         pattern="^adm_stats$"),
                CallbackQueryHandler(adm_ok_cb,            pattern="^adm_ok_"),
                CallbackQueryHandler(adm_rej_cb,           pattern="^adm_rej_"),
                CallbackQueryHandler(setwallet_start,      pattern="^setwallet_"),
                CallbackQueryHandler(check_sub_cb,         pattern="^check_sub$"),
                CallbackQueryHandler(noop_cb,              pattern="^noop$"),
                CallbackQueryHandler(noop_cb,              pattern="^adm_back$"),
            ],
            ST_BUY_SEL_CRYPTO:  [CallbackQueryHandler(buy_sel_crypto,  pattern="^buy_crypto_"),
                                  CallbackQueryHandler(home_cb,          pattern="^home$")],
            ST_BUY_ENTER_AMT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_enter_amt),
                                  CallbackQueryHandler(home_cb,          pattern="^home$")],
            ST_BUY_ENTER_CARD:  [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_enter_card)],
            ST_SELL_SEL_CRYPTO: [CallbackQueryHandler(sell_sel_crypto, pattern="^sell_crypto_"),
                                  CallbackQueryHandler(home_cb,         pattern="^home$")],
            ST_SELL_ENTER_AMT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_enter_amt),
                                  CallbackQueryHandler(home_cb,         pattern="^home$")],
            ST_SELL_ENTER_WALLET:  [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_enter_wallet)],
            ST_SELL_ENTER_RECEIPT: [
                MessageHandler(filters.PHOTO | filters.Document.ALL | (filters.TEXT & ~filters.COMMAND), sell_enter_receipt),
                CallbackQueryHandler(skip_receipt_cb, pattern="^skip_receipt$"),
            ],
            ST_FEEDBACK:        [MessageHandler(filters.TEXT & ~filters.COMMAND, feedback_send),
                                  CallbackQueryHandler(home_cb, pattern="^home$")],
            ST_ADM_BROADCAST:   [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_broadcast_send)],
            ST_ADM_SET_WALLET:  [MessageHandler(filters.TEXT & ~filters.COMMAND, setwallet_save)],
            ST_ADM_SET_FEE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_fees_save)],
            ST_WITHDRAW:        [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_card)],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("admin", admin_cmd)],
        per_message=False,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("admin", admin_cmd))
    print("💎 NOZex bot ishga tushdi!")
    app.run_polling()

if __name__ == "__main__":
    main()
