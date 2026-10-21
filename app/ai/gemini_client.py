import logging

from google import genai
from app.config import settings

logger = logging.getLogger(__name__)

client = genai.Client(api_key=settings.gemini_api_key)


def generate_text(prompt: str) -> str:
    """Generate text using the configured Gemini model."""
    logger.info("Sending request to Gemini model.")

    try:
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
        )
    except Exception:
        logger.exception("Gemini API request failed.")
        raise

    if not response.text:
        logger.error("Gemini returned an empty response.")
        raise RuntimeError("Gemini returned an empty response.")

    logger.info("Gemini returned a response successfully.")
    return response.text
