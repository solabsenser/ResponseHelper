import os
import asyncio
import logging
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from db import *
from ai import *

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

bot = Bot(
    TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()

# ------------------------
# Styles
# ------------------------

STYLES = {
    "calm": "🙂 Спокойно",
    "confident": "😎 Уверенно",
    "funny": "😂 С юмором",
    "hard": "🔥 Жестче",
    "friendly": "❤️ Дружелюбно",
    "business": "💼 Деловой",
    "smart": "🧠 Умно",
    "conflict": "🤝 Закрыть конфликт",
    "sarcasm": "😏 С сарказмом",
    "short": "🎯 Коротко",
    "better": "✨ Лучше моего"
}

# ------------------------
# Cache
# ------------------------

USER_CACHE = {}

# ------------------------
# Keyboard
# ------------------------

def style_keyboard():

    buttons = []

    row = []

    for key, value in STYLES.items():

        row.append(
            InlineKeyboardButton(
                text=value,
                callback_data=f"style:{key}"
            )
        )

        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(
            text="🗑 Очистить",
            callback_data="clear"
        )
    ])

    return InlineKeyboardMarkup(
        inline_keyboard=buttons
    )


def result_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="🔄 Еще",
                    callback_data="again"
                ),
                InlineKeyboardButton(
                    text="🎨 Другой стиль",
                    callback_data="styles"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🗑 Очистить",
                    callback_data="clear"
                )
            ]

        ]
    )

# ------------------------
# Start
# ------------------------

@dp.message(CommandStart())
async def start(message: Message):

    await add_user(message.from_user)

    text = """
<b>💬 ReplyGo</b>

Не знаешь что ответить?

Отправь:

• сообщение

• скриншот

• голосовое

Я предложу несколько вариантов ответа.
"""

    await message.answer(
        text,
        reply_markup=style_keyboard()
    )

# ------------------------
# Text
# ------------------------

@dp.message(F.text)

async def text_handler(message: Message):

    await add_user(message.from_user)

    USER_CACHE[message.from_user.id] = {
        "text": message.text,
        "type": "text"
    }

    await message.answer(
        "Выбери стиль 👇",
        reply_markup=style_keyboard()
    )

# ------------------------
# Photo
# ------------------------

@dp.message(F.photo)

async def photo_handler(message: Message):

    await add_user(message.from_user)

    file = await bot.get_file(
        message.photo[-1].file_id
    )

    path = f"temp_{message.from_user.id}.jpg"

    await bot.download_file(
        file.file_path,
        path
    )

    USER_CACHE[message.from_user.id] = {
        "type": "photo",
        "photo": path
    }

    await message.answer(
        "📸 Скриншот получен.\n\nВыбери стиль.",
        reply_markup=style_keyboard()
    )

# ------------------------
# Voice
# ------------------------

@dp.message(F.voice)

async def voice_handler(message: Message):

    await add_user(message.from_user)

    file = await bot.get_file(
        message.voice.file_id
    )

    path = f"voice_{message.from_user.id}.ogg"

    await bot.download_file(
        file.file_path,
        path
    )

    USER_CACHE[message.from_user.id] = {
        "type": "voice",
        "voice": path
    }

    await message.answer(
        "🎤 Голосовое получено.\n\nВыбери стиль.",
        reply_markup=style_keyboard()
    )

# ------------------------
# Callbacks
# ------------------------

@dp.callback_query(F.data == "clear")
async def clear_callback(call: CallbackQuery):

    USER_CACHE.pop(call.from_user.id, None)

    await call.message.edit_text(
        "🗑 Контекст очищен.\n\nОтправь новое сообщение, скриншот или голосовое."
    )

    await call.answer()


@dp.callback_query(F.data == "styles")
async def styles_callback(call: CallbackQuery):

    await call.message.edit_reply_markup(
        reply_markup=style_keyboard()
    )

    await call.answer()


@dp.callback_query(F.data == "again")
async def again_callback(call: CallbackQuery):

    cache = USER_CACHE.get(call.from_user.id)

    if not cache:
        await call.answer("Нет данных.", show_alert=True)
        return

    style = cache.get("last_style", "calm")

    await call.message.edit_text(
        "🧠 Генерирую новые варианты..."
    )

    try:

        if cache["type"] == "text":

            answer = await generate_text(
                cache["text"],
                style
            )

        elif cache["type"] == "photo":

            answer = await generate_photo(
                cache["photo"],
                style
            )

        else:

            answer = await generate_voice(
                cache["voice"],
                style
            )

        cache["last_answer"] = answer

        await call.message.edit_text(
            answer,
            reply_markup=result_keyboard()
        )

    except Exception as e:

        logging.exception(e)

        await call.message.edit_text(
            "❌ Не удалось сгенерировать ответ."
        )

    await call.answer()


@dp.callback_query(F.data.startswith("style:"))
async def style_callback(call: CallbackQuery):

    cache = USER_CACHE.get(call.from_user.id)

    if not cache:
        await call.answer(
            "Сначала отправь сообщение.",
            show_alert=True
        )
        return

    style = call.data.split(":")[1]

    cache["last_style"] = style

    await call.message.edit_text(
        "🧠 Думаю..."
    )

    try:

        if cache["type"] == "text":

            result = await generate_text(
                cache["text"],
                style
            )

            original = cache["text"]

        elif cache["type"] == "photo":

            result = await generate_photo(
                cache["photo"],
                style
            )

            original = "[PHOTO]"

        else:

            result = await generate_voice(
                cache["voice"],
                style
            )

            original = "[VOICE]"

        cache["last_answer"] = result

        await save_history(
            call.from_user.id,
            original,
            result,
            style
        )

        await increase_requests(
            call.from_user.id
        )

        title = STYLES.get(style, "Ответ")

        await call.message.edit_text(
            f"<b>{title}</b>\n\n{result}",
            reply_markup=result_keyboard()
        )

    except Exception as e:

        logging.exception(e)

        await call.message.edit_text(
            "❌ Произошла ошибка при генерации ответа."
        )

    await call.answer()


# ------------------------
# Unknown
# ------------------------

@dp.message()
async def unknown(message: Message):

    await message.answer(
        "Поддерживаются только:\n\n"
        "• текст\n"
        "• фото\n"
        "• голосовые"
    )


# ------------------------
# Startup
# ------------------------

async def on_startup():

    logging.info("Initializing database...")

    await init_db()

    logging.info("Bot started.")


async def main():

    await on_startup()

    await dp.start_polling(bot)


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print("Bot stopped.")
