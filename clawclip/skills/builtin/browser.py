"""Browser Skill — Playwright-based browser automation."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

from clawclip.core.types import SkillContext, SkillResult, ToolDefinition

logger = logging.getLogger(__name__)

_PLAYWRIGHT_MISSING = (
    "Playwright not installed. Run: pip install playwright && playwright install chromium"
)


class BrowserSkill:
    """Browser automation — navigate, click, type, extract, screenshot."""

    # Class-level browser/page state — shared across all calls
    _browser: Any = None
    _page: Any = None
    _playwright: Any = None

    # ── Identity ────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "browser"

    @property
    def description(self) -> str:
        return "Browser automation — navigate, click, type, extract, screenshot"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def triggers(self) -> list[str]:
        return ["/browse", "/web", "/click", "/scrape"]

    @property
    def required_permissions(self) -> list[str]:
        return ["browser"]

    # ── Tool definitions ────────────────────────────────────────

    @property
    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="browser_navigate",
                description="Navigate to a URL and return the page title and final URL",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to navigate to",
                        },
                        "wait_for": {
                            "type": "string",
                            "enum": ["load", "networkidle", "domcontentloaded"],
                            "description": "Wait condition after navigation (default: load)",
                            "default": "load",
                        },
                    },
                    "required": ["url"],
                },
                required_permissions=["browser"],
            ),
            ToolDefinition(
                name="browser_click",
                description="Click an element identified by a CSS selector",
                parameters={
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector of the element to click",
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Timeout in milliseconds (default: 5000)",
                            "default": 5000,
                        },
                    },
                    "required": ["selector"],
                },
                required_permissions=["browser"],
            ),
            ToolDefinition(
                name="browser_type",
                description="Type text into an input field identified by a CSS selector",
                parameters={
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector of the input field",
                        },
                        "text": {
                            "type": "string",
                            "description": "Text to type into the field",
                        },
                        "clear_first": {
                            "type": "boolean",
                            "description": "Clear the field before typing (default: true)",
                            "default": True,
                        },
                    },
                    "required": ["selector", "text"],
                },
                required_permissions=["browser"],
            ),
            ToolDefinition(
                name="browser_screenshot",
                description="Take a screenshot of the current page or a specific element, returned as base64 PNG",
                parameters={
                    "type": "object",
                    "properties": {
                        "full_page": {
                            "type": "boolean",
                            "description": "Capture the full scrollable page (default: false)",
                            "default": False,
                        },
                        "selector": {
                            "type": "string",
                            "description": "CSS selector for element screenshot (optional, empty = full viewport/page)",
                            "default": "",
                        },
                    },
                },
                required_permissions=["browser"],
            ),
            ToolDefinition(
                name="browser_extract",
                description="Extract text or an attribute value from elements matching a CSS selector",
                parameters={
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector to extract content from (default: body)",
                            "default": "body",
                        },
                        "attribute": {
                            "type": "string",
                            "enum": ["innerText", "innerHTML", "href", "value"],
                            "description": "Property/attribute to extract (default: innerText)",
                            "default": "innerText",
                        },
                    },
                },
                required_permissions=["browser"],
            ),
            ToolDefinition(
                name="browser_wait",
                description="Wait for an element to reach a specific state",
                parameters={
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector to wait for",
                        },
                        "state": {
                            "type": "string",
                            "enum": ["visible", "hidden", "attached", "detached"],
                            "description": "State to wait for (default: visible)",
                            "default": "visible",
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Timeout in milliseconds (default: 10000)",
                            "default": 10000,
                        },
                    },
                    "required": ["selector"],
                },
                required_permissions=["browser"],
            ),
            ToolDefinition(
                name="browser_evaluate",
                description="Execute JavaScript in the page context and return the JSON-serialized result",
                parameters={
                    "type": "object",
                    "properties": {
                        "script": {
                            "type": "string",
                            "description": "JavaScript expression or statement to evaluate in the page",
                        },
                    },
                    "required": ["script"],
                },
                required_permissions=["browser"],
            ),
            ToolDefinition(
                name="browser_get_links",
                description="Extract all links (text + href) from elements matching a CSS selector",
                parameters={
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector for link elements (default: a)",
                            "default": "a",
                        },
                        "base_url": {
                            "type": "string",
                            "description": "Base URL to resolve relative hrefs (optional)",
                            "default": "",
                        },
                    },
                },
                required_permissions=["browser"],
            ),
            ToolDefinition(
                name="browser_fill_form",
                description="Fill multiple form fields at once and optionally submit the form",
                parameters={
                    "type": "object",
                    "properties": {
                        "fields": {
                            "type": "object",
                            "description": "Mapping of CSS selector → value to fill",
                            "additionalProperties": {"type": "string"},
                        },
                        "submit_selector": {
                            "type": "string",
                            "description": "CSS selector of the submit button to click after filling (optional)",
                            "default": "",
                        },
                    },
                    "required": ["fields"],
                },
                required_permissions=["browser"],
            ),
            ToolDefinition(
                name="browser_get_page_info",
                description="Get comprehensive information about the current page (title, URL, meta, headings, link/image counts)",
                parameters={
                    "type": "object",
                    "properties": {},
                },
                required_permissions=["browser"],
            ),
        ]

    # ── Lifecycle ───────────────────────────────────────────────

    async def initialize(self, context: SkillContext) -> None:
        pass

    async def shutdown(self) -> None:
        await self._close_browser()

    # ── Entry point ─────────────────────────────────────────────

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        # Lazy-initialise browser; surface ImportError as a friendly message.
        try:
            await self._ensure_browser()
        except ImportError:
            return SkillResult(success=False, output=_PLAYWRIGHT_MISSING, error="import_error")
        except Exception as exc:
            return SkillResult(
                success=False,
                output=f"Failed to start browser: {exc}",
                error=str(exc),
            )

        dispatch = {
            "browser_navigate": self._navigate,
            "browser_click": self._click,
            "browser_type": self._type,
            "browser_screenshot": self._screenshot,
            "browser_extract": self._extract,
            "browser_wait": self._wait,
            "browser_evaluate": self._evaluate,
            "browser_get_links": self._get_links,
            "browser_fill_form": self._fill_form,
            "browser_get_page_info": self._get_page_info,
        }

        handler = dispatch.get(tool_name)
        if handler is None:
            return SkillResult(success=False, output=f"Unknown browser tool: {tool_name}")

        try:
            return await handler(arguments)
        except Exception as exc:
            logger.exception("Browser tool '%s' raised an unhandled exception", tool_name)
            return SkillResult(success=False, output=f"Browser error: {exc}", error=str(exc))

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult:
        """Handle /browse, /web, /scrape, /click triggers."""
        if trigger in ("/browse", "/web"):
            url = args.strip()
            if not url:
                return SkillResult(success=False, output="Usage: /browse <url>")
            return await self.execute("browser_navigate", {"url": url}, context)

        if trigger == "/click":
            selector = args.strip()
            if not selector:
                return SkillResult(success=False, output="Usage: /click <css-selector>")
            return await self.execute("browser_click", {"selector": selector}, context)

        if trigger == "/scrape":
            selector = args.strip() or "body"
            return await self.execute("browser_extract", {"selector": selector}, context)

        return SkillResult(success=False, output=f"Unknown trigger: {trigger}")

    # ── Browser management ──────────────────────────────────────

    async def _ensure_browser(self) -> None:
        """Lazy-initialise a shared Playwright chromium browser + page."""
        if BrowserSkill._page is not None:
            return

        # This raises ImportError if playwright is not installed — caught upstream.
        from playwright.async_api import async_playwright  # noqa: PLC0415

        BrowserSkill._playwright = await async_playwright().start()
        BrowserSkill._browser = await BrowserSkill._playwright.chromium.launch(headless=True)
        BrowserSkill._page = await BrowserSkill._browser.new_page()
        logger.debug("Playwright browser initialised (chromium, headless)")

    @classmethod
    async def _close_browser(cls) -> None:
        """Gracefully close the shared browser instance."""
        try:
            if cls._page is not None:
                await cls._page.close()
                cls._page = None
            if cls._browser is not None:
                await cls._browser.close()
                cls._browser = None
            if cls._playwright is not None:
                await cls._playwright.stop()
                cls._playwright = None
        except Exception as exc:  # pragma: no cover
            logger.warning("Error closing browser: %s", exc)

    # ── Tool implementations ────────────────────────────────────

    async def _navigate(self, arguments: dict[str, Any]) -> SkillResult:
        url: str = arguments.get("url", "")
        wait_for: str = arguments.get("wait_for", "load")

        if not url:
            return SkillResult(success=False, output="No URL provided")

        page = BrowserSkill._page

        async def _do_navigate() -> tuple[str, str]:
            await page.goto(url, wait_until=wait_for)
            return page.title(), page.url  # type: ignore[return-value]

        title, final_url = await asyncio.wait_for(_do_navigate(), timeout=30)
        return SkillResult(
            success=True,
            output=f"Navigated to: {final_url}\nTitle: {title}",
        )

    async def _click(self, arguments: dict[str, Any]) -> SkillResult:
        selector: str = arguments.get("selector", "")
        timeout: int = int(arguments.get("timeout", 5000))

        if not selector:
            return SkillResult(success=False, output="No selector provided")

        page = BrowserSkill._page

        async def _do_click() -> None:
            await page.click(selector, timeout=timeout)

        await asyncio.wait_for(_do_click(), timeout=timeout / 1000 + 5)
        return SkillResult(success=True, output=f"Clicked element: {selector}")

    async def _type(self, arguments: dict[str, Any]) -> SkillResult:
        selector: str = arguments.get("selector", "")
        text: str = arguments.get("text", "")
        clear_first: bool = bool(arguments.get("clear_first", True))

        if not selector:
            return SkillResult(success=False, output="No selector provided")

        page = BrowserSkill._page

        async def _do_type() -> None:
            if clear_first:
                await page.fill(selector, "")
            await page.type(selector, text)

        await asyncio.wait_for(_do_type(), timeout=15)
        return SkillResult(
            success=True,
            output=f"Typed {len(text)} characters into: {selector}",
        )

    async def _screenshot(self, arguments: dict[str, Any]) -> SkillResult:
        full_page: bool = bool(arguments.get("full_page", False))
        selector: str = arguments.get("selector", "")

        page = BrowserSkill._page

        async def _do_screenshot() -> bytes:
            if selector:
                element = await page.query_selector(selector)
                if element is None:
                    raise ValueError(f"Element not found: {selector}")
                return await element.screenshot()
            return await page.screenshot(full_page=full_page)

        png_bytes: bytes = await asyncio.wait_for(_do_screenshot(), timeout=30)
        encoded = base64.b64encode(png_bytes).decode("ascii")
        target = selector if selector else ("full page" if full_page else "viewport")
        return SkillResult(
            success=True,
            output=f"Screenshot captured ({target}): {len(png_bytes)} bytes",
            artifacts=[{"type": "image/png", "encoding": "base64", "data": encoded}],
        )

    async def _extract(self, arguments: dict[str, Any]) -> SkillResult:
        selector: str = arguments.get("selector", "body")
        attribute: str = arguments.get("attribute", "innerText")

        page = BrowserSkill._page

        async def _do_extract() -> str:
            if attribute in ("innerText", "innerHTML"):
                return await page.eval_on_selector(selector, f"el => el.{attribute}")
            # For href / value use getAttribute
            value = await page.eval_on_selector(
                selector, f"el => el.getAttribute('{attribute}') ?? el.{attribute} ?? ''"
            )
            return str(value) if value is not None else ""

        text: str = await asyncio.wait_for(_do_extract(), timeout=15)
        return SkillResult(
            success=True,
            output=text or "(empty)",
        )

    async def _wait(self, arguments: dict[str, Any]) -> SkillResult:
        selector: str = arguments.get("selector", "")
        state: str = arguments.get("state", "visible")
        timeout: int = int(arguments.get("timeout", 10000))

        if not selector:
            return SkillResult(success=False, output="No selector provided")

        page = BrowserSkill._page

        async def _do_wait() -> None:
            await page.wait_for_selector(selector, state=state, timeout=timeout)

        await asyncio.wait_for(_do_wait(), timeout=timeout / 1000 + 5)
        return SkillResult(
            success=True,
            output=f"Element '{selector}' reached state '{state}'",
        )

    async def _evaluate(self, arguments: dict[str, Any]) -> SkillResult:
        script: str = arguments.get("script", "")

        if not script:
            return SkillResult(success=False, output="No script provided")

        page = BrowserSkill._page

        async def _do_eval() -> Any:
            return await page.evaluate(script)

        result = await asyncio.wait_for(_do_eval(), timeout=30)
        try:
            serialized = json.dumps(result, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            serialized = str(result)

        return SkillResult(success=True, output=serialized)

    async def _get_links(self, arguments: dict[str, Any]) -> SkillResult:
        selector: str = arguments.get("selector", "a")
        base_url: str = arguments.get("base_url", "")

        page = BrowserSkill._page

        async def _do_get_links() -> list[dict[str, str]]:
            raw: list[dict[str, str]] = await page.evaluate(
                """
                (args) => {
                    const [sel, base] = args;
                    const els = Array.from(document.querySelectorAll(sel));
                    return els.map(el => {
                        let href = el.getAttribute('href') || '';
                        if (base && href && !href.startsWith('http') && !href.startsWith('//')) {
                            try { href = new URL(href, base).href; } catch(_) {}
                        }
                        return { text: (el.innerText || el.textContent || '').trim(), href };
                    });
                }
                """,
                [selector, base_url],
            )
            return raw

        links = await asyncio.wait_for(_do_get_links(), timeout=15)
        output = json.dumps(links, ensure_ascii=False, indent=2)
        return SkillResult(
            success=True,
            output=f"Found {len(links)} link(s):\n{output}",
        )

    async def _fill_form(self, arguments: dict[str, Any]) -> SkillResult:
        fields: dict[str, str] = arguments.get("fields", {})
        submit_selector: str = arguments.get("submit_selector", "")

        if not fields:
            return SkillResult(success=False, output="No fields provided")

        page = BrowserSkill._page
        filled: list[str] = []

        async def _do_fill() -> None:
            for field_selector, value in fields.items():
                await page.fill(field_selector, str(value))
                filled.append(field_selector)
            if submit_selector:
                await page.click(submit_selector)

        await asyncio.wait_for(_do_fill(), timeout=30)
        result_msg = f"Filled {len(filled)} field(s): {', '.join(filled)}"
        if submit_selector:
            result_msg += f"\nSubmitted via: {submit_selector}"
        return SkillResult(success=True, output=result_msg)

    async def _get_page_info(self, _arguments: dict[str, Any]) -> SkillResult:
        page = BrowserSkill._page

        async def _do_info() -> dict[str, Any]:
            return await page.evaluate(
                """
                () => {
                    const metaDesc = document.querySelector('meta[name="description"]');
                    const h1s = Array.from(document.querySelectorAll('h1'))
                                     .map(el => el.innerText.trim())
                                     .filter(Boolean);
                    return {
                        title: document.title,
                        url: window.location.href,
                        meta_description: metaDesc ? metaDesc.getAttribute('content') : '',
                        h1s: h1s,
                        links_count: document.querySelectorAll('a[href]').length,
                        images_count: document.querySelectorAll('img').length,
                    };
                }
                """
            )

        info = await asyncio.wait_for(_do_info(), timeout=15)
        output = (
            f"Title: {info.get('title', '')}\n"
            f"URL: {info.get('url', '')}\n"
            f"Meta description: {info.get('meta_description', '(none)')}\n"
            f"H1s: {info.get('h1s', [])}\n"
            f"Links: {info.get('links_count', 0)}\n"
            f"Images: {info.get('images_count', 0)}"
        )
        return SkillResult(success=True, output=output)


# ── Factory ─────────────────────────────────────────────────────


def create_skill(config: dict[str, Any] | None = None) -> BrowserSkill:  # noqa: ARG001
    """Module-level factory used by SkillLoader."""
    return BrowserSkill()
