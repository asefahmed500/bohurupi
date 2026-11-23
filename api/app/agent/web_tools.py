"""Free internet tools — no API keys, all open libraries / public APIs.

- Wikipedia search + summaries (Wikimedia REST, CC-BY-SA)
- DuckDuckGo HTML-free results via duckduckgo-search (optional, filtered)
- Read a public URL and extract readable text (httpx + BeautifulSoup)

Every tool returns real retrieved content with source URLs. Network failures
return a clear error string — never fabricated facts.
"""

import ipaddress
import logging
from urllib.parse import urlparse

import httpx
from langchain_core.tools import StructuredTool

logger = logging.getLogger("bohurupi.web_tools")

UA = {"User-Agent": "BohurupiAssistant/1.0 (multilingual voice agent; contact: admin@bohurupi.dev)"}
JUNK_HOSTS = ("google.com", "gemini.google.com", "gstatic.com", "youtube.com")


def _safe_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        addr = ipaddress.ip_address(parsed.hostname)
        return not (addr.is_private or addr.is_loopback or addr.is_link_local)
    except ValueError:
        # hostname (not an IP) — allow public DNS names, block localhost aliases
        host = (parsed.hostname or "").lower()
        return host not in ("localhost", "127.0.0.1", "::1") and not host.endswith(".local")


def wikipedia_search(query: str, max_results: int = 3) -> list[dict]:
    """Search Wikipedia and return title, URL and summary for each hit."""
    with httpx.Client(headers=UA, timeout=20) as client:
        r = client.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query[:200],
                "format": "json",
                "srlimit": max(1, min(5, max_results)),
            },
        )
        r.raise_for_status()
        titles = [item["title"] for item in r.json().get("query", {}).get("search", [])]
        out = []
        for title in titles:
            try:
                s = client.get(
                    "https://en.wikipedia.org/api/rest_v1/page/summary/" + title.replace(" ", "_"),
                    timeout=20,
                )
                if s.status_code == 200:
                    data = s.json()
                    out.append(
                        {
                            "title": data.get("title", title),
                            "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                            "extract": (data.get("extract") or "")[:700],
                        }
                    )
            except Exception:
                continue
        return out


def duckduckgo_results(query: str, max_results: int = 3) -> list[dict]:
    """Optional extra search results; returns [] if the library/proxy fails."""
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddg:
            rows = list(ddg.text(query[:200], max_results=max_results))
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "extract": (r.get("body") or "")[:300],
            }
            for r in rows
            if r.get("href") and not any(junk in r.get("href", "") for junk in JUNK_HOSTS)
        ]
    except Exception:
        logger.warning("DuckDuckGo unavailable — using Wikipedia only")
        return []


def web_search(query: str, max_results: int = 3) -> list[dict]:
    """Search the internet for current information.

    Returns titled results with URLs and snippets.
    """
    out = wikipedia_search(query, max_results)
    if len(out) < max_results:
        out.extend(duckduckgo_results(query, max_results - len(out)))
    return out[:max_results]


def fetch_url(url: str, max_chars: int = 6000) -> str:
    """Fetch a public web page and return its readable text (source included)."""
    if not _safe_url(url):
        return "Error: only public http(s) URLs are allowed."
    try:
        from bs4 import BeautifulSoup

        with httpx.Client(headers=UA, timeout=20, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            soup = BeautifulSoup(r.text[:1_000_000], "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "noscript"]):
                tag.decompose()
            lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
            text = "\n".join(lines)
            return f"SOURCE: {url}\n{text[:max_chars]}"
    except Exception as e:
        return f"Could not fetch {url}: {type(e).__name__}: {str(e)[:160]}"


def get_web_tools() -> list[StructuredTool]:
    return [
        StructuredTool.from_function(
            func=web_search,
            name="web_search",
            description=(
                "Search the internet (Wikipedia + DuckDuckGo) for current facts. "
                "Use for questions about recent events, people, places or anything "
                "outside your knowledge. Returns titles, URLs and snippets."
            ),
        ),
        StructuredTool.from_function(
            func=fetch_url,
            name="fetch_url",
            description=(
                "Read a public web page URL and return its text. "
                "Use to verify details from a search result."
            ),
        ),
        StructuredTool.from_function(
            func=wikipedia_search,
            name="wikipedia_search",
            description="Search Wikipedia and return article summaries with source links.",
        ),
    ]
