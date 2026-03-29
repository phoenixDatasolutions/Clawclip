"""Unit tests for WebSearchSkill (HTTP mocked)."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clawclip.skills.builtin.web_search import WebSearchSkill
from clawclip.core.types import SkillContext

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers to build mock httpx responses
# ---------------------------------------------------------------------------


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()  # no-op
    resp.text = "page content"
    resp.headers = {"content-type": "text/html"}
    return resp


def _make_async_client_cm(response: MagicMock) -> MagicMock:
    """Return a context-manager mock whose __aenter__ returns a client that returns response."""
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.get = AsyncMock(return_value=response)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def skill() -> WebSearchSkill:
    return WebSearchSkill()


@pytest.fixture
def context_no_key() -> SkillContext:
    """Context without an API key — forces DuckDuckGo path."""
    return SkillContext(user_id="test", config={"provider": "duckduckgo"})


@pytest.fixture
def context_tavily() -> SkillContext:
    return SkillContext(
        user_id="test",
        config={"provider": "tavily", "api_key": "fake-tavily-key"},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWebSearchSkillSearch:
    async def test_tavily_search(self, skill, context_tavily):
        tavily_payload = {
            "results": [
                {
                    "title": "Python Testing Guide",
                    "url": "https://example.com/testing",
                    "content": "A comprehensive guide to Python unit testing with pytest.",
                }
            ]
        }
        mock_cm = _make_async_client_cm(_mock_response(tavily_payload))

        with (
            patch("clawclip.skills.builtin.web_search._HTTPX_AVAILABLE", True),
            patch("clawclip.skills.builtin.web_search.httpx") as mock_httpx,
        ):
            mock_httpx.AsyncClient.return_value = mock_cm

            result = await skill.execute(
                "web_search", {"query": "python testing"}, context_tavily
            )

        assert result.success is True
        assert "Python Testing Guide" in result.output

    async def test_fallback_to_duckduckgo(self, skill, context_no_key):
        ddg_payload = {
            "AbstractText": "Python is a programming language.",
            "AbstractURL": "https://python.org",
            "RelatedTopics": [
                {"Text": "Python docs", "FirstURL": "https://docs.python.org"}
            ],
        }
        mock_cm = _make_async_client_cm(_mock_response(ddg_payload))

        with (
            patch("clawclip.skills.builtin.web_search._HTTPX_AVAILABLE", True),
            patch("clawclip.skills.builtin.web_search.httpx") as mock_httpx,
        ):
            mock_httpx.AsyncClient.return_value = mock_cm

            result = await skill.execute(
                "web_search", {"query": "python"}, context_no_key
            )

        assert result.success is True
        assert "python" in result.output.lower()

    async def test_empty_results(self, skill, context_no_key):
        empty_payload = {"AbstractText": "", "AbstractURL": "", "RelatedTopics": []}
        mock_cm = _make_async_client_cm(_mock_response(empty_payload))

        with (
            patch("clawclip.skills.builtin.web_search._HTTPX_AVAILABLE", True),
            patch("clawclip.skills.builtin.web_search.httpx") as mock_httpx,
        ):
            mock_httpx.AsyncClient.return_value = mock_cm

            result = await skill.execute(
                "web_search", {"query": "very_obscure_xyzzy_query"}, context_no_key
            )

        # Should succeed gracefully even with no results
        assert result.success is True

    async def test_search_requires_query(self, skill, context_no_key):
        result = await skill.execute("web_search", {"query": ""}, context_no_key)
        assert result.success is False
        assert "query" in result.output.lower()


class TestWebSearchSkillFetchUrl:
    async def test_fetch_url(self, skill, context_no_key):
        page_resp = MagicMock()
        page_resp.status_code = 200
        page_resp.raise_for_status = MagicMock()
        page_resp.text = "Hello from the page"
        page_resp.headers = {"content-type": "text/html"}

        client = AsyncMock()
        client.get = AsyncMock(return_value=page_resp)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=client)
        cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("clawclip.skills.builtin.web_search._HTTPX_AVAILABLE", True),
            patch("clawclip.skills.builtin.web_search.httpx") as mock_httpx,
        ):
            mock_httpx.AsyncClient.return_value = cm

            result = await skill.execute(
                "fetch_url",
                {"url": "https://example.com"},
                context_no_key,
            )

        assert result.success is True
        assert "Hello from the page" in result.output


class TestWebSearchSkillTriggers:
    async def test_trigger_search(self, skill, context_no_key):
        ddg_payload = {
            "AbstractText": "Python is great.",
            "AbstractURL": "https://python.org",
            "RelatedTopics": [],
        }
        mock_cm = _make_async_client_cm(_mock_response(ddg_payload))

        with (
            patch("clawclip.skills.builtin.web_search._HTTPX_AVAILABLE", True),
            patch("clawclip.skills.builtin.web_search.httpx") as mock_httpx,
        ):
            mock_httpx.AsyncClient.return_value = mock_cm

            result = await skill.handle_trigger("/search", "python testing", context_no_key)

        assert result.success is True
