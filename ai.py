import logging
import base64
from typing import List, Optional
import os
import json
from groq import Groq

logger = logging.getLogger(__name__)


class AIAssistant:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = Groq(api_key=api_key)
        
        # Используем только рабочие модели
        self.text_model = "llama-3.1-70b-versatile"
        self.vision_model = "llama-3.2-11b-vision-preview"
        self.audio_model = "whisper-large-v3"
        
        logger.info("=" * 50)
        logger.info("🤖 ИНИЦИАЛИЗАЦИЯ AI АССИСТЕНТА")
        logger.info(f"📝 Текстовая модель: {self.text_model}")
        logger.info(f"👁️ Vision модель: {self.vision_model}")
        logger.info(f"🎤 Аудио модель: {self.audio_model}")
        logger.info("=" * 50)
        
        self._test_api()

    def _test_api(self):
        """Проверка API ключа"""
        try:
            logger.info("🔄 Тестирую подключение к Groq API...")
            
            test = self.client.chat.completions.create(
                model=self.text_model,
                messages=[{"role": "user", "content": "Скажи ОК"}],
                max_tokens=5,
                temperature=0.1
            )
            
            result = test.choices[0].message.content
            logger.info(f"✅ Groq API работает! Ответ: {result}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Groq API: {e}")
            logger.error(f"⚠️ Проверь GROQ_API_KEY в настройках Render")
            logger.error(f"⚠️ Убедись, что ключ активен на https://console.groq.com")

    def _get_style_prompt(self, style: str) -> str:
        """Промпты для стилей"""
        styles = {
            "calm": "Спокойный, мягкий, умиротворяющий тон",
            "confident": "Уверенный, прямой, убедительный тон",
            "funny": "Юмористичный, остроумный, игривый тон",
            "hard": "Твердый, прямой, бескомпромиссный тон",
            "friendly": "Дружелюбный, теплый, открытый тон",
            "business": "Деловой, профессиональный, официальный тон",
            "smart": "Умный, проницательный, глубокий тон",
            "conflict": "Дипломатичный, примиряющий, нейтральный тон",
            "sarcastic": "Саркастичный, ироничный, острый тон",
            "short": "Краткий, лаконичный, по делу",
            "improve": "Улучшить сообщение, сделать его лучше"
        }
        return styles.get(style, "Естественный человеческий тон")

    def _build_prompt(self, content: str, style: str) -> str:
        """Создание промпта"""
        style_desc = self._get_style_prompt(style)
        
        # Название стиля на русском
        style_names = {
            "calm": "спокойный",
            "confident": "уверенный",
            "funny": "смешной",
            "hard": "жесткий",
            "friendly": "дружелюбный",
            "business": "деловой",
            "smart": "умный",
            "conflict": "дипломатичный",
            "sarcastic": "саркастичный",
            "short": "короткий",
            "improve": "улучшенный"
        }
        style_ru = style_names.get(style, style)
        
        return f"""Ты — ReplyGo, ассистент для генерации ответов в Telegram.

Сообщение пользователя: "{content}"

Нужно сгенерировать 3 варианта ответа.
Стиль: {style_ru}
Описание стиля: {style_desc}

ВАЖНЫЕ ПРАВИЛА:
1. Ответы должны звучать КАК ОТ РЕАЛЬНОГО ЧЕЛОВЕКА
2. НЕ используй шаблонные фразы: "Я понимаю", "Без проблем", "Вот несколько вариантов"
3. НЕ используй эмодзи (если только это не требуется стилем)
4. НЕ используй "AI-слова": "безусловно", "в заключение", "следует отметить"
5. Каждый ответ должен быть РАЗНЫМ по смыслу
6. Ответы должны быть КОРОТКИМИ (1-2 предложения)
7. Используй разговорный язык как в переписке

Формат вывода (строго 3 пункта):
1. [первый вариант ответа]
2. [второй вариант ответа]
3. [третий вариант ответа]

Только ответы, без пояснений!"""

    def _parse_replies(self, response: str) -> List[str]:
        """Парсинг ответов"""
        if not response:
            logger.warning("⚠️ Пустой ответ от модели")
            return self._get_fallback_replies()
        
        logger.info(f"📥 Сырой ответ от модели: {response[:200]}...")
        
        lines = response.strip().split('\n')
        replies = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Ищем формат "1. ответ" или "1) ответ"
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
            
            # Если строка не начинается с цифры, добавляем как есть (если не хватает)
            if len(replies) < 3 and line:
                replies.append(line)
        
        # Если не хватает ответов
        while len(replies) < 3:
            if len(replies) == 0:
                logger.warning("⚠️ Не удалось распарсить ответы")
                return self._get_fallback_replies()
            replies.append(f"Вариант {len(replies) + 1}")
        
        logger.info(f"✅ Распаршено {len(replies)} ответов")
        for i, r in enumerate(replies, 1):
            logger.info(f"  {i}. {r[:50]}...")
        
        return replies[:3]

    def _get_fallback_replies(self) -> List[str]:
        """Запасные ответы"""
        logger.warning("⚠️ Использую запасные ответы")
        return [
            "Отличная мысль! Полностью поддерживаю.",
            "Хорошо сказано! Давай обсудим детали.",
            "Согласен с тобой. Отличный подход!"
        ]

    def generate(self, content_type: str, content: any, style: str) -> List[str]:
        """Генерация ответов"""
        try:
            logger.info(f"🔄 Генерация | Тип: {content_type} | Стиль: {style}")
            
            if content_type == "image":
                return self._generate_from_image(content, style)
            else:
                return self._generate_from_text(content, style)
                
        except Exception as e:
            logger.error(f"❌ Ошибка генерации: {e}")
            return self._get_fallback_replies()

    def _generate_from_text(self, text: str, style: str) -> List[str]:
        """Генерация из текста"""
        try:
            prompt = self._build_prompt(text, style)
            logger.info(f"📝 Промпт: {prompt[:100]}...")
            
            response = self.client.chat.completions.create(
                model=self.text_model,
                messages=[
                    {"role": "system", "content": "Ты ассистент для генерации естественных ответов."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.8,
                max_tokens=250,
                top_p=0.9
            )
            
            result = response.choices[0].message.content
            logger.info("📥 Получен ответ от модели")
            return self._parse_replies(result)
            
        except Exception as e:
            logger.error(f"❌ Ошибка текстовой генерации: {e}")
            logger.error(f"Детали: {str(e)}")
            return self._get_fallback_replies()

    def _generate_from_image(self, image_path: str, style: str) -> List[str]:
        """Генерация из изображения"""
        try:
            with open(image_path, "rb") as img:
                image_data = base64.b64encode(img.read()).decode("utf-8")
            
            logger.info("🔄 Отправка изображения в Groq Vision...")
            
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
                            "text": f"Извлеки текст из этого изображения и сгенерируй 3 ответа в стиле {style}. Ответы должны быть естественными и человечными."
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
            logger.info("📥 Получен ответ от Vision модели")
            return self._parse_replies(result)
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки изображения: {e}")
            return [
                "Не удалось обработать изображение.",
                "Попробуй отправить текст вместо скриншота.",
                "Или используй более четкое изображение."
            ]

    async def transcribe_audio(self, audio_path: str) -> str:
        """Транскрипция аудио"""
        try:
            with open(audio_path, "rb") as audio_file:
                response = self.client.audio.transcriptions.create(
                    file=audio_file,
                    model=self.audio_model,
                    response_format="text"
                )
                result = response.strip()
                logger.info(f"🎤 Транскрипция: {result[:50]}...")
                return result
                
        except Exception as e:
            logger.error(f"❌ Ошибка транскрипции: {e}")
            return ""

    def generate_from_voice(self, text: str, style: str) -> List[str]:
        """Генерация из голоса"""
        return self._generate_from_text(text, style)
