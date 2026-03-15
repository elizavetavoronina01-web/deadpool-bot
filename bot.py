import logging
import sqlite3
import asyncio
import aiohttp
import json
import os
import random
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, LabeledPrice
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, PreCheckoutQueryHandler, filters, ContextTypes

# ===== НАСТРОЙКИ =====
BOT_TOKEN = "8701234942:AAGlPtJqTx_VWmAbZvUpEZXQYcyDoVQCp0A"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY","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")
WEBAPP_URL = "https://web-production-7040f.up.railway.app/index.html"
CHANNEL_ID = "@deadpoolnah"
TONAPI_KEY = os.environ.get("TONAPI_KEY")  # ← обязательно добавь в Railway Variables!
COLLECTION_ADDRESS = "EQBG-g6ahkAUGWpefWbx-D_9sQ8oWbvy6puuq78U2c4NUDFS"  # Plush Pepes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== БАЗА ДАННЫХ =====
def init_db():
    conn = sqlite3.connect("deadpool.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        balance INTEGER DEFAULT 0,
        referral_code TEXT UNIQUE,
        referred_by INTEGER,
        premium_until TEXT,
        total_cases INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS cases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        result TEXT,
        rarity TEXT,
        stars_spent INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        gift_name TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS floor_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        floor_ton REAL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect("deadpool.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def create_user(user_id, username, referred_by=None):
    conn = sqlite3.connect("deadpool.db")
    c = conn.cursor()
    ref_code = f"dp{user_id}"
    c.execute("INSERT OR IGNORE INTO users (user_id, username, referral_code, referred_by) VALUES (?,?,?,?)",
              (user_id, username, ref_code, referred_by))
    if referred_by:
        c.execute("UPDATE users SET balance = balance + 5 WHERE user_id=?", (referred_by,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect("deadpool.db")
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = [row[0] for row in c.fetchall()]
    conn.close()
    return users

def get_premium_users():
    conn = sqlite3.connect("deadpool.db")
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("SELECT user_id FROM users WHERE premium_until > ?", (now,))
    users = [row[0] for row in c.fetchall()]
    conn.close()
    return users

# ===== GROQ AI =====
async def ask_deadpool(message: str) -> str:
    prompt = """ты - дедпул, который анализирует сообщения и выдаёт краткий пересказ в своем стиле))).с эмодзи и сарказмом. не используй формальный язык, будь максимально неформальным и смешным в стиле дедпула. не пиши длинные предложения, будь кратким и ёмким. не используй сложные слова, говори просто и понятно. не пиши вступления, сразу к сути. не используй клише и избитые фразы. будь оригинальным и креативным. добавляй эмодзи в каждом предложении для выразительности. твоя задача - сделать пересказ максимально забавным и запоминающимся, чтобы читатели улыбались и хотели читать дальше. и добавляй матюки в стиле дедпула"""
   
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": message}
                    ],
                    "max_tokens": 300
                }
            ) as resp:
                data = await resp.json()
                logger.info(f"Groq response: {data}")
                return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return "💀 Дедпул думает... попробуй ещё раз!"

# ===== TONAPI - актуальный floor Plush Pepes (на март 2026 ~7600-8000 TON) =====
async def get_plush_pepe_floor():
    if not TONAPI_KEY:
        return None, "❌ Нет TONAPI_KEY в Railway Variables!"
    
    url = f"https://tonapi.io/v2/nfts/items?collection={COLLECTION_ADDRESS}&limit=1&sort=price_asc"
    headers = {"Authorization": f"Bearer {TONAPI_KEY}"}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return None, f"Ошибка TON API: {resp.status}"
                data = await resp.json()
                items = data.get("nft_items", [])
                if not items or "sale" not in items[0]:
                    return None, "Нет активных продаж сейчас 😢"
                
                price_nano = int(items[0]["sale"]["price"]["value"])
                floor_ton = price_nano / 1_000_000_000
                
                conn = sqlite3.connect("deadpool.db")
                c = conn.cursor()
                c.execute("INSERT INTO floor_history (floor_ton) VALUES (?)", (floor_ton,))
                conn.commit()
                conn.close()
                
                return floor_ton, f"🔥 Floor Plush Pepe: **{floor_ton:,.0f} TON** (самый дешёвый сейчас)"
    except Exception as e:
        logger.error(f"TONAPI error: {e}")
        return None, "Не удалось достать цену... TON шалит 💀"

# ===== МОНИТОРИНГ + СНАЙП-АЛЕРТ =====
async def check_new_gifts(context: ContextTypes.DEFAULT_TYPE):
    floor, msg = await get_plush_pepe_floor()
    if not floor:
        return
    
    conn = sqlite3.connect("deadpool.db")
    c = conn.cursor()
    c.execute("SELECT floor_ton FROM floor_history ORDER BY id DESC LIMIT 2")
    history = c.fetchall()
    conn.close()
    
    if len(history) >= 2 and history[1][0] > 0:
        drop_percent = (history[1][0] - floor) / history[1][0] * 100
        if drop_percent >= 10:
            alert = f"🚨 СНАЙП! Floor рухнул на {drop_percent:.1f}%!\n{msg}\n\nБеги в Mini App и хватай, пока не поздно, бля!"
            for user_id in get_premium_users():
                try:
                    await context.bot.send_message(user_id, alert)
                except:
                    pass
    
    # Обычный апдейт премиумам
    for user_id in get_premium_users():
        try:
            await context.bot.send_message(user_id, f"💀 Дедпул обновил:\n{msg}")
        except:
            pass

# ===== КОМАНДЫ БОТА =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    referred_by = None
    if args and args[0].startswith("ref"):
        try:
            referred_by = int(args[0][3:])
        except:
            pass
   
    if not get_user(user.id):
        create_user(user.id, user.username or user.first_name, referred_by)
   
    response = await ask_deadpool(f"поприветствуй нового пользователя {user.first_name} в боте с NFT подарками телеграм, скажи что тут можно открывать кейсы и следить за новыми подарками")
   
    keyboard = [
        [InlineKeyboardButton("🎰 Открыть Mini App", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton("🔥 Floor Plush Pepe", callback_data="floor")],
        [InlineKeyboardButton("🔔 Премиум алерты", callback_data="premium"),
         InlineKeyboardButton("👥 Реферальная ссылка", callback_data="referral")],
        [InlineKeyboardButton("📊 Мой профиль", callback_data="profile"),
         InlineKeyboardButton("🏆 Топ игроков", callback_data="top")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
   
    await update.message.reply_text(response, reply_markup=reply_markup)

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
   
    if not user:
        create_user(user_id, query.from_user.username)
        user = get_user(user_id)
   
    conn = sqlite3.connect("deadpool.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (user_id,))
    refs_count = c.fetchone()[0]
    conn.close()
   
    premium_status = "❌ Нет"
    if user[6] and datetime.fromisoformat(user[6]) > datetime.now():
        premium_status = f"✅ До {user[6][:10]}"
   
    text = f"""👤 Твой профиль, боец 💀
⭐ Баланс: {user[2]} Stars
🎰 Кейсов открыто: {user[7] if len(user) > 7 else 0}
👥 Рефералов: {refs_count}
🔔 Премиум: {premium_status}
🔗 Реф. код: `{user[3]}`"""
   
    await query.edit_message_text(text, parse_mode="Markdown")

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
   
    if not user:
        create_user(user_id, query.from_user.username)
        user = get_user(user_id)
   
    bot_info = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref{user_id}"
   
    response = await ask_deadpool("расскажи про реферальную систему - приглашай друзей и получай 5 звёзд за каждого. будь краток и смешон")
   
    await query.edit_message_text(
        f"{response}\n\n🔗 Твоя ссылка:\n`{ref_link}`",
        parse_mode="Markdown"
    )

async def premium_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
   
    keyboard = [
        [InlineKeyboardButton("⭐ Купить премиум — 50 Stars", callback_data="buy_premium")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
   
    text = """🔔 Премиум алерты от Дедпула
С премиумом ты получаешь:
⚡ Мгновенные уведомления о новых NFT подарках
📊 Аналитику редкости и цен
🎯 Снайпер — находит дешёвые подарки
🎰 +1 бесплатный кейс в день
Стоимость: 50 ⭐ Stars / месяц"""
   
    await query.edit_message_text(text, reply_markup=reply_markup)

async def buy_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
   
    await context.bot.send_invoice(
        chat_id=query.from_user.id,
        title="🔔 Премиум алерты",
        description="Мгновенные алерты на новые NFT подарки + бонусы от Дедпула на 30 дней",
        payload="premium_30days",
        currency="XTR",
        prices=[LabeledPrice("Премиум 30 дней", 50)]
    )

async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payload = update.message.successful_payment.invoice_payload
   
    conn = sqlite3.connect("deadpool.db")
    c = conn.cursor()
   
    if payload == "premium_30days":
        until = (datetime.now() + timedelta(days=30)).isoformat()
        c.execute("UPDATE users SET premium_until=? WHERE user_id=?", (until, user_id))
   
    conn.commit()
    conn.close()
   
    response = await ask_deadpool("пользователь только что купил премиум подписку, поздравь его в стиле дедпула")
    await update.message.reply_text(response)

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
   
    conn = sqlite3.connect("deadpool.db")
    c = conn.cursor()
    c.execute("SELECT username, total_cases FROM users ORDER BY total_cases DESC LIMIT 10")
    top_users = c.fetchall()
    conn.close()
   
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    text = "🏆 Топ игроков по кейсам\n\n"
   
    for i, (username, cases) in enumerate(top_users):
        text += f"{medals[i]} @{username or 'Аноним'} — {cases} кейсов\n"
   
    if not top_users:
        text += "Пока пусто... будь первым! 💀"
   
    await query.edit_message_text(text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
   
    user = update.effective_user
    if not get_user(user.id):
        create_user(user.id, user.username or user.first_name)
   
    if update.message.chat.type == "private" or (update.message.text and f"@" in update.message.text):
        response = await ask_deadpool(update.message.text)
        await update.message.reply_text(response)

async def floor_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    floor, msg = await get_plush_pepe_floor()
    await query.edit_message_text(msg or "Ошибка", parse_mode="Markdown")

# ===== ЗАПУСК =====
def main():
    init_db()
   
    app = Application.builder().token(BOT_TOKEN).build()
   
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(profile, pattern="^profile$"))
    app.add_handler(CallbackQueryHandler(referral, pattern="^referral$"))
    app.add_handler(CallbackQueryHandler(premium_info, pattern="^premium$"))
    app.add_handler(CallbackQueryHandler(buy_premium, pattern="^buy_premium$"))
    app.add_handler(CallbackQueryHandler(top, pattern="^top$"))
    app.add_handler(CallbackQueryHandler(floor_button, pattern="^floor$"))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
   
    job_queue = app.job_queue
    job_queue.run_repeating(check_new_gifts, interval=300, first=10)
   
    logger.info("🚀 Дедпул-бот с реальным NFT снайпингом запущен!")
    app.run_polling()

import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler

class MiniAppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=".", **kwargs)
    def log_message(self, format, *args):
        pass

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), MiniAppHandler)
    server.serve_forever()

if __name__ == "__main__":
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    main()
