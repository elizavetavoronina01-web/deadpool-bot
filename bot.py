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
GROK_API_KEY = os.environ.get("GROK_API_KEY")
WEBAPP_URL = "https://web-production-7040f.up.railway.app/miniapp"  # Замени после деплоя
CHANNEL_ID = "@deadpoolnah"  # Замени на свой канал

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

# ===== GROK AI =====
async def ask_deadpool(message: str) -> str:
    prompt = """ты - дедпул, который анализирует сообщения и выдаёт краткий пересказ в своем стиле))).с эмодзи и сарказмом. не используй формальный язык, будь максимально неформальным и смешным в стиле дедпула. не пиши длинные предложения, будь кратким и ёмким. не используй сложные слова, говори просто и понятно. не пиши вступления, сразу к сути. не используй клише и избитые фразы. будь оригинальным и креативным. добавляй эмодзи в каждом предложении для выразительности. твоя задача - сделать пересказ максимально забавным и запоминающимся, чтобы читатели улыбались и хотели читать дальше. и добавляй матюки в стиле дедпула"""
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.x.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "grok-3-mini",
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": message}
                    ],
                    "max_tokens": 300
                }
            ) as resp:
                data = await resp.json()
                return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Grok error: {e}")
        return "🤖 Дедпул временно отдыхает... но скоро вернётся с матюками 💀"

# ===== ПАРСИНГ FRAGMENT =====
async def get_new_gifts():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.fragment.com/api",
                json={"@type": "getCollectibles", "type": "tg_stars_transaction", "offset": 0, "limit": 10},
                headers={"Content-Type": "application/json"}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("collectibles", [])
    except Exception as e:
        logger.error(f"Fragment error: {e}")
    return []

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
    
    # Отвечаем только если бота упомянули или это ЛС
    if update.message.chat.type == "private" or (update.message.text and f"@" in update.message.text):
        response = await ask_deadpool(update.message.text)
        await update.message.reply_text(response)

# ===== МОНИТОРИНГ НОВЫХ ПОДАРКОВ =====
async def check_new_gifts(context: ContextTypes.DEFAULT_TYPE):
    gifts = await get_new_gifts()
    if not gifts:
        return
    
    # Берём только свежие (упрощённая логика)
    if gifts:
        gift = gifts[0]
        gift_name = gift.get("name", "Новый подарок")
        
        message = await ask_deadpool(f"объяви что вышел новый NFT подарок в телеграм под названием {gift_name}, зазови всех покупать и смотреть в боте")
        
        # Шлём всем премиум пользователям сразу
        premium_users = get_premium_users()
        for user_id in premium_users:
            try:
                await context.bot.send_message(user_id, f"⚡ АЛЕРТ!\n\n{message}")
            except:
                pass

# ===== АВТО ПОСТЫ В КАНАЛ =====
async def post_to_channel(context: ContextTypes.DEFAULT_TYPE):
    topics = [
        "расскажи про рынок NFT подарков телеграм сегодня, что горячего, зазови подписчиков в бота",
        "дай совет как зарабатывать на NFT подарках телеграм, будь краток и смешон, упомяни бота",
        "расскажи про редкие NFT подарки телеграм и почему их стоит покупать прямо сейчас"
    ]
    
    topic = random.choice(topics)
    message = await ask_deadpool(topic)
    
    try:
        bot_info = await context.bot.get_me()
        keyboard = [[InlineKeyboardButton("🎰 Открыть бота", url=f"https://t.me/{bot_info.username}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(CHANNEL_ID, message, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Channel post error: {e}")

# ===== ЗАПУСК =====
def main():
    init_db()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(profile, pattern="^profile$"))
    app.add_handler(CallbackQueryHandler(referral, pattern="^referral$"))
    app.add_handler(CallbackQueryHandler(premium_info, pattern="^premium$"))
    app.add_handler(CallbackQueryHandler(buy_premium, pattern="^buy_premium$"))
    app.add_handler(CallbackQueryHandler(top, pattern="^top$"))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Задачи по расписанию
    job_queue = app.job_queue
    job_queue.run_repeating(check_new_gifts, interval=300, first=10)  # каждые 5 минут
    job_queue.run_repeating(post_to_channel, interval=21600, first=60)  # каждые 6 часов
    
    logger.info("🚀 Дедпул-бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
