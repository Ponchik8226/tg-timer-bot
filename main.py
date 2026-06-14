"""
Telegram-бот для личного использования в группе (pyTelegramBotAPI).

Команды: /ping, /t (/timer, "тайм", "таймер"), /my_timers ("таймеры"),
/del (/cancel, "удалить", "отмена"), /start, /help.

Таймеры — через threading.Timer, не блокируют polling.
ВАЖНО: таймеры хранятся в памяти и теряются при перезапуске процесса.

Дополнительно: поднимается крошечный Flask-сервер на порту из переменной
окружения PORT. Это нужно для бесплатных хостингов (например, Render) —
без открытого порта они считают приложение неработающим и "засыпают" его.
"""

import html
import logging
import os
import re
import threading
import time

import telebot
from flask import Flask
from telebot import types


# =============================================================================
#                               КОНФИГУРАЦИЯ
# =============================================================================

# Токен передаётся через переменную окружения BOT_TOKEN (см. инструкцию по деплою)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("timer_bot")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

START_TIME = time.time()


# =============================================================================
#                          ХРАНИЛИЩЕ АКТИВНЫХ ТАЙМЕРОВ
# =============================================================================

# TIMERS: timer_id -> {chat_id, user_id, user_mention, description,
#                       end_time, duration, timer_obj}
TIMERS = {}

# USER_TIMERS: user_id -> множество timer_id пользователя
USER_TIMERS = {}

_next_timer_id = 1
_timers_lock = threading.Lock()


# =============================================================================
#                          ПАРСЕР ВРЕМЕНИ ДЛЯ ТАЙМЕРА
# =============================================================================

# "1д5ч30м10с" -> компоненты, все группы опциональны
_TIME_PATTERN = re.compile(
    r"^(?:(\d+)д)?(?:(\d+)ч)?(?:(\d+)м)?(?:(\d+)с)?$",
    re.IGNORECASE,
)


def parse_duration(time_str: str):
    """Парсит "1д5ч30м10с" и т.п. в секунды. None — если строка некорректна."""
    match = _TIME_PATTERN.match(time_str.strip())
    if not match:
        return None

    days, hours, minutes, seconds = (
        int(group) if group else 0 for group in match.groups()
    )
    total_seconds = days * 86400 + hours * 3600 + minutes * 60 + seconds

    if total_seconds <= 0:
        return None

    return total_seconds


def format_duration(seconds: int) -> str:
    """
    Преобразует количество секунд в человекочитаемую строку,
    например: "1д 5ч 30м 10с".
    """
    seconds = int(seconds)
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if minutes:
        parts.append(f"{minutes}м")
    if secs or not parts:
        parts.append(f"{secs}с")

    return " ".join(parts)


# =============================================================================
#                          ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

def build_user_mention(user: types.User) -> str:
    """HTML-ссылка tg://user?id=... — тегает пользователя даже без username."""
    display_name = html.escape(user.first_name or "Пользователь")
    return f'<a href="tg://user?id={user.id}">{display_name}</a>'


def get_uptime_str() -> str:
    """Аптайм бота с момента запуска, например "1д 5ч 30м 10с"."""
    uptime_seconds = int(time.time() - START_TIME)
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if minutes:
        parts.append(f"{minutes}м")
    parts.append(f"{seconds}с")

    return " ".join(parts)


# =============================================================================
#                          ЛОГИКА ТАЙМЕРОВ
# =============================================================================

def fire_timer(timer_id: int):
    """Срабатывает по таймеру: тегает пользователя и шлёт описание."""
    with _timers_lock:
        info = TIMERS.pop(timer_id, None)
        if info is not None:
            USER_TIMERS.get(info["user_id"], set()).discard(timer_id)

    if info is None:
        logger.info("Таймер #%s сработал, но был отменён ранее.", timer_id)
        return

    logger.info(
        "Таймер #%s сработал (chat_id=%s, user_id=%s).",
        timer_id, info["chat_id"], info["user_id"],
    )

    if info["description"]:
        text = (
            f"⏰ {info['user_mention']}, время вышло!\n"
            f"📝 {html.escape(info['description'])}"
        )
    else:
        text = f"⏰ {info['user_mention']}, время вышло!"

    try:
        bot.send_message(info["chat_id"], text)
    except Exception:
        logger.exception("Не удалось отправить сообщение по таймеру #%s", timer_id)


