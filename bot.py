import os
import re
import threading
import time
from datetime import datetime, timezone, timedelta
import telebot
from telebot.types import BotCommand, InlineKeyboardMarkup, InlineKeyboardButton
from supabase import create_client, Client
from flask import Flask

# --- КОНФИГУРАЦИЯ И КЛЮЧИ ---
TOKEN = os.environ.get("TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

bot = telebot.TeleBot(TOKEN)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

MIN_BET = 100
SALARY_AMOUNT = 15000
SALARY_COOLDOWN_HOURS = 12

# Регистрация команд в меню Telegram (кнопка "/")
bot.set_my_commands([
    BotCommand("start", "Главное меню"),
    BotCommand("info", "Правила и виды ставок"),
    BotCommand("synonyms", "Синонимы к ставкам"),
    BotCommand("eutop", "Топ лучших игроков в чате")
])

# Словарь синонимов для ставок
BET_SYNONYMS = {
    "красное": "красное",
    "красный": "красное",
    "red": "красное",
    "ред": "красное",
    "черное": "черное",
    "черный": "черное",
    "чёрное": "черное",
    "чёрный": "черное",
    "black": "черное",
    "блек": "черное",
    "блэк": "черное",
    "чет": "чет",
    "чёт": "чет",
    "нечет": "нечет",
    "нечёт": "нечёт",
    "1-18": "1-18",
    "малые": "1-18",
    "низ": "1-18",
    "нижние": "1-18",
    "19-36": "19-36",
    "большие": "19-36",
    "верх": "19-36",
    "верхние": "19-36",
    "д1": "д1",
    "первые": "д1",
    "д2": "д2",
    "вторые": "д2",
    "д3": "д3",
    "третьи": "д3",
    "к1": "к1",
    "к2": "к2",
    "к3": "к3",
}

READABLE_BET_NAMES = {
    "красное": "красное",
    "черное": "чёрное",
    "чет": "чёт",
    "нечёт": "нечёт",
    "1-18": "1-18",
    "19-36": "19-36",
    "д1": "первую дюжину",
    "д2": "вторую дюжину",
    "д3": "третью дюжину",
    "к1": "первую колонку",
    "к2": "вторую колонку",
    "к3": "третью колонку",
}

active_rounds = {}
rounds_lock = threading.Lock()


def format_money(amount):
    """Форматирует числа с точками: 1000000 -> 1.000.000"""
    return f"{amount:,}".replace(",", ".")


def get_user_data(chat_id, user_id):
    res = (
        supabase.table("EUusers")
        .select("balance, last_salary")
        .eq("chat_id", str(chat_id))
        .eq("user_id", str(user_id))
        .execute()
    )
    if res.data:
        return res.data[0]
    return None


def register_user_if_not_exists(chat_id, user_id):
    data = get_user_data(chat_id, user_id)
    if data is None:
        try:
            supabase.table("EUusers").insert(
                {
                    "chat_id": str(chat_id),
                    "user_id": str(user_id),
                }
            ).execute()
        except Exception:
            supabase.table("EUusers").insert(
                {
                    "chat_id": str(chat_id),
                    "user_id": str(user_id),
                    "balance": 2000,
                }
            ).execute()
        data = get_user_data(chat_id, user_id)
    return data


def update_user_balance(chat_id, user_id, amount):
    current_data = register_user_if_not_exists(chat_id, user_id)
    new_balance = current_data["balance"] + amount
    supabase.table("EUusers").update({"balance": new_balance}).eq(
        "chat_id", str(chat_id)
    ).eq("user_id", str(user_id)).execute()
    return new_balance


def update_user_salary_time(chat_id, user_id, new_balance, time_str):
    supabase.table("EUusers").update({
        "balance": new_balance,
        "last_salary": time_str
    }).eq("chat_id", str(chat_id)).eq("user_id", str(user_id)).execute()


# --- ФОНОВЫЙ ПИНГ БАЗЫ ДАННЫХ (каждые 4 дня) ---
def keep_db_alive():
    while True:
        time.sleep(4 * 24 * 60 * 60) 
        try:
            supabase.table('EUusers').select('user_id').limit(1).execute()
            print("🟢 Успешный пинг базы данных для предотвращения спящего режима.")
        except Exception as e:
            print(f"❌ Ошибка при пинге базы: {e}")

threading.Thread(target=keep_db_alive, daemon=True).start()


# --- FLASK СЕРВЕР ДЛЯ RENDER И UPTIMEROBOT ---
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive!"

def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_server, daemon=True).start()


