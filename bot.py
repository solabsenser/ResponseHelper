import asyncio
import logging
import os
import tempfile
from datetime import datetime
from typing import Optional
import aiofiles
import requests
from PIL import Image
import cv2
import pytesseract
import magic
from faster_whisper import WhisperModel

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

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Initialize database and AI
db = Database(TURSO_DATABASE_URL, TURSO_AUTH_TOKEN)
ai = AIAssistant(GROQ_API_KEY)

# Initialize Whisper model
whisper_model = None
try:
    whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
    logger.info("Whisper model loaded successfully")
except Exception as e:
    logger.error(f"Failed to load Whisper model: {e}")


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


# Middleware to track user
@dp.message.middleware()
async def user_middleware(message: Message, handler):
    """Track user and ensure they exist in database."""
    try:
        user = message.from_user
        if user:
            await db.get_or_create_user(
                user.id,
                user.username,
                user.first_name
            )
    except Exception as e:
        logger.error(f"User middleware error: {e}")
    return await handler(message, {})


@dp.callback_query.middleware()
async def callback_user_middleware(callback: CallbackQuery, handler):
    """Track user from callbacks."""
    try:
        user = callback.from_user
        if user:
            await db.get_or_create_user(
                user.id,
                user.username,
                user.first_name
            )
    except Exception as e:
        logger.error(f"Callback user middleware error: {e}")
    return await handler(callback, {})


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
    """Handle voice messages."""
    user_id = message.from_user.id
    
    # Check daily limit
    can_proceed, count = await db.check_daily_limit(user_id)
    if not can_proceed:
        await message.answer(
            "⚠️ You've reached your daily limit of 50 requests.\n"
            "Please try again tomorrow! 🌙"
        )
        return
    
    if not whisper_model:
        await message.answer(
            "❌ Voice transcription is not available at the moment.\n"
            "Please try sending text instead."
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
        
        # Transcribe using Whisper
        segments, info = whisper_model.transcribe(voice_path, beam_size=5)
        text = " ".join([segment.text for segment in segments])
        
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
        # Open image with PIL
        image = Image.open(image_path)
        
        # Preprocess for better OCR
        image = preprocess_image(image)
        
        # Perform OCR
        text = pytesseract.image_to_string(image, lang='eng+rus')
        
        return text.strip() if text else None
        
    except Exception as e:
        logger.error(f"OCR error: {e}")
        return None


def preprocess_image(image: Image.Image) -> Image.Image:
    """Preprocess image for better OCR."""
    try:
        # Convert to grayscale
        gray = image.convert('L')
        
        # Convert to numpy array for OpenCV
        import numpy as np
        img_array = np.array(gray)
        
        # Apply threshold
        _, thresh = cv2.threshold(img_array, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Convert back to PIL
        return Image.fromarray(thresh)
        
    except Exception as e:
        logger.error(f"Preprocessing error: {e}")
        return image


# Callback handlers
@dp.callback_query(F.data.startswith("style_"))
async def handle_style_selection(callback: CallbackQuery, state: FSMContext):
    """Handle style selection."""
    style = callback.data.replace("style_", "")
    user_id = callback.from_user.id
    
    # Get stored data
    data = await state.get_data()
    content_type = data.get("content_type", "text")
    content = data.get("content")
    
    if not content:
        await callback.message.edit_text(
            "❌ Something went wrong. Please start over with /start"
        )
        await callback.answer()
        return
    
    # Process based on content type
    try:
        if content_type == "image" and isinstance(content, str) and content.endswith('.jpg'):
            # Generate from image (already processed)
            replies = ai.generate("image", content, style)
        elif content_type == "text":
            # Generate from text
            replies = ai.generate("text", content, style)
        else:
            replies = ["I couldn't generate replies for this content type."] * 3
        
        # Increment daily requests
        await db.increment_daily_requests(user_id)
        
        # Save to history
        await db.save_history(user_id, str(content)[:500], "\n".join(replies), style)
        
        # Save last request
        await db.save_last_request(user_id, str(content)[:500], "\n".join(replies), style)
        
        # Format response
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
        
        # Store for later use
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
    """Handle text action."""
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
    """Handle image action."""
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
    """Handle voice action."""
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
    """Handle history action."""
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
    """Handle stats action."""
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
    """Handle clear action."""
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
    """Handle more action - generate new replies."""
    user_id = callback.from_user.id
    
    # Check daily limit
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
    
    # Generate new replies with same style
    replies = ai.generate("text", content, style)
    
    # Increment daily requests
    await db.increment_daily_requests(user_id)
    
    # Save to history
    await db.save_history(user_id, str(content)[:500], "\n".join(replies), style)
    
    # Save last request
    await db.save_last_request(user_id, str(content)[:500], "\n".join(replies), style)
    
    # Update state
    await state.update_data(last_replies=replies)
    
    # Format response
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
    """Handle change style action."""
    data = await state.get_data()
    content = data.get("content")
    
    if not content:
        await callback.message.edit_text(
            "❌ I lost your context. Please start over with /start"
        )
        await callback.answer()
        return
    
    # Store content and set state
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
    """Handle main menu action."""
    await callback.message.edit_text(
        "🏠 <b>Main Menu</b>\n\n"
        "What would you like to do?",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()


# Error handlers
@dp.errors()
async def error_handler(update, exception):
    """Handle errors gracefully."""
    logger.error(f"Update: {update}, Exception: {exception}")
    
    if isinstance(update, types.Message):
        await update.answer(
            "❌ An error occurred. Please try again later."
        )
    return True


async def main():
    """Main entry point."""
    try:
        # Initialize database tables
        await db._init_tables()
        logger.info("✅ Database initialized")
        
        logger.info("🚀 Starting ReplyGo bot...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
