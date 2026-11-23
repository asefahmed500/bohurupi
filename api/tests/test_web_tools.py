"""Free web tools: real retrieved data, no API keys."""

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.graph import get_graph
from app.agent.web_tools import fetch_url, get_web_tools, wikipedia_search


def test_web_tools_registered():
    names = {tool.name for tool in get_web_tools()}
    assert {"web_search", "fetch_url", "wikipedia_search"} <= names


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000/admin", "file:///etc/passwd", "http://169.254.169.254/latest/meta-data"])
def test_fetch_url_blocks_private_targets(url):
    assert "Error" in fetch_url(url)


def test_wikipedia_search_returns_real_source():
    hits = wikipedia_search("Paris capital of France", max_results=2)
    assert hits
    assert any("paris" in h["title"].lower() for h in hits)
    assert all(h["url"].startswith("https://") for h in hits if h["url"])
    assert any("capital" in h["extract"].lower() for h in hits)


@pytest.mark.asyncio
async def test_agent_calls_web_tool_for_current_fact():
    """The graph must actually invoke a web tool, not answer from memory alone."""
    state = await get_graph().ainvoke(
        {
            "messages": [
                SystemMessage(
                    content=(
                        "You MUST use the web_search tool before answering any "
                        "factual question. Cite the URL."
                    )
                ),
                HumanMessage(
                    content=(
                        "Search the web: what is the capital of Japan? Reply with "
                        "one short sentence and the source URL."
                    )
                ),
            ],
            "text": "what is the capital of Japan",
            "in_lang": "",
            "out_lang": "en",
            "reply": "",
            "reply_lang": "",
            "translations": {},
        }
    )
    kinds = [type(m).__name__ for m in state["messages"]]
    assert "ToolMessage" in kinds, kinds
    assert "tokyo" in (state.get("reply") or "").lower(), state.get("reply")
