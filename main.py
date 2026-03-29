#!/usr/bin/env python3
"""
Telegram Bar Bot
- Menyu ko'rsatish
- Buyurtma qabul qilish
- Admin panel
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ===================== SOZLAMALAR =====================
BOT_TOKEN = "8627453491:AAFgKPUgHdhhtNK3bX5SkhRUirQFUwa2kdI"  # @BotFather dan olingan token
ADMIN_IDS = [7399101034]  # Admin Telegram ID raqamlari

# ===================== MENYU =====================
MENU = {
    "🍺 Pivo": {
        "Heineken": 25000,
        "Carlsberg": 22000,
        "Baltika": 18000,
        "Corona": 30000,
    },
    "🍹 Kokteyllar": {
        "Mojito": 45000,
        "Margarita": 50000,
        "Pina Colada": 48000,
        "Sex on the Beach": 52000,
    },
    "🥃 Qattiq ichimliklar": {
        "Vodka (50ml)": 20000,
        "Viski (50ml)": 35000,
        "Koʻk (50ml)": 30000,
    },
    "🥤 Alkogolsiz": {
        "Coca-Cola": 12000,
        "Limonad": 15000,
        "Sharbat": 14000,
        "Suv": 8000,
    },
}

# ===================== HOLAT KONSTANTALARI =====================
CHOOSING_CATEGORY, CHOOSING_ITEM, CHOOSING_QTY, CONFIRMING_ORDER = range(4)
ADMIN_MENU = 10

# Buyurtmalar saqlash (xotirada, production uchun DB ishlatish tavsiya etiladi)
orders_db = {}  # {order_id: order_data}
order_counter = [0]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ===================== YORDAMCHI FUNKSIYALAR =====================

def get_cart_text(cart: dict) -> str:
    if not cart:
        return "🛒 Savat bo'sh"
    text = "🛒 *Sizning savatchangiz:*\n\n"
    total = 0
    for item, data in cart.items():
        subtotal = data["price"] * data["qty"]
        text += f"• {item} x{data['qty']} = {subtotal:,} so'm\n"
        total += subtotal
    text += f"\n💰 *Jami: {total:,} so'm*"
    return text


def get_order_id():
    order_counter[0] += 1
    return order_counter[0]


# ===================== FOYDALANUVCHI HANDLERLARI =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cart"] = {}
    keyboard = [
        [InlineKeyboardButton("📋 Menyu", callback_data="menu")],
        [InlineKeyboardButton("🛒 Savat", callback_data="cart")],
        [InlineKeyboardButton("📦 Buyurtma berish", callback_data="order")],
    ]
    if update.effective_user.id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("⚙️ Admin panel", callback_data="admin")])

    await update.message.reply_text(
        "🍸 *Bar Botiga xush kelibsiz!*\n\n"
        "Ichimliklar tanlang va buyurtma bering.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_menu_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = []
    for category in MENU:
        keyboard.append([InlineKeyboardButton(category, callback_data=f"cat_{category}")])
    keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data="back_main")])

    await query.edit_message_text(
        "📋 *Menyu kategoriyalari:*\nBitta kategoriyani tanlang:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_category_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    category = query.data.replace("cat_", "")
    context.user_data["current_category"] = category
    items = MENU.get(category, {})

    keyboard = []
    for item, price in items.items():
        keyboard.append([InlineKeyboardButton(
            f"{item} — {price:,} so'm",
            callback_data=f"item_{item}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 Kategoriyalar", callback_data="menu")])

    await query.edit_message_text(
        f"*{category}*\nMahsulot tanlang:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def add_item_to_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    item_name = query.data.replace("item_", "")
    category = context.user_data.get("current_category", "")
    price = MENU.get(category, {}).get(item_name, 0)

    cart = context.user_data.setdefault("cart", {})
    if item_name in cart:
        cart[item_name]["qty"] += 1
    else:
        cart[item_name] = {"price": price, "qty": 1}

    keyboard = [
        [InlineKeyboardButton("➕ Yana qo'shish", callback_data=f"item_{item_name}")],
        [InlineKeyboardButton("🛒 Savatni ko'rish", callback_data="cart")],
        [InlineKeyboardButton("📋 Menyuga qaytish", callback_data="menu")],
    ]

    await query.edit_message_text(
        f"✅ *{item_name}* savatchaga qo'shildi!\n\n{get_cart_text(cart)}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    cart = context.user_data.get("cart", {})
    keyboard = []

    if cart:
        keyboard.append([InlineKeyboardButton("✅ Buyurtma berish", callback_data="confirm_order")])
        keyboard.append([InlineKeyboardButton("🗑 Savatni tozalash", callback_data="clear_cart")])
    keyboard.append([InlineKeyboardButton("📋 Menyuga qaytish", callback_data="menu")])
    keyboard.append([InlineKeyboardButton("🏠 Bosh sahifa", callback_data="back_main")])

    await query.edit_message_text(
        get_cart_text(cart),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def clear_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["cart"] = {}

    keyboard = [[InlineKeyboardButton("📋 Menyu", callback_data="menu")]]
    await query.edit_message_text(
        "🗑 Savat tozalandi!",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    cart = context.user_data.get("cart", {})
    if not cart:
        await query.answer("Savat bo'sh!", show_alert=True)
        return

    order_id = get_order_id()
    user = update.effective_user
    total = sum(d["price"] * d["qty"] for d in cart.values())

    order = {
        "id": order_id,
        "user_id": user.id,
        "username": user.username or user.first_name,
        "cart": dict(cart),
        "total": total,
        "status": "🟡 Kutilmoqda",
    }
    orders_db[order_id] = order

    # Foydalanuvchiga tasdiqlash
    await query.edit_message_text(
        f"✅ *Buyurtmangiz qabul qilindi!*\n\n"
        f"🔢 Buyurtma #{order_id}\n"
        f"{get_cart_text(cart)}\n\n"
        f"Tez orada tayyorlanadi! 🍸",
        parse_mode="Markdown",
    )

    # Adminlarga xabar yuborish
    admin_text = (
        f"🔔 *Yangi buyurtma #{order_id}!*\n\n"
        f"👤 Mijoz: @{order['username']} (ID: {user.id})\n"
        f"{get_cart_text(cart)}\n"
    )
    for admin_id in ADMIN_IDS:
        keyboard = [
            [
                InlineKeyboardButton("✅ Qabul qilish", callback_data=f"admin_accept_{order_id}"),
                InlineKeyboardButton("❌ Bekor qilish", callback_data=f"admin_reject_{order_id}"),
            ]
        ]
        try:
            await context.bot.send_message(
                admin_id,
                admin_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception as e:
            logger.error(f"Admin {admin_id} ga xabar yuborib bo'lmadi: {e}")

    context.user_data["cart"] = {}


async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("📋 Menyu", callback_data="menu")],
        [InlineKeyboardButton("🛒 Savat", callback_data="cart")],
    ]
    if update.effective_user.id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("⚙️ Admin panel", callback_data="admin")])

    await query.edit_message_text(
        "🍸 *Bar Boti*\nNima qilmoqchisiz?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ===================== ADMIN HANDLERLARI =====================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id not in ADMIN_IDS:
        await query.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    active_orders = [o for o in orders_db.values() if "Kutilmoqda" in o["status"]]

    keyboard = [
        [InlineKeyboardButton(f"📦 Faol buyurtmalar ({len(active_orders)})", callback_data="admin_orders")],
        [InlineKeyboardButton("📊 Statistika", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="back_main")],
    ]

    await query.edit_message_text(
        "⚙️ *Admin Panel*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id not in ADMIN_IDS:
        await query.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    active = [o for o in orders_db.values() if "Kutilmoqda" in o["status"]]

    if not active:
        keyboard = [[InlineKeyboardButton("🔙 Orqaga", callback_data="admin")]]
        await query.edit_message_text(
            "📦 Faol buyurtmalar yo'q.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    text = "📦 *Faol buyurtmalar:*\n\n"
    keyboard = []
    for o in active:
        text += f"#{o['id']} — @{o['username']} — {o['total']:,} so'm\n"
        keyboard.append([
            InlineKeyboardButton(f"✅ #{o['id']} qabul", callback_data=f"admin_accept_{o['id']}"),
            InlineKeyboardButton(f"❌ #{o['id']} bekor", callback_data=f"admin_reject_{o['id']}"),
        ])
    keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin")])

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def admin_accept_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.replace("admin_accept_", ""))
    if order_id in orders_db:
        orders_db[order_id]["status"] = "✅ Qabul qilindi"
        user_id = orders_db[order_id]["user_id"]
        try:
            await context.bot.send_message(
                user_id,
                f"✅ Buyurtmangiz *#{order_id}* qabul qilindi! Tez orada tayyorlanadi 🍸",
                parse_mode="Markdown",
            )
        except Exception:
            pass
        await query.edit_message_text(f"✅ Buyurtma #{order_id} qabul qilindi.")


async def admin_reject_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.replace("admin_reject_", ""))
    if order_id in orders_db:
        orders_db[order_id]["status"] = "❌ Bekor qilindi"
        user_id = orders_db[order_id]["user_id"]
        try:
            await context.bot.send_message(
                user_id,
                f"❌ Kechirasiz, buyurtmangiz *#{order_id}* bekor qilindi.",
                parse_mode="Markdown",
            )
        except Exception:
            pass
        await query.edit_message_text(f"❌ Buyurtma #{order_id} bekor qilindi.")


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    total_orders = len(orders_db)
    accepted = sum(1 for o in orders_db.values() if "Qabul" in o["status"])
    rejected = sum(1 for o in orders_db.values() if "Bekor" in o["status"])
    total_revenue = sum(o["total"] for o in orders_db.values() if "Qabul" in o["status"])

    keyboard = [[InlineKeyboardButton("🔙 Orqaga", callback_data="admin")]]
    await query.edit_message_text(
        f"📊 *Statistika:*\n\n"
        f"📦 Jami buyurtmalar: {total_orders}\n"
        f"✅ Qabul qilingan: {accepted}\n"
        f"❌ Bekor qilingan: {rejected}\n"
        f"💰 Daromad: {total_revenue:,} so'm",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ===================== ASOSIY =====================

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Foydalanuvchi handlerlari
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(show_menu_categories, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(show_category_items, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(add_item_to_cart, pattern="^item_"))
    app.add_handler(CallbackQueryHandler(show_cart, pattern="^cart$"))
    app.add_handler(CallbackQueryHandler(clear_cart, pattern="^clear_cart$"))
    app.add_handler(CallbackQueryHandler(confirm_order, pattern="^confirm_order$"))
    app.add_handler(CallbackQueryHandler(back_main, pattern="^back_main$"))

    # Admin handlerlari
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin$"))
    app.add_handler(CallbackQueryHandler(admin_orders, pattern="^admin_orders$"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_accept_order, pattern="^admin_accept_"))
    app.add_handler(CallbackQueryHandler(admin_reject_order, pattern="^admin_reject_"))

    print("🤖 Bar bot ishga tushdi!")
    app.run_polling()


if __name__ == "__main__":
    main()
