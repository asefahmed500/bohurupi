"""Agent tools (F11): web search, translate, summarize, read document aloud.

Web search uses Tavily when TAVILY_API_KEY is set; the agent works without it.
"""

import logging

logger = logging.getLogger("bohurupi.tools")


def get_tools():
    """Tools bound to the reasoning node (empty list = plain chat)."""
    from app.config import settings

    tools = []
    if settings.tavily_api_key:
        try:
            from langchain_tavily import TavilySearch

            tools.append(
                TavilySearch(
                    max_results=4,
                    topic="general",
                )
            )
        except Exception as e:
            logger.warning("Could not init Tavily search: %s", e)
    return tools


# ---- direct helpers (not agent tools) ----

async def translate_text(text: str, target_code: str) -> str:
    """Translate via the LLM. Never raises — returns the original on failure."""
    from app.i18n import LANGUAGES

    target = LANGUAGES.get(target_code)
    if target is None:
        return text
    try:
        from langchain_core.messages import HumanMessage

        from app.agent.llm import get_llm
        from app.agent.prompts import TRANSLATE_PROMPT

        llm = get_llm(temperature=0.1)
        prompt = TRANSLATE_PROMPT.format(
            target_language=target.name, target_native=target.native, text=text
        )
        resp = await llm.ainvoke([HumanMessage(content=prompt)])
        return resp.content.strip() or text
    except Exception as e:
        logger.warning("Translation failed (%s); returning original", e)
        return text


async def summarize_text(text: str, lang_hint: str | None = None) -> str:
    from langchain_core.messages import HumanMessage

    from app.agent.llm import get_llm

    llm = get_llm(temperature=0.2)
    instr = (
        "Summarize the following text in 2-4 spoken-friendly sentences."
        + (f" Write the summary in {lang_hint}." if lang_hint else "")
    )
    resp = await llm.ainvoke([HumanMessage(content=f"{instr}\n\nTEXT:\n{text}")])
    return resp.content.strip()
