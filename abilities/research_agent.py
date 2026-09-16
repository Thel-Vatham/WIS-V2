"""
WIS Research Agent — Specialized Deep-Research Ability.
=======================================================
Combines Playwright browser automation with DuckDuckGo and Wikipedia
into a single, focused investigative agent that can:
- Perform multi-step web research following links deeply
- Extract structured content from complex pages
- Handle JavaScript-rendered pages (SPA, dashboards, etc.)
- Summarize findings from multiple sources
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from abilities.base import Ability

logger = logging.getLogger("wis.abilities.research_agent")


class ResearchAgent(Ability):
    """Specialized deep-research agent with browser and multi-source search."""

    @property
    def name(self):
        return "research_agent"

    @property
    def description(self):
        return (
            "Specialized deep-research agent. Use for complex web investigations, "
            "multi-source research, extracting content from complex/JS pages, "
            "and compiling structured summaries. "
            "Actions: deep_search, browse_and_extract, multi_source_research, fetch_page."
        )

    @property
    def domain(self):
        return "knowledge"

    def get_schema(self):
        return [
            {
                "action": "deep_search",
                "description": "Multi-provider web search with fallback chain: DDG lib -> DDG HTML -> Wikipedia EN -> Wikipedia ES.",
                "params": {"query": "Search query string", "max_results": "Max results (default 5)"}
            },
            {
                "action": "browse_and_extract",
                "description": "Navigate to a URL, wait for JS to render, and extract the main text content.",
                "params": {"url": "URL to open", "selector": "CSS selector to extract (optional, default: body)"}
            },
            {
                "action": "multi_source_research",
                "description": "Run a research query across multiple sources concurrently and compile a single report.",
                "params": {"query": "Research topic", "sources": "List of source types: ddg, wikipedia, browser"}
            },
            {
                "action": "fetch_page",
                "description": "Fetch raw text content of a URL without JavaScript rendering (fast, lightweight).",
                "params": {"url": "URL to fetch"}
            },
        ]

    async def execute(self, action: str, params: dict) -> dict:
        a = (action or "").lower().strip()
        try:
            if a == "deep_search":
                return await asyncio.to_thread(self._deep_search, params)
            if a == "browse_and_extract":
                return await asyncio.to_thread(self._browse_and_extract, params)
            if a == "multi_source_research":
                return await self._multi_source_research(params)
            if a == "fetch_page":
                return await asyncio.to_thread(self._fetch_page, params)
            return {"success": False, "message": f"Unknown action: {action}"}
        except Exception as e:
            logger.error("ResearchAgent error: %s", e)
            return {"success": False, "message": str(e)}

    # ── Internal methods ────────────────────────────────────────────────────────

    def _deep_search(self, params: dict) -> dict:
        query = params.get("query", "")
        max_results = int(params.get("max_results", 5))
        results = []

        # 1. DuckDuckGo lib
        try:
            try:
                from duckduckgo_search import DDGS
            except ImportError:
                from ddgs import DDGS
            ddgs = DDGS()
            seen = set()
            for item in ddgs.text(query, max_results=max_results * 2):
                url = item.get("href", "")
                if url in seen:
                    continue
                seen.add(url)
                results.append({
                    "title": item.get("title", ""),
                    "snippet": item.get("body", "")[:300],
                    "url": url,
                    "source": "DuckDuckGo",
                })
                if len(results) >= max_results:
                    break
        except Exception as e:
            logger.warning("DDG lib failed: %s", e)

        # 2. Wikipedia fallback
        if len(results) < 2:
            wiki_result = self._wikipedia_search(query)
            if wiki_result:
                results.append(wiki_result)

        if not results:
            return {"success": False, "message": f"No results found for: {query}"}

        text = f"Research results for: {query}\n\n"
        for i, r in enumerate(results, 1):
            text += f"{i}. **{r['title']}** [{r['source']}]\n"
            text += f"   {r['snippet']}\n"
            if r.get("url"):
                text += f"   URL: {r['url']}\n"
            text += "\n"

        return {"success": True, "data": results, "message": text}

    def _wikipedia_search(self, query: str) -> dict | None:
        import urllib.request, urllib.parse, json as json_lib
        for lang in ("en", "es"):
            try:
                params = urllib.parse.urlencode({
                    "action": "query", "list": "search",
                    "srsearch": query, "utf8": "", "format": "json", "srlimit": 3,
                })
                url = f"https://{lang}.wikipedia.org/w/api.php?{params}"
                req = urllib.request.Request(url, headers={
                    "User-Agent": "WIS-ResearchAgent/3.0 (https://wis.local) Python/3.11",
                    "Accept": "application/json",
                })
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json_lib.loads(resp.read().decode("utf-8"))
                items = data.get("query", {}).get("search", [])
                if not items:
                    continue
                item = items[0]
                title = item.get("title", "")
                snippet = re.sub("<[^<]+>", "", item.get("snippet", ""))[:300]
                return {
                    "title": title,
                    "snippet": snippet,
                    "url": f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
                    "source": f"Wikipedia-{lang.upper()}",
                }
            except Exception:
                continue
        return None

    def _browse_and_extract(self, params: dict) -> dict:
        url = params.get("url", "")
        selector = params.get("selector", "body")
        if not url:
            return {"success": False, "message": "Missing 'url' parameter."}
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, timeout=20000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                try:
                    text = page.locator(selector).inner_text(timeout=5000)
                except Exception:
                    text = page.evaluate("document.body.innerText")
                browser.close()
            # Trim whitespace runs
            text = re.sub(r"\n{3,}", "\n\n", text).strip()[:5000]
            return {"success": True, "data": text, "message": text}
        except ImportError:
            return self._fetch_page(params)
        except Exception as e:
            logger.error("browse_and_extract error: %s", e)
            return self._fetch_page(params)

    def _fetch_page(self, params: dict) -> dict:
        url = params.get("url", "")
        if not url:
            return {"success": False, "message": "Missing 'url' parameter."}
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={
                "User-Agent": "WIS-ResearchAgent/3.0 (https://wis.local) Python/3.11",
                "Accept": "text/html,application/xhtml+xml",
            })
            with urllib.request.urlopen(req, timeout=12) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            # Strip HTML tags
            text = re.sub("<[^<]+?>", " ", html)
            text = re.sub(r"\s{3,}", "\n\n", text).strip()[:5000]
            return {"success": True, "data": text, "message": text}
        except Exception as e:
            return {"success": False, "message": f"Fetch error: {e}"}

    async def _multi_source_research(self, params: dict) -> dict:
        query = params.get("query", "")
        sources = params.get("sources", ["ddg", "wikipedia"])
        tasks = []
        if "ddg" in sources or "browser" in sources:
            tasks.append(asyncio.to_thread(self._deep_search, {"query": query}))
        if "wikipedia" in sources:
            tasks.append(asyncio.to_thread(self._wikipedia_search, query))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        combined = []
        for r in results:
            if isinstance(r, Exception):
                continue
            if isinstance(r, dict) and r.get("success"):
                combined.append(r.get("message", ""))
            elif isinstance(r, dict) and r:
                combined.append(str(r))

        report = f"=== Multi-source Research: {query} ===\n\n" + "\n\n---\n\n".join(combined)
        return {"success": bool(combined), "data": combined, "message": report}
