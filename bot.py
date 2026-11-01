import os, sqlite3, tempfile, asyncio
from dotenv import load_dotenv
from telegram import Update, LabeledPrice, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, PreCheckoutQueryHandler, CallbackQueryHandler
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
PAYMENT_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.environ.get("PORT", 10000))
FREE_LIMIT = 20

def init_db():
    conn = sqlite3.connect("memory.db")
    conn.execute("CREATE TABLE IF NOT EXISTS history (user_id INTEGER, role TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, is_premium INTEGER DEFAULT 0, msg_count INTEGER DEFAULT 0, joined DATETIME DEFAULT CURRENT_TIMESTAMP)")
    conn.commit()
    conn.close()

def get_user(user_id, username=""):
    conn = sqlite3.connect("memory.db")
    conn.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    if username:
        conn.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
    cur = conn.cursor()
    cur.execute("SELECT is_premium, msg_count FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    return {"is_premium": bool(row[0]), "msg_count": row[1]} if row else {"is_premium": False, "msg_count": 0}

def inc_count(uid): 
    conn = sqlite3.connect("memory.db")
    conn.execute("UPDATE users SET msg_count=msg_count+1 WHERE user_id=?", (uid,)); conn.commit(); conn.close()
def set_premium(uid):
    conn = sqlite3.connect("memory.db")
    conn.execute("UPDATE users SET is_premium=1 WHERE user_id=?", (uid,)); conn.commit(); conn.close()
def get_history(uid, limit=12):
    conn = sqlite3.connect("memory.db")
    cur = conn.cursor()
    cur.execute("SELECT role, content FROM history WHERE user_id=? ORDER BY timestamp DESC LIMIT ?", (uid, limit))
    rows = cur.fetchall()[::-1]; conn.close()
    return [{"role": r, "content": c} for r,c in rows]
def save_message(uid, role, content):
    conn = sqlite3.connect("memory.db")
    conn.execute("INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)", (uid, role, content)); conn.commit(); conn.close()
def clear_history(uid):
    conn = sqlite3.connect("memory.db")
    conn.execute("DELETE FROM history WHERE user_id=?", (uid,)); conn.commit(); conn.close()

init_db()
SYSTEM_PROMPT = "You are POLY AI, a friendly multilingual assistant. ALWAYS detect the language of the user's last message and reply in THAT SAME LANGUAGE. Sinhala->Sinhala, Tamil->Tamil, English->English. You are helpful, warm, concise."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id, update.effective_user.username or "")
    is_premium = user["is_premium"]
    msg = f"👋 Hi {update.effective_user.first_name}!\n\nI am *POLY* — Fluent in You 🌍\n\nI speak Sinhala, Tamil, English, Hindi, Arabic +100 languages!\n\n🧠 I remember you | 🖼️ Read photos | 🎤 Voice messages\n\n📊 Today: {user['msg_count']}/{FREE_LIMIT} free messages\n{'💎 Premium Active — Unlimited!' if is_premium else '💎 /premium — $5/month unlimited'} \n\nJust talk to me in any language!"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💳 Pay $5 with Card (Stripe)", callback_data="pay_card")],
        [InlineKeyboardButton("⭐ Pay 250 Stars (1-Click)", callback_data="pay_stars")],
        [InlineKeyboardButton("❓ What is Premium?", callback_data="what_premium")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "💎 *POLY Premium — $5/month*\n\n✅ Unlimited GPT-4o messages\n✅ Voice messages\n✅ Photo reading\n✅ Long memory\n✅ No daily limit\n\nChoose payment:"
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "pay_stars":
        prices = [LabeledPrice("POLY Premium", 250)]
        await context.bot.send_invoice(chat_id=query.message.chat_id, title="POLY Premium", description="Unlimited access for 1 month", payload="premium_stars", provider_token="", currency="XTR", prices=prices)
    elif query.data == "pay_card":
        if not PAYMENT_TOKEN:
            await query.message.reply_text("Card payment not configured. Use Stars for now!")
            return
        prices = [LabeledPrice("POLY Premium", 500)]
        await context.bot.send_invoice(chat_id=query.message.chat_id, title="POLY Premium", description="Unlimited access for 1 month", payload="premium_card", provider_token=PAYMENT_TOKEN, currency="USD", prices=prices)
    elif query.data == "what_premium":
        await query.message.reply_text("💎 Premium gives unlimited messages, voice, vision, and memory. Just $5/month!")

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_premium(update.effective_user.id)
    await update.message.reply_text("🎉 *Premium Activated!* Thank you! You now have unlimited access to POLY! 💎", parse_mode="Markdown")

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.effective_user.id)
    await update.message.reply_text("🧹 Memory cleared!")

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ CEO only!")
        return
    await update.message.reply_text("👑 CEO Panel:\n/admin — this\n/stats — users\n/users — list\n/broadcast <msg> — broadcast")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    conn = sqlite3.connect("memory.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), SUM(is_premium), SUM(msg_count) FROM users")
    total, prem, msgs = cur.fetchone()
    conn.close()
    await update.message.reply_text(f"📊 Stats:\nUsers: {total or 0}\nPremium: {prem or 0}\nMessages: {msgs or 0}")

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    conn = sqlite3.connect("memory.db")
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, is_premium, msg_count FROM users ORDER BY msg_count DESC LIMIT 20")
    rows = cur.fetchall()
    conn.close()
    txt = "👥 Top Users:\n"
    for r in rows:
        txt += f"{r[0]} @{r[1]} — {'💎' if r[2] else 'free'} — {r[3]} msgs\n"
    await update.message.reply_text(txt)

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    msg = " ".join(context.args)
    if not msg:
        await update.message.reply_text("Usage: /broadcast Your message")
        return
    conn = sqlite3.connect("memory.db")
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    users = cur.fetchall()
    conn.close()
    sent = 0
    for (uid,) in users:
        try:
            await context.bot.send_message(chat_id=uid, text=msg)
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await update.message.reply_text(f"📢 Broadcast sent to {sent} users!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    uid = update.effective_user.id
    username = update.effective_user.username or ""
    user = get_user(uid, username)
    text = update.message.text

    if not user["is_premium"] and user["msg_count"] >= FREE_LIMIT:
        await premium(update, context)
        return

    save_message(uid, "user", text)
    history = get_history(uid)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    try:
        resp = client.chat.completions.create(model="gpt-4o-mini", messages=messages, max_tokens=1000)
        reply = resp.choices[0].message.content
    except Exception as e:
        reply = f"Error: {e}"

    save_message(uid, "assistant", reply)
    inc_count(uid)
    await update.message.reply_text(reply)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("premium", premium))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if WEBHOOK_URL:
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=TELEGRAM_TOKEN, webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_TOKEN}")
    else:
        app.run_polling()

if __name__ == "__main__":
    main()