def create_timer(message: types.Message, duration_seconds: int, description: str):
    """
    Создаёт новый таймер, сохраняет его в общих структурах и запускает
    threading.Timer на фоновое срабатывание.
    """
    global _next_timer_id

    user = message.from_user
    mention = build_user_mention(user)
    end_time = time.time() + duration_seconds

    with _timers_lock:
        timer_id = _next_timer_id
        _next_timer_id += 1

        timer_obj = threading.Timer(duration_seconds, fire_timer, args=(timer_id,))
        timer_obj.daemon = True  # не мешает завершению процесса

        TIMERS[timer_id] = {
            "chat_id": message.chat.id,
            "user_id": user.id,
            "user_mention": mention,
            "description": description,
            "end_time": end_time,
            "duration": duration_seconds,
            "timer_obj": timer_obj,
        }
        USER_TIMERS.setdefault(user.id, set()).add(timer_id)

        timer_obj.start()

    logger.info(
        "Создан таймер #%s на %s сек (user_id=%s, chat_id=%s).",
        timer_id, duration_seconds, user.id, message.chat.id,
    )

    desc_part = f"\n📝 Описание: {html.escape(description)}" if description else ""
    bot.reply_to(
        message,
        f"✅ Таймер #{timer_id} установлен на {format_duration(duration_seconds)}."
        f"{desc_part}",
    )


def cancel_timer(timer_id: int, user_id: int) -> str:
    """Отменяет таймер по ID, если он принадлежит user_id."""
    with _timers_lock:
        info = TIMERS.get(timer_id)

        if info is None:
            return f"❌ Таймер #{timer_id} не найден (возможно, он уже сработал или удалён)."

        if info["user_id"] != user_id:
            return f"❌ Таймер #{timer_id} принадлежит другому пользователю — отменить его может только автор."

        info["timer_obj"].cancel()
        del TIMERS[timer_id]
        USER_TIMERS.get(user_id, set()).discard(timer_id)

    logger.info("Таймер #%s отменён пользователем %s.", timer_id, user_id)
    return f"🗑 Таймер #{timer_id} успешно удалён."


# =============================================================================
#                          ОБРАБОТЧИКИ КОМАНД
# =============================================================================

HELP_TEXT = (
    "<b>🤖 Команды бота</b>\n\n"

    "<b>⏰ Таймер</b>\n"
    "<code>/t [время] [описание]</code>\n"
    "Синонимы: <code>/timer</code>, <code>таймер</code>, <code>тайм</code>\n"
    "Время: <code>д</code>/<code>ч</code>/<code>м</code>/<code>с</code> "
    "(дни/часы/минуты/секунды), можно комбинировать.\n"
    "Описание необязательно. По срабатыванию бот напишет в чат и упомянет вас.\n"
    "Примеры:\n"
    "  <code>/t 1д5ч30с купить продукты</code>\n"
    "  <code>/t 5м вытащить мясо с морозильника</code>\n\n"

    "<b>📑 Мои таймеры</b>\n"
    "<code>/my_timers</code> или <code>таймеры</code>\n"
    "Список активных таймеров с ID и оставшимся временем.\n\n"

    "<b>🗑 Удалить таймер</b>\n"
    "<code>/del [ID]</code>\n"
    "Синонимы: <code>/cancel</code>, <code>удалить</code>, <code>отмена</code>\n"
    "ID берётся из <code>/my_timers</code>.\n"
    "Пример: <code>/del 3</code>\n\n"

    "🏓 <code>/ping</code>\n"
    "Проверка отклика бота + аптайм.\n\n"
)


@bot.message_handler(commands=["start", "help"])
def handle_help(message: types.Message):
    bot.reply_to(message, HELP_TEXT)


@bot.message_handler(commands=["ping"])
def handle_ping(message: types.Message):
    """Замеряет время round-trip к Telegram API и показывает Uptime."""
    start = time.perf_counter()
    sent = bot.send_message(message.chat.id, "🏓 Pong!")
    elapsed_ms = (time.perf_counter() - start) * 1000

    bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=sent.message_id,
        text=(
            f"🏓 Pong!\n"
            f"Ping: <code>{elapsed_ms:.3f}</code> ms\n"
            f"Uptime: {get_uptime_str()}"
        ),
    )


def _send_timer_usage_hint(message: types.Message):
    """Отправляет подсказку по правильному формату команды таймера."""
    bot.reply_to(
        message,
        "⚠️ Не удалось распознать команду таймера.\n\n"
        "Используйте формат: <code>[команда] [время] [описание]</code>\n"
        "Время задаётся буквами д/ч/м/с, например:\n"
        "<code>/t 1д5ч30с проверить код</code>\n"
        "<code>/t 10с</code> (описание не обязательно)",
    )


