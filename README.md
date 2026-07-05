# ReplyGo - AI Telegram Bot

ReplyGo is an AI-powered Telegram bot that helps you craft the perfect replies to messages using natural language processing.

## Features

### 📝 Text Processing
- Generate 3 natural reply options from any text
- 11 different reply styles to choose from
- Natural, human-like responses

### 📸 Screenshot OCR
- Extract text from screenshots using OCR
- Fallback to Groq Vision AI for better accuracy
- Support for multiple languages

### 🎤 Voice Messages
- Transcribe voice messages using Whisper
- Generate reply options from transcribed text
- Fast and accurate transcription

### ✨ Reply Styles
- 🙂 Calm
- 😎 Confident
- 😂 Funny
- 🔥 Hard
- ❤️ Friendly
- 💼 Business
- 🧠 Smart
- 🤝 End conflict
- 😏 Sarcastic
- 🎯 Short
- ✨ Improve my reply

### 📊 User Features
- 50 requests per day limit
- History tracking
- Daily usage statistics
- Clear history option
- Persistent user data

## Technology Stack

- **Python 3.11** - Core language
- **aiogram 3** - Telegram Bot API
- **Groq API** - AI language model
- **Turso (libsql)** - Database
- **Pillow & OpenCV** - Image processing
- **pytesseract** - OCR fallback
- **faster-whisper** - Voice transcription
- **Docker** - Containerization

## Installation

### Prerequisites
- Python 3.11+
- Docker (optional)
- Groq API key
- Turso database

### Local Development

1. Clone the repository:
```bash
git clone https://github.com/yourusername/replygo.git
cd replygo
