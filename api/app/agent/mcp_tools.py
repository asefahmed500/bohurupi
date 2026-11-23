"""Outbound MCP integration: expose tools from configured MCP servers to the
LangGraph reason node.

Configure MCP_SERVERS_JSON in the environment:
  [{"url":"http://localhost:8000/mcp","headers":{"X-MCP-API-Key":"..."}}]

Each remote tool becomes a LangChain StructuredTool. Every call opens a fresh
MCP session (short-lived, safe across async tasks and restarts).
"""

import json
import logging

from langchain_core.tools import StructuredTool
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.config import settings

logger = logging.getLogger("bohurupi.mcp_client")


async def _call_remote(url: str, headers: dict, name: str, arguments: dict) -> str:
    import httpx

    async with httpx.AsyncClient(headers=headers, timeout=60) as client:
        async with streamable_http_client(url, http_client=client) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments=arguments)
    parts = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts) if parts else "(no output)"


async def get_mcp_tools() -> list[StructuredTool]:
    raw = settings.mcp_servers_json.strip()
    if not raw or raw in ("[]", "{}", "null"):
        return []
    try:
        configs = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("MCP_SERVERS_JSON is not valid JSON")
        return []
    if isinstance(configs, dict):
        configs = [configs]

    tools: list[StructuredTool] = []
    for cfg in configs:
        url = str(cfg.get("url", ""))
        headers = {str(k): str(v) for k, v in (cfg.get("headers") or {}).items()}
        if not url:
            continue
        try:
            import httpx

            async with httpx.AsyncClient(headers=headers, timeout=20) as client:
                async with streamable_http_client(url, http_client=client) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        listed = await session.list_tools()

            def make_invoker(tool_name: str, tool_url: str, tool_headers: dict):
                async def _invoke(**kwargs):
                    return await _call_remote(tool_url, tool_headers, tool_name, kwargs)

                return _invoke

            for remote in listed.tools:
                tools.append(
                    StructuredTool.from_function(
                        coroutine=make_invoker(remote.name, url, headers),
                        name=f"mcp_{remote.name}",
                        description=f"[MCP:{url}] {remote.description or remote.name}",
                    )
                )
        except Exception:
            logger.exception("Could not load MCP tools from %s", url)
    return tools
