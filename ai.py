import logging
import base64
from typing import List
import os
from groq import Groq

logger = logging.getLogger(__name__)


class AIAssistant:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = Groq(api_key=api_key)
        self.text_model = "llama-3.1-70b-versatile"
        self.vision_model = "llama-3.2-90b-vision-preview"
        self.audio_model = "whisper-large-v3"
        self._test_api()
        logger.info(f"✅ AI Assistant initialized")

    def _test_api(self):
        try:
            test = self.client.chat.completions.create(
                model=self.text_model,
                messages=[{"role": "user", "content": "Say OK"}],
                max_tokens=5
            )
            logger.info("✅ Groq API test successful")
        except Exception as e:
            logger.error(f"❌ Groq API test failed: {e}")

    def _get_style_prompt(self, style: str) -> str:
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
        return style_prompts.get(style, "Будь естественным и человечным.")

    def _build_prompt(self, content: str, style: str) -> str:
        style_instruction = self._get_style_prompt(style)

        return f"""Ты ReplyGo, полезный AI-помощник, который генерирует естественные варианты ответов на сообщения.

Пользователь хочет, чтобы ты ответил на это сообщение: "{content}"

Стиль: {style}
Инструкция: {style_instruction}

Важные правила:
1. Сгенерируй ровно 3 варианта ответа
2. НИКОГДА не начинай с фраз "Я понимаю", "Без проблем", "Вот несколько вариантов ответа"
3. НИКОГДА не используй эмодзи, если стиль явно этого не требует
4. НИКОГДА не звучи как ChatGPT или AI
5. ВСЕГДА звучи как реальный человек
6. Делай ответы короткими и естественными
7. Используй язык как в Telegram
8. Каждый ответ должен быть полным, самостоятельным сообщением
9. Никогда не генерируй угрозы, незаконные советы, ненависть или насилие

Формат ответа:
1. [Первый вариант ответа]
2. [Второй вариант ответа]
3. [Третий вариант ответа]

Сгенерируй только ответы, без дополнительного текста или объяснений."""

    def _parse_replies(self, response: str) -> List[str]:
        if not response:
            return ["Не удалось сгенерировать ответ.", "Попробуй еще раз.", "Попробуй другой стиль."]
        
        lines = response.strip().split('\n')
        replies = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            if line and line[0].isdigit() and '. ' in line:
                parts = line.split('. ', 1)
                if len(parts) == 2 and parts[1].strip():
                    replies.append(parts[1].strip())
            elif line and not line.startswith(('1.', '2.', '3.')):
                if len(replies) < 3:
                    replies.append(line)

        while len(replies) < 3:
            if len(replies) == 0:
                replies = ["Вариант ответа 1", "Вариант ответа 2", "Вариант ответа 3"]
                break
            else:
                replies.append(f"Вариант {len(replies) + 1}")

        return replies[:3]

    def generate(self, content_type: str, content: any, style: str) -> List[str]:
        try:
            logger.info(f"Generating replies for style: {style}")
            
            if content_type == "image":
                return self._generate_from_image(content, style)
            else:
                return self._generate_from_text(content, style)
        except Exception as e:
            logger.error(f"Error generating replies: {e}", exc_info=True)
            return ["Не удалось сгенерировать ответы.", "Попробуй позже.", "Попробуй другой стиль."]

    def _generate_from_text(self, text: str, style: str) -> List[str]:
        prompt = self._build_prompt(text, style)

        try:
            completion = self.client.chat.completions.create(
                model=self.text_model,
                messages=[
                    {"role": "system", "content": "Ты полезный помощник, который генерирует естественные варианты ответов."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.8,
                max_tokens=300
            )

            response = completion.choices[0].message.content
            return self._parse_replies(response)

        except Exception as e:
            logger.error(f"Error in text generation: {e}", exc_info=True)
            return [
                "Отличная мысль! Полностью с тобой согласен.",
                "Понимаю, о чем ты говоришь. Дай подумать.",
                "Спасибо, что поделился. Ценю твою точку зрения."
            ]

    def _generate_from_image(self, image_path: str, style: str) -> List[str]:
        try:
            with open(image_path, "rb") as image_file:
                image_data = base64.b64encode(image_file.read()).decode("utf-8")

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
                            "text": f"Извлеки текст из этого изображения и сгенерируй 3 естественных варианта ответа в стиле {style}."
                        }
                    ]
                }
            ]

            completion = self.client.chat.completions.create(
                model=self.vision_model,
                messages=messages,
                temperature=0.8,
                max_tokens=300
            )

            response = completion.choices[0].message.content
            return self._parse_replies(response)

        except Exception as e:
            logger.error(f"Error in image generation: {e}", exc_info=True)
            return ["Не удалось обработать изображение.", "Попробуй отправить текст.", "Или попробуй более четкий скриншот."]

    async def transcribe_audio(self, audio_path: str) -> str:
        try:
            with open(audio_path, "rb") as audio_file:
                transcription = self.client.audio.transcriptions.create(
                    file=audio_file,
                    model=self.audio_model,
                    response_format="text"
                )
                return transcription.strip()
        except Exception as e:
            logger.error(f"Error transcribing audio: {e}", exc_info=True)
            return ""

    def generate_from_voice(self, text: str, style: str) -> List[str]:
        return self._generate_from_text(text, style)