# --- ОБРАБОТКА ДЛЯ ЛИЧНЫХ СООБЩЕНИЙ (ЛС) ---
@bot.message_handler(func=lambda m: m.chat.type == "private", commands=["start", "info", "rules", "synonyms", "синонимы", "eutop", "топ"])
def handle_private_commands(message):
    markup = InlineKeyboardMarkup()
    add_button = InlineKeyboardButton(
        "➕ Добавить в чат", 
        url="https://t.me/EU_RouletteBot?startgroup=true"
    )
    markup.add(add_button)
    
    text = (
        "👋 Привет!\n\n"
        "Чтобы начать игру, добавь бота в свой чат."
    )
    bot.reply_to(message, text, reply_markup=markup)


@bot.message_handler(func=lambda m: m.chat.type == "private")
def handle_private_text(message):
    return


# --- КОМАНДЫ ДЛЯ ГРУППОВЫХ ЧАТОВ ---
@bot.message_handler(commands=["start"])
def cmd_start(message):
    text = (
        "Добро пожаловать в Европейскую рулетку!\n\n"
        "Делай ставки прямо в чате, например: `100 красное` или `1000 к1`\n\n"
        "Хочешь поделиться банком? Ответом `передать 100`\n\n"
        "• Посмотреть свой счет: `баланс`\n"
        "• Получить бонус: `зарплата`\n"
        "• Посмотреть шпаргалку: `шпора`\n"
        "• Правила и виды ставок: /rules\n"
        "• Синонимы к ставкам: /synonyms\n"
        "• Топ игроков: /eutop\n\n"
        "💡 Минимальная ставка: 🪙 100"
    )
    bot.reply_to(message, text, parse_mode="Markdown")


@bot.message_handler(commands=["info", "rules"])
def cmd_info(message):
    text = (
        "🔴 <b>Основные ставки:</b>\n\n"
        "Красное / Черное (<code>красное</code>, <code>черное</code>)\n"
        "• Множитель: <b>2x</b> | Шанс: <b>48.65%</b>\n\n"
        "Чёт / Нечёт (<code>чёт</code>, <code>нёчет</code>)\n"
        "• Множитель: <b>2x</b> | Шанс: <b>48.65%</b>\n\n"
        "1-18 / 19-36 (<code>низ</code>, <code>верх</code>)\n"
        "• Множитель: <b>2x</b> | Шанс: <b>48.65%</b>\n\n"
        "📊 <b>Дюжины и колонки:</b>\n\n"
        "Дюжины (<code>д1</code>, <code>д2</code>, <code>д3</code>)\n"
        "• Множитель: <b>3x</b> | Шанс: <b>32.43%</b>\n\n"
        "Колонки (<code>к1</code>, <code>к2</code>, <code>к3</code>)\n"
        "• Множитель: <b>3x</b> | Шанс: <b>32.43%</b>\n\n"
        "🎯 <b>Точное число</b> (от <code>0</code> до <code>36</code>)\n"
        "• Множитель: <b>36x</b> | Шанс: <b>2.70%</b>"
    )
    bot.reply_to(message, text, parse_mode="HTML")


