"""LLM factory — Z.AI GLM through the OpenAI-compatible endpoint.

Provider is pluggable: swapping ZAI_BASE_URL / ZAI_MODEL (or adding another
factory) is all that is needed to run on a different provider.
"""

import logging

logger = logging.getLogger("bohurupi.llm")

_llm = None


def get_llm(temperature: float = 0.4):
    """Return a chat model instance (streaming-capable, tool-capable)."""
    global _llm
    if _llm is not None:
        return _llm

    from app.config import settings

    if not settings.zai_api_key:
        logger.warning("ZAI_API_KEY not set; LLM features disabled")

    from langchain_openai import ChatOpenAI

    _llm = ChatOpenAI(
        model=settings.zai_model,
        api_key=settings.zai_api_key or "missing",
        base_url=settings.zai_base_url,
        temperature=temperature,
        streaming=True,
        max_retries=2,
        timeout=60,
    )
    return _llm


def llm_ready() -> bool:
    from app.config import settings

    return bool(settings.zai_api_key)
