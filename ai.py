import logging
import base64
from typing import List, Optional
import os
from groq import Groq

logger = logging.getLogger(__name__)


class AIAssistant:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = Groq(api_key=api_key)
        
        # Используем только рабочие модели
        self.text_model = "llama-3.1-70b-versatile"
        self.vision_model = "llama-3.2-11b-vision-preview"  # Работает с изображениями
        self.audio_model = "whisper-large-v3"
        
        self._test_api()
        logger.info(f"✅ AI Assistant готов к работе")

    def _test_api(self):
        """Проверка API ключа"""
        try:
            test = self.client.chat.completions.create(
                model=self.text_model,
                messages=[{"role": "user", "content": "Привет"}],
                max_tokens=10
            )
            logger.info("✅ Groq API работает")
        except Exception as e:
            logger.error(f"❌ Ошибка API: {e}")

    def _get_style_prompt(self, style: str) -> str:
        """Промпты для стилей ответов"""
        style_prompts = {
            "calm": "Будь спокойным и умиротворяющим. Используй мягкие слова. Сохраняй позитивный настрой.",
            "confident": "Будь уверенным и напористым. Используй прямые формулировки. Покажи убежденность.",
            "funny": "Будь юмористичным и остроумным. Используй игру слов. Развлекай собеседника.",
            "hard": "Будь сильным и прямым. Не уступай. Используй твердые формулировки. Никогда не генерируй угрозы, незаконные советы, ненависть или насилие.",
            "friendly": "Будь теплым и открытым. Используй дружелюбный тон. Проявляй искренний интерес.",
            "business": "Будь профессиональным и официальным. Используй деловой язык. Будь кратким.",
            "smart": "Будь умным и проницательным. Покажи глубокое понимание. Используй сложные формулировки.",
            "conflict": "Будь дипломатичным. Сосредоточься на разрешении конфликта. Используй нейтральный язык.",
            "sarcastic": "Будь остроумным и ироничным. Используй сарказм уместно. Сохраняй остроту.",
            "short": "Будь кратким и лаконичным. Используй короткие предложения. Переходи к сути.",
            "improve": "Улучши сообщение пользователя, сохраняя исходный смысл. Сделай его более четким и эффективным."
        }
        return style_prompts.get(style, "Будь естественным и человечным. Пиши как в Telegram.")

    def _build_prompt(self, content: str, style: str) -> str:
        """Создание промпта для модели"""
        style_instruction = self._get_style_prompt(style)
        
        return f"""Ты ReplyGo - помощник для генерации ответов в Telegram.

Сообщение пользователя: "{content}"

Стиль: {style}
Инструкция: {style_instruction}

Сгенерируй 3 варианта ответа в указанном стиле.
Правила:
- Ответы должны быть как у реального человека
- Не используй эмодзи (если стиль не требует)
- Не начинай с "Я понимаю", "Без проблем" и т.д.
- Каждый ответ - законченное предложение
- Ответы должны быть разными по смыслу

Формат:
1. [первый ответ]
2. [второй ответ]
3. [третий ответ]

Только ответы, без лишнего текста!"""

    def _parse_replies(self, response: str) -> List[str]:
        """Парсинг ответов от модели"""
        if not response:
            return self._get_fallback_replies()
        
        lines = response.strip().split('\n')
        replies = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Парсим формат "1. ответ"
            if line and line[0].isdigit() and '. ' in line:
                parts = line.split('. ', 1)
                if len(parts) == 2 and parts[1].strip():
                    replies.append(parts[1].strip())
            # Если нет нумерации, но есть текст
            elif line and not line.startswith(('1.', '2.', '3.')):
                if len(replies) < 3:
                    replies.append(line)
        
        # Если не хватает ответов
        while len(replies) < 3:
            if len(replies) == 0:
                return self._get_fallback_replies()
            replies.append(f"Вариант {len(replies) + 1}")
        
        return replies[:3]

    def _get_fallback_replies(self) -> List[str]:
        """Запасные ответы на случай ошибки"""
        return [
            "Хорошая мысль! Согласен с тобой.",
            "Понимаю, о чем ты. Давай обсудим.",
            "Спасибо за сообщение! Ценю твой подход."
        ]

    def generate(self, content_type: str, content: any, style: str) -> List[str]:
        """Основной метод генерации ответов"""
        try:
            logger.info(f"Генерация ответов | Стиль: {style} | Тип: {content_type}")
            
            if content_type == "image":
                return self._generate_from_image(content, style)
            else:
                return self._generate_from_text(content, style)
                
        except Exception as e:
            logger.error(f"Ошибка генерации: {e}", exc_info=True)
            return self._get_fallback_replies()

    def _generate_from_text(self, text: str, style: str) -> List[str]:
        """Генерация из текста"""
        try:
            prompt = self._build_prompt(text, style)
            
            response = self.client.chat.completions.create(
                model=self.text_model,
                messages=[
                    {"role": "system", "content": "Ты полезный помощник."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.8,
                max_tokens=300
            )
            
            result = response.choices[0].message.content
            return self._parse_replies(result)
            
        except Exception as e:
            logger.error(f"Ошибка текстовой генерации: {e}")
            return self._get_fallback_replies()

    def _generate_from_image(self, image_path: str, style: str) -> List[str]:
        """Генерация из изображения"""
        try:
            # Пробуем через Vision API
            with open(image_path, "rb") as img:
                image_data = base64.b64encode(img.read()).decode("utf-8")
            
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_data}"
                            }
                        },
                        {
                            "type": "text",
                            "text": f"Извлеки текст из изображения и сгенерируй 3 ответа в стиле {style}"
                        }
                    ]
                }
            ]
            
            response = self.client.chat.completions.create(
                model=self.vision_model,
                messages=messages,
                temperature=0.8,
                max_tokens=300
            )
            
            result = response.choices[0].message.content
            return self._parse_replies(result)
            
        except Exception as e:
            logger.error(f"Ошибка обработки изображения: {e}")
            return [
                "Не удалось обработать изображение.",
                "Попробуй отправить текст.",
                "Или используй более четкий скриншот."
            ]

    async def transcribe_audio(self, audio_path: str) -> str:
        """Транскрипция голосового сообщения"""
        try:
            with open(audio_path, "rb") as audio_file:
                response = self.client.audio.transcriptions.create(
                    file=audio_file,
                    model=self.audio_model,
                    response_format="text"
                )
                return response.strip()
                
        except Exception as e:
            logger.error(f"Ошибка транскрипции: {e}")
            return ""

    def generate_from_voice(self, text: str, style: str) -> List[str]:
        """Генерация из транскрибированного голоса"""
        return self._generate_from_text(text, style)