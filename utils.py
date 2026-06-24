"""
Общие хелперы, используемые разными частями бота: парсинг и форматирование
времени, упоминания пользователей, аптайм бота, разбивка длинных сообщений.
"""

import html
import re
import time


START_TIME = time.time()


# "1д5ч30м10с" или "1d5h30m10s" -> компоненты, все группы опциональны
_TIME_PATTERN = re.compile(
    r"^(?:(\d+)[дd])?(?:(\d+)[чh])?(?:(\d+)[мm])?(?:(\d+)[сs])?$",
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


def build_mention(user_id: int, first_name: str) -> str:
    """HTML-ссылка tg://user?id=... — тегает пользователя даже без username."""
    display_name = html.escape(first_name or "Пользователь")
    return f'<a href="tg://user?id={user_id}">{display_name}</a>'


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


def split_message(text: str, limit: int = 4000):
    """Делит длинный текст на части не длиннее limit символов по границам строк."""
    if len(text) <= limit:
        return [text]

    chunks = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def build_stats_report() -> str:
    """Формирует текст отчёта /стата: сводка + топ-10 по активности."""
    import database  # импорт здесь чтобы избежать циклических зависимостей

    total_users, total_chats, totals = database.get_stats_overview()
    top_rows = database.get_top_activity(limit=10)

    lines = [
        "<b>📊 Общая статистика</b>",
        "",
        f"👤 Пользователей: {total_users}",
        f"💬 Чатов: {total_chats}",
        f"✉️ Сообщений: {totals['messages']}",
        f"🔠 Символов: {totals['chars']}",
        f"🎟 Стикеров: {totals['stickers']}",
        f"🖼 Фото: {totals['photos']}",
        f"🎬 Видео: {totals['videos']}",
        f"🎤 Голосовых: {totals['voice']}",
        f"🎞 GIF: {totals['gifs']}",
        f"↩️ Пересланных: {totals['forwards']}",
    ]

    if top_rows:
        lines.append("")
        lines.append("<b>🏆 Топ-10 по активности</b>")
        for i, row in enumerate(top_rows, start=1):
            (username, first_name, chat_title,
             messages, chars, stickers, photos, videos, voice, gifs, forwards) = row

            display_name = f"@{username}" if username else (first_name or "Без имени")
            display_name = html.escape(display_name)
            chat_label = html.escape(chat_title or "Без названия")

            extra_parts = []
            if stickers:
                extra_parts.append(f"стикеры {stickers}")
            if photos:
                extra_parts.append(f"фото {photos}")
            if videos:
                extra_parts.append(f"видео {videos}")
            if voice:
                extra_parts.append(f"голосовые {voice}")
            if gifs:
                extra_parts.append(f"gif {gifs}")
            if forwards:
                extra_parts.append(f"пересланных {forwards}")
            extra = f" ({', '.join(extra_parts)})" if extra_parts else ""

            lines.append(
                f"{i}. {display_name} — {chat_label}: "
                f"{messages} сообщ., {chars} симв.{extra}"
            )

    return "\n".join(lines)