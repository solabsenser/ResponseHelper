import asyncio
import logging
import os
import tempfile
from datetime import datetime
from typing import Optional
import aiofiles
import requests
from PIL import Image, ImageEnhance
import pytesseract

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
from aiohttp import web

from db import Database
from ai import AIAssistant

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize bot
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")
PORT = int(os.getenv("PORT", 10000))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Initialize database and AI
db = Database(TURSO_DATABASE_URL, TURSO_AUTH_TOKEN)
ai = AIAssistant(GROQ_API_KEY)


# FSM States
class ReplyStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_style = State()
    waiting_for_image = State()
    waiting_for_voice = State()
    waiting_for_style_after_text = State()
    waiting_for_style_after_image = State()
    waiting_for_style_after_voice = State()


# Helper functions
def get_main_keyboard() -> InlineKeyboardMarkup:
    """Главное меню."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Текст", callback_data="action_text")
    builder.button(text="📸 Скриншот", callback_data="action_image")
    builder.button(text="🎤 Голос", callback_data="action_voice")
    builder.button(text="📊 История", callback_data="action_history")
    builder.button(text="📈 Статистика", callback_data="action_stats")
    builder.button(text="🗑 Очистить историю", callback_data="action_clear")
    builder.adjust(2)
    return builder.as_markup()


def get_style_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора стиля."""
    builder = InlineKeyboardBuilder()
    styles = [
        ("🙂 Спокойный", "calm"),
        ("😎 Уверенный", "confident"),
        ("😂 Смешной", "funny"),
        ("🔥 Жесткий", "hard"),
        ("❤️ Дружелюбный", "friendly"),
        ("💼 Деловой", "business"),
        ("🧠 Умный", "smart"),
        ("🤝 Помирить", "conflict"),
        ("😏 Саркастичный", "sarcastic"),
        ("🎯 Короткий", "short"),
        ("✨ Улучшить мой ответ", "improve")
    ]
    for label, style in styles:
        builder.button(text=label, callback_data=f"style_{style}")
    builder.adjust(3)
    return builder.as_markup()


def get_reply_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура после генерации ответов."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Ещё варианты", callback_data="action_more")
    builder.button(text="🎨 Сменить стиль", callback_data="action_change_style")
    builder.button(text="🗑 Очистить", callback_data="action_clear")
    builder.button(text="🏠 Главное меню", callback_data="action_main")
    builder.adjust(2)
    return builder.as_markup()


def format_replies(replies: list) -> str:
    """Форматирование ответов."""
    return "\n\n".join([f"{i+1}. {reply}" for i, reply in enumerate(replies)])


# Middleware
@dp.message.middleware()
async def user_middleware(handler, event, data):
    """Отслеживание пользователя."""
    try:
        message = event
        if message and hasattr(message, 'from_user') and message.from_user:
            user = message.from_user
            await db.get_or_create_user(
                user.id,
                user.username,
                user.first_name
            )
    except Exception as e:
        logger.error(f"User middleware error: {e}")
    return await handler(event, data)


@dp.callback_query.middleware()
async def callback_user_middleware(handler, event, data):
    """Отслеживание пользователя из callback."""
    try:
        callback = event
        if callback and hasattr(callback, 'from_user') and callback.from_user:
            user = callback.from_user
            await db.get_or_create_user(
                user.id,
                user.username,
                user.first_name
            )
    except Exception as e:
        logger.error(f"Callback user middleware error: {e}")
    return await handler(event, data)


