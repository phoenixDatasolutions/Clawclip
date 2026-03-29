"""API Testing Skill — make HTTP requests and test endpoints using httpx."""

from __future__ import annotations

import json
import logging
from typing import Any

from clawclip.core.types import SkillContext, SkillResult, ToolDefinition

logger = logging.getLogger(__name__)

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

_DEFAULT_TIMEOUT = 15


class APITestingSkill:
    """Make HTTP requests and test API endpoints using httpx async client."""

    @property
    def name(self) -> str:
        return "api_testing"

    @property
    def description(self) -> str:
        return "Make HTTP requests (GET, POST, PUT, DELETE) and test API endpoints"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="http_get",
                description="Send a GET request to a URL",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Target URL"},
                        "headers": {"type": "object", "description": "Request headers"},
                        "params": {"type": "object", "description": "Query parameters"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 15},
                    },
                    "required": ["url"],
                },
                required_permissions=["web.request"],
            ),
            ToolDefinition(
                name="http_post",
                description="Send a POST request with JSON or form body",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Target URL"},
                        "body": {"type": "object", "description": "JSON body"},
                        "headers": {"type": "object", "description": "Request headers"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 15},
                    },
                    "required": ["url"],
                },
                required_permissions=["web.request"],
            ),
            ToolDefinition(
                name="http_put",
                description="Send a PUT request with JSON body",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Target URL"},
                        "body": {"type": "object", "description": "JSON body"},
                        "headers": {"type": "object", "description": "Request headers"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 15},
                    },
                    "required": ["url"],
                },
                required_permissions=["web.request"],
            ),
            ToolDefinition(
                name="http_delete",
                description="Send a DELETE request",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Target URL"},
                        "headers": {"type": "object", "description": "Request headers"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 15},
                    },
                    "required": ["url"],
                },
                required_permissions=["web.request"],
            ),
            ToolDefinition(
                name="test_endpoint",
                description="Test an endpoint and validate response code and body",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Target URL"},
                        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"], "default": "GET"},
                        "body": {"type": "object", "description": "Request body (for POST/PUT)"},
                        "headers": {"type": "object", "description": "Request headers"},
                        "expected_status": {"type": "integer", "description": "Expected HTTP status code", "default": 200},
                        "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 15},
                    },
                    "required": ["url"],
                },
                required_permissions=["web.request"],
            ),
        ]

    @property
    def triggers(self) -> list[str]:
        return ["/api", "/http", "/curl"]

    @property
    def required_permissions(self) -> list[str]:
        return ["web.request"]

    async def initialize(self, context: SkillContext) -> None:
        pass

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        if not _HTTPX_AVAILABLE:
            return SkillResult(success=False, output="httpx is not installed", error="missing dependency")

        if tool_name == "http_get":
            return await self._request("GET", arguments)
        if tool_name == "http_post":
            return await self._request("POST", arguments)
        if tool_name == "http_put":
            return await self._request("PUT", arguments)
        if tool_name == "http_delete":
            return await self._request("DELETE", arguments)
        if tool_name == "test_endpoint":
            return await self._test_endpoint(arguments)

        return SkillResult(success=False, output=f"Unknown tool: {tool_name}")

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult:
        parts = args.strip().split(maxsplit=1)
        if not parts:
            return SkillResult(success=False, output="Usage: /api <METHOD> <url> or /api <url>")

        if parts[0].upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
            method = parts[0].upper()
            url = parts[1] if len(parts) > 1 else ""
        else:
            method = "GET"
            url = parts[0]

        if not url:
            return SkillResult(success=False, output="URL is required")

        return await self._request(method, {"url": url})

    async def shutdown(self) -> None:
        pass

    # ── private helpers ──────────────────────────────────────────

    async def _request(self, method: str, args: dict[str, Any]) -> SkillResult:
        url = args.get("url", "")
        if not url:
            return SkillResult(success=False, output="url is required")

        headers = args.get("headers") or {}
        params = args.get("params")
        body = args.get("body")
        timeout = int(args.get("timeout", _DEFAULT_TIMEOUT))

        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                headers={"User-Agent": "ClawClip-APITest/1.0", **headers},
                follow_redirects=True,
            ) as client:
                kwargs: dict[str, Any] = {}
                if params:
                    kwargs["params"] = params
                if body is not None:
                    kwargs["json"] = body

                response = await client.request(method, url, **kwargs)

            return _format_response(response)
        except httpx.TimeoutException:
            return SkillResult(success=False, output=f"Request timed out after {timeout}s", error="timeout")
        except Exception as e:
            return SkillResult(success=False, output=f"Request failed: {e}", error=str(e))

    async def _test_endpoint(self, args: dict[str, Any]) -> SkillResult:
        method = args.get("method", "GET").upper()
        expected_status = int(args.get("expected_status", 200))

        result = await self._request(method, args)
        if not result.success:
            return result

        first_line = result.output.split("\n", 1)[0]
        try:
            actual_status = int(first_line.split()[1])
        except (IndexError, ValueError):
            actual_status = -1

        passed = actual_status == expected_status
        status_line = f"Test {'PASSED' if passed else 'FAILED'}: expected {expected_status}, got {actual_status}"

        return SkillResult(
            success=passed,
            output=f"{status_line}\n\n{result.output}",
            error=None if passed else status_line,
        )


def _format_response(response: "httpx.Response") -> SkillResult:
    status = response.status_code
    headers_summary = dict(response.headers)
    content_type = headers_summary.get("content-type", "")

    body_preview = ""
    if "json" in content_type:
        try:
            parsed = response.json()
            body_preview = json.dumps(parsed, indent=2)[:5000]
            if len(json.dumps(parsed)) > 5000:
                body_preview += "\n... (truncated)"
        except Exception:
            body_preview = response.text[:5000]
    elif "text" in content_type:
        body_preview = response.text[:5000]
        if len(response.text) > 5000:
            body_preview += "\n... (truncated)"
    else:
        body_preview = f"(binary content, {len(response.content)} bytes)"

    output = (
        f"HTTP {status} {response.reason_phrase}\n"
        f"URL: {response.url}\n"
        f"Content-Type: {content_type}\n"
        f"Response time: {response.elapsed.total_seconds() * 1000:.0f}ms\n"
        f"\n{body_preview}"
    )

    return SkillResult(
        success=200 <= status < 300,
        output=output,
        artifacts=[{
            "status_code": status,
            "content_type": content_type,
            "elapsed_ms": response.elapsed.total_seconds() * 1000,
        }],
        error=f"HTTP {status}" if not (200 <= status < 300) else None,
    )


def create_skill(config: dict) -> APITestingSkill:
    return APITestingSkill()
