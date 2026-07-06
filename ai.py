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
        
        # 🔥 АКТУАЛЬНЫЕ МОДЕЛИ (работают на 100%)
        self.text_model = "llama-3.3-70b-versatile"      # Самая новая текстовая
        self.vision_model = "llama-3.2-11b-vision-preview"  # Для изображений
        self.audio_model = "whisper-large-v3"            # Для голоса
        
        logger.info("=" * 50)
        logger.info("🤖 ИНИЦИАЛИЗАЦИЯ AI АССИСТЕНТА")
        logger.info(f"📝 Текстовая модель: {self.text_model}")
        logger.info(f"👁️ Vision модель: {self.vision_model}")
        logger.info(f"🎤 Аудио модель: {self.audio_model}")
        logger.info("=" * 50)
        
        self._test_api()

    def _test_api(self):
        """Проверка API ключа и доступности моделей"""
        try:
            logger.info("🔄 Тестирую подключение к Groq API...")
            
            # Пробуем новую модель
            test = self.client.chat.completions.create(
                model=self.text_model,
                messages=[{"role": "user", "content": "Скажи ОК"}],
                max_tokens=5
            )
            
            result = test.choices[0].message.content
            logger.info(f"✅ Groq API работает! Модель {self.text_model} доступна")
            logger.info(f"✅ Ответ: {result}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            logger.error("⚠️ Проверь GROQ_API_KEY в настройках Render")
            logger.error("⚠️ Также проверь https://console.groq.com/docs/models")

    def _get_style_prompt(self, style: str) -> str:
        """Промпты для стилей"""
        styles = {
            "calm": "Спокойный, мягкий, умиротворяющий тон. Используй добрые слова.",
            "confident": "Уверенный, прямой, убедительный тон. Без сомнений.",
            "funny": "Юмористичный, остроумный, игривый тон. Добавь легкую иронию.",
            "hard": "Твердый, прямой, бескомпромиссный тон. Без мягкостей.",
            "friendly": "Дружелюбный, теплый, открытый тон. Как лучший друг.",
            "business": "Деловой, профессиональный, официальный тон. Сухо и по делу.",
            "smart": "Умный, проницательный, глубокий тон. Покажи эрудицию.",
            "conflict": "Дипломатичный, примиряющий, нейтральный тон. Сгладь углы.",
            "sarcastic": "Саркастичный, ироничный, острый тон. С хитринкой.",
            "short": "Краткий, лаконичный, только суть. Максимум 5 слов.",
            "improve": "Улучши сообщение пользователя, сделай его лучше и понятнее."
        }
        return styles.get(style, "Естественный человеческий тон в переписке")

    def _build_prompt(self, content: str, style: str) -> str:
        """Создание промпта"""
        style_desc = self._get_style_prompt(style)
        style_names = {
            "calm": "спокойный", "confident": "уверенный", "funny": "смешной",
            "hard": "жесткий", "friendly": "дружелюбный", "business": "деловой",
            "smart": "умный", "conflict": "дипломатичный", "sarcastic": "саркастичный",
            "short": "короткий", "improve": "улучшенный"
        }
        style_ru = style_names.get(style, style)
        
        return f"""Ты ReplyGo - ассистент для генерации ответов в Telegram.

Сообщение пользователя: "{content}"

Сгенерируй 3 варианта ответа.
Стиль: {style_ru}
Характер: {style_desc}

ПРАВИЛА (строго соблюдать):
1. Ответы как от реального человека, НЕ как ChatGPT
2. НЕ используй: "Я понимаю", "Без проблем", "Вот варианты"
3. НЕ используй эмодзи и восклицательные знаки
4. Каждый ответ РАЗНЫЙ по смыслу
5. Коротко (1-2 предложения)
6. Разговорный язык

Формат:
1. [ответ 1]
2. [ответ 2]
3. [ответ 3]

Только ответы, без пояснений!"""

    def _parse_replies(self, response: str) -> List[str]:
        """Парсинг ответов"""
        if not response:
            return self._get_fallback_replies()
        
        lines = response.strip().split('\n')
        replies = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Формат "1. ответ" или "1) ответ"
            if line and len(line) > 2 and line[0].isdigit():
                if '. ' in line:
                    parts = line.split('. ', 1)
                    if len(parts) == 2 and parts[1].strip():
                        replies.append(parts[1].strip())
                        continue
                elif ') ' in line:
                    parts = line.split(') ', 1)
                    if len(parts) == 2 and parts[1].strip():
                        replies.append(parts[1].strip())
                        continue
            
            # Если строка без номера
            if len(replies) < 3 and line:
                replies.append(line)
        
        # Добиваем до 3
        while len(replies) < 3:
            if len(replies) == 0:
                return self._get_fallback_replies()
            replies.append(f"Вариант {len(replies) + 1}")
        
        return replies[:3]

    def _get_fallback_replies(self) -> List[str]:
        """Запасные ответы"""
        return [
            "Хорошая мысль! Полностью поддерживаю.",
            "Отличный подход! Давай обсудим детали.",
            "Согласен с тобой. Действуй!"
        ]

    def generate(self, content_type: str, content: any, style: str) -> List[str]:
        """Главная функция генерации"""
        try:
            logger.info(f"🔄 Генерация | Тип: {content_type} | Стиль: {style}")
            
            if content_type == "image":
                return self._generate_from_image(content, style)
            else:
                return self._generate_from_text(content, style)
                
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            return self._get_fallback_replies()

    def _generate_from_text(self, text: str, style: str) -> List[str]:
        """Генерация из текста"""
        try:
            prompt = self._build_prompt(text, style)
            
            response = self.client.chat.completions.create(
                model=self.text_model,
                messages=[
                    {"role": "system", "content": "Ты ассистент для генерации ответов."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.85,
                max_tokens=200
            )
            
            result = response.choices[0].message.content
            return self._parse_replies(result)
            
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            return self._get_fallback_replies()

    def _generate_from_image(self, image_path: str, style: str) -> List[str]:
        """Генерация из изображения"""
        try:
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
            logger.error(f"❌ Ошибка изображения: {e}")
            return [
                "Не удалось обработать изображение.",
                "Попробуй отправить текст.",
                "Используй более четкий скриншот."
            ]

    async def transcribe_audio(self, audio_path: str) -> str:
        """Транскрипция голоса"""
        try:
            with open(audio_path, "rb") as audio_file:
                response = self.client.audio.transcriptions.create(
                    file=audio_file,
                    model=self.audio_model,
                    response_format="text"
                )
                return response.strip()
        except Exception as e:
            logger.error(f"❌ Ошибка транскрипции: {e}")
            return ""

    def generate_from_voice(self, text: str, style: str) -> List[str]:
        """Генерация из голоса"""
        return self._generate_from_text(text, style)