# Command handlers
@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Команда /start."""
    welcome_text = (
        "👋 <b>Добро пожаловать в ReplyGo!</b>\n\n"
        "Я твой AI-помощник для создания идеальных ответов.\n\n"
        "<b>Что я умею:</b>\n"
        "📝 Генерировать ответы из текста\n"
        "📸 Извлекать текст из скриншотов\n"
        "🎤 Расшифровывать и отвечать на голосовые сообщения\n\n"
        "<b>Как пользоваться:</b>\n"
        "1. Отправь мне текст, скриншот или голосовое\n"
        "2. Выбери стиль ответа\n"
        "3. Получи 3 варианта ответа!\n\n"
        "<b>Лимит:</b> 50 запросов в день\n\n"
        "Нажми на кнопку ниже, чтобы начать! 👇"
    )
    
    keyboard = get_main_keyboard()
    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="HTML")


# Message handlers
@dp.message(F.text & ~F.text.startswith('/'))
async def handle_text(message: Message, state: FSMContext):
    """Обработка текстовых сообщений."""
    user_id = message.from_user.id
    
    can_proceed, count = await db.check_daily_limit(user_id)
    if not can_proceed:
        await message.answer(
            "⚠️ Ты достиг дневного лимита в 50 запросов.\n"
            "Попробуй завтра! 🌙"
        )
        return
    
    await state.update_data(content_type="text", content=message.text)
    await state.set_state(ReplyStates.waiting_for_style_after_text)
    
    await message.answer(
        f"📝 <b>Отлично! Теперь выбери стиль ответа:</b>\n\n"
        f"Сообщение: \"{message.text[:50]}{'...' if len(message.text) > 50 else ''}\"",
        reply_markup=get_style_keyboard(),
        parse_mode="HTML"
    )


@dp.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    """Обработка фото."""
    user_id = message.from_user.id
    
    can_proceed, count = await db.check_daily_limit(user_id)
    if not can_proceed:
        await message.answer(
            "⚠️ Ты достиг дневного лимита в 50 запросов.\n"
            "Попробуй завтра! 🌙"
        )
        return
    
    await message.answer("📸 Обрабатываю твой скриншот... Это может занять несколько секунд.")
    
    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        file_path = file.file_path
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
            await bot.download_file(file_path, tmp_file.name)
            tmp_path = tmp_file.name
        
        text = ocr_image(tmp_path)
        os.unlink(tmp_path)
        
        if not text:
            await message.answer("🔄 Пробую AI зрение для извлечения текста...")
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
                await bot.download_file(file_path, tmp_file.name)
                image_path = tmp_file.name
            
            replies = ai.generate("image", image_path, "smart")
            os.unlink(image_path)
            
            if not replies or len(replies) < 3:
                await message.answer(
                    "❌ Не удалось извлечь текст из этого изображения.\n"
                    "Попробуй отправить более четкий скриншот или просто текст."
                )
                return
            
            await state.update_data(
                content_type="image",
                content=image_path,
                extracted_text=text or "Неизвестный текст"
            )
            await state.set_state(ReplyStates.waiting_for_style_after_image)
            
            await message.answer(
                "✅ Текст извлечен из изображения!\n\n"
                "Теперь выбери стиль ответа:",
                reply_markup=get_style_keyboard()
            )
            return
        
        await state.update_data(
            content_type="text",
            content=text,
            extracted_text=text
        )
        await state.set_state(ReplyStates.waiting_for_style_after_text)
        
        await message.answer(
            f"📝 <b>Текст извлечен из изображения:</b>\n\n"
            f"\"{text[:100]}{'...' if len(text) > 100 else ''}\"\n\n"
            "Теперь выбери стиль ответа:",
            reply_markup=get_style_keyboard(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Error processing photo: {e}")
        await message.answer(
            "❌ Не удалось обработать это изображение.\n"
            "Попробуй отправить более четкий скриншот или используй текст."
        )


@dp.message(F.voice)
async def handle_voice(message: Message, state: FSMContext):
    """Обработка голосовых сообщений."""
    user_id = message.from_user.id
    
    can_proceed, count = await db.check_daily_limit(user_id)
    if not can_proceed:
        await message.answer(
            "⚠️ Ты достиг дневного лимита в 50 запросов.\n"
            "Попробуй завтра! 🌙"
        )
        return
    
    await message.answer("🎤 Расшифровываю голосовое сообщение... Это может занять несколько секунд.")
    
    try:
        voice = message.voice
        file = await bot.get_file(voice.file_id)
        file_path = file.file_path
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.ogg') as tmp_file:
            await bot.download_file(file_path, tmp_file.name)
            voice_path = tmp_file.name
        
        text = await ai.transcribe_audio(voice_path)
        os.unlink(voice_path)
        
        if not text or len(text.strip()) < 2:
            await message.answer(
                "❌ Не удалось расшифровать голосовое сообщение.\n"
                "Попробуй говорить более четко или отправь текст."
            )
            return
        
        await state.update_data(content_type="text", content=text)
        await state.set_state(ReplyStates.waiting_for_style_after_voice)
        
        await message.answer(
            f"📝 <b>Расшифрованный текст:</b>\n\n"
            f"\"{text[:100]}{'...' if len(text) > 100 else ''}\"\n\n"
            "Теперь выбери стиль ответа:",
            reply_markup=get_style_keyboard(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Error processing voice: {e}")
        await message.answer(
            "❌ Не удалось обработать голосовое сообщение.\n"
            "Попробуй еще раз или отправь текст."
        )


def ocr_image(image_path: str) -> Optional[str]:
    """Извлечение текста из изображения."""
    try:
        image = Image.open(image_path)
        image = preprocess_image(image)
        text = pytesseract.image_to_string(image, lang='rus+eng')
        text = text.strip()
        if not text or len(text) < 3:
            text = pytesseract.image_to_string(image, lang='rus')
            text = text.strip()
        return text if text else None
    except Exception as e:
        logger.error(f"OCR error: {e}")
        return None


def preprocess_image(image: Image.Image) -> Image.Image:
    """Предобработка изображения для OCR."""
    try:
        if image.mode != 'L':
            image = image.convert('L')
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(2.0)
        enhancer = ImageEnhance.Sharpness(image)
        image = enhancer.enhance(2.0)
        threshold = 128
        image = image.point(lambda p: p > threshold and 255)
        return image
    except Exception as e:
        logger.error(f"Preprocessing error: {e}")
        return image


# Callback handlers
@dp.callback_query(F.data.startswith("style_"))
async def handle_style_selection(callback: CallbackQuery, state: FSMContext):
    """Выбор стиля."""
    style = callback.data.replace("style_", "")
    user_id = callback.from_user.id
    
    data = await state.get_data()
    content_type = data.get("content_type", "text")
    content = data.get("content")
    
    # Словарь для перевода стилей на русский
    style_names = {
        "calm": "спокойный",
        "confident": "уверенный",
        "funny": "смешной",
        "hard": "жесткий",
        "friendly": "дружелюбный",
        "business": "деловой",
        "smart": "умный",
        "conflict": "помирить",
        "sarcastic": "саркастичный",
        "short": "короткий",
        "improve": "улучшить ответ"
    }
    
    if not content:
        await callback.message.edit_text(
            "❌ Что-то пошло не так. Начни заново с /start"
        )
        await callback.answer()
        return
    
    try:
        if content_type == "image" and isinstance(content, str) and content.endswith('.jpg'):
            replies = ai.generate("image", content, style)
        elif content_type == "text":
            replies = ai.generate("text", content, style)
        else:
            replies = ["Не удалось сгенерировать ответы."] * 3
        
        await db.increment_daily_requests(user_id)
        await db.save_history(user_id, str(content)[:500], "\n".join(replies), style)
        await db.save_last_request(user_id, str(content)[:500], "\n".join(replies), style)
        
        replies_text = format_replies(replies)
        today_stats = await db.get_today_stats(user_id)
        style_ru = style_names.get(style, style)
        
        await callback.message.edit_text(
            f"🎯 <b>Вот твои варианты ответов</b> [стиль: {style_ru}]\n\n"
            f"{replies_text}\n\n"
            f"📊 Сегодня использовано: {today_stats}/50\n\n"
            "Что хочешь сделать дальше?",
            reply_markup=get_reply_keyboard(),
            parse_mode="HTML"
        )
        
        await state.update_data(
            last_style=style,
            last_replies=replies,
            current_style=style
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error generating replies: {e}")
        await callback.message.edit_text(
            "❌ Не удалось сгенерировать ответы.\n"
            "Попробуй позже."
        )
        await callback.answer()


@dp.callback_query(F.data == "action_text")
async def handle_action_text(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📝 <b>Отправь мне любое текстовое сообщение</b>\n\n"
        "Я проанализирую его и сгенерирую 3 варианта ответа.\n\n"
        "Просто напиши сообщение ниже! ✍️",
        parse_mode="HTML"
    )
    await state.set_state(ReplyStates.waiting_for_text)
    await callback.answer()


@dp.callback_query(F.data == "action_image")
async def handle_action_image(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📸 <b>Отправь мне скриншот</b>\n\n"
        "Я извлеку текст из него и сгенерирую варианты ответов.\n\n"
        "Убедись, что текст четкий и читаемый! 📱",
        parse_mode="HTML"
    )
    await state.set_state(ReplyStates.waiting_for_image)
    await callback.answer()


@dp.callback_query(F.data == "action_voice")
async def handle_action_voice(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🎤 <b>Отправь мне голосовое сообщение</b>\n\n"
        "Я расшифрую его и сгенерирую варианты ответов.\n\n"
        "Говори четко для лучшего результата! 🗣️",
        parse_mode="HTML"
    )
    await state.set_state(ReplyStates.waiting_for_voice)
    await callback.answer()


@dp.callback_query(F.data == "action_history")
async def handle_action_history(callback: CallbackQuery):
    user_id = callback.from_user.id
    history = await db.get_history(user_id)
    
    if not history:
        await callback.message.edit_text(
            "📊 <b>Твоя история пуста</b>\n\n"
            "Начни генерировать ответы, чтобы заполнить историю!",
            parse_mode="HTML"
        )
        await callback.answer()
        return
    
    history_text = "📊 <b>Твоя история ответов</b>\n\n"
    for i, item in enumerate(history[:5], 1):
        created_at = item.get('created_at', '')
        if isinstance(created_at, str):
            created_at = created_at[:19]
        history_text += f"#{i} <b>{item['style']}</b>\n"
        history_text += f"📝 Вход: {item['input'][:50]}...\n"
        history_text += f"💬 Ответ: {item['output'][:50]}...\n"
        history_text += f"⏰ {created_at}\n\n"
    
    if len(history) > 5:
        history_text += f"\n... и еще {len(history) - 5} записей"
    
    await callback.message.edit_text(
        history_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="action_main")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "action_stats")
async def handle_action_stats(callback: CallbackQuery):
    user_id = callback.from_user.id
    today_stats = await db.get_today_stats(user_id)
    history = await db.get_history(user_id)
    history_count = len(history)
    
    await callback.message.edit_text(
        f"📈 <b>Твоя статистика</b>\n\n"
        f"Сегодня использовано: {today_stats}/50\n"
        f"Всего в истории: {history_count}\n\n"
        "Продолжай в том же духе! 💪",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="action_main")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "action_clear")
async def handle_action_clear(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await db.clear_history(user_id)
    await state.clear()
    
    await callback.message.edit_text(
        "🗑 <b>История очищена</b>\n\n"
        "Готов начать заново! ✨",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="action_main")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "action_more")
async def handle_action_more(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    can_proceed, count = await db.check_daily_limit(user_id)
    if not can_proceed:
        await callback.message.edit_text(
            "⚠️ Ты достиг дневного лимита в 50 запросов.\n"
            "Попробуй завтра! 🌙"
        )
        await callback.answer()
        return
    
    data = await state.get_data()
    content = data.get("content")
    style = data.get("current_style", "smart")
    
    if not content:
        await callback.message.edit_text(
            "❌ Я потерял контекст. Начни заново с /start"
        )
        await callback.answer()
        return
    
    replies = ai.generate("text", content, style)
    await db.increment_daily_requests(user_id)
    await db.save_history(user_id, str(content)[:500], "\n".join(replies), style)
    await db.save_last_request(user_id, str(content)[:500], "\n".join(replies), style)
    await state.update_data(last_replies=replies)
    
    replies_text = format_replies(replies)
    today_stats = await db.get_today_stats(user_id)
    
    await callback.message.edit_text(
        f"🔄 <b>Новые варианты ответов</b> [стиль: {style}]\n\n"
        f"{replies_text}\n\n"
        f"📊 Сегодня использовано: {today_stats}/50\n\n"
        "Что хочешь сделать дальше?",
        reply_markup=get_reply_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "action_change_style")
async def handle_action_change_style(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    content = data.get("content")
    
    if not content:
        await callback.message.edit_text(
            "❌ Я потерял контекст. Начни заново с /start"
        )
        await callback.answer()
        return
    
    await state.update_data(content_type="text", content=content)
    await state.set_state(ReplyStates.waiting_for_style_after_text)
    
    await callback.message.edit_text(
        "🎨 <b>Выбери новый стиль:</b>\n\n"
        "Выбери другой стиль, чтобы получить новые варианты ответов.",
        reply_markup=get_style_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "action_main")
async def handle_action_main(callback: CallbackQuery):
    await callback.message.edit_text(
        "🏠 <b>Главное меню</b>\n\n"
        "Что хочешь сделать?",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()


# Error handler
@dp.errors()
async def error_handler(event, exception):
    logger.error(f"Event: {event}, Exception: {exception}")
    try:
        if hasattr(event, 'message') and event.message:
            await event.message.answer("❌ Произошла ошибка. Попробуй позже.")
        elif hasattr(event, 'callback_query') and event.callback_query:
            await event.callback_query.message.answer("❌ Произошла ошибка. Попробуй позже.")
    except:
        pass
    return True


# Web server for health check
async def health_check(request):
    return web.Response(text="OK", status=200)


async def start_web():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"✅ Web server started on port {PORT}")
    return app


async def main():
    try:
        await db._ensure_initialized()
        logger.info("✅ Database initialized")
        await start_web()
        logger.info("🚀 Запускаю ReplyGo бота...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())