@bot.message_handler(commands=["synonyms", "синонимы"])
def cmd_synonyms(message):
    text = (
        "💬 <b>Синонимы к ставкам:</b>\n\n"
        "🔴 Красное: <code>красное</code>, <code>красный</code>, <code>red</code>, <code>ред</code>\n"
        "⚫ Черное: <code>черное</code>, <code>черный</code>, <code>блек</code>, <code>блэк</code>\n"
        "⚖️ Чёт / Нечёт: <code>чет</code>, <code>чёт</code> / <code>нечет</code>, <code>нечёт</code>\n"
        "📉 1-18: <code>1-18</code>, <code>малые</code>, <code>низ</code>\n"
        "📈 19-36: <code>19-36</code>, <code>большие</code>, <code>верх</code>\n"
        "📊 Дюжины: <code>д1</code>, <code>д2</code>, <code>д3</code>\n"
        "📊 Колонки: <code>к1</code>, <code>к2</code>, <code>к3</code>"
    )
    bot.reply_to(message, text, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text and m.text.lower().strip() in ["шпаргалка", "шпора"])
def send_cheat_sheet(message):
    photo_file_id = "AgACAgIAAxkBAAFQXDpqaKQHNolijIBfoCiVbMXInXJdewACdhtrG16NSUvtnjU8eSyfSgEAAwIAA3MAAz0E"
    
    try:
        bot.send_photo(
            chat_id=message.chat.id,
            photo=photo_file_id
        )
    except Exception as e:
        bot.reply_to(message, "❌ Не удалось отправить шпаргалку.")
        
@bot.message_handler(commands=["eutop", "топ"])
def cmd_eutop(message):
    chat_id = message.chat.id
    try:
        res = (
            supabase.table("EUusers")
            .select("user_id", "balance")
            .eq("chat_id", str(chat_id))
            .gt("balance", 0)
            .order("balance", desc=True)
            .execute()
        )
        
        if not res.data:
            bot.reply_to(message, "📊 В этом чате пока нет игроков в рейтинге.")
            return

        text = "**Топ лучших игроков в чате**\n\n"
        for idx, row in enumerate(res.data, start=1):
            uid = int(row["user_id"])
            bal = row["balance"]
            
            try:
                member = bot.get_chat_member(chat_id, uid)
                name = member.user.first_name
            except Exception:
                name = f"Игрок {uid}"
                
            # Здесь убрали ссылки — теперь выводятся просто имя и баланс
            text += f"{idx}. {name} • 🪙 **{format_money(bal)}**\n"
            
        bot.reply_to(message, text, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, "❌ Не удалось загрузить топ игроков.")

