import logging
import base64
from typing import List, Dict, Any
import os
from groq import Groq

logger = logging.getLogger(__name__)


class AIAssistant:
    def __init__(self, api_key: str):
        self.client = Groq(api_key=api_key)
        self.model = "llama-3.2-90b-vision-preview"

    def _get_style_prompt(self, style: str) -> str:
        """Get style-specific prompt instructions."""
        style_prompts = {
            "calm": "Be calm and soothing. Use gentle language. Stay positive and peaceful.",
            "confident": "Be assertive and self-assured. Use direct language. Show conviction.",
            "funny": "Be humorous and witty. Use clever wordplay. Keep it entertaining.",
            "hard": "Be strong and direct. Don't back down. Use firm language. Never generate threats, illegal advice, hate, or violence.",
            "friendly": "Be warm and approachable. Use friendly language. Show genuine interest.",
            "business": "Be professional and formal. Use business language. Keep it concise.",
            "smart": "Be intelligent and insightful. Show deep understanding. Use sophisticated language.",
            "conflict": "Be diplomatic and de-escalating. Focus on resolution. Use neutral language.",
            "sarcastic": "Be witty and ironic. Use sarcasm appropriately. Keep it clever.",
            "short": "Be brief and concise. Use short sentences. Get to the point.",
            "improve": "Improve the user's message while keeping the original intent. Enhance clarity and impact."
        }
        return style_prompts.get(style, "Be natural and human-like.")

    def _build_prompt(self, content: str, style: str) -> str:
        """Build the prompt for Groq API."""
        style_instruction = self._get_style_prompt(style)

        return f"""You are ReplyGo, a helpful AI assistant that generates natural reply options for messages.

The user wants you to reply to this message: "{content}"

Style: {style}
Instruction: {style_instruction}

Important rules:
1. Generate exactly 3 reply options
2. NEVER start with phrases like "I understand", "No problem", "Here are several replies"
3. NEVER use emojis unless the style explicitly requires it
4. NEVER sound like ChatGPT or AI
5. ALWAYS sound like a real human
6. Keep replies short and natural
7. Use Telegram-style language
8. Each reply must be a complete, standalone message
9. Never generate threats, illegal advice, hate, or violence

Format your response as:
1. [First reply option]
2. [Second reply option]
3. [Third reply option]

Generate only the replies, no additional text or explanations."""

    def _parse_replies(self, response: str) -> List[str]:
        """Parse the AI response to extract replies."""
        lines = response.strip().split('\n')
        replies = []

        for line in lines:
            line = line.strip()
            if line and any(line.startswith(f"{i}.") for i in range(1, 6)):
                # Remove the number prefix
                reply = line.split('.', 1)[1].strip() if '.' in line else line
                if reply:
                    replies.append(reply)
            elif line and not line.startswith(('1.', '2.', '3.')):
                # Handle replies without numbering
                pass

        # If we couldn't parse numbered replies, use all non-empty lines
        if len(replies) < 3:
            for line in lines:
                line = line.strip()
                if line and not line.startswith(('1.', '2.', '3.')):
                    if len(replies) < 3:
                        replies.append(line)

        # Ensure we have exactly 3 replies
        while len(replies) < 3:
            replies.append(f"Reply option {len(replies) + 1}")

        return replies[:3]

    def generate(self, content_type: str, content: Any, style: str) -> List[str]:
        """Universal function to generate replies."""
        try:
            if content_type == "image":
                return self._generate_from_image(content, style)
            else:
                return self._generate_from_text(content, style)

        except Exception as e:
            logger.error(f"Error generating replies: {e}")
            return ["I couldn't generate replies right now. Please try again later."]

    def _generate_from_text(self, text: str, style: str) -> List[str]:
        """Generate replies from text input."""
        prompt = self._build_prompt(text, style)

        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that generates natural reply options."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.8,
                max_tokens=300
            )

            response = completion.choices[0].message.content
            return self._parse_replies(response)

        except Exception as e:
            logger.error(f"Error in text generation: {e}")
            return ["I couldn't generate replies right now.", "Please try again later.", "Apologies for the inconvenience."]

    def _generate_from_image(self, image_path: str, style: str) -> List[str]:
        """Generate replies from image using Groq Vision."""
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
                            "text": f"Extract the text from this image and generate 3 natural reply options in {style} style. The text is: "
                        }
                    ]
                }
            ]

            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.8,
                max_tokens=300
            )

            response = completion.choices[0].message.content
            return self._parse_replies(response)

        except Exception as e:
            logger.error(f"Error in image generation: {e}")
            return ["I couldn't process this image.", "Please try sending text instead.", "Or try a clearer screenshot."]

    def generate_from_voice(self, text: str, style: str) -> List[str]:
        """Generate replies from transcribed voice text."""
        return self._generate_from_text(text, style)
