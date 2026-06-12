"""Bilingual content generation via GPT with Gemini fallback."""

import json
import re
import time
import random
import logging
from datetime import date
from typing import Dict, Optional

from openai import OpenAI, RateLimitError, AuthenticationError
from config import Config

logger = logging.getLogger(__name__)

_LABEL_PREFIX_RE = re.compile(
    r'^\s*(title|fact|english|persian|answer|عنوان|واقعیت)\s*:?\s*',
    re.IGNORECASE,
)


def _strip_label(text: str) -> str:
    return _LABEL_PREFIX_RE.sub('', text.strip()).strip()


def _parse_json_response(raw: str) -> Dict[str, str]:
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    content = json.loads(raw)

    if "english" not in content or "persian" not in content:
        raise ValueError("Invalid JSON: missing 'english' or 'persian' keys")

    content["english"] = _strip_label(content["english"])
    content["persian"] = _strip_label(content["persian"])
    if "image_prompt" in content:
        content["image_prompt"] = _strip_label(content["image_prompt"])

    return content


def _generate_with_gemini(config: Config, prompt: str, topic: str) -> Dict[str, str]:
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set in .env")

    try:
        from google import genai as google_genai
    except ImportError:
        raise RuntimeError("google-genai not installed. Run: pip install google-genai")

    client = google_genai.Client(api_key=config.GEMINI_API_KEY)

    GEMINI_MODELS = [
        ("gemini-2.5-flash-lite", "free"),
        ("gemini-2.5-flash",      "free"),
        ("gemini-2.5-pro",        "paid"),
    ]

    last_error: Optional[Exception] = None

    for model_name, tier in GEMINI_MODELS:
        logger.info(f"Trying Gemini model: {model_name} ({tier})")

        for attempt in range(config.MAX_RETRIES):
            try:
                response = client.models.generate_content(model=model_name, contents=prompt)
                raw = response.text.strip()
                content = _parse_json_response(raw)
                content["topic"] = topic
                logger.info(f"[Gemini/{model_name}] {content['english'][:50]}...")
                return content
            except Exception as e:
                last_error = e
                err_str = str(e)
                if any(x in err_str for x in ["404", "quota", "rate", "not found",
                                               "no longer available", "deprecated",
                                               "billing", "unavailable"]):
                    logger.warning(f"[{model_name}] Unavailable: {e}")
                    break
                logger.warning(f"[{model_name}] Attempt {attempt + 1} failed: {e}")
                if attempt < config.MAX_RETRIES - 1:
                    time.sleep(config.RETRY_DELAY)
        else:
            logger.warning(f"[{model_name}] All retries exhausted")

    raise RuntimeError(f"Gemini fallback failed. Last error: {last_error}")


class ContentGenerator:
    """Generate English + Persian fact content (GPT primary, Gemini fallback)."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.client = OpenAI(api_key=self.config.OPENAI_API_KEY)

    def generate(self) -> Dict[str, str]:
        rotation = getattr(self.config, "TOPIC_ROTATION", None)
        if rotation:
            day_index = date.today().toordinal() % len(rotation)
            category = rotation[day_index]
            topic = random.choice(category)
        else:
            topic = random.choice(self.config.TOPICS)

        logger.info(f"Topic: {topic}")

        prompt = (
            f"You write for @vienna_streetvibes — a Farsi-language Instagram channel "
            f"for Persian speakers (Iranians & Afghans) living in or considering moving to Vienna. "
            f"Write ONE 'Vienna Daily' fact about: '{topic}'. "
            f"Rules: "
            f"(1) Must be about Vienna or Austria specifically. "
            f"(2) Must be useful or genuinely surprising for someone who lives in Vienna. "
            f"(3) Tone: like a friend telling you a real tip — short, punchy, max 2 sentences. "
            f"(4) NOT tourist-guide style. The reader already lives there or plans to. "
            f"(5) Persian translation must be natural Farsi — not literal. "
            f"(6) image_prompt: 8-12 words describing a specific Vienna visual scene. "
            f"    Must be purely visual — no text, no people, no logos. "
            f'Output ONLY JSON: {{"english": "...", "persian": "...", "image_prompt": "..."}}'
        )

        last_error: Optional[Exception] = None

        for attempt in range(self.config.MAX_RETRIES):
            try:
                response = self.client.chat.completions.create(
                    model=self.config.GPT_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=self.config.GPT_TEMPERATURE,
                    max_tokens=self.config.GPT_MAX_TOKENS,
                )
                raw = response.choices[0].message.content.strip()
                content = _parse_json_response(raw)
                content["topic"] = topic
                logger.info(f"[OpenAI] {content['english'][:50]}...")
                return content

            except RateLimitError as e:
                last_error = e
                if "insufficient_quota" in str(e).lower() or "quota" in str(e).lower():
                    logger.warning("OpenAI quota exceeded — switching to Gemini")
                    break
                wait = self.config.RETRY_DELAY * (2 ** attempt)
                logger.warning(f"Rate limited — waiting {wait}s")
                time.sleep(wait)

            except AuthenticationError as e:
                last_error = e
                logger.warning(f"OpenAI auth error: {e} — switching to Gemini")
                break

            except Exception as e:
                last_error = e
                logger.warning(f"OpenAI attempt {attempt + 1} failed: {e}")
                if attempt < self.config.MAX_RETRIES - 1:
                    time.sleep(self.config.RETRY_DELAY)

        logger.info("Attempting Gemini fallback...")
        try:
            return _generate_with_gemini(self.config, prompt, topic)
        except RuntimeError as gemini_error:
            raise RuntimeError(
                f"Content generation failed. OpenAI: {last_error} | Gemini: {gemini_error}"
            ) from gemini_error
