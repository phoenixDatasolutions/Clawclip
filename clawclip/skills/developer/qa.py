"""QA Skill — run tests, check code quality, and generate QA reports."""

from __future__ import annotations

import asyncio
import importlib
import logging
import pkgutil
import re
from typing import Any

from clawclip.core.types import SkillContext, SkillResult, ToolDefinition

logger = logging.getLogger(__name__)

_TEST_TIMEOUT = 300
_LINT_TIMEOUT = 60


class QASkill:
    """Run pytest suites, lint code, type-check, and summarise QA results."""

    @property
    def name(self) -> str:
        return "qa"

    @property
    def description(self) -> str:
        return "Run tests, check code quality, and generate QA reports"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="run_tests",
                description="Run pytest with configurable options",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Test path to run",
                            "default": "tests/",
                        },
                        "markers": {
                            "type": "string",
                            "description": "Pytest marker expression (e.g. 'unit')",
                        },
                        "verbose": {
                            "type": "boolean",
                            "description": "Enable verbose output",
                            "default": False,
                        },
                        "coverage": {
                            "type": "boolean",
                            "description": "Collect coverage for clawclip package",
                            "default": False,
                        },
                        "fail_fast": {
                            "type": "boolean",
                            "description": "Stop on first failure",
                            "default": False,
                        },
                    },
                },
                required_permissions=["qa.run"],
            ),
            ToolDefinition(
                name="run_unit_tests",
                description="Run only unit tests quickly",
                parameters={
                    "type": "object",
                    "properties": {
                        "module": {
                            "type": "string",
                            "description": "Optional module name to restrict (e.g. 'test_skills')",
                        },
                        "fail_fast": {
                            "type": "boolean",
                            "description": "Stop on first failure",
                            "default": True,
                        },
                    },
                },
                required_permissions=["qa.run"],
            ),
            ToolDefinition(
                name="run_integration_tests",
                description="Run integration tests",
                parameters={
                    "type": "object",
                    "properties": {
                        "fail_fast": {
                            "type": "boolean",
                            "description": "Stop on first failure",
                            "default": False,
                        },
                    },
                },
                required_permissions=["qa.run"],
            ),
            ToolDefinition(
                name="get_test_coverage",
                description="Get a coverage report for the specified module",
                parameters={
                    "type": "object",
                    "properties": {
                        "module": {
                            "type": "string",
                            "description": "Package to measure coverage for",
                            "default": "clawclip",
                        },
                        "format": {
                            "type": "string",
                            "enum": ["term", "html", "json"],
                            "description": "Coverage report format",
                            "default": "term",
                        },
                    },
                },
                required_permissions=["qa.run"],
            ),
            ToolDefinition(
                name="lint_code",
                description="Run the ruff linter against a path",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to lint",
                            "default": "clawclip/",
                        },
                        "fix": {
                            "type": "boolean",
                            "description": "Auto-fix safe violations",
                            "default": False,
                        },
                    },
                },
                required_permissions=["qa.lint"],
            ),
            ToolDefinition(
                name="type_check",
                description="Run mypy type checking",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to type-check",
                            "default": "clawclip/",
                        },
                        "strict": {
                            "type": "boolean",
                            "description": "Enable mypy strict mode",
                            "default": False,
                        },
                    },
                },
                required_permissions=["qa.lint"],
            ),
            ToolDefinition(
                name="check_imports",
                description="Verify all modules in a package import cleanly",
                parameters={
                    "type": "object",
                    "properties": {
                        "package": {
                            "type": "string",
                            "description": "Top-level package to walk",
                            "default": "clawclip",
                        },
                    },
                },
                required_permissions=["qa.run"],
            ),
            ToolDefinition(
                name="get_test_summary",
                description="Parse raw pytest output and return a structured summary",
                parameters={
                    "type": "object",
                    "properties": {
                        "output": {
                            "type": "string",
                            "description": "Raw pytest stdout/stderr to parse",
                        },
                    },
                    "required": ["output"],
                },
                required_permissions=["qa.run"],
            ),
        ]

    @property
    def triggers(self) -> list[str]:
        return ["/test", "/qa", "/coverage", "/lint"]

    @property
    def required_permissions(self) -> list[str]:
        return ["qa.run"]

    async def initialize(self, context: SkillContext) -> None:
        pass

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        cwd = arguments.get("cwd", context.working_directory or ".")

        if tool_name == "run_tests":
            return await self._run_tests(arguments, cwd)

        if tool_name == "run_unit_tests":
            return await self._run_unit_tests(arguments, cwd)

        if tool_name == "run_integration_tests":
            return await self._run_integration_tests(arguments, cwd)

        if tool_name == "get_test_coverage":
            return await self._get_test_coverage(arguments, cwd)

        if tool_name == "lint_code":
            return await self._lint_code(arguments, cwd)

        if tool_name == "type_check":
            return await self._type_check(arguments, cwd)

        if tool_name == "check_imports":
            return self._check_imports(arguments)

        if tool_name == "get_test_summary":
            output = arguments.get("output", "")
            if not output:
                return SkillResult(success=False, output="output parameter is required")
            summary = self._parse_pytest_output(output)
            lines = [
                f"passed:   {summary['passed']}",
                f"failed:   {summary['failed']}",
                f"errors:   {summary['errors']}",
                f"warnings: {summary['warnings']}",
                f"duration: {summary['duration']}s",
                f"status:   {summary['status'].upper()}",
            ]
            return SkillResult(
                success=summary["status"] == "pass",
                output="\n".join(lines),
                artifacts=[{"type": "test_summary", "data": summary}],
            )

        return SkillResult(success=False, output=f"Unknown QA tool: {tool_name}")

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult:
        args = args.strip()

        if trigger == "/test":
            if not args or args == "unit":
                return await self.execute("run_unit_tests", {}, context)
            if args == "integration":
                return await self.execute("run_integration_tests", {}, context)
            if args == "all":
                return await self.execute("run_tests", {"path": "tests/"}, context)
            # Treat remaining text as a module name
            return await self.execute("run_unit_tests", {"module": args}, context)

        if trigger == "/qa":
            cwd = context.working_directory or "."
            test_result = await self._run_tests({}, cwd)
            lint_result = await self._lint_code({}, cwd)
            combined = (
                "=== Tests ===\n"
                + test_result.output
                + "\n\n=== Lint ===\n"
                + lint_result.output
            )
            return SkillResult(
                success=test_result.success and lint_result.success,
                output=combined,
                error=test_result.error or lint_result.error,
            )

        if trigger == "/coverage":
            return await self.execute("get_test_coverage", {}, context)

        if trigger == "/lint":
            return await self.execute("lint_code", {}, context)

        return SkillResult(success=False, output=f"Unknown trigger: {trigger}")

    async def shutdown(self) -> None:
        pass

    # ── private helpers ──────────────────────────────────────────

    async def _run_tests(self, args: dict[str, Any], cwd: str) -> SkillResult:
        path = args.get("path", "tests/")
        cmd = ["python", "-m", "pytest", path]
        if args.get("verbose"):
            cmd.append("-v")
        if args.get("fail_fast"):
            cmd.append("-x")
        if args.get("markers"):
            cmd += ["-m", args["markers"]]
        if args.get("coverage"):
            cmd += ["--cov=clawclip", "--cov-report=term-missing"]
        cmd += ["--tb=short", "-q"]
        return await self._run_command(cmd, cwd, timeout=_TEST_TIMEOUT)

    async def _run_unit_tests(self, args: dict[str, Any], cwd: str) -> SkillResult:
        module = args.get("module", "")
        base = "tests/unit/"
        path = f"{base}{module}" if module else base
        cmd = ["python", "-m", "pytest", path, "-q", "--tb=short"]
        if args.get("fail_fast", True):
            cmd.append("-x")
        return await self._run_command(cmd, cwd, timeout=_TEST_TIMEOUT)

    async def _run_integration_tests(self, args: dict[str, Any], cwd: str) -> SkillResult:
        cmd = ["python", "-m", "pytest", "tests/integration/", "-q", "--tb=short"]
        if args.get("fail_fast", False):
            cmd.append("-x")
        return await self._run_command(cmd, cwd, timeout=_TEST_TIMEOUT)

    async def _get_test_coverage(self, args: dict[str, Any], cwd: str) -> SkillResult:
        module = args.get("module", "clawclip")
        fmt = args.get("format", "term")
        cmd = [
            "python", "-m", "pytest", "tests/unit/",
            f"--cov={module}",
            f"--cov-report={fmt}",
            "-q", "--no-header",
        ]
        return await self._run_command(cmd, cwd, timeout=_TEST_TIMEOUT)

    async def _lint_code(self, args: dict[str, Any], cwd: str) -> SkillResult:
        path = args.get("path", "clawclip/")
        cmd = ["python", "-m", "ruff", "check", path, "--output-format=concise"]
        if args.get("fix", False):
            cmd.append("--fix")
        try:
            return await self._run_command(cmd, cwd, timeout=_LINT_TIMEOUT)
        except FileNotFoundError:
            return SkillResult(
                success=False,
                output="ruff is not installed — run: pip install ruff",
                error="ruff not found",
            )

    async def _type_check(self, args: dict[str, Any], cwd: str) -> SkillResult:
        path = args.get("path", "clawclip/")
        cmd = ["python", "-m", "mypy", path, "--ignore-missing-imports"]
        if args.get("strict", False):
            cmd.append("--strict")
        return await self._run_command(cmd, cwd, timeout=_LINT_TIMEOUT)

    def _check_imports(self, args: dict[str, Any]) -> SkillResult:
        package = args.get("package", "clawclip")
        failures: list[str] = []
        try:
            root = importlib.import_module(package)
        except ImportError as exc:
            return SkillResult(
                success=False,
                output=f"Cannot import root package '{package}': {exc}",
                error=str(exc),
            )

        root_path = getattr(root, "__path__", [])
        for finder, module_name, _is_pkg in pkgutil.walk_packages(
            root_path, prefix=f"{package}."
        ):
            try:
                importlib.import_module(module_name)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{module_name}: {exc}")

        if failures:
            return SkillResult(
                success=False,
                output="Import failures:\n" + "\n".join(failures),
                error=f"{len(failures)} module(s) failed to import",
            )
        return SkillResult(
            success=True,
            output=f"All modules in '{package}' import cleanly.",
        )

    @staticmethod
    def _parse_pytest_output(output: str) -> dict[str, Any]:
        """Parse pytest summary line into structured counts."""
        passed = failed = errors = warnings = 0
        duration = "0.00"

        # Match lines like: "5 passed, 1 failed, 2 warnings in 3.14s"
        pattern = re.compile(
            r"(?:(\d+) passed)?[,\s]*"
            r"(?:(\d+) failed)?[,\s]*"
            r"(?:(\d+) error(?:s)?)?[,\s]*"
            r"(?:(\d+) warning(?:s)?)?[,\s]*"
            r"in\s+([\d.]+)s"
        )
        for line in output.splitlines():
            m = pattern.search(line)
            if m:
                passed = int(m.group(1) or 0)
                failed = int(m.group(2) or 0)
                errors = int(m.group(3) or 0)
                warnings = int(m.group(4) or 0)
                duration = m.group(5) or "0.00"
                break

        status = "fail" if (failed or errors) else "pass"
        return {
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "warnings": warnings,
            "duration": duration,
            "status": status,
        }

    @staticmethod
    async def _run_command(
        cmd: list[str],
        cwd: str,
        timeout: int = _TEST_TIMEOUT,
    ) -> SkillResult:
        """Run a subprocess command and return a SkillResult."""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )

            output = stdout.decode("utf-8", errors="replace")
            error_output = stderr.decode("utf-8", errors="replace")

            combined = output
            if error_output:
                combined += f"\n[stderr]\n{error_output}"

            return SkillResult(
                success=process.returncode == 0,
                output=combined.strip() or "(no output)",
                error=error_output if process.returncode != 0 else None,
            )
        except asyncio.TimeoutError:
            return SkillResult(
                success=False,
                output=f"Command timed out after {timeout}s",
                error="timeout",
            )
        except Exception as exc:
            return SkillResult(
                success=False,
                output=f"Error running command: {exc}",
                error=str(exc),
            )


def create_skill(config: dict) -> QASkill:
    return QASkill()
