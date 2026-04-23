from __future__ import annotations

import asyncio
import html
import json
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import structlog

from app.core.config import settings
from app.modules.deep_research.schemas import DeepResearchResult, DeepResearchSource
from app.services.llm_router import llm_router

logger = structlog.get_logger(__name__)

_SEARCH_URL = "https://duckduckgo.com/html/"
_BRAVE_SEARCH_URL = "https://search.brave.com/search"
_MAX_FETCH_CONCURRENCY = 4
_DEFAULT_SOURCE_TITLE = "Untitled source"
_INTERNAL_SEARCH_HOSTS = {
    "duckduckgo.com",
    "search.brave.com",
    "cdn.search.brave.com",
    "imgs.search.brave.com",
    "tiles.search.brave.com",
}


def _trim_trailing_url_noise(raw: str) -> str:
    candidate = (raw or "").strip()
    if not candidate:
        return ""
    candidate = re.sub(r"[*_`]+$", "", candidate)
    candidate = candidate.rstrip(".,;:!?\\]}>\"'")
    while candidate.endswith(")") and candidate.count(")") > candidate.count("("):
        candidate = candidate[:-1]
    return candidate


def is_deep_research_enabled(
    *,
    payload_deep_research: bool,
    features: dict | None,
    autopilot_enabled: bool,
    model_court_enabled: bool,
) -> bool:
    if autopilot_enabled or model_court_enabled:
        return False
    if not settings.deep_research_enabled:
        return False
    if payload_deep_research:
        return True
    if isinstance(features, dict):
        return bool(features.get("deep_research"))
    return False


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _strip_html(raw_html: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", raw_html)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p\s*>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    return _normalize_whitespace(html.unescape(text))


def _safe_url(raw_url: str) -> str:
    candidate = _trim_trailing_url_noise(html.unescape((raw_url or "").strip()))
    if not candidate:
        return ""
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"
    parsed = urlparse(candidate)
    if candidate.startswith("/l/?") or (
        parsed.netloc.lower().endswith("duckduckgo.com") and parsed.path.startswith("/l/")
    ):
        encoded = parse_qs(parsed.query).get("uddg", [""])[0]
        candidate = unquote(encoded) if encoded else ""
        parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return candidate
    return ""


def normalize_public_web_url(raw_url: str) -> str:
    return _safe_url(raw_url)


def _is_internal_search_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host in _INTERNAL_SEARCH_HOSTS


def _parse_brave_results(raw_html: str, limit: int) -> list[DeepResearchSource]:
    results: list[DeepResearchSource] = []
    seen_urls: set[str] = set()
    pattern = re.compile(
        r"""<a[^>]*href=["'](?P<href>https?://[^"']+)["'][^>]*>(?P<title>.*?)</a>""",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(raw_html):
        if len(results) >= limit:
            break
        url = _safe_url(match.group("href"))
        if not url or url in seen_urls or _is_internal_search_url(url):
            continue
        title = _strip_html(match.group("title"))
        if not title:
            continue
        seen_urls.add(url)
        results.append(
            DeepResearchSource(
                index=len(results) + 1,
                title=title,
                url=url,
                snippet="",
            )
        )
    return results


def _parse_search_results(raw_html: str, limit: int) -> list[DeepResearchSource]:
    results: list[DeepResearchSource] = []
    seen_urls: set[str] = set()
    pattern = re.compile(
        r"""<a[^>]*class=["']result__a["'][^>]*href=["'](?P<href>[^"']+)["'][^>]*>(?P<title>.*?)</a>""",
        re.IGNORECASE | re.DOTALL,
    )
    snippets = re.findall(
        r"""<a[^>]*class=["']result__snippet["'][^>]*>(.*?)</a>""",
        raw_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    snippet_idx = 0
    for match in pattern.finditer(raw_html):
        if len(results) >= limit:
            break
        url = _safe_url(match.group("href"))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        title = _strip_html(match.group("title")) or _DEFAULT_SOURCE_TITLE
        snippet = _strip_html(snippets[snippet_idx]) if snippet_idx < len(snippets) else ""
        snippet_idx += 1
        results.append(
            DeepResearchSource(
                index=len(results) + 1,
                title=title,
                url=url,
                snippet=snippet,
            )
        )
    return results


async def _search_sources(query: str, max_results: int) -> list[DeepResearchSource]:
    # 1) Brave HTML search (no key, generally reachable in this environment)
    try:
        async with httpx.AsyncClient(
            timeout=max(3, settings.deep_research_fetch_timeout_seconds),
            follow_redirects=True,
        ) as client:
            response = await client.get(
                _BRAVE_SEARCH_URL,
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (GPTHub DeepResearch)"},
            )
            response.raise_for_status()
        brave_results = _parse_brave_results(response.text, max_results)
        if brave_results:
            return brave_results
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            logger.info("deep_research.brave_rate_limited", query=query)
        else:
            logger.warning("deep_research.brave_search_failed", query=query, error=str(exc))
    except Exception as exc:
        logger.warning("deep_research.brave_search_failed", query=query, error=str(exc))

    # 2) DuckDuckGo fallback
    try:
        async with httpx.AsyncClient(
            timeout=max(3, settings.deep_research_fetch_timeout_seconds),
            follow_redirects=True,
        ) as client:
            response = await client.get(
                _SEARCH_URL,
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (GPTHub DeepResearch)"},
            )
            response.raise_for_status()
    except Exception as exc:
        logger.warning("deep_research.search_failed", query=query, error=str(exc))
        return []
    return _parse_search_results(response.text, max_results)


async def _fetch_source_content(url: str) -> str:
    try:
        async with httpx.AsyncClient(
            timeout=max(3, settings.deep_research_fetch_timeout_seconds),
            follow_redirects=True,
        ) as client:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (GPTHub DeepResearch)"})
            response.raise_for_status()
            text = _strip_html(response.text)
            return text[: max(400, settings.deep_research_source_char_limit)].strip()
    except Exception as exc:
        logger.warning("deep_research.fetch_failed", url=url, error=str(exc))
        return ""


async def fetch_webpage_excerpt(url: str) -> str:
    normalized = _safe_url(url)
    if not normalized:
        return ""
    return await _fetch_source_content(normalized)


def _extract_json_array(raw: str) -> list[str] | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except Exception:
            return None
    if not isinstance(parsed, list):
        return None
    return [str(item).strip() for item in parsed if str(item).strip()]


async def _build_subqueries(user_text: str, model: str) -> list[str]:
    fallback = [
        user_text,
        f"{user_text} latest updates",
        f"{user_text} expert analysis",
    ]
    if settings.mws_stub_mode or not settings.openai_api_key:
        return fallback[: max(1, settings.deep_research_max_queries)]

    prompt = f"""Generate web-search subqueries for deep research.
User request: {user_text}
Return strict JSON array only, 2-5 short search queries."""
    try:
        raw = await llm_router.generate_text(
            prompt=prompt,
            model=model,
            temperature=0.1,
            max_tokens=180,
            system_prompt="You output only JSON array of search queries.",
        )
        parsed = _extract_json_array(raw)
        if not parsed:
            return fallback[: max(1, settings.deep_research_max_queries)]
        return parsed[: max(1, settings.deep_research_max_queries)]
    except Exception as exc:
        logger.warning("deep_research.subquery_generation_failed", error=str(exc))
        return fallback[: max(1, settings.deep_research_max_queries)]


async def _synthesize_answer(
    *,
    model: str,
    user_text: str,
    sources: list[DeepResearchSource],
    max_tokens: int | None,
) -> str:
    source_blocks = []
    for source in sources:
        content = source.content or source.snippet
        source_blocks.append(f"[{source.index}] {source.title}\nURL: {source.url}\n{content}")

    context = "\n\n".join(source_blocks)
    if settings.mws_stub_mode or not settings.openai_api_key:
        lines = [
            f"Deep research summary: {user_text}",
            "",
            "Key findings:",
        ]
        for source in sources:
            point = source.snippet or source.content[:220] or source.title
            lines.append(f"- [{source.index}] {point}")
        lines.append("")
        lines.append("Sources:")
        lines.extend(f"{source.index}. {source.title} — {source.url}" for source in sources)
        return "\n".join(lines)

    synthesis_prompt = f"""You are a research analyst.
Create a concise but thorough article for the user request.
Rules:
- Use only facts from provided sources.
- Add inline citations like [1], [2].
- Include sections and a short conclusion.
- If sources conflict, mention uncertainty.

User request:
{user_text}

Sources:
{context}
"""
    try:
        answer = await llm_router.generate_text(
            prompt=synthesis_prompt,
            model=model,
            temperature=0.2,
            max_tokens=max_tokens or max(300, settings.deep_research_max_output_tokens),
            system_prompt="You write factual research summaries with citations.",
        )
        answer = (answer or "").strip()
        if answer:
            return answer
    except Exception as exc:
        logger.warning("deep_research.synthesis_failed", error=str(exc))

    lines = [f"Could not complete deep synthesis for: {user_text}", "", "Sources:"]
    lines.extend(f"{source.index}. {source.title} — {source.url}" for source in sources)
    return "\n".join(lines)


def format_deep_research_answer(result: DeepResearchResult) -> str:
    answer = (result.answer or "").strip()
    if not result.sources:
        return answer
    citations_block = "\n".join(f"{source.index}. {source.title} — {source.url}" for source in result.sources)
    if "Sources:" in answer:
        return answer
    return f"{answer}\n\nSources:\n{citations_block}"


async def run_deep_research(
    *,
    selected_model: str,
    user_text: str,
    max_tokens: int | None,
) -> DeepResearchResult:
    queries = await _build_subqueries(user_text=user_text, model=selected_model)
    logger.info("deep_research.query_plan_ready", query_count=len(queries))

    search_results: list[list[DeepResearchSource]] = []
    for idx, query in enumerate(queries):
        search_results.append(
            await _search_sources(query=query, max_results=max(1, settings.deep_research_max_sources))
        )
        # Gentle pacing lowers search-provider 429 risk for bursty prompts.
        if idx < len(queries) - 1:
            await asyncio.sleep(0.25)

    deduped: list[DeepResearchSource] = []
    seen_urls: set[str] = set()
    for result_set in search_results:
        for item in result_set:
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            deduped.append(item)
            if len(deduped) >= max(1, settings.deep_research_max_sources):
                break
        if len(deduped) >= max(1, settings.deep_research_max_sources):
            break

    logger.info("deep_research.sources_found", sources_found=len(deduped))

    if not deduped:
        return DeepResearchResult(
            answer="Deep Research: could not find accessible web sources for this query right now.",
            sources=[],
        )

    semaphore = asyncio.Semaphore(_MAX_FETCH_CONCURRENCY)

    async def _fetch_with_limit(source: DeepResearchSource) -> str:
        async with semaphore:
            return await _fetch_source_content(source.url)

    fetched_contents = await asyncio.gather(*[_fetch_with_limit(source) for source in deduped])
    sources: list[DeepResearchSource] = []
    for source, content in zip(deduped, fetched_contents, strict=False):
        if not content and not source.snippet:
            continue
        sources.append(
            DeepResearchSource(
                index=len(sources) + 1,
                title=source.title or _DEFAULT_SOURCE_TITLE,
                url=source.url,
                snippet=source.snippet,
                content=content,
            )
        )

    logger.info("deep_research.pages_fetched", fetched_count=len(sources))

    if not sources:
        return DeepResearchResult(
            answer="Deep Research: web sources were found but page extraction failed.",
            sources=[],
        )

    answer = await _synthesize_answer(
        model=selected_model,
        user_text=user_text,
        sources=sources,
        max_tokens=max_tokens,
    )
    logger.info("deep_research.synthesis_done", sources_used=len(sources))
    return DeepResearchResult(answer=answer, sources=sources)
