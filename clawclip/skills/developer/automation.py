"""Automation Skill — CI/CD pipelines, scripts, environment checks, and test watching."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clawclip.core.types import SkillContext, SkillResult, ToolDefinition

logger = logging.getLogger(__name__)

_RUN_TIMEOUT = 300
_INSTALL_TIMEOUT = 120


class AutomationSkill:
    """Automate CI/CD tasks — install, lint, test, coverage, Makefile targets, and test watching."""

    @property
    def name(self) -> str:
        return "automation"

    @property
    def description(self) -> str:
        return "Automate CI/CD tasks, run scripts, and manage pipelines"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="run_makefile_target",
                description="Run a Makefile target in the project directory",
                parameters={
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string",
                            "description": "The Makefile target to run",
                        },
                        "cwd": {
                            "type": "string",
                            "description": "Working directory (optional)",
                        },
                    },
                    "required": ["target"],
                },
                required_permissions=["automation.run"],
            ),
            ToolDefinition(
                name="run_script",
                description="Run a .sh or .py script file",
                parameters={
                    "type": "object",
                    "properties": {
                        "script_path": {
                            "type": "string",
                            "description": "Absolute or relative path to the script",
                        },
                        "args": {
                            "type": "string",
                            "description": "Optional arguments to pass to the script",
                        },
                    },
                    "required": ["script_path"],
                },
                required_permissions=["automation.run"],
            ),
            ToolDefinition(
                name="check_environment",
                description="Verify that the dev environment is set up correctly",
                parameters={
                    "type": "object",
                    "properties": {},
                },
                required_permissions=["automation.read"],
            ),
            ToolDefinition(
                name="install_dependencies",
                description="Install Python dependencies via pip",
                parameters={
                    "type": "object",
                    "properties": {
                        "extras": {
                            "type": "string",
                            "description": "Extras group to install (e.g. 'test', 'dev')",
                            "default": "test",
                        },
                        "upgrade": {
                            "type": "boolean",
                            "description": "Pass --upgrade to pip",
                            "default": False,
                        },
                    },
                },
                required_permissions=["automation.install"],
            ),
            ToolDefinition(
                name="run_ci_pipeline",
                description="Run the full CI pipeline: install → lint → unit tests → integration tests → coverage",
                parameters={
                    "type": "object",
                    "properties": {
                        "skip_lint": {
                            "type": "boolean",
                            "description": "Skip the lint step",
                            "default": False,
                        },
                        "skip_coverage": {
                            "type": "boolean",
                            "description": "Skip the coverage step",
                            "default": False,
                        },
                    },
                },
                required_permissions=["automation.run"],
            ),
            ToolDefinition(
                name="generate_test_report",
                description="Generate a Markdown test report by running the test suite",
                parameters={
                    "type": "object",
                    "properties": {
                        "include_coverage": {
                            "type": "boolean",
                            "description": "Include coverage data in the report",
                            "default": True,
                        },
                    },
                },
                required_permissions=["automation.run"],
            ),
            ToolDefinition(
                name="watch_tests",
                description="Watch source files for changes and re-run unit tests automatically",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Source directory to watch",
                            "default": "clawclip/",
                        },
                        "test_path": {
                            "type": "string",
                            "description": "Test directory to run on change",
                            "default": "tests/unit/",
                        },
                        "interval_seconds": {
                            "type": "integer",
                            "description": "Polling interval in seconds",
                            "default": 5,
                        },
                        "max_runs": {
                            "type": "integer",
                            "description": "Maximum number of test runs before stopping",
                            "default": 10,
                        },
                    },
                },
                required_permissions=["automation.run"],
            ),
        ]

    @property
    def triggers(self) -> list[str]:
        return ["/pipeline", "/report", "/watch"]

    @property
    def required_permissions(self) -> list[str]:
        return ["automation.run"]

    async def initialize(self, context: SkillContext) -> None:
        pass

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        cwd = arguments.get("cwd", context.working_directory or ".")

        if tool_name == "run_makefile_target":
            target = arguments.get("target", "")
            if not target:
                return SkillResult(success=False, output="target is required")
            return await self._run_command(["make", target], cwd, timeout=_RUN_TIMEOUT)

        if tool_name == "run_script":
            return await self._run_script(arguments, cwd)

        if tool_name == "check_environment":
            return await self._check_environment(cwd)

        if tool_name == "install_dependencies":
            return await self._install_dependencies(arguments, cwd)

        if tool_name == "run_ci_pipeline":
            return await self._run_ci_pipeline(arguments, cwd)

        if tool_name == "generate_test_report":
            return await self._generate_test_report(arguments, cwd)

        if tool_name == "watch_tests":
            return await self._watch_tests(arguments, cwd)

        return SkillResult(success=False, output=f"Unknown automation tool: {tool_name}")

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult:
        args = args.strip()

        if trigger in ("/ci", "/pipeline"):
            return await self.execute("run_ci_pipeline", {}, context)

        if trigger == "/report":
            return await self.execute("generate_test_report", {}, context)

        if trigger == "/watch":
            watch_args: dict[str, Any] = {}
            if args.isdigit():
                watch_args["interval_seconds"] = int(args)
            return await self.execute("watch_tests", watch_args, context)

        return SkillResult(success=False, output=f"Unknown trigger: {trigger}")

    async def shutdown(self) -> None:
        pass

    # ── private helpers ──────────────────────────────────────────

    async def _run_script(self, args: dict[str, Any], cwd: str) -> SkillResult:
        script_path = args.get("script_path", "")
        if not script_path:
            return SkillResult(success=False, output="script_path is required")

        path = Path(script_path)
        if not path.exists():
            return SkillResult(
                success=False,
                output=f"Script not found: {script_path}",
                error="file not found",
            )

        suffix = path.suffix.lower()
        if suffix not in (".sh", ".py"):
            return SkillResult(
                success=False,
                output=f"Unsupported script type '{suffix}' — must be .sh or .py",
                error="unsupported type",
            )

        extra = args.get("args", "").split() if args.get("args") else []
        if suffix == ".sh":
            cmd = ["bash", str(script_path)] + extra
        else:
            cmd = ["python", str(script_path)] + extra

        return await self._run_command(cmd, cwd, timeout=_RUN_TIMEOUT)

    async def _check_environment(self, cwd: str) -> SkillResult:
        lines: list[str] = []
        overall_ok = True

        # Python version
        result = await self._run_command(
            ["python", "--version"], cwd, timeout=10
        )
        if result.success:
            version_str = result.output.strip().replace("Python ", "")
            try:
                parts = [int(x) for x in version_str.split(".")[:2]]
                ok = parts[0] > 3 or (parts[0] == 3 and parts[1] >= 12)
            except ValueError:
                ok = False
            mark = "✓" if ok else "✗"
            lines.append(f"Python: {version_str} {mark}")
            if not ok:
                overall_ok = False
        else:
            lines.append("Python: not found ✗")
            overall_ok = False

        # Git
        git_result = await self._run_command(["git", "--version"], cwd, timeout=10)
        if git_result.success:
            git_ver = git_result.output.strip().replace("git version ", "")
            lines.append(f"Git: {git_ver} ✓")
        else:
            lines.append("Git: not found ✗")
            overall_ok = False

        # pytest
        pt_result = await self._run_command(
            ["python", "-m", "pytest", "--version"], cwd, timeout=10
        )
        if pt_result.success:
            pt_ver = pt_result.output.strip().splitlines()[0]
            lines.append(f"pytest: {pt_ver} ✓")
        else:
            lines.append("pytest: not installed ✗")
            overall_ok = False

        # clawclip package
        pkg_result = await self._run_command(
            ["python", "-c", "import clawclip; print(clawclip.__version__ if hasattr(clawclip, '__version__') else 'installed')"],
            cwd,
            timeout=10,
        )
        if pkg_result.success:
            pkg_ver = pkg_result.output.strip()
            lines.append(f"clawclip package: {pkg_ver} ✓")
        else:
            lines.append("clawclip package: not installed ✗")
            overall_ok = False

        return SkillResult(
            success=overall_ok,
            output="\n".join(lines),
            error=None if overall_ok else "One or more environment checks failed",
        )

    async def _install_dependencies(self, args: dict[str, Any], cwd: str) -> SkillResult:
        extras = args.get("extras", "test")
        cmd = ["pip", "install", "-e", f".[{extras}]", "-q"]
        if args.get("upgrade", False):
            cmd.append("--upgrade")
        return await self._run_command(cmd, cwd, timeout=_INSTALL_TIMEOUT)

    async def _run_ci_pipeline(self, args: dict[str, Any], cwd: str) -> SkillResult:
        skip_lint = args.get("skip_lint", False)
        skip_coverage = args.get("skip_coverage", False)

        steps: list[dict[str, Any]] = []
        overall_ok = True
        pipeline_start = time.monotonic()

        async def _step(name: str, cmd: list[str], timeout: int) -> bool:
            nonlocal overall_ok
            t0 = time.monotonic()
            result = await self._run_command(cmd, cwd, timeout=timeout)
            duration_ms = int((time.monotonic() - t0) * 1000)
            status = "pass" if result.success else "fail"
            steps.append({
                "name": name,
                "status": status,
                "output": result.output,
                "duration_ms": duration_ms,
            })
            if not result.success:
                overall_ok = False
            return result.success

        # Step 1 — install deps
        ok = await _step(
            "install deps",
            ["pip", "install", "-e", ".[test]", "-q"],
            _INSTALL_TIMEOUT,
        )
        if not ok:
            return self._pipeline_result(steps, overall_ok, pipeline_start)

        # Step 2 — lint (optional)
        if not skip_lint:
            ok = await _step(
                "lint",
                ["python", "-m", "ruff", "check", "clawclip/", "--output-format=concise"],
                _LINT_TIMEOUT,
            )
            if not ok:
                return self._pipeline_result(steps, overall_ok, pipeline_start)

        # Step 3 — unit tests
        ok = await _step(
            "unit tests",
            ["python", "-m", "pytest", "tests/unit/", "-q", "--tb=short", "-x"],
            _RUN_TIMEOUT,
        )
        if not ok:
            return self._pipeline_result(steps, overall_ok, pipeline_start)

        # Step 4 — integration tests
        ok = await _step(
            "integration tests",
            ["python", "-m", "pytest", "tests/integration/", "-q", "--tb=short"],
            _RUN_TIMEOUT,
        )
        if not ok:
            return self._pipeline_result(steps, overall_ok, pipeline_start)

        # Step 5 — coverage (optional)
        if not skip_coverage:
            await _step(
                "coverage",
                [
                    "python", "-m", "pytest", "tests/unit/",
                    "--cov=clawclip", "--cov-report=term-missing",
                    "-q", "--no-header",
                ],
                _RUN_TIMEOUT,
            )

        return self._pipeline_result(steps, overall_ok, pipeline_start)

    @staticmethod
    def _pipeline_result(
        steps: list[dict[str, Any]],
        overall_ok: bool,
        start: float,
    ) -> SkillResult:
        total_ms = int((time.monotonic() - start) * 1000)
        summary_lines = [
            f"  {'✓' if s['status'] == 'pass' else '✗'} {s['name']} ({s['duration_ms']}ms)"
            for s in steps
        ]
        overall_label = "PASS" if overall_ok else "FAIL"
        output = (
            f"CI Pipeline — {overall_label} ({total_ms}ms)\n"
            + "\n".join(summary_lines)
        )
        return SkillResult(
            success=overall_ok,
            output=output,
            artifacts=[{
                "type": "ci_pipeline",
                "data": {
                    "steps": steps,
                    "overall_status": "pass" if overall_ok else "fail",
                    "total_duration_ms": total_ms,
                },
            }],
            error=None if overall_ok else "Pipeline failed",
        )

    async def _generate_test_report(self, args: dict[str, Any], cwd: str) -> SkillResult:
        include_coverage = args.get("include_coverage", True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Run unit tests
        unit_start = time.monotonic()
        unit_result = await self._run_command(
            ["python", "-m", "pytest", "tests/unit/", "-q", "--tb=short"],
            cwd, timeout=_RUN_TIMEOUT,
        )
        unit_duration = time.monotonic() - unit_start
        unit_counts = self._parse_counts(unit_result.output)

        # Run integration tests
        int_start = time.monotonic()
        int_result = await self._run_command(
            ["python", "-m", "pytest", "tests/integration/", "-q", "--tb=short"],
            cwd, timeout=_RUN_TIMEOUT,
        )
        int_duration = time.monotonic() - int_start
        int_counts = self._parse_counts(int_result.output)

        total_passed = unit_counts["passed"] + int_counts["passed"]
        total_failed = unit_counts["failed"] + int_counts["failed"]
        total_tests = total_passed + total_failed
        overall_pass = total_failed == 0 and unit_result.success and int_result.success
        status_badge = "PASS" if overall_pass else "FAIL"

        coverage_section = ""
        if include_coverage:
            cov_result = await self._run_command(
                [
                    "python", "-m", "pytest", "tests/unit/",
                    "--cov=clawclip", "--cov-report=term-missing",
                    "-q", "--no-header",
                ],
                cwd, timeout=_RUN_TIMEOUT,
            )
            coverage_section = f"\n## Coverage\n\n```\n{cov_result.output.strip()}\n```\n"

        report = (
            f"# ClawClip Test Report\n"
            f"**Date:** {date_str}\n"
            f"**Status:** {'✅' if overall_pass else '❌'} {status_badge}\n"
            f"\n## Summary\n\n"
            f"| Category    | Tests | Passed | Failed |\n"
            f"|-------------|-------|--------|--------|\n"
            f"| Unit        | {unit_counts['passed'] + unit_counts['failed']:5} | {unit_counts['passed']:6} | {unit_counts['failed']:6} |\n"
            f"| Integration | {int_counts['passed'] + int_counts['failed']:5} | {int_counts['passed']:6} | {int_counts['failed']:6} |\n"
            f"| **Total**   | **{total_tests}** | **{total_passed}** | **{total_failed}** |\n"
            f"\n## Duration\n\n"
            f"Unit: {unit_duration:.1f}s | Integration: {int_duration:.1f}s\n"
            + coverage_section
        )

        return SkillResult(
            success=overall_pass,
            output=report,
            artifacts=[{"type": "test_report", "format": "markdown", "content": report}],
            error=None if overall_pass else "Tests failed",
        )

    async def _watch_tests(self, args: dict[str, Any], cwd: str) -> SkillResult:
        watch_path = args.get("path", "clawclip/")
        test_path = args.get("test_path", "tests/unit/")
        interval = int(args.get("interval_seconds", 5))
        max_runs = int(args.get("max_runs", 10))

        watch_dir = Path(cwd) / watch_path
        if not watch_dir.exists():
            return SkillResult(
                success=False,
                output=f"Watch path does not exist: {watch_dir}",
                error="path not found",
            )

        def _collect_mtimes() -> dict[str, float]:
            mtimes: dict[str, float] = {}
            for py_file in watch_dir.rglob("*.py"):
                try:
                    mtimes[str(py_file)] = os.stat(py_file).st_mtime
                except OSError:
                    pass
            return mtimes

        run_log: list[str] = []
        runs = 0
        prev_mtimes = _collect_mtimes()

        # Run once immediately
        result = await self._run_command(
            ["python", "-m", "pytest", str(test_path), "-q", "--tb=short", "-x"],
            cwd, timeout=_RUN_TIMEOUT,
        )
        status = "PASS" if result.success else "FAIL"
        run_log.append(f"[run 1] {status}")
        runs += 1

        while runs < max_runs:
            await asyncio.sleep(interval)
            current_mtimes = _collect_mtimes()

            changed = [
                f for f, mtime in current_mtimes.items()
                if prev_mtimes.get(f) != mtime
            ] + [
                f for f in prev_mtimes if f not in current_mtimes
            ]

            if changed:
                prev_mtimes = current_mtimes
                runs += 1
                logger.debug("watch_tests: changes detected in %d file(s), run %d", len(changed), runs)
                result = await self._run_command(
                    ["python", "-m", "pytest", str(test_path), "-q", "--tb=short", "-x"],
                    cwd, timeout=_RUN_TIMEOUT,
                )
                status = "PASS" if result.success else "FAIL"
                changed_names = ", ".join(Path(f).name for f in changed[:3])
                run_log.append(f"[run {runs}] {status} (changed: {changed_names})")
            else:
                prev_mtimes = current_mtimes

        summary = "\n".join(run_log)
        return SkillResult(
            success=True,
            output=f"Watch complete after {runs} run(s):\n{summary}",
        )

    @staticmethod
    def _parse_counts(output: str) -> dict[str, int]:
        """Extract passed/failed counts from pytest output."""
        import re
        passed = failed = 0
        m = re.search(r"(?:(\d+) passed)?.*?(?:(\d+) failed)?.*?in\s+[\d.]+s", output)
        if m:
            passed = int(m.group(1) or 0)
            failed = int(m.group(2) or 0)
        return {"passed": passed, "failed": failed}

    @staticmethod
    async def _run_command(
        cmd: list[str],
        cwd: str,
        timeout: int = _RUN_TIMEOUT,
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


def create_skill(config: dict) -> AutomationSkill:
    return AutomationSkill()