def _process_timer_request(message: types.Message, args_text: str):
    """Разбирает аргументы на время и описание, создаёт таймер."""
    args_text = args_text.strip()
    if not args_text:
        _send_timer_usage_hint(message)
        return

    parts = args_text.split(maxsplit=1)
    time_part = parts[0]
    description = parts[1].strip() if len(parts) > 1 else ""

    duration_seconds = parse_duration(time_part)
    if duration_seconds is None:
        _send_timer_usage_hint(message)
        return

    create_timer(message, duration_seconds, description)


@bot.message_handler(commands=["t", "timer"])
def handle_timer_slash(message: types.Message):
    parts = message.text.split(maxsplit=1)
    args_text = parts[1] if len(parts) > 1 else ""
    _process_timer_request(message, args_text)


@bot.message_handler(
    func=lambda m: bool(re.match(r"^(тайм|таймер)\b", (m.text or ""), re.IGNORECASE))
)
def handle_timer_text(message: types.Message):
    parts = message.text.split(maxsplit=1)
    args_text = parts[1] if len(parts) > 1 else ""
    _process_timer_request(message, args_text)


def _show_my_timers(message: types.Message):
    user_id = message.from_user.id
    now = time.time()

    with _timers_lock:
        timer_ids = sorted(USER_TIMERS.get(user_id, set()))
        timers_info = [
            (tid, TIMERS[tid]["end_time"], TIMERS[tid]["description"])
            for tid in timer_ids
            if tid in TIMERS
        ]

    if not timers_info:
        bot.reply_to(message, "У вас нет активных таймеров.")
        return

    lines = ["<b>📑 Ваши активные таймеры:</b>"]
    for tid, end_time, description in timers_info:
        remaining = max(int(end_time - now), 0)
        desc_part = f" — {html.escape(description)}" if description else ""
        lines.append(f"• #{tid}: осталось {format_duration(remaining)}{desc_part}")

    lines.append("\nДля удаления используйте: <code>/del [ID]</code>")
    bot.reply_to(message, "\n".join(lines))


@bot.message_handler(commands=["my_timers"])
def handle_my_timers_command(message: types.Message):
    _show_my_timers(message)


@bot.message_handler(
    func=lambda m: bool(re.match(r"^таймеры\b", (m.text or ""), re.IGNORECASE))
)
def handle_my_timers_text(message: types.Message):
    _show_my_timers(message)


def _send_cancel_usage_hint(message: types.Message):
    """Подсказка по правильному формату команды удаления таймера."""
    bot.reply_to(
        message,
        "⚠️ Укажите ID таймера для удаления.\n"
        "Формат: <code>/del [ID]</code> или <code>удалить [ID]</code>\n"
        "Посмотреть свои ID можно командой /my_timers.",
    )


def _process_cancel_request(message: types.Message, args_text: str):
    args_text = args_text.strip()
    if not args_text:
        _send_cancel_usage_hint(message)
        return

    timer_id_str = args_text.split(maxsplit=1)[0].lstrip("#")

    if not timer_id_str.isdigit():
        _send_cancel_usage_hint(message)
        return

    timer_id = int(timer_id_str)
    result_text = cancel_timer(timer_id, message.from_user.id)
    bot.reply_to(message, result_text)


@bot.message_handler(commands=["del", "del_timer", "cancel"])
def handle_cancel_slash(message: types.Message):
    parts = message.text.split(maxsplit=1)
    args_text = parts[1] if len(parts) > 1 else ""
    _process_cancel_request(message, args_text)


@bot.message_handler(
    func=lambda m: bool(re.match(r"^(удалить|отмена)\b", (m.text or ""), re.IGNORECASE))
)
def handle_cancel_text(message: types.Message):
    parts = message.text.split(maxsplit=1)
    args_text = parts[1] if len(parts) > 1 else ""
    _process_cancel_request(message, args_text)


# =============================================================================
#                  МИНИ-СЕРВЕР ДЛЯ "ПРОБУЖДЕНИЯ" НА БЕСПЛАТНОМ ХОСТИНГЕ
# =============================================================================

web_app = Flask(__name__)


@web_app.route("/")
def health_check():
    """Render проверяет этот адрес, чтобы понять, что приложение живо."""
    return "Bot is running!"


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)


# =============================================================================
#                          ТОЧКА ВХОДА / ЗАПУСК БОТА
# =============================================================================

def main():
    logger.info("Бот запускается...")

    # Веб-сервер запускаем в отдельном потоке, чтобы он не блокировал polling
    threading.Thread(target=run_web_server, daemon=True).start()

    while True:
        try:
            logger.info("Запуск polling...")
            bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
        except Exception:
            logger.exception("Бот упал с ошибкой, перезапуск через 5 секунд...")
            time.sleep(5)


if __name__ == "__main__":
    main()