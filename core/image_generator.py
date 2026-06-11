"""Image generation via OpenAI (gpt-image-1 / dall-e-3 / dall-e-2) with Google Imagen fallback."""

import base64
import time
import logging
from io import BytesIO
from typing import Optional

import requests
from PIL import Image
from openai import OpenAI, RateLimitError
from config import Config

logger = logging.getLogger(__name__)

_OPENAI_MODELS = [
    ("gpt-image-1", "1024x1536", True),
    ("dall-e-3",    "1024x1792", False),
    ("dall-e-2",    "1024x1024", False),
]

_TERMINAL_KEYWORDS = [
    "does not exist", "invalid_value", "invalid value",
    "not found", "no longer", "billing", "authentication",
    "auth", "insufficient", "hard limit", "unsupported",
    "permission", "access",
]

_IMAGEN_429_RETRY_DELAYS = [30, 60]

_GEMINI_IMAGE_MODELS = [
    "gemini-2.0-flash-preview-image-generation",
    "gemini-2.0-flash-exp-image-generation",
]


def _generate_with_gemini(config: Config, prompt: str) -> Image.Image:
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError("google-genai not installed. Run: pip install google-genai")

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    last_error: Optional[Exception] = None

    for model_name in _GEMINI_IMAGE_MODELS:
        logger.info(f"Trying Gemini image model: {model_name}")
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
            )
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.data:
                    logger.info(f"[Gemini/{model_name}] Image ready")
                    return Image.open(BytesIO(part.inline_data.data))
            raise RuntimeError("Gemini returned no image data.")
        except Exception as e:
            last_error = e
            logger.warning(f"[Gemini/{model_name}] Failed: {e}")
            continue

    raise RuntimeError(f"Gemini image generation failed. Last error: {last_error}")


def _generate_with_imagen(config: Config, prompt: str) -> Image.Image:
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError("google-genai not installed. Run: pip install google-genai")

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    IMAGEN_MODELS = ["imagen-3.0-generate-002", "imagen-4.0-generate-001"]
    last_error: Optional[Exception] = None

    for model_name in IMAGEN_MODELS:
        max_attempts = 1 + len(_IMAGEN_429_RETRY_DELAYS)
        for attempt in range(max_attempts):
            logger.info(f"Imagen [{model_name}] attempt {attempt + 1}/{max_attempts}")
            try:
                result = client.models.generate_images(
                    model=model_name,
                    prompt=prompt,
                    config=types.GenerateImagesConfig(number_of_images=1, aspect_ratio="9:16"),
                )
                if result.generated_images:
                    img_bytes = result.generated_images[0].image.image_bytes
                    logger.info(f"[Imagen/{model_name}] Image ready")
                    return Image.open(BytesIO(img_bytes))
                raise RuntimeError("Imagen returned no images.")
            except Exception as e:
                last_error = e
                err_str = str(e)
                if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < len(_IMAGEN_429_RETRY_DELAYS):
                    wait = _IMAGEN_429_RETRY_DELAYS[attempt]
                    logger.warning(f"[Imagen/{model_name}] 429 — waiting {wait}s...")
                    time.sleep(wait)
                    continue
                logger.warning(f"[Imagen/{model_name}] Failed: {e}")
                break

    raise RuntimeError(f"Imagen failed. Last error: {last_error}")


class ImageGenerator:
    """Generate vertical 9:16 images (OpenAI primary, Gemini/Imagen fallback)."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.client = OpenAI(api_key=self.config.OPENAI_API_KEY)

    def _try_openai_model(self, model_id: str, size: str, uses_b64: bool, prompt: str) -> Image.Image:
        kwargs = dict(model=model_id, prompt=prompt, size=size, n=1)
        if not uses_b64:
            kwargs["quality"] = self.config.DALL_E_QUALITY
        response = self.client.images.generate(**kwargs)
        if uses_b64:
            raw = base64.b64decode(response.data[0].b64_json)
            return Image.open(BytesIO(raw))
        url = response.data[0].url
        raw = requests.get(url, timeout=30).content
        return Image.open(BytesIO(raw))

    def generate(self, description: str) -> Image.Image:
        prompt = (
            f"Cinematic Vienna scene, golden hour, vertical 9:16 portrait. "
            f"No text, no words, no letters, no captions, no watermarks — purely visual. "
            f"Concept: {description}"
        )

        last_openai_error: Optional[Exception] = None

        for model_id, size, uses_b64 in _OPENAI_MODELS:
            logger.info(f"Trying OpenAI model: {model_id}")
            try:
                img = self._try_openai_model(model_id, size, uses_b64, prompt)
                logger.info(f"[{model_id}] Image ready")
                return img
            except RateLimitError as e:
                last_openai_error = e
                if "insufficient_quota" in str(e).lower() or "quota" in str(e).lower():
                    logger.warning(f"[{model_id}] Quota exceeded — trying next model")
                    continue
                wait = self.config.RETRY_DELAY * 3
                logger.warning(f"[{model_id}] Rate limited — waiting {wait}s")
                time.sleep(wait)
                continue
            except Exception as e:
                last_openai_error = e
                if any(k in str(e).lower() for k in _TERMINAL_KEYWORDS):
                    logger.warning(f"[{model_id}] Not available: {e}")
                    continue
                logger.warning(f"[{model_id}] Error: {e}")
                continue

        logger.info("All OpenAI models failed — trying Gemini image generation...")
        try:
            return _generate_with_gemini(self.config, prompt)
        except RuntimeError as gemini_error:
            logger.warning(f"Gemini image failed: {gemini_error} — trying Imagen...")
            try:
                return _generate_with_imagen(self.config, prompt)
            except RuntimeError as imagen_error:
                raise RuntimeError(
                    f"Image generation failed.\n"
                    f"OpenAI: {last_openai_error}\n"
                    f"Gemini: {gemini_error}\n"
                    f"Imagen: {imagen_error}"
                ) from imagen_error
