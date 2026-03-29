"""Unit tests for clawclip.agents.context — SharedContext key-value store."""

from __future__ import annotations

import asyncio

import pytest

from clawclip.agents.context import SharedContext


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSharedContext:

    async def test_set_and_get(self) -> None:
        """set() then get() returns the stored value."""
        ctx = SharedContext()
        await ctx.set("key", "value")
        assert await ctx.get("key") == "value"

    async def test_get_missing_returns_none(self) -> None:
        """get() for a key that was never set returns None."""
        ctx = SharedContext()
        assert await ctx.get("missing") is None

    async def test_get_with_default(self) -> None:
        """get() with a default returns that default for missing keys."""
        ctx = SharedContext()
        assert await ctx.get("missing", "default") == "default"

    async def test_create_child(self) -> None:
        """Child context inherits values from its parent."""
        parent = SharedContext()
        await parent.set("inherited", 42)

        child = parent.create_child()
        assert await child.get("inherited") == 42

    async def test_child_isolation(self) -> None:
        """Writing to a child does not affect the parent."""
        parent = SharedContext()
        child = parent.create_child()

        await child.set("local", "child-only")

        assert await parent.get("local") is None
        assert await child.get("local") == "child-only"

    async def test_concurrent_safe(self) -> None:
        """100 concurrent set/get operations do not corrupt state."""
        ctx = SharedContext()

        async def worker(i: int) -> None:
            await ctx.set(f"k{i}", i)
            val = await ctx.get(f"k{i}")
            assert val == i

        await asyncio.gather(*[worker(i) for i in range(100)])

    async def test_add_artifact(self) -> None:
        """add_artifact() stores artifact dict; get_artifacts() retrieves it."""
        ctx = SharedContext()
        artifact = {"type": "file", "name": "output.txt", "data": b"hello"}
        await ctx.add_artifact(artifact)

        artifacts = await ctx.get_artifacts()
        assert len(artifacts) == 1
        assert artifacts[0]["name"] == "output.txt"

    async def test_add_history(self) -> None:
        """set() calls append to history; get_history() returns them."""
        ctx = SharedContext()
        await ctx.set("a", 1)
        await ctx.set("b", 2)

        history = ctx.get_history()
        assert len(history) == 2
        assert history[0]["key"] == "a"
        assert history[1]["key"] == "b"
