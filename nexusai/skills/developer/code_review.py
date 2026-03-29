"""Code Review Skill — analyze source files and format structured review data for LLMs."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from nexusai.core.types import SkillContext, SkillResult, ToolDefinition

logger = logging.getLogger(__name__)

# Rough complexity heuristics per language
_COMPLEXITY_KEYWORDS = {
    "if", "elif", "else", "for", "while", "try", "except", "with",
    "switch", "case", "catch", "finally", "foreach", "do",
}


class CodeReviewSkill:
    """Read source files and produce structured data ready for LLM code review."""

    @property
    def name(self) -> str:
        return "code_review"

    @property
    def description(self) -> str:
        return "Analyze source files for complexity, issues, and improvement opportunities"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="review_code",
                description="Read a file and return structured code review data",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to source file"},
                        "focus": {"type": "string", "description": "Review focus area (security, performance, style, all)", "default": "all"},
                    },
                    "required": ["path"],
                },
                required_permissions=["files.read"],
            ),
            ToolDefinition(
                name="analyze_complexity",
                description="Estimate cyclomatic complexity of a source file",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to source file"},
                    },
                    "required": ["path"],
                },
                required_permissions=["files.read"],
            ),
            ToolDefinition(
                name="find_issues",
                description="Scan a file for common issues: TODO/FIXME/HACK comments, bare excepts, debug prints",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to source file"},
                    },
                    "required": ["path"],
                },
                required_permissions=["files.read"],
            ),
            ToolDefinition(
                name="suggest_improvements",
                description="Read a file and return a prompt-ready improvement context block",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to source file"},
                    },
                    "required": ["path"],
                },
                required_permissions=["files.read"],
            ),
        ]

    @property
    def triggers(self) -> list[str]:
        return ["/review"]

    @property
    def required_permissions(self) -> list[str]:
        return ["files.read"]

    async def initialize(self, context: SkillContext) -> None:
        pass

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        if tool_name == "review_code":
            return await self._review_code(arguments)
        if tool_name == "analyze_complexity":
            return await self._analyze_complexity(arguments)
        if tool_name == "find_issues":
            return await self._find_issues(arguments)
        if tool_name == "suggest_improvements":
            return await self._suggest_improvements(arguments)
        return SkillResult(success=False, output=f"Unknown tool: {tool_name}")

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult:
        if not args.strip():
            return SkillResult(success=False, output="Usage: /review <file_path>")
        return await self.execute("review_code", {"path": args.strip()}, context)

    async def shutdown(self) -> None:
        pass

    # ── private helpers ──────────────────────────────────────────

    async def _read_source(self, path_str: str) -> tuple[str, str] | SkillResult:
        resolved = Path(path_str).resolve()

        def _do_read() -> str:
            if not resolved.is_file():
                raise ValueError(f"Not a file: {resolved}")
            return resolved.read_text(encoding="utf-8", errors="replace")

        try:
            content = await asyncio.get_event_loop().run_in_executor(None, _do_read)
            return content, resolved.suffix.lstrip(".")
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))

    async def _review_code(self, args: dict[str, Any]) -> SkillResult:
        path_str = args.get("path", "")
        focus = args.get("focus", "all")

        result = await self._read_source(path_str)
        if isinstance(result, SkillResult):
            return result
        content, ext = result

        lines = content.splitlines()
        line_count = len(lines)
        char_count = len(content)

        complexity = _estimate_complexity(content)
        issues = _find_code_issues(lines)

        output_parts = [
            f"=== Code Review: {path_str} ===",
            f"Language: {ext or 'unknown'}",
            f"Lines: {line_count}  |  Characters: {char_count}",
            f"Estimated complexity score: {complexity}",
            "",
            "--- Issues found ---",
            "\n".join(issues) if issues else "(none detected)",
            "",
            "--- Review focus: {focus} ---".format(focus=focus),
            "File content (first 100 lines):",
            "",
        ]
        preview = "\n".join(lines[:100])
        if line_count > 100:
            preview += f"\n... ({line_count - 100} more lines)"
        output_parts.append(preview)

        return SkillResult(
            success=True,
            output="\n".join(output_parts),
            artifacts=[{
                "path": path_str,
                "language": ext,
                "line_count": line_count,
                "complexity_score": complexity,
                "issues": issues,
                "focus": focus,
                "content": content,
            }],
        )

    async def _analyze_complexity(self, args: dict[str, Any]) -> SkillResult:
        path_str = args.get("path", "")
        result = await self._read_source(path_str)
        if isinstance(result, SkillResult):
            return result
        content, ext = result

        score = _estimate_complexity(content)
        rating = "low" if score < 10 else "medium" if score < 20 else "high"

        output = (
            f"Complexity analysis: {path_str}\n"
            f"Score: {score} ({rating})\n"
            f"Heuristic: count of branching/looping keywords"
        )
        return SkillResult(success=True, output=output, artifacts=[{"complexity_score": score, "rating": rating}])

    async def _find_issues(self, args: dict[str, Any]) -> SkillResult:
        path_str = args.get("path", "")
        result = await self._read_source(path_str)
        if isinstance(result, SkillResult):
            return result
        content, _ = result

        issues = _find_code_issues(content.splitlines())
        if not issues:
            return SkillResult(success=True, output=f"No issues found in {path_str}")
        output = f"Issues in {path_str}:\n" + "\n".join(issues)
        return SkillResult(success=True, output=output, artifacts=[{"issues": issues}])

    async def _suggest_improvements(self, args: dict[str, Any]) -> SkillResult:
        path_str = args.get("path", "")
        result = await self._read_source(path_str)
        if isinstance(result, SkillResult):
            return result
        content, ext = result

        prompt_block = (
            f"Please review the following {ext or 'source'} code and suggest improvements "
            f"for readability, performance, security, and best practices.\n\n"
            f"File: {path_str}\n\n"
            f"```{ext}\n{content[:8000]}\n```"
        )
        return SkillResult(
            success=True,
            output=prompt_block,
            artifacts=[{"prompt_ready_context": prompt_block, "path": path_str}],
        )


def _estimate_complexity(content: str) -> int:
    score = 1
    for word in content.split():
        if word.lower().rstrip(":()") in _COMPLEXITY_KEYWORDS:
            score += 1
    return score


def _find_code_issues(lines: list[str]) -> list[str]:
    issues = []
    markers = ["TODO", "FIXME", "HACK", "XXX", "BUG", "NOQA"]
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        for marker in markers:
            if marker in line.upper():
                issues.append(f"Line {i}: {marker} — {stripped[:120]}")
                break
        if "except:" in stripped or "except :" in stripped:
            issues.append(f"Line {i}: bare except — {stripped[:120]}")
        if stripped.startswith("print(") or stripped.startswith("console.log("):
            issues.append(f"Line {i}: debug print/log — {stripped[:120]}")
    return issues


def create_skill(config: dict) -> CodeReviewSkill:
    return CodeReviewSkill()