# --- ОБРАБОТКА БАЛАНСА И ЗАРПЛАТЫ ---
@bot.message_handler(
    func=lambda m: m.text and m.text.lower().strip() == "баланс"
)
def handle_balance(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    user_data = register_user_if_not_exists(chat_id, user_id)
    bal = user_data["balance"]

    text = (
        f"💳 Баланс [{first_name}](tg://user?id={user_id})\n\n"
        f"🪙 **{format_money(bal)}**"
    )
    bot.reply_to(message, text, parse_mode="Markdown")


@bot.message_handler(
    func=lambda m: m.text and m.text.lower().strip() in ["получить зарплату", "зарплата", "зп"]
)
def handle_salary(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    
    user_data = register_user_if_not_exists(chat_id, user_id)
    last_salary_str = user_data.get("last_salary")
    
    now = datetime.now(timezone.utc)
    
    if last_salary_str:
        try:
            last_salary_time = datetime.fromisoformat(last_salary_str)
            if last_salary_time.tzinfo is None:
                last_salary_time = last_salary_time.replace(tzinfo=timezone.utc)
            
            next_available_time = last_salary_time + timedelta(hours=SALARY_COOLDOWN_HOURS)
            
            if now < next_available_time:
                diff = next_available_time - now
                hours = int(diff.total_seconds() // 3600)
                minutes = int((diff.total_seconds() % 3600) // 60)
                
                time_left_str = f"{hours} ч. {minutes} мин."
                if hours == 0:
                    time_left_str = f"{minutes} мин."
                
                bot.reply_to(
                    message,
                    f"⏳ Получить зарплату можно будет через **{time_left_str}**",
                    parse_mode="Markdown"
                )
                return
        except Exception:
            pass

    new_bal = user_data["balance"] + SALARY_AMOUNT
    update_user_salary_time(chat_id, user_id, new_bal, now.isoformat())
    
    text = (
        f"🎁 Вы получили зарплату! Начислено 🪙 **{format_money(SALARY_AMOUNT)}**\n\n"
        f"💳 Баланс [{first_name}](tg://user?id={user_id})\n\n"
        f"🪙 **{format_money(new_bal)}**"
    )
    bot.reply_to(message, text, parse_mode="Markdown")


# --- ПЕРЕВОД СРЕДСТВ ИГРОКАМ И СТАВКИ ---
@bot.message_handler(func=lambda m: m.text and not m.text.startswith("/"))
def handle_text_messages(message):
    text_lower = message.text.strip().lower()
    
    match_transfer = re.match(r"^передать(?:\s+(\d+[\d\.\,]*(?:\.\d+)?))?$", text_lower)
    
    if match_transfer:
        if not message.reply_to_message or not message.reply_to_message.from_user or message.reply_to_message.from_user.is_bot:
            return

        amount_str = match_transfer.group(1)
        chat_id = message.chat.id
        from_user = message.from_user
        reply_user = message.reply_to_message.from_user

        if from_user.id == reply_user.id:
            bot.reply_to(message, "❌ Нельзя переводить деньги самому себе.")
            return

        target_user_id = reply_user.id
        target_name = reply_user.first_name
        target_mention = f"[{target_name}](tg://user?id={target_user_id})"

        if amount_str:
            clean_sum = amount_str.replace(".", "").replace(",", "")
            amount = int(clean_sum) if clean_sum.isdigit() else 100
        else:
            amount = 100

        if amount <= 0:
            return

        sender_data = register_user_if_not_exists(chat_id, from_user.id)
        if sender_data["balance"] < amount:
            bot.reply_to(message, "❌ У вас недостаточно средств для перевода.")
            return

        register_user_if_not_exists(chat_id, target_user_id)

        update_user_balance(chat_id, from_user.id, -amount)
        update_user_balance(chat_id, target_user_id, amount)

        sender_mention = f"[{from_user.first_name}](tg://user?id={from_user.id})"
        msg_text = f"{sender_mention} передал {target_mention} 🪙 **{format_money(amount)}**"
        bot.send_message(chat_id, msg_text, parse_mode="Markdown")
        return

    text = message.text.strip()
    parts = text.split()
    
    if len(parts) < 2:
        return

    sum_str = parts[0].replace(".", "").replace(",", "")
    if not sum_str.isdigit():
        return

    raw_bet = " ".join(parts[1:]).lower().replace("ё", "е")

    normalized_bet = None
    if raw_bet in BET_SYNONYMS:
        normalized_bet = BET_SYNONYMS[raw_bet]
    elif raw_bet.isdigit() and 0 <= int(raw_bet) <= 36:
        normalized_bet = str(int(raw_bet))

    if not normalized_bet:
        return

    amount = int(sum_str)
    if amount < MIN_BET:
        bot.reply_to(message, "❌ Минимальная ставка 🪙 100", parse_mode="Markdown")
        return
        
    chat_id = message.chat.id
    user_id = message.from_user.id
    first_name = message.from_user.first_name

    user_data = register_user_if_not_exists(chat_id, user_id)
    current_bal = user_data["balance"]
    
    if current_bal < amount:
        bot.reply_to(message, "❌ Вам не хватает денег для ставки")
        return

    update_user_balance(chat_id, user_id, -amount)

    if normalized_bet.isdigit():
        readable_name = f"число *{normalized_bet}*"
    else:
        bet_display = READABLE_BET_NAMES.get(normalized_bet, normalized_bet)
        readable_name = f"*{bet_display}*"

    bot.reply_to(
        message,
        f"✅ Вы поставили 🪙 {format_money(amount)} на {readable_name}\n\n"
        "15 сек. после каждой ставки (макс. 1 мин.)",
        parse_mode="Markdown",
    )

    with rounds_lock:
        now = time.time()
        if chat_id not in active_rounds:
            active_rounds[chat_id] = {
                "start_time": now,
                "max_time": now + 60,
                "timer": None,
                "bets": [],
            }
        
        round_data = active_rounds[chat_id]
        round_data["bets"].append(
            {
                "user_id": user_id,
                "first_name": first_name,
                "amount": amount,
                "bet": normalized_bet,
            }
        )

        if round_data["timer"]:
            round_data["timer"].cancel()

        remaining_max = round_data["max_time"] - now
        timeout = min(15.0, remaining_max)
        if timeout < 1:
            timeout = 1.0

        t = threading.Timer(
            timeout, finish_round, args=(chat_id, message.chat.id)
        )
        round_data["timer"] = t
        t.start()


def finish_round(chat_id, target_chat_id):
    with rounds_lock:
        if chat_id not in active_rounds:
            return
        round_info = active_rounds.pop(chat_id)

    bets = round_info["bets"]
    if not bets:
        return

    import random

    red_numbers = {
        1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36,
    }

    winning_number = random.randint(0, 36)

    if winning_number == 0:
        num_type_str = "🟢 Шарик упал на *0*"
        color = "green"
    elif winning_number in red_numbers:
        num_type_str = f"🔴 Шарик упал на *красное {winning_number}*"
        color = "red"
    else:
        num_type_str = f"⚫ Шарик упал на *чёрное {winning_number}*"
        color = "black"

    user_payouts = {}
    user_names = {}

    for b in bets:
        uid = b["user_id"]
        user_names[uid] = b["first_name"]
        bet_val = b["bet"]
        amount = b["amount"]
        won = 0

        if bet_val.isdigit():
            if int(bet_val) == winning_number:
                won = amount * 36
        elif bet_val == "красное":
            if color == "red":
                won = amount * 2
        elif bet_val == "черное":
            if color == "black":
                won = amount * 2
        elif bet_val == "чет":
            if winning_number != 0 and winning_number % 2 == 0:
                won = amount * 2
        elif bet_val == "нечет":
            if winning_number != 0 and winning_number % 2 != 0:
                won = amount * 2
        elif bet_val == "1-18":
            if 1 <= winning_number <= 18:
                won = amount * 2
        elif bet_val == "19-36":
            if 19 <= winning_number <= 36:
                won = amount * 2
        elif bet_val == "д1":
            if 1 <= winning_number <= 12:
                won = amount * 3
        elif bet_val == "д2":
            if 13 <= winning_number <= 24:
                won = amount * 3
        elif bet_val == "д3":
            if 25 <= winning_number <= 36:
                won = amount * 3
        elif bet_val == "к1":
            if winning_number != 0 and winning_number % 3 == 1:
                won = amount * 3
        elif bet_val == "к2":
            if winning_number != 0 and winning_number % 3 == 2:
                won = amount * 3
        elif bet_val == "к3":
            if winning_number != 0 and winning_number % 3 == 0:
                won = amount * 3

        if won > 0:
            user_payouts[uid] = user_payouts.get(uid, 0) + won

    result_text = f"{num_type_str}\n\n"

    if user_payouts:
        result_text += "*Победители:*\n"
        for uid, total_win in user_payouts.items():
            update_user_balance(chat_id, uid, total_win)
            name = user_names[uid]
            result_text += (
                f"[{name}](tg://user?id={uid}) — Выиграл 🪙 **{format_money(total_win)}**\n"
            )
    else:
        result_text += "*Победителей нет*"

    bot.send_message(target_chat_id, result_text, parse_mode="Markdown")


if __name__ == "__main__":
    print("Бот запущен и готов принимать ставки...")
    bot.infinity_polling()
