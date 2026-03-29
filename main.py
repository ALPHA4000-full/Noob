from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = "8627453491:AAFgKPUgHdhhtNK3bX5SkhRUirQFUwa2kdI"
ADMIN_ID = 7399101034

orders = []

RESPONSES = {
    "fanta": "🍹 Fanta: 0.5 / 1.0 / 1.5 / 2.0 / 2.5",
    "pizza": "🍕 Pizza mavjud!",
    "cola": "🥤 Cola bor!"
}

# START
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🍹 Bar botga xush kelibsiz!")

# USER MESSAGE
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    text = update.message.text.lower()

    # SAVE ORDER
    orders.append(f"{user.full_name}: {text}")

    # AUTO REPLY
    reply = "❗ Tushunmadim"
    for k in RESPONSES:
        if k in text:
            reply = RESPONSES[k]

    await update.message.reply_text(reply)

    # 👨‍💼 ADMIN CONTROL (HAMMASI BORADI)
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📦 Yangi message\n👤 {user.full_name}\n🆔 {user.id}\n📝 {text}"
    )

# 📊 ADMIN PANEL
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if user_id != ADMIN_ID:
        return

    if len(orders) == 0:
        await update.message.reply_text("📭 Hozircha order yo‘q")
    else:
        text = "📊 Orders:\n\n" + "\n".join(orders[-10:])
        await update.message.reply_text(text)

app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("panel", panel))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("Bot ishladi...")
app.run_polling()
