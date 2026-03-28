from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from openagent.domain.tools import ToolArtifact, ToolContext, ToolExecutionResult, ToolOutputLimits
from openagent.tools.base import BaseTool


DEFAULT_USER_AGENT = "openagent/1.0 (+https://github.com/wangzhongyuan11/open-claude-code)"


def _fetch_url(url: str, timeout: int = 20) -> tuple[str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/json,text/plain;q=0.9,*/*;q=0.8",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
        content_type = response.headers.get("Content-Type", "")
        charset = response.headers.get_content_charset() or "utf-8"
    text = raw.decode(charset, errors="replace")
    return text, content_type


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", "", text)
    text = re.sub(r"(?is)<style.*?>.*?</style>", "", text)
    text = re.sub(r"(?s)<[^>]+>", "\n", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class WebFetchTool(BaseTool):
    tool_id = "webfetch"
    name = "webfetch"
    description = "Fetch a web resource and return the text content. Large outputs are truncated by the tool runtime."
    output_limits = ToolOutputLimits(max_chars=16000, max_lines=400, direction="head")
    input_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "raw": {"type": "boolean"},
        },
        "required": ["url"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        url = arguments["url"]
        raw = bool(arguments.get("raw", False))
        if not re.match(r"^https?://", url):
            return ToolExecutionResult.failure(
                "webfetch requires an http:// or https:// URL.",
                error_type="invalid_url",
                hint="Provide an absolute HTTP(S) URL.",
                metadata={"url": url, "operation": "webfetch"},
            )
        try:
            text, content_type = _fetch_url(url)
        except Exception as exc:
            return ToolExecutionResult.failure(
                f"failed to fetch {url}: {exc}",
                error_type=type(exc).__name__,
                retryable=True,
                hint="Retry with a reachable URL or narrower request.",
                metadata={"url": url, "operation": "webfetch"},
            )
        output = text if raw else (_strip_html(text) if "html" in content_type.lower() else text)
        artifacts = [ToolArtifact(kind="url", path=url, description="Fetched web resource")]
        return ToolExecutionResult.success(
            output,
            title=f"Fetched {url}",
            metadata={
                "url": url,
                "operation": "webfetch",
                "content_type": content_type,
                "raw": str(raw).lower(),
            },
            artifacts=artifacts,
        )


class WebSearchTool(BaseTool):
    tool_id = "websearch"
    name = "websearch"
    description = "Search the public web and return a concise list of result links and snippets."
    output_limits = ToolOutputLimits(max_chars=12000, max_lines=200, direction="head")
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer"},
        },
        "required": ["query"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        query = arguments["query"]
        max_results = int(arguments.get("max_results", 5))
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            text, _ = _fetch_url(url)
        except Exception as exc:
            return ToolExecutionResult.failure(
                f"failed to search the web for {query!r}: {exc}",
                error_type=type(exc).__name__,
                retryable=True,
                hint="Retry later or use a narrower query.",
                metadata={"query": query, "operation": "websearch"},
            )
        matches = re.findall(
            r'(?is)<a[^>]*class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?<a[^>]*class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
            text,
        )
        results: list[dict[str, Any]] = []
        for href, title, snippet in matches[:max_results]:
            results.append(
                {
                    "title": _strip_html(title),
                    "url": html.unescape(href),
                    "snippet": _strip_html(snippet),
                }
            )
        if not results:
            # Fallback: return cleaned page text rather than hard-failing.
            cleaned = _strip_html(text)
            return ToolExecutionResult.success(
                cleaned[:4000] or "(no search results found)",
                title=f"Searched the web for {query}",
                metadata={"query": query, "operation": "websearch", "result_count": "0"},
            )
        lines = []
        for idx, item in enumerate(results, start=1):
            lines.append(f"{idx}. {item['title']}\nURL: {item['url']}\nSnippet: {item['snippet']}")
        return ToolExecutionResult.success(
            "\n\n".join(lines),
            title=f"Searched the web for {query}",
            metadata={
                "query": query,
                "operation": "websearch",
                "result_count": str(len(results)),
                "results_json": json.dumps(results, ensure_ascii=False),
            },
            artifacts=[ToolArtifact(kind="url", path=item["url"], description=item["title"]) for item in results],
        )
