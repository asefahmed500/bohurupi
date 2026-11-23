"""Agent graph (PRD §4.1, extended with the tool loop):

    detect -> reason (LLM, tools) <-> tools -> translate -> END

Token streaming for the chat UI comes from graph.astream(stream_mode="messages");
the speak/post stages run in the streaming service layer so audio starts after
the first sentence rather than after the whole reply (PRD §2.9).
"""

import logging
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import RetryPolicy

from app.agent.mcp_tools import get_mcp_tools
from app.agent.tools import get_tools, translate_text
from app.agent.web_tools import get_web_tools

logger = logging.getLogger("bohurupi.agent.graph")


def _retryable_llm_error(exc: Exception) -> bool:
    """Never burn retries on permanent provider errors (balance/key/model)."""
    message = str(exc).lower()
    permanent = (
        "insufficient balance",
        "no resource package",
        "recharge",
        "invalid api key",
        "authentication",
        "model not found",
        "does not exist",
    )
    return not any(phrase in message for phrase in permanent)


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    text: str  # user input text
    in_lang: str  # detected input language (ISO code, "" when unknown)
    out_lang: str  # requested output language ("auto" mirrors input)
    reply: str  # final reply text (post-translation)
    reply_lang: str  # language the reply is written in
    translations: dict[str, str]  # {lang: translated_reply} cache


# ---- nodes ----


_detector = None


def _get_detector():
    """Lingua detector built once (from_languages + preloaded models is expensive)."""
    global _detector
    if _detector is None:
        from lingua import LanguageDetectorBuilder

        _detector = (
            LanguageDetectorBuilder.from_languages(*_LINGUA_LANGS)
            .with_preloaded_language_models()
            .build()
        )
    return _detector


def detect_language(state: AgentState) -> dict:
    """Language ID on short text via lingua-py."""
    text = state["text"].strip()
    if not text:
        return {"in_lang": "", "reply_lang": ""}
    detected = _get_detector().detect_language_of(text)
    code = detected.iso_code_639_1.name.lower() if detected else ""
    return {"in_lang": _LINGUA_CODE_OVERRIDES.get(code, code)}


async def reason(state: AgentState, config: RunnableConfig) -> dict:
    """LLM reasoning node with tool binding."""
    from app.agent.llm import get_llm

    llm = get_llm()
    tools = get_tools() + get_web_tools() + await get_mcp_tools()
    llm_bound = llm.bind_tools(tools) if tools else llm
    ai_msg = await llm_bound.ainvoke(state["messages"], config=config)
    return {"messages": [ai_msg]}


def route_after_reason(state: AgentState) -> Literal["tools", "translate"]:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "translate"


async def _tool_node(state: AgentState) -> dict:
    tool_node = ToolNode(
        get_tools() + get_web_tools() + await get_mcp_tools(),
        handle_tool_errors=True,
    )
    return await tool_node.ainvoke(state)


async def translate(state: AgentState) -> dict:
    """Translate the reply if the requested output language differs (FR-2)."""
    ai = next(
        (m for m in reversed(state["messages"]) if isinstance(m, AIMessage) and m.content),
        None,
    )
    reply = _content_str(ai.content) if ai else ""
    out_lang = state.get("out_lang") or "auto"
    target = out_lang if out_lang != "auto" else state.get("in_lang") or "en"
    reply_lang = target
    translations = dict(state.get("translations") or {})

    # If the model was asked to answer in `target`, its reply is already there.
    # When mirroring ("auto") the reply language follows the user's input, which
    # detect_language established — so no translation needed on the hot path.
    if out_lang != "auto" and state.get("in_lang") and out_lang != state.get("in_lang"):
        translated = await translate_text(reply, out_lang)
        if translated and translated != reply:
            translations[out_lang] = translated
            reply, reply_lang = translated, out_lang

    return {"reply": reply, "reply_lang": reply_lang, "translations": translations}


# ---- assembly ----

from lingua import Language as _Language  # noqa: E402

_LINGUA_LANGS = [
    _Language.BENGALI, _Language.ENGLISH, _Language.HINDI, _Language.URDU,
    _Language.ARABIC, _Language.SPANISH, _Language.FRENCH, _Language.GERMAN,
    _Language.PORTUGUESE, _Language.RUSSIAN, _Language.TURKISH, _Language.CHINESE,
    _Language.JAPANESE, _Language.KOREAN, _Language.ITALIAN, _Language.DUTCH,
    _Language.POLISH, _Language.INDONESIAN, _Language.TAMIL, _Language.VIETNAMESE,
    # expanded voice library
    _Language.AFRIKAANS, _Language.AZERBAIJANI, _Language.BULGARIAN,
    _Language.BOSNIAN, _Language.CATALAN, _Language.CZECH, _Language.DANISH,
    _Language.GREEK, _Language.FINNISH, _Language.HEBREW, _Language.CROATIAN,
    _Language.HUNGARIAN, _Language.ICELANDIC, _Language.GEORGIAN, _Language.KAZAKH,
    _Language.LITHUANIAN, _Language.LATVIAN, _Language.MACEDONIAN, _Language.MARATHI,
    _Language.MALAY, _Language.ROMANIAN, _Language.SLOVAK,
    _Language.ALBANIAN, _Language.SERBIAN, _Language.SWEDISH, _Language.SWAHILI,
    _Language.TELUGU, _Language.THAI, _Language.UKRAINIAN,
]

# lingua reports a few ISO codes differently from our language catalog
_LINGUA_CODE_OVERRIDES = {"no": "nb"}


def _content_str(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return str(content or "")


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("detect", detect_language, retry_policy=RetryPolicy(max_attempts=2))
    g.add_node(
        "reason",
        reason,
        retry_policy=RetryPolicy(max_attempts=3, retry_on=_retryable_llm_error),
    )
    g.add_node("tools", _tool_node)
    g.add_node("translate", translate, retry_policy=RetryPolicy(max_attempts=2))
    g.add_edge(START, "detect")
    g.add_edge("detect", "reason")
    g.add_conditional_edges("reason", route_after_reason, ["tools", "translate"])
    g.add_edge("tools", "reason")
    g.add_edge("translate", END)
    return g.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
