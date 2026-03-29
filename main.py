from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

TOKEN = "8627453491:AAFgKPUgHdhhtNK3bX5SkhRUirQFUwa2kdI"
ADMIN_ID = 7399101034

orders = {}
order_id = 1

# 👤 USER START
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🍹 Zakazingizni yozing (masalan: 1 pizza 1 lavash)")

# 📦 USER ORDER
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global order_id

    user = update.message.from_user
    text = update.message.text

    oid = order_id
    order_id += 1

    orders[oid] = {
        "user_id": user.id,
        "text": text
    }

    # 👨‍💼 ADMIN MESSAGE + BUTTONS
    keyboard = [
        [
            InlineKeyboardButton("✅ Confirm", callback_data=f"ok:{oid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"no:{oid}")
        ]
    ]

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📦 NEW ORDER #{oid}\n\n👤 {user.full_name}\n🆔 {user.id}\n📝 {text}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    await update.message.reply_text("✅ Zakazingiz qabul qilindi!")

# ⚙️ ADMIN ACTION
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, oid = query.data.split(":")
    oid = int(oid)

    order = orders.get(oid)

    if not order:
        await query.edit_message_text("❌ Order topilmadi")
        return

    if action == "ok":
        await context.bot.send_message(
            chat_id=order["user_id"],
            text=f"✅ Zakazingiz tasdiqlandi!\n📦 Order #{oid}"
        )
        await query.edit_message_text(f"✅ Order #{oid} CONFIRMED")

    elif action == "no":
        await context.bot.send_message(
            chat_id=order["user_id"],
            text=f"❌ Zakazingiz bekor qilindi\n📦 Order #{oid}"
        )
        await query.edit_message_text(f"❌ Order #{oid} REJECTED")

# 🚀 BOT START
app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
app.add_handler(CallbackQueryHandler(button))

print("Bot ishladi...")
app.run_polling()
