"""Database Ops Skill — run queries, inspect schemas, and export data from SQLite databases."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from clawclip.core.types import SkillContext, SkillResult, ToolDefinition

logger = logging.getLogger(__name__)

try:
    import aiosqlite
    _AIOSQLITE_AVAILABLE = True
except ImportError:
    _AIOSQLITE_AVAILABLE = False

_WRITE_KEYWORDS = {"INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE", "REPLACE"}


def _requires_write(sql: str) -> bool:
    first_word = sql.strip().split(maxsplit=1)[0].upper() if sql.strip() else ""
    return first_word in _WRITE_KEYWORDS


class DatabaseOpsSkill:
    """SQLite database operations — query, inspect, and export data."""

    @property
    def name(self) -> str:
        return "db_ops"

    @property
    def description(self) -> str:
        return "Run SQL queries, list tables, describe schemas, and export data from SQLite"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="run_query",
                description="Execute a SQL query on a SQLite database and return results",
                parameters={
                    "type": "object",
                    "properties": {
                        "db_path": {"type": "string", "description": "Path to the SQLite database file"},
                        "sql": {"type": "string", "description": "SQL query to execute"},
                        "max_rows": {"type": "integer", "description": "Maximum rows to return", "default": 100},
                    },
                    "required": ["db_path", "sql"],
                },
                required_permissions=["db.read", "db.write"],
            ),
            ToolDefinition(
                name="list_tables",
                description="List all tables in a SQLite database",
                parameters={
                    "type": "object",
                    "properties": {
                        "db_path": {"type": "string", "description": "Path to the SQLite database file"},
                    },
                    "required": ["db_path"],
                },
                required_permissions=["db.read"],
            ),
            ToolDefinition(
                name="describe_table",
                description="Show the schema (columns and types) of a table",
                parameters={
                    "type": "object",
                    "properties": {
                        "db_path": {"type": "string", "description": "Path to the SQLite database file"},
                        "table_name": {"type": "string", "description": "Table name"},
                    },
                    "required": ["db_path", "table_name"],
                },
                required_permissions=["db.read"],
            ),
            ToolDefinition(
                name="export_query",
                description="Run a SELECT query and return results as CSV",
                parameters={
                    "type": "object",
                    "properties": {
                        "db_path": {"type": "string", "description": "Path to the SQLite database file"},
                        "sql": {"type": "string", "description": "SELECT query"},
                        "max_rows": {"type": "integer", "description": "Maximum rows to export", "default": 500},
                    },
                    "required": ["db_path", "sql"],
                },
                required_permissions=["db.read"],
            ),
        ]

    @property
    def triggers(self) -> list[str]:
        return ["/db", "/sql"]

    @property
    def required_permissions(self) -> list[str]:
        return ["db.read"]

    async def initialize(self, context: SkillContext) -> None:
        pass

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        if not _AIOSQLITE_AVAILABLE:
            return SkillResult(success=False, output="aiosqlite is not installed", error="missing dependency")

        if tool_name == "run_query":
            return await self._run_query(arguments)
        if tool_name == "list_tables":
            return await self._list_tables(arguments)
        if tool_name == "describe_table":
            return await self._describe_table(arguments)
        if tool_name == "export_query":
            return await self._export_query(arguments)

        return SkillResult(success=False, output=f"Unknown tool: {tool_name}")

    async def handle_trigger(
        self,
        trigger: str,
        args: str,
        context: SkillContext,
    ) -> SkillResult:
        parts = args.strip().split(maxsplit=1)
        if len(parts) < 2:
            return SkillResult(success=False, output="Usage: /db <db_path> <SQL query or 'tables'>")

        db_path = parts[0]
        rest = parts[1].strip()

        if rest.lower() == "tables":
            return await self.execute("list_tables", {"db_path": db_path}, context)

        return await self.execute("run_query", {"db_path": db_path, "sql": rest}, context)

    async def shutdown(self) -> None:
        pass

    # ── private helpers ──────────────────────────────────────────

    def _validate_db_path(self, db_path: str) -> tuple[Path, SkillResult | None]:
        resolved = Path(db_path).resolve()
        if not resolved.exists():
            return resolved, SkillResult(success=False, output=f"Database file not found: {resolved}")
        if resolved.suffix not in (".db", ".sqlite", ".sqlite3", ""):
            pass  # allow any extension, warn is optional
        return resolved, None

    async def _run_query(self, args: dict[str, Any]) -> SkillResult:
        db_path = args.get("db_path", "")
        sql = args.get("sql", "").strip()
        max_rows = int(args.get("max_rows", 100))

        if not sql:
            return SkillResult(success=False, output="sql is required")

        resolved, err = self._validate_db_path(db_path)
        if err:
            return err

        try:
            async with aiosqlite.connect(str(resolved)) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(sql) as cursor:
                    if cursor.description:
                        columns = [d[0] for d in cursor.description]
                        rows = await cursor.fetchmany(max_rows)
                        lines = ["\t".join(columns)]
                        lines += ["\t".join(str(v) for v in row) for row in rows]
                        truncated = len(rows) == max_rows
                        output = "\n".join(lines)
                        if truncated:
                            output += f"\n... (limited to {max_rows} rows)"
                    else:
                        await db.commit()
                        output = f"Query executed. Rows affected: {cursor.rowcount}"
            return SkillResult(success=True, output=output)
        except Exception as e:
            return SkillResult(success=False, output=f"Query error: {e}", error=str(e))

    async def _list_tables(self, args: dict[str, Any]) -> SkillResult:
        db_path = args.get("db_path", "")
        resolved, err = self._validate_db_path(db_path)
        if err:
            return err

        try:
            async with aiosqlite.connect(str(resolved)) as db:
                async with db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name") as cursor:
                    rows = await cursor.fetchall()
            if not rows:
                return SkillResult(success=True, output="No tables found in database")
            output = "Tables:\n" + "\n".join(f"  {row[0]}" for row in rows)
            return SkillResult(success=True, output=output)
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))

    async def _describe_table(self, args: dict[str, Any]) -> SkillResult:
        db_path = args.get("db_path", "")
        table_name = args.get("table_name", "")
        if not table_name:
            return SkillResult(success=False, output="table_name is required")

        resolved, err = self._validate_db_path(db_path)
        if err:
            return err

        try:
            async with aiosqlite.connect(str(resolved)) as db:
                async with db.execute(f"PRAGMA table_info({table_name})") as cursor:
                    rows = await cursor.fetchall()
            if not rows:
                return SkillResult(success=False, output=f"Table '{table_name}' not found or empty schema")

            lines = [f"Table: {table_name}", f"{'Col':<4}  {'Name':<20}  {'Type':<15}  {'NotNull':<8}  {'Default':<12}  PK"]
            lines.append("-" * 70)
            for row in rows:
                cid, name, col_type, notnull, default_val, pk = row
                lines.append(f"{cid:<4}  {name:<20}  {col_type:<15}  {str(bool(notnull)):<8}  {str(default_val):<12}  {pk}")
            return SkillResult(success=True, output="\n".join(lines))
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))

    async def _export_query(self, args: dict[str, Any]) -> SkillResult:
        db_path = args.get("db_path", "")
        sql = args.get("sql", "").strip()
        max_rows = int(args.get("max_rows", 500))

        if not sql:
            return SkillResult(success=False, output="sql is required")
        if _requires_write(sql):
            return SkillResult(success=False, output="export_query only supports SELECT statements")

        resolved, err = self._validate_db_path(db_path)
        if err:
            return err

        try:
            import csv
            import io

            async with aiosqlite.connect(str(resolved)) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(sql) as cursor:
                    if not cursor.description:
                        return SkillResult(success=False, output="Query returned no columns")
                    columns = [d[0] for d in cursor.description]
                    rows = await cursor.fetchmany(max_rows)

            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(columns)
            writer.writerows(rows)
            csv_output = buf.getvalue()

            truncated = len(rows) == max_rows
            output = csv_output
            if truncated:
                output += f"\n# ... (limited to {max_rows} rows)"

            return SkillResult(
                success=True,
                output=output,
                artifacts=[{"format": "csv", "row_count": len(rows), "columns": columns}],
            )
        except Exception as e:
            return SkillResult(success=False, output=str(e), error=str(e))


def create_skill(config: dict) -> DatabaseOpsSkill:
    return DatabaseOpsSkill()
