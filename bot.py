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
    """Get main inline keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Text", callback_data="action_text")
    builder.button(text="📸 Screenshot", callback_data="action_image")
    builder.button(text="🎤 Voice", callback_data="action_voice")
    builder.button(text="📊 History", callback_data="action_history")
    builder.button(text="📈 Stats", callback_data="action_stats")
    builder.button(text="🗑 Clear History", callback_data="action_clear")
    builder.adjust(2)
    return builder.as_markup()


def get_style_keyboard() -> InlineKeyboardMarkup:
    """Get style selection keyboard."""
    builder = InlineKeyboardBuilder()
    styles = [
        ("🙂 Calm", "calm"),
        ("😎 Confident", "confident"),
        ("😂 Funny", "funny"),
        ("🔥 Hard", "hard"),
        ("❤️ Friendly", "friendly"),
        ("💼 Business", "business"),
        ("🧠 Smart", "smart"),
        ("🤝 End conflict", "conflict"),
        ("😏 Sarcastic", "sarcastic"),
        ("🎯 Short", "short"),
        ("✨ Improve my reply", "improve")
    ]
    for label, style in styles:
        builder.button(text=label, callback_data=f"style_{style}")
    builder.adjust(3)
    return builder.as_markup()


def get_reply_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard after generating replies."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 More", callback_data="action_more")
    builder.button(text="🎨 Change style", callback_data="action_change_style")
    builder.button(text="🗑 Clear", callback_data="action_clear")
    builder.button(text="🏠 Main", callback_data="action_main")
    builder.adjust(2)
    return builder.as_markup()


def format_replies(replies: list) -> str:
    """Format reply options for display."""
    return "\n\n".join([f"{i+1}. {reply}" for i, reply in enumerate(replies)])


# Middleware to track user - исправленная версия для aiogram 3.x
@dp.message.middleware()
async def user_middleware(handler, event, data):
    """Track user and ensure they exist in database."""
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
    """Track user from callbacks."""
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
    """Handle /start command."""
    welcome_text = (
        "👋 <b>Welcome to ReplyGo!</b>\n\n"
        "I'm your AI assistant that helps you craft the perfect replies.\n\n"
        "<b>What I can do:</b>\n"
        "📝 Generate replies from text\n"
        "📸 Extract text from screenshots\n"
        "🎤 Transcribe and reply to voice messages\n\n"
        "<b>How to use:</b>\n"
        "1. Send me a message, screenshot, or voice\n"
        "2. Choose a reply style\n"
        "3. Get 3 natural reply options!\n\n"
        "<b>Daily limit:</b> 50 requests\n\n"
        "Click the button below to get started! 👇"
    )
    
    keyboard = get_main_keyboard()
    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="HTML")


# Message handlers
@dp.message(F.text & ~F.text.startswith('/'))
async def handle_text(message: Message, state: FSMContext):
    """Handle text messages."""
    user_id = message.from_user.id
    
    # Check daily limit
    can_proceed, count = await db.check_daily_limit(user_id)
    if not can_proceed:
        await message.answer(
            "⚠️ You've reached your daily limit of 50 requests.\n"
            "Please try again tomorrow! 🌙"
        )
        return
    
    # Store text in state
    await state.update_data(content_type="text", content=message.text)
    await state.set_state(ReplyStates.waiting_for_style_after_text)
    
    await message.answer(
        f"📝 <b>Great! Now choose a reply style:</b>\n\n"
        f"Message: \"{message.text[:50]}{'...' if len(message.text) > 50 else ''}\"",
        reply_markup=get_style_keyboard(),
        parse_mode="HTML"
    )


@dp.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    """Handle photo messages."""
    user_id = message.from_user.id
    
    # Check daily limit
    can_proceed, count = await db.check_daily_limit(user_id)
    if not can_proceed:
        await message.answer(
            "⚠️ You've reached your daily limit of 50 requests.\n"
            "Please try again tomorrow! 🌙"
        )
        return
    
    # Download and process photo
    await message.answer("📸 Processing your screenshot... This may take a moment.")
    
    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        file_path = file.file_path
        
        # Download to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
            await bot.download_file(file_path, tmp_file.name)
            tmp_path = tmp_file.name
        
        # OCR the image
        text = ocr_image(tmp_path)
        
        # Clean up temp file
        os.unlink(tmp_path)
        
        if not text:
            # Try Groq Vision
            await message.answer("🔄 Trying AI vision for text extraction...")
            
            # Download image for Groq Vision
            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
                await bot.download_file(file_path, tmp_file.name)
                image_path = tmp_file.name
            
            # Generate replies using Groq Vision
            replies = ai.generate("image", image_path, "smart")
            
            # Clean up
            os.unlink(image_path)
            
            if not replies or len(replies) < 3:
                await message.answer(
                    "❌ I couldn't extract text from this image.\n"
                    "Please try with a clearer screenshot or send text instead."
                )
                return
            
            # Store context
            await state.update_data(
                content_type="image",
                content=image_path,
                extracted_text=text or "Unknown text"
            )
            await state.set_state(ReplyStates.waiting_for_style_after_image)
            
            await message.answer(
                "✅ Text extracted from image!\n\n"
                "Now choose a reply style:",
                reply_markup=get_style_keyboard()
            )
            return
        
        # Store text from OCR
        await state.update_data(
            content_type="text",
            content=text,
            extracted_text=text
        )
        await state.set_state(ReplyStates.waiting_for_style_after_text)
        
        await message.answer(
            f"📝 <b>Text extracted from image:</b>\n\n"
            f"\"{text[:100]}{'...' if len(text) > 100 else ''}\"\n\n"
            "Now choose a reply style:",
            reply_markup=get_style_keyboard(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Error processing photo: {e}")
        await message.answer(
            "❌ Sorry, I couldn't process this image.\n"
            "Please try sending a clearer screenshot or use text instead."
        )


@dp.message(F.voice)
async def handle_voice(message: Message, state: FSMContext):
    """Handle voice messages using Groq Whisper API."""
    user_id = message.from_user.id
    
    # Check daily limit
    can_proceed, count = await db.check_daily_limit(user_id)
    if not can_proceed:
        await message.answer(
            "⚠️ You've reached your daily limit of 50 requests.\n"
            "Please try again tomorrow! 🌙"
        )
        return
    
    await message.answer("🎤 Transcribing your voice message... This may take a moment.")
    
    try:
        voice = message.voice
        file = await bot.get_file(voice.file_id)
        file_path = file.file_path
        
        # Download to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.ogg') as tmp_file:
            await bot.download_file(file_path, tmp_file.name)
            voice_path = tmp_file.name
        
        # Transcribe using Groq Whisper
        text = await ai.transcribe_audio(voice_path)
        
        # Clean up temp file
        os.unlink(voice_path)
        
        if not text or len(text.strip()) < 2:
            await message.answer(
                "❌ I couldn't transcribe this voice message.\n"
                "Please try speaking more clearly or send text instead."
            )
            return
        
        # Store text
        await state.update_data(content_type="text", content=text)
        await state.set_state(ReplyStates.waiting_for_style_after_voice)
        
        await message.answer(
            f"📝 <b>Transcribed text:</b>\n\n"
            f"\"{text[:100]}{'...' if len(text) > 100 else ''}\"\n\n"
            "Now choose a reply style:",
            reply_markup=get_style_keyboard(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Error processing voice: {e}")
        await message.answer(
            "❌ Sorry, I couldn't process this voice message.\n"
            "Please try again or send text instead."
        )


def ocr_image(image_path: str) -> Optional[str]:
    """Extract text from image using OCR."""
    try:
        image = Image.open(image_path)
        image = preprocess_image(image)
        text = pytesseract.image_to_string(image, lang='eng+rus')
        text = text.strip()
        if not text or len(text) < 3:
            text = pytesseract.image_to_string(image, lang='eng')
            text = text.strip()
        return text if text else None
    except Exception as e:
        logger.error(f"OCR error: {e}")
        return None


def preprocess_image(image: Image.Image) -> Image.Image:
    """Preprocess image for better OCR using PIL only."""
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
    """Handle style selection."""
    style = callback.data.replace("style_", "")
    user_id = callback.from_user.id
    
    data = await state.get_data()
    content_type = data.get("content_type", "text")
    content = data.get("content")
    
    if not content:
        await callback.message.edit_text(
            "❌ Something went wrong. Please start over with /start"
        )
        await callback.answer()
        return
    
    try:
        if content_type == "image" and isinstance(content, str) and content.endswith('.jpg'):
            replies = ai.generate("image", content, style)
        elif content_type == "text":
            replies = ai.generate("text", content, style)
        else:
            replies = ["I couldn't generate replies for this content type."] * 3
        
        await db.increment_daily_requests(user_id)
        await db.save_history(user_id, str(content)[:500], "\n".join(replies), style)
        await db.save_last_request(user_id, str(content)[:500], "\n".join(replies), style)
        
        replies_text = format_replies(replies)
        today_stats = await db.get_today_stats(user_id)
        
        await callback.message.edit_text(
            f"🎯 <b>Here are your reply options</b> [{style} style]\n\n"
            f"{replies_text}\n\n"
            f"📊 Today's usage: {today_stats}/50\n\n"
            "What would you like to do next?",
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
            "❌ Sorry, I couldn't generate replies right now.\n"
            "Please try again later."
        )
        await callback.answer()


@dp.callback_query(F.data == "action_text")
async def handle_action_text(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📝 <b>Send me any text message</b>\n\n"
        "I'll analyze it and generate 3 natural reply options.\n\n"
        "Just type your message below! ✍️",
        parse_mode="HTML"
    )
    await state.set_state(ReplyStates.waiting_for_text)
    await callback.answer()


@dp.callback_query(F.data == "action_image")
async def handle_action_image(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📸 <b>Send me a screenshot</b>\n\n"
        "I'll extract text from it and generate reply options.\n\n"
        "Make sure the text is clear and readable! 📱",
        parse_mode="HTML"
    )
    await state.set_state(ReplyStates.waiting_for_image)
    await callback.answer()


@dp.callback_query(F.data == "action_voice")
async def handle_action_voice(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🎤 <b>Send me a voice message</b>\n\n"
        "I'll transcribe it and generate reply options.\n\n"
        "Speak clearly for best results! 🗣️",
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
            "📊 <b>Your history is empty</b>\n\n"
            "Start generating replies to build your history!",
            parse_mode="HTML"
        )
        await callback.answer()
        return
    
    history_text = "📊 <b>Your Reply History</b>\n\n"
    for i, item in enumerate(history[:5], 1):
        created_at = item.get('created_at', '')
        if isinstance(created_at, str):
            created_at = created_at[:19]
        history_text += f"#{i} <b>{item['style']}</b>\n"
        history_text += f"📝 Input: {item['input'][:50]}...\n"
        history_text += f"💬 Output: {item['output'][:50]}...\n"
        history_text += f"⏰ {created_at}\n\n"
    
    if len(history) > 5:
        history_text += f"\n... and {len(history) - 5} more entries"
    
    await callback.message.edit_text(
        history_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back", callback_data="action_main")]
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
        f"📈 <b>Your Stats</b>\n\n"
        f"Today's usage: {today_stats}/50\n"
        f"Total in history: {history_count}\n\n"
        "Keep going! 💪",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back", callback_data="action_main")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "action_clear")
async def handle_action_clear(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await db.clear_history(user_id)
    await state.clear()
    
    await callback.message.edit_text(
        "🗑 <b>Your history has been cleared</b>\n\n"
        "Ready to start fresh! ✨",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Main Menu", callback_data="action_main")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "action_more")
async def handle_action_more(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    can_proceed, count = await db.check_daily_limit(user_id)
    if not can_proceed:
        await callback.message.edit_text(
            "⚠️ You've reached your daily limit of 50 requests.\n"
            "Please try again tomorrow! 🌙"
        )
        await callback.answer()
        return
    
    data = await state.get_data()
    content = data.get("content")
    style = data.get("current_style", "smart")
    
    if not content:
        await callback.message.edit_text(
            "❌ I lost your context. Please start over with /start"
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
        f"🔄 <b>New reply options</b> [{style} style]\n\n"
        f"{replies_text}\n\n"
        f"📊 Today's usage: {today_stats}/50\n\n"
        "What would you like to do next?",
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
            "❌ I lost your context. Please start over with /start"
        )
        await callback.answer()
        return
    
    await state.update_data(content_type="text", content=content)
    await state.set_state(ReplyStates.waiting_for_style_after_text)
    
    await callback.message.edit_text(
        "🎨 <b>Choose a new style:</b>\n\n"
        "Pick a different style to get new reply options.",
        reply_markup=get_style_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "action_main")
async def handle_action_main(callback: CallbackQuery):
    await callback.message.edit_text(
        "🏠 <b>Main Menu</b>\n\n"
        "What would you like to do?",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()


# Error handler - исправленная версия
@dp.errors()
async def error_handler(event, exception):
    """Handle errors gracefully."""
    logger.error(f"Event: {event}, Exception: {exception}")
    
    # Try to notify user if possible
    try:
        if hasattr(event, 'message') and event.message:
            await event.message.answer("❌ An error occurred. Please try again later.")
        elif hasattr(event, 'callback_query') and event.callback_query:
            await event.callback_query.message.answer("❌ An error occurred. Please try again later.")
    except:
        pass
    
    return True


# Web server for health check
async def health_check(request):
    """Health check endpoint for Render."""
    return web.Response(text="OK", status=200)


async def start_web():
    """Start web server for health checks."""
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
    """Main entry point."""
    try:
        # Initialize database tables
        await db._ensure_initialized()
        logger.info("✅ Database initialized")
        
        # Start web server for health checks
        await start_web()
        
        # Start bot
        logger.info("🚀 Starting ReplyGo bot...